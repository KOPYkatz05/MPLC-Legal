"""Exercise the frozen server through a real, CA-verified HTTPS health request."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import signal
import socket
import sqlite3
import ssl
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, build_opener


RUNTIME_PREFIX = "frozen-https-smoke-"
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class SmokeError(RuntimeError):
    pass


def _absolute(path: str | os.PathLike[str]) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse(path: Path) -> bool:
    value = os.lstat(path)
    attributes = getattr(value, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(value.st_mode) or bool(attributes & reparse_flag)


def _prepare_runtime_root(parent: Path) -> Path:
    parent = _absolute(parent)
    if not parent.is_dir() or _is_reparse(parent):
        raise SmokeError(f"Runtime parent must be a normal directory: {parent}")
    root = parent / f"{RUNTIME_PREFIX}{uuid.uuid4().hex}"
    if root.exists():
        raise SmokeError(f"Runtime root must be initially absent: {root}")
    root.mkdir()
    return root


def _remove_runtime_root(root: Path, parent: Path) -> None:
    root = _absolute(root)
    parent = _absolute(parent)
    if root.parent != parent or not root.name.startswith(RUNTIME_PREFIX):
        raise SmokeError(f"Refusing to remove an unexpected runtime root: {root}")
    if root.exists():
        if _is_reparse(root):
            raise SmokeError(f"Refusing to remove a reparse-point runtime root: {root}")
        shutil.rmtree(root)


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _read_last_success(path: Path) -> dict:
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="strict").splitlines()
    except OSError as exc:
        raise SmokeError(f"Could not read frozen import-smoke output: {path}") from exc
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("status") == "ok":
            return value
    raise SmokeError(f"Frozen import-smoke output has no successful JSON result: {path}")


@contextlib.contextmanager
def _temporary_environment(values: dict[str, str]):
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _create_runtime_configuration(
    runtime_root: Path,
    port: int,
) -> tuple[Path, Path, Path]:
    data_root = runtime_root / "data"
    mission_root = runtime_root / "mission-documents"
    backup_root = runtime_root / "mirror-backups"
    mission_root.mkdir()
    backup_root.mkdir()
    environment = {
        "MISSION_LEGAL_DATA_DIR": str(data_root),
        "MISSION_LEGAL_DATABASE_PATH": str(data_root / "app.db"),
        "MISSION_LEGAL_SERVER_PROCESS": "1",
        "MISSIONS_ROOT": str(mission_root),
    }
    with _temporary_environment(environment):
        from server.configuration import save_server_configuration
        from server.tls import generate_local_tls

        save_server_configuration(
            {
                "host": "127.0.0.1",
                "port": port,
                "mission_storage_root": str(mission_root),
                "onedrive_backup_dir": str(backup_root),
            }
        )
        tls_paths = generate_local_tls(overwrite=True, protect_keys=False)
    return data_root, Path(tls_paths["ca_cert"]), Path(tls_paths["server_key"])


def _verified_health(
    *,
    url: str,
    ca_certificate: Path,
    process: subprocess.Popen,
    timeout_seconds: int,
) -> dict:
    context = ssl.create_default_context(cafile=str(ca_certificate))
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context))
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            with opener.open(url, timeout=2) as response:
                if response.status != 200:
                    raise SmokeError(f"Health endpoint returned HTTP {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise SmokeError("Health endpoint did not return a JSON object")
                return payload
        except (HTTPError, URLError, OSError, json.JSONDecodeError, SmokeError) as exc:
            last_error = exc
            time.sleep(0.25)
    raise SmokeError(
        f"Frozen HTTPS server did not become healthy at {url}: {last_error}"
    )


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()
        process.wait(timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


def _database_integrity(path: Path) -> str:
    if not path.is_file():
        raise SmokeError(f"Frozen HTTPS smoke did not create its database: {path}")
    try:
        with contextlib.closing(
            sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        ) as connection:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error as exc:
        raise SmokeError(f"Could not integrity-check HTTPS smoke database: {exc}") from exc
    messages = [str(row[0]) for row in rows]
    if messages != ["ok"]:
        raise SmokeError(f"HTTPS smoke database integrity failed: {messages}")
    return "ok"


def run(args: argparse.Namespace) -> dict:
    server_executable = _absolute(args.server_exe)
    runtime_parent = _absolute(args.runtime_parent)
    base_result_path = _absolute(args.base_smoke_result)
    output_path = _absolute(args.output)
    stdout_path = _absolute(args.server_stdout)
    stderr_path = _absolute(args.server_stderr)
    if not server_executable.is_file() or _is_reparse(server_executable):
        raise SmokeError(f"Frozen server executable is missing or unsafe: {server_executable}")

    base_result = _read_last_success(base_result_path)
    expected_base = {
        "api_version": str(args.api_version),
        "app_version": str(args.app_version),
        "frozen": True,
        "role": "server",
        "schema_version": int(args.schema_version),
        "status": "ok",
    }
    for name, expected in expected_base.items():
        if base_result.get(name) != expected:
            raise SmokeError(
                f"Frozen import-smoke {name!r} mismatch: "
                f"expected {expected!r}, found {base_result.get(name)!r}"
            )

    executable_hash = _sha256(server_executable)
    executable_size = server_executable.stat().st_size
    runtime_root = _prepare_runtime_root(runtime_parent)
    process: subprocess.Popen | None = None
    try:
        port = _free_loopback_port()
        data_root, ca_certificate, server_key = _create_runtime_configuration(
            runtime_root,
            port,
        )
        server_certificate = (
            data_root / "Configuration" / "tls" / "mission-legal-server.pem"
        )
        child_environment = os.environ.copy()
        child_environment.update(
            {
                "MISSION_LEGAL_DATA_DIR": str(data_root),
                "MISSION_LEGAL_DATABASE_PATH": str(data_root / "app.db"),
                "MISSION_LEGAL_SERVER_PROCESS": "1",
                "MISSION_LEGAL_SERVER_HOST": "127.0.0.1",
                "MISSION_LEGAL_SERVER_PORT": str(port),
                "MISSION_LEGAL_TLS_CERT": str(server_certificate),
                "MISSION_LEGAL_TLS_KEY": str(server_key),
                "MISSIONS_ROOT": str(runtime_root / "mission-documents"),
                "NO_PROXY": "127.0.0.1,localhost",
                "no_proxy": "127.0.0.1,localhost",
            }
        )
        creation_flags = 0
        if os.name == "nt":
            creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
            "w", encoding="utf-8"
        ) as stderr_handle:
            process = subprocess.Popen(
                [
                    str(server_executable),
                    "--tls-cert",
                    str(server_certificate),
                    "--tls-key",
                    str(server_key),
                ],
                cwd=server_executable.parent,
                env=child_environment,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                creationflags=creation_flags,
            )
            health = _verified_health(
                url=f"https://127.0.0.1:{port}/health",
                ca_certificate=ca_certificate,
                process=process,
                timeout_seconds=args.timeout_seconds,
            )
            expected_health = {
                "api_version": str(args.api_version),
                "app_version": str(args.app_version),
                "schema_version": int(args.schema_version),
                "status": "ok",
            }
            for name, expected in expected_health.items():
                if health.get(name) != expected:
                    raise SmokeError(
                        f"HTTPS health {name!r} mismatch: "
                        f"expected {expected!r}, found {health.get(name)!r}"
                    )
            _stop_process(process)
            process = None

        if _sha256(server_executable) != executable_hash:
            raise SmokeError("Frozen server executable changed during HTTPS smoke")
        evidence = {
            "api_version": str(args.api_version),
            "app_version": str(args.app_version),
            "database_integrity": _database_integrity(data_root / "app.db"),
            "executable_sha256": executable_hash,
            "executable_size": executable_size,
            "frozen_executable": True,
            "host": "127.0.0.1",
            "schema_version": int(args.schema_version),
            "status": "ok",
            "tls_peer_verified": True,
            "transport": "https",
        }
        combined_result = dict(base_result)
        combined_result["https_health"] = evidence
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(combined_result, ensure_ascii=True, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return evidence
    finally:
        if process is not None:
            _stop_process(process)
        _remove_runtime_root(runtime_root, runtime_parent)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-exe", required=True)
    parser.add_argument("--runtime-parent", required=True)
    parser.add_argument("--base-smoke-result", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--server-stdout", required=True)
    parser.add_argument("--server-stderr", required=True)
    parser.add_argument("--app-version", required=True)
    parser.add_argument("--api-version", required=True)
    parser.add_argument("--schema-version", required=True, type=int)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        evidence = run(args)
    except (OSError, SmokeError, ValueError) as exc:
        print(f"Frozen HTTPS smoke failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
