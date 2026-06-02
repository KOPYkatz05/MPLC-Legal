from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from utils.logger import logger


def _make_writable(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
    except Exception:
        logger.debug(f"Could not update permissions for {path}")


def cleanup_pycache(
    root: str | Path = ".",
    *,
    dry_run: bool = False,
    skip_dirs: tuple[str, ...] = ("venv", ".git"),
) -> list[Path]:
    """
    Remove stale __pycache__ directories under the given root.

    Locked files are skipped instead of failing the whole cleanup.
    """
    root_path = Path(root).resolve()
    removed: list[Path] = []

    def should_skip(path: Path) -> bool:
        return any(part in skip_dirs for part in path.parts)

    def delete_dir(pycache_dir: Path) -> None:
        if dry_run:
            logger.info(f"[dry-run] Would remove {pycache_dir}")
            removed.append(pycache_dir)
            return

        try:
            for child in pycache_dir.rglob("*"):
                _make_writable(child)

            _make_writable(pycache_dir)

            def onerror(func, path, exc_info):
                exc = exc_info[1]

                if isinstance(exc, PermissionError):
                    _make_writable(Path(path))
                    try:
                        func(path)
                        return
                    except Exception:
                        pass

                raise exc

            shutil.rmtree(pycache_dir, onerror=onerror)
            removed.append(pycache_dir)
            logger.info(f"Removed stale __pycache__: {pycache_dir}")
        except Exception:
            logger.warning(
                f"Skipped locked or inaccessible __pycache__: {pycache_dir}"
            )

    for pycache_dir in sorted(
        root_path.rglob("__pycache__")
    ):
        if not pycache_dir.is_dir():
            continue

        if should_skip(pycache_dir):
            continue

        delete_dir(pycache_dir)

    return removed
