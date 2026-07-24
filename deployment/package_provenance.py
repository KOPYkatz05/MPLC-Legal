"""Create and verify deterministic frozen-package provenance manifests.

The manifest intentionally lives beside a PyInstaller role directory rather
than inside it.  That keeps the complete package inventory self-consistent and
avoids excluding the manifest from its own tree hash.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import stat
import struct
import subprocess
import sys
import uuid
from pathlib import Path, PurePosixPath


MANIFEST_FORMAT = 1
HASH_CHUNK_SIZE = 4 * 1024 * 1024
OCR_MODEL_LAYOUTS = {
    "det": Path("det/en/en_PP-OCRv3_det_infer"),
    "rec": Path("rec/en/en_PP-OCRv4_rec_infer"),
    "cls": Path("cls/ch_ppocr_mobile_v2.0_cls_infer"),
}


class _VSFixedFileInfo(ctypes.Structure):
    _fields_ = [
        ("signature", ctypes.c_uint32),
        ("struct_version", ctypes.c_uint32),
        ("file_version_ms", ctypes.c_uint32),
        ("file_version_ls", ctypes.c_uint32),
        ("product_version_ms", ctypes.c_uint32),
        ("product_version_ls", ctypes.c_uint32),
        ("file_flags_mask", ctypes.c_uint32),
        ("file_flags", ctypes.c_uint32),
        ("file_os", ctypes.c_uint32),
        ("file_type", ctypes.c_uint32),
        ("file_subtype", ctypes.c_uint32),
        ("file_date_ms", ctypes.c_uint32),
        ("file_date_ls", ctypes.c_uint32),
    ]


class ProvenanceError(RuntimeError):
    pass


def _canonical_bytes(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProvenanceError(f"JSON object contains duplicate key: {key!r}")
        result[key] = value
    return result


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_reparse_stat(value: os.stat_result) -> bool:
    attributes = getattr(value, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _absolute_path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.abspath(os.fspath(value)))


def _assert_no_reparse_ancestors(path: Path) -> None:
    current = path if path.exists() else path.parent
    current = _absolute_path(current)
    while True:
        try:
            current_stat = os.lstat(current)
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(current_stat.st_mode) or _is_reparse_stat(current_stat):
                raise ProvenanceError(f"Path contains a symbolic link or reparse point: {current}")
        parent = current.parent
        if parent == current:
            return
        current = parent


def _assert_separate_manifest(package_dir: Path, manifest_path: Path) -> None:
    try:
        manifest_path.relative_to(package_dir)
    except ValueError:
        return
    raise ProvenanceError(
        "The provenance manifest must live outside the package directory to avoid "
        f"self-hash recursion: {manifest_path}"
    )


def _safe_relative_path(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ProvenanceError(f"Package path escaped its root: {path}") from exc
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in ("", ".", "..") for part in pure.parts)
        or any(":" in part or "\\" in part for part in pure.parts)
    ):
        raise ProvenanceError(f"Unsafe relative package path: {relative!r}")
    return relative


def _walk_regular_files(root: Path) -> list[tuple[str, Path]]:
    root = _absolute_path(root)
    _assert_no_reparse_ancestors(root)
    try:
        root_stat = os.lstat(root)
    except FileNotFoundError as exc:
        raise ProvenanceError(f"Directory does not exist: {root}") from exc
    if not stat.S_ISDIR(root_stat.st_mode) or _is_reparse_stat(root_stat):
        raise ProvenanceError(f"Expected a normal non-reparse directory: {root}")

    pending = [root]
    files: list[tuple[str, Path]] = []
    seen_casefolded: set[str] = set()
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise ProvenanceError(f"Could not enumerate package directory {directory}: {exc}") from exc
        for entry in entries:
            entry_path = Path(entry.path)
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ProvenanceError(f"Could not inspect package path {entry_path}: {exc}") from exc
            if entry.is_symlink() or _is_reparse_stat(entry_stat):
                raise ProvenanceError(
                    f"Package tree contains a symbolic link or reparse point: {entry_path}"
                )
            if stat.S_ISDIR(entry_stat.st_mode):
                pending.append(entry_path)
                continue
            if not stat.S_ISREG(entry_stat.st_mode):
                raise ProvenanceError(f"Package tree contains a non-regular file: {entry_path}")
            relative = _safe_relative_path(root, entry_path)
            folded = relative.casefold()
            if folded in seen_casefolded:
                raise ProvenanceError(
                    f"Package tree contains case-insensitive duplicate paths: {relative}"
                )
            seen_casefolded.add(folded)
            files.append((relative, entry_path))
    files.sort(key=lambda item: item[0])
    return files


def _hash_stable_file(path: Path) -> tuple[int, str]:
    try:
        before = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or _is_reparse_stat(before):
            raise ProvenanceError(f"Expected a normal regular file: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            for chunk in iter(lambda: handle.read(HASH_CHUNK_SIZE), b""):
                digest.update(chunk)
            after_open = os.fstat(handle.fileno())
        after = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ProvenanceError(f"Could not hash {path}: {exc}") from exc
    identity_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(
        getattr(before, name, None) != getattr(opened, name, None)
        or getattr(before, name, None) != getattr(after_open, name, None)
        or getattr(before, name, None) != getattr(after, name, None)
        for name in identity_fields
    ):
        raise ProvenanceError(f"File changed while provenance was being calculated: {path}")
    return before.st_size, digest.hexdigest()


def _inventory(root: Path) -> tuple[list[dict], str, int]:
    first_pass = _walk_regular_files(root)
    files = []
    total_size = 0
    for relative, path in first_pass:
        size, sha256 = _hash_stable_file(path)
        files.append({"path": relative, "sha256": sha256, "size": size})
        total_size += size
    second_pass = [relative for relative, _path in _walk_regular_files(root)]
    if second_pass != [entry["path"] for entry in files]:
        raise ProvenanceError(f"File inventory changed while scanning: {root}")
    return files, _sha256_bytes(_canonical_bytes(files)), total_size


def _safe_requested_package_paths(values: list[str]) -> list[str]:
    requested = []
    seen = set()
    for value in values:
        relative = str(value).replace("\\", "/")
        pure = PurePosixPath(relative)
        if (
            pure.is_absolute()
            or pure.as_posix() != relative
            or not pure.parts
            or any(part in ("", ".", "..") for part in pure.parts)
            or any(":" in part or "\\" in part for part in pure.parts)
        ):
            raise ProvenanceError(
                f"Unsafe Windows-version executable path: {value!r}"
            )
        folded = relative.casefold()
        if folded in seen:
            raise ProvenanceError(
                f"Windows-version executable was supplied more than once: {relative}"
            )
        seen.add(folded)
        requested.append(relative)
    requested.sort()
    return requested


def _fixed_version(ms: int, ls: int) -> tuple[int, int, int, int]:
    return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)


def _expected_fixed_version(app_version: str) -> tuple[int, int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(app_version))
    if match is None:
        raise ProvenanceError(
            "Application version must begin with three numeric components for "
            f"Windows version validation: {app_version!r}"
        )
    return tuple(int(value) for value in match.groups()) + (0,)


def _windows_version_string_matches(value: str, app_version: str) -> bool:
    if value == str(app_version):
        return True
    # Windows tooling commonly renders a three-part x.y.z version as the
    # equivalent fixed-resource form x.y.z.0 even when the string table was
    # authored with three components.
    if re.fullmatch(r"\d+\.\d+\.\d+", str(app_version)):
        return value == f"{app_version}.0"
    return False


def _read_windows_version_resource(path: Path) -> dict:
    if os.name != "nt":
        raise ProvenanceError(
            "Windows executable version resources can only be verified on Windows"
        )
    _assert_no_reparse_ancestors(path)
    size, _sha256 = _hash_stable_file(path)
    try:
        with path.open("rb") as handle:
            signature = handle.read(2)
    except OSError as exc:
        raise ProvenanceError(f"Could not inspect Windows executable {path}: {exc}") from exc
    if size < 2 or signature != b"MZ":
        raise ProvenanceError(f"Expected a Windows PE executable: {path}")

    version = ctypes.WinDLL("version", use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    version.GetFileVersionInfoSizeW.restype = ctypes.c_uint32
    version.GetFileVersionInfoW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    version.GetFileVersionInfoW.restype = ctypes.c_bool
    version.VerQueryValueW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    version.VerQueryValueW.restype = ctypes.c_bool

    ignored_handle = ctypes.c_uint32()
    resource_size = version.GetFileVersionInfoSizeW(
        str(path), ctypes.byref(ignored_handle)
    )
    if not resource_size:
        raise ProvenanceError(f"Executable has no Windows version resource: {path}")
    buffer = ctypes.create_string_buffer(resource_size)
    if not version.GetFileVersionInfoW(str(path), 0, resource_size, buffer):
        raise ProvenanceError(f"Could not read Windows version resource: {path}")

    def query(sub_block: str):
        value = ctypes.c_void_p()
        length = ctypes.c_uint32()
        if not version.VerQueryValueW(
            buffer, sub_block, ctypes.byref(value), ctypes.byref(length)
        ):
            return None, 0
        return value.value, length.value

    fixed_pointer, fixed_length = query("\\")
    if not fixed_pointer or fixed_length < ctypes.sizeof(_VSFixedFileInfo):
        raise ProvenanceError(f"Executable has no fixed Windows version info: {path}")
    fixed = ctypes.cast(
        fixed_pointer, ctypes.POINTER(_VSFixedFileInfo)
    ).contents
    if fixed.signature != 0xFEEF04BD:
        raise ProvenanceError(f"Executable Windows version signature is invalid: {path}")

    translations = []
    translation_pointer, translation_length = query("\\VarFileInfo\\Translation")
    if translation_pointer and translation_length >= 4:
        words = ctypes.cast(
            translation_pointer, ctypes.POINTER(ctypes.c_uint16)
        )
        for index in range(0, translation_length // 2 - 1, 2):
            translations.append((words[index], words[index + 1]))
    if (0x0409, 1200) not in translations:
        translations.append((0x0409, 1200))

    strings = {}
    for key in ("FileVersion", "ProductVersion"):
        for language, code_page in translations:
            pointer, length = query(
                f"\\StringFileInfo\\{language:04X}{code_page:04X}\\{key}"
            )
            if pointer and length:
                strings[key] = ctypes.wstring_at(pointer, length).rstrip("\0")
                break
        if not strings.get(key):
            raise ProvenanceError(
                f"Executable Windows version resource has no {key}: {path}"
            )

    return {
        "file_version": strings["FileVersion"],
        "fixed_file_version": ".".join(
            str(value)
            for value in _fixed_version(
                fixed.file_version_ms, fixed.file_version_ls
            )
        ),
        "fixed_product_version": ".".join(
            str(value)
            for value in _fixed_version(
                fixed.product_version_ms, fixed.product_version_ls
            )
        ),
        "product_version": strings["ProductVersion"],
    }


def _windows_executable_versions(
    package_dir: Path,
    requested_paths: list[str],
    app_version: str,
    inventory: list[dict],
) -> list[dict]:
    requested = _safe_requested_package_paths(requested_paths)
    package_paths = {entry["path"] for entry in inventory}
    expected_fixed = ".".join(
        str(value) for value in _expected_fixed_version(app_version)
    )
    records = []
    for relative in requested:
        if relative not in package_paths:
            raise ProvenanceError(
                f"Windows-version executable is not in the package inventory: {relative}"
            )
        record = _read_windows_version_resource(
            package_dir / Path(*PurePosixPath(relative).parts)
        )
        if (
            not _windows_version_string_matches(
                record["file_version"], str(app_version)
            )
            or not _windows_version_string_matches(
                record["product_version"], str(app_version)
            )
            or record["fixed_file_version"] != expected_fixed
            or record["fixed_product_version"] != expected_fixed
        ):
            raise ProvenanceError(
                "Executable Windows ProductVersion/FileVersion does not match "
                f"APP_VERSION {app_version!r}: {relative} -> {record}"
            )
        records.append({"path": relative, **record})
    return records


def _run_git(repo_root: Path, arguments: list[str], *, text: bool = False):
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=text,
            check=False,
        )
    except OSError as exc:
        raise ProvenanceError(
            f"Git provenance command failed to start: {' '.join(arguments)}. {exc}"
        ) from exc
    detail = completed.stderr
    if isinstance(detail, bytes):
        detail = detail.decode("utf-8", errors="replace")
    diagnostic_lines = [line.strip() for line in detail.splitlines() if line.strip()]
    unexpected_diagnostics = [
        line
        for line in diagnostic_lines
        if not (
            line.startswith("warning: in the working copy of ")
            and " will be replaced by " in line
            and line.endswith("the next time Git touches it")
        )
    ]
    if completed.returncode != 0 or unexpected_diagnostics:
        raise ProvenanceError(
            f"Git provenance command failed or emitted diagnostics: "
            f"{' '.join(arguments)}. {'; '.join(unexpected_diagnostics)}"
        )
    return completed.stdout


def _git_source_state(repo_root: Path) -> dict:
    commit = _run_git(repo_root, ["rev-parse", "HEAD"], text=True).strip()
    if len(commit) != 40 or any(character not in "0123456789abcdefABCDEF" for character in commit):
        raise ProvenanceError(f"Git returned an invalid commit identifier: {commit!r}")
    diff = _run_git(repo_root, ["diff", "--binary", "HEAD", "--"])
    untracked_output = _run_git(
        repo_root,
        ["ls-files", "--others", "--exclude-standard", "-z"],
    )
    untracked_raw = [value for value in untracked_output.split(b"\0") if value]
    untracked = []
    for raw_path in sorted(untracked_raw):
        relative = os.fsdecode(raw_path)
        pure = PurePosixPath(relative.replace("\\", "/"))
        if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
            raise ProvenanceError(f"Git returned an unsafe untracked path: {relative!r}")
        candidate = _absolute_path(repo_root / Path(*pure.parts))
        try:
            candidate.relative_to(repo_root)
        except ValueError as exc:
            raise ProvenanceError(f"Untracked path escaped the repository: {relative}") from exc
        _assert_no_reparse_ancestors(candidate)
        size, sha256 = _hash_stable_file(candidate)
        untracked.append({"path": pure.as_posix(), "sha256": sha256, "size": size})

    state_payload = {
        "commit": commit.lower(),
        "diff_sha256": _sha256_bytes(diff),
        "untracked": untracked,
    }
    return {
        "git_commit": commit.lower(),
        "git_dirty": bool(diff or untracked),
        "git_state_sha256": _sha256_bytes(_canonical_bytes(state_payload)),
    }


def _dependency_locks(repo_root: Path, paths: list[str]) -> list[dict]:
    records = []
    seen: set[str] = set()
    for raw_path in paths:
        candidate = _absolute_path(raw_path)
        _assert_no_reparse_ancestors(candidate)
        try:
            relative = candidate.relative_to(repo_root).as_posix()
        except ValueError as exc:
            raise ProvenanceError(f"Dependency lock escaped the repository: {candidate}") from exc
        if relative.casefold() in seen:
            raise ProvenanceError(f"Dependency lock was supplied more than once: {relative}")
        seen.add(relative.casefold())
        size, sha256 = _hash_stable_file(candidate)
        records.append({"path": relative, "sha256": sha256, "size": size})
    records.sort(key=lambda item: item["path"])
    return records


def _tool_versions(distributions: list[str]) -> dict:
    tools = {}
    for distribution in sorted(set(distributions), key=str.casefold):
        try:
            tools[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ProvenanceError(
                f"Required build-tool distribution is not installed: {distribution}"
            ) from exc
    return tools


def _build_environment(distributions: list[str]) -> dict:
    return {
        "platform": {
            "machine": platform.machine(),
            "release": platform.release(),
            "system": platform.system(),
            "version": platform.version(),
        },
        "python": {
            "bits": struct.calcsize("P") * 8,
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "tools": _tool_versions(distributions),
    }


def _validate_server_https_smoke_result(
    result: dict,
    *,
    app_version: str,
    api_version: str,
    schema_version: int,
    package_inventory: list[dict],
) -> None:
    evidence = result.get("https_health")
    expected_keys = {
        "api_version",
        "app_version",
        "database_integrity",
        "executable_sha256",
        "executable_size",
        "frozen_executable",
        "host",
        "schema_version",
        "status",
        "tls_peer_verified",
        "transport",
    }
    if not isinstance(evidence, dict) or set(evidence) != expected_keys:
        raise ProvenanceError(
            "Server package smoke result has no valid frozen HTTPS health evidence"
        )
    expected = {
        "api_version": str(api_version),
        "app_version": str(app_version),
        "database_integrity": "ok",
        "frozen_executable": True,
        "host": "127.0.0.1",
        "schema_version": int(schema_version),
        "status": "ok",
        "tls_peer_verified": True,
        "transport": "https",
    }
    for key, value in expected.items():
        if evidence.get(key) != value:
            raise ProvenanceError(
                f"Server frozen HTTPS smoke {key!r} mismatch: "
                f"expected {value!r}, found {evidence.get(key)!r}"
            )
    executable_hash = evidence.get("executable_sha256")
    executable_size = evidence.get("executable_size")
    if (
        not isinstance(executable_hash, str)
        or re.fullmatch(r"[a-f0-9]{64}", executable_hash) is None
        or not isinstance(executable_size, int)
        or isinstance(executable_size, bool)
        or executable_size <= 0
    ):
        raise ProvenanceError(
            "Server frozen HTTPS smoke has invalid executable hash/size evidence"
        )
    executable_records = [
        item
        for item in package_inventory
        if item.get("path") == "MissionLegalServer.exe"
    ]
    if len(executable_records) != 1:
        raise ProvenanceError(
            "Server package inventory must contain exactly one MissionLegalServer.exe"
        )
    executable_record = executable_records[0]
    if (
        executable_record.get("sha256") != executable_hash
        or executable_record.get("size") != executable_size
    ):
        raise ProvenanceError(
            "Frozen HTTPS smoke is not bound to the packaged MissionLegalServer.exe"
        )


def _read_smoke_result(
    path: Path,
    role: str,
    app_version: str,
    api_version: str,
    schema_version: int,
    package_inventory: list[dict],
) -> dict:
    _assert_no_reparse_ancestors(path)
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="strict").splitlines()
    except OSError as exc:
        raise ProvenanceError(f"Could not read package smoke output {path}: {exc}") from exc
    result = None
    for line in reversed(lines):
        try:
            candidate = json.loads(line, object_pairs_hook=_unique_json_object)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("status") == "ok":
            result = candidate
            break
    if result is None:
        raise ProvenanceError(f"Package smoke output contains no successful JSON result: {path}")
    expected = {
        "api_version": str(api_version),
        "app_version": str(app_version),
        "role": role,
        "schema_version": schema_version,
        "status": "ok",
    }
    for key, value in expected.items():
        if result.get(key) != value:
            raise ProvenanceError(
                f"Package smoke result {key!r} mismatch: expected {value!r}, found {result.get(key)!r}"
            )
    if result.get("frozen") is not True:
        raise ProvenanceError("Package smoke result did not prove a frozen executable")
    if role == "server":
        _validate_server_https_smoke_result(
            result,
            app_version=app_version,
            api_version=api_version,
            schema_version=schema_version,
            package_inventory=package_inventory,
        )
    return result


def _ocr_model_manifest(ocr_root: Path, package_inventory: list[dict]) -> dict:
    ocr_root = _absolute_path(ocr_root)
    _assert_no_reparse_ancestors(ocr_root)
    package_by_path = {entry["path"]: entry for entry in package_inventory}
    models = []
    for name, layout in OCR_MODEL_LAYOUTS.items():
        source_root = ocr_root / layout
        source_files, source_digest, source_size = _inventory(source_root)
        package_prefix = f"_internal/ocr_models/{name}"
        expected_package_paths = set()
        for source_entry in source_files:
            package_path = f"{package_prefix}/{source_entry['path']}"
            expected_package_paths.add(package_path)
            packaged = package_by_path.get(package_path)
            if packaged is None:
                raise ProvenanceError(f"Bundled OCR model file is missing: {package_path}")
            if packaged["size"] != source_entry["size"] or packaged["sha256"] != source_entry["sha256"]:
                raise ProvenanceError(f"Bundled OCR model does not match its source: {package_path}")
        actual_package_paths = {
            path for path in package_by_path if path.startswith(package_prefix + "/")
        }
        if actual_package_paths != expected_package_paths:
            unexpected = sorted(actual_package_paths - expected_package_paths)
            missing = sorted(expected_package_paths - actual_package_paths)
            raise ProvenanceError(
                f"Bundled OCR model inventory mismatch for {name}; missing={missing}, unexpected={unexpected}"
            )
        models.append(
            {
                "files": source_files,
                "name": name,
                "package_prefix": package_prefix,
                "source_layout": layout.as_posix(),
                "total_size": source_size,
                "tree_sha256": source_digest,
            }
        )
    return {
        "models": models,
        "tree_sha256": _sha256_bytes(_canonical_bytes(models)),
    }


def _validate_recorded_paths(files: list[dict]) -> None:
    previous = None
    seen_casefolded = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size"}:
            raise ProvenanceError("Manifest file inventory contains an invalid entry")
        relative = entry["path"]
        if not isinstance(relative, str):
            raise ProvenanceError("Manifest file inventory contains a non-string path")
        pure = PurePosixPath(relative)
        if (
            pure.is_absolute()
            or pure.as_posix() != relative
            or any(part in ("", ".", "..") for part in pure.parts)
            or any(":" in part or "\\" in part for part in pure.parts)
        ):
            raise ProvenanceError(f"Manifest contains an unsafe relative path: {relative!r}")
        if previous is not None and relative <= previous:
            raise ProvenanceError("Manifest file inventory is not uniquely sorted")
        folded = relative.casefold()
        if folded in seen_casefolded:
            raise ProvenanceError(f"Manifest contains a case-insensitive duplicate path: {relative}")
        seen_casefolded.add(folded)
        previous = relative
        if not isinstance(entry["size"], int) or entry["size"] < 0:
            raise ProvenanceError(f"Manifest contains an invalid size for {relative}")
        if not isinstance(entry["sha256"], str) or len(entry["sha256"]) != 64:
            raise ProvenanceError(f"Manifest contains an invalid SHA-256 for {relative}")


def _load_manifest(path: Path) -> dict:
    _assert_no_reparse_ancestors(path)
    try:
        raw = path.read_text(encoding="utf-8-sig")
        manifest = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"Provenance manifest is unreadable: {path}. {exc}") from exc
    if not isinstance(manifest, dict):
        raise ProvenanceError("Provenance manifest root must be an object")
    return manifest


def _write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_reparse_ancestors(path)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    payload = json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def create_manifest(args) -> dict:
    repo_root = _absolute_path(args.repo_root)
    package_dir = _absolute_path(args.package_dir)
    manifest_path = _absolute_path(args.manifest_path)
    _assert_no_reparse_ancestors(repo_root)
    _assert_no_reparse_ancestors(manifest_path)
    _assert_separate_manifest(package_dir, manifest_path)
    files, tree_sha256, total_size = _inventory(package_dir)
    schema_version = int(args.schema_version)
    smoke_result = _read_smoke_result(
        _absolute_path(args.smoke_result),
        args.role,
        args.app_version,
        args.api_version,
        schema_version,
        files,
    )
    ocr_models = None
    if args.role == "client":
        if not args.ocr_model_root:
            raise ProvenanceError("Client provenance requires --ocr-model-root")
        ocr_models = _ocr_model_manifest(_absolute_path(args.ocr_model_root), files)
    elif args.ocr_model_root:
        raise ProvenanceError("Server provenance must not specify --ocr-model-root")
    windows_executables = _windows_executable_versions(
        package_dir,
        args.windows_version_exe,
        args.app_version,
        files,
    )

    manifest = {
        "application": {
            "api_version": str(args.api_version),
            "app_version": str(args.app_version),
            "schema_version": schema_version,
        },
        "build_environment": _build_environment(args.tool_package),
        "dependency_locks": _dependency_locks(repo_root, args.dependency_lock),
        "file_count": len(files),
        "files": files,
        "manifest_format": MANIFEST_FORMAT,
        "ocr_models": ocr_models,
        "role": args.role,
        "smoke_result": smoke_result,
        "source": _git_source_state(repo_root),
        "total_size": total_size,
        "tree_sha256": tree_sha256,
        "windows_executables": windows_executables,
    }
    _write_manifest(manifest_path, manifest)
    return manifest


def verify_manifest(args) -> dict:
    repo_root = _absolute_path(args.repo_root)
    package_dir = _absolute_path(args.package_dir)
    manifest_path = _absolute_path(args.manifest_path)
    _assert_separate_manifest(package_dir, manifest_path)
    manifest = _load_manifest(manifest_path)
    if manifest.get("manifest_format") != MANIFEST_FORMAT:
        raise ProvenanceError(
            f"Unsupported provenance manifest format: {manifest.get('manifest_format')!r}"
        )
    if manifest.get("role") != args.expected_role:
        raise ProvenanceError(
            f"Provenance role mismatch: expected {args.expected_role!r}, found {manifest.get('role')!r}"
        )
    application = manifest.get("application")
    if not isinstance(application, dict):
        raise ProvenanceError("Provenance manifest has no application version record")
    expected_application = {
        "api_version": str(args.expected_api_version),
        "app_version": str(args.expected_app_version),
        "schema_version": int(args.expected_schema_version),
    }
    if application != expected_application:
        raise ProvenanceError(
            f"Provenance application version mismatch: expected {expected_application}, found {application}"
        )

    recorded_files = manifest.get("files")
    if not isinstance(recorded_files, list):
        raise ProvenanceError("Provenance manifest has no file inventory")
    _validate_recorded_paths(recorded_files)
    recorded_digest = _sha256_bytes(_canonical_bytes(recorded_files))
    if recorded_digest != manifest.get("tree_sha256"):
        raise ProvenanceError("Provenance manifest file inventory digest is invalid")
    if len(recorded_files) != manifest.get("file_count"):
        raise ProvenanceError("Provenance manifest file count is invalid")
    if sum(entry["size"] for entry in recorded_files) != manifest.get("total_size"):
        raise ProvenanceError("Provenance manifest total size is invalid")

    current_files, current_digest, current_size = _inventory(package_dir)
    if current_files != recorded_files or current_digest != recorded_digest:
        raise ProvenanceError(
            "Frozen package tree does not match its provenance manifest; rebuild the role package"
        )
    if current_size != manifest.get("total_size"):
        raise ProvenanceError("Frozen package total size does not match its provenance manifest")

    recorded_windows = manifest.get("windows_executables")
    if not isinstance(recorded_windows, list):
        raise ProvenanceError(
            "Provenance manifest has no Windows executable version record"
        )
    windows_keys = {
        "file_version",
        "fixed_file_version",
        "fixed_product_version",
        "path",
        "product_version",
    }
    for record in recorded_windows:
        if (
            not isinstance(record, dict)
            or set(record) != windows_keys
            or any(not isinstance(value, str) for value in record.values())
        ):
            raise ProvenanceError(
                "Provenance manifest contains an invalid Windows executable version record"
            )
    recorded_windows_paths = [record["path"] for record in recorded_windows]
    normalized_windows_paths = _safe_requested_package_paths(
        recorded_windows_paths
    )
    if recorded_windows_paths != normalized_windows_paths:
        raise ProvenanceError(
            "Windows executable version records are not uniquely sorted"
        )
    required_windows_paths = _safe_requested_package_paths(
        args.required_windows_version_exe
    )
    if required_windows_paths and required_windows_paths != recorded_windows_paths:
        raise ProvenanceError(
            "Provenance manifest does not cover the required PyInstaller executables: "
            f"expected {required_windows_paths}, found {recorded_windows_paths}"
        )
    current_windows = _windows_executable_versions(
        package_dir,
        recorded_windows_paths,
        args.expected_app_version,
        current_files,
    )
    if current_windows != recorded_windows:
        raise ProvenanceError(
            "Packaged executable ProductVersion/FileVersion no longer matches provenance"
        )

    recorded_source = manifest.get("source")
    current_source = _git_source_state(repo_root)
    if recorded_source != current_source:
        raise ProvenanceError(
            "Current Git source state does not match the frozen package provenance; rebuild the role package"
        )

    recorded_environment = manifest.get("build_environment")
    if (
        not isinstance(recorded_environment, dict)
        or set(recorded_environment) != {"platform", "python", "tools"}
        or not isinstance(recorded_environment.get("platform"), dict)
        or not isinstance(recorded_environment.get("python"), dict)
        or not isinstance(recorded_environment.get("tools"), dict)
        or any(
            not isinstance(name, str) or not isinstance(version, str)
            for name, version in recorded_environment.get("tools", {}).items()
        )
    ):
        raise ProvenanceError(
            "Provenance manifest has no valid build-environment record"
        )
    current_environment = _build_environment(
        list(recorded_environment["tools"])
    )
    if current_environment != recorded_environment:
        raise ProvenanceError(
            "Current Python/platform/build-tool versions do not match package provenance; "
            "rebuild the role package"
        )

    recorded_locks = manifest.get("dependency_locks")
    if not isinstance(recorded_locks, list):
        raise ProvenanceError("Provenance manifest has no dependency-lock record")
    lock_paths = []
    for item in recorded_locks:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256", "size"}
            or not isinstance(item.get("path"), str)
        ):
            raise ProvenanceError(
                "Provenance manifest contains an invalid dependency-lock record"
            )
        pure = PurePosixPath(item["path"])
        if (
            pure.is_absolute()
            or pure.as_posix() != item["path"]
            or any(part in ("", ".", "..") for part in pure.parts)
            or any(":" in part or "\\" in part for part in pure.parts)
        ):
            raise ProvenanceError(
                f"Provenance manifest contains an unsafe dependency-lock path: {item['path']!r}"
            )
        lock_paths.append(str(repo_root / Path(*pure.parts)))
    current_locks = _dependency_locks(repo_root, lock_paths)
    if recorded_locks != current_locks:
        raise ProvenanceError("Dependency lock files no longer match the frozen package provenance")

    smoke = manifest.get("smoke_result")
    if not isinstance(smoke, dict) or smoke.get("status") != "ok" or smoke.get("frozen") is not True:
        raise ProvenanceError("Provenance manifest has no successful frozen smoke result")
    if (
        smoke.get("role") != args.expected_role
        or str(smoke.get("app_version")) != str(args.expected_app_version)
        or str(smoke.get("api_version")) != str(args.expected_api_version)
        or int(smoke.get("schema_version")) != int(args.expected_schema_version)
    ):
        raise ProvenanceError("Recorded smoke result does not match the expected role/version")
    if args.expected_role == "server":
        _validate_server_https_smoke_result(
            smoke,
            app_version=args.expected_app_version,
            api_version=args.expected_api_version,
            schema_version=args.expected_schema_version,
            package_inventory=current_files,
        )

    ocr_models = manifest.get("ocr_models")
    if args.expected_role == "client":
        if not isinstance(ocr_models, dict) or not isinstance(ocr_models.get("models"), list):
            raise ProvenanceError("Client provenance has no OCR model manifest")
        if _sha256_bytes(_canonical_bytes(ocr_models["models"])) != ocr_models.get("tree_sha256"):
            raise ProvenanceError("Client OCR model manifest digest is invalid")
        package_by_path = {entry["path"]: entry for entry in current_files}
        for model in ocr_models["models"]:
            prefix = model.get("package_prefix")
            model_files = model.get("files")
            if not isinstance(prefix, str) or not isinstance(model_files, list):
                raise ProvenanceError("Client OCR model manifest contains an invalid model")
            _validate_recorded_paths(model_files)
            if _sha256_bytes(_canonical_bytes(model_files)) != model.get("tree_sha256"):
                raise ProvenanceError(f"OCR model manifest digest is invalid: {model.get('name')}")
            expected_paths = set()
            for item in model_files:
                package_path = f"{prefix}/{item['path']}"
                expected_paths.add(package_path)
                packaged = package_by_path.get(package_path)
                if packaged is None or packaged["size"] != item["size"] or packaged["sha256"] != item["sha256"]:
                    raise ProvenanceError(f"Bundled OCR model provenance mismatch: {package_path}")
            actual_paths = {path for path in package_by_path if path.startswith(prefix + "/")}
            if actual_paths != expected_paths:
                raise ProvenanceError(f"Bundled OCR model inventory mismatch: {prefix}")
    elif ocr_models is not None:
        raise ProvenanceError("Server provenance unexpectedly contains OCR models")
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a package provenance manifest")
    create.add_argument("--repo-root", required=True)
    create.add_argument("--package-dir", required=True)
    create.add_argument("--manifest-path", required=True)
    create.add_argument("--role", choices=("client", "server"), required=True)
    create.add_argument("--app-version", required=True)
    create.add_argument("--api-version", required=True)
    create.add_argument("--schema-version", required=True, type=int)
    create.add_argument("--smoke-result", required=True)
    create.add_argument("--dependency-lock", action="append", default=[])
    create.add_argument("--tool-package", action="append", default=[])
    create.add_argument("--ocr-model-root")
    create.add_argument("--windows-version-exe", action="append", default=[])

    verify = subparsers.add_parser("verify", help="Verify a package provenance manifest")
    verify.add_argument("--repo-root", required=True)
    verify.add_argument("--package-dir", required=True)
    verify.add_argument("--manifest-path", required=True)
    verify.add_argument("--expected-role", choices=("client", "server"), required=True)
    verify.add_argument("--expected-app-version", required=True)
    verify.add_argument("--expected-api-version", required=True)
    verify.add_argument("--expected-schema-version", required=True, type=int)
    verify.add_argument(
        "--required-windows-version-exe", action="append", default=[]
    )
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            result = create_manifest(args)
        else:
            result = verify_manifest(args)
    except (KeyError, ProvenanceError, ValueError, TypeError) as exc:
        print(f"Package provenance failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "app_version": result["application"]["app_version"],
                "role": result["role"],
                "tree_sha256": result["tree_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
