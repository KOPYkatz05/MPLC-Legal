"""Isolated background downloader for Mission Legal client updates."""

import argparse
import json
import os
from pathlib import Path


def _write_state(path, payload):
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Download and stage a Mission Legal client update"
    )
    parser.add_argument("--state-file", required=True)
    args = parser.parse_args(argv)
    state_path = Path(args.state_file)

    try:
        from services.update_service import ClientUpdateService

        service = ClientUpdateService()
        if not service.enabled:
            raise RuntimeError("Client updates are not configured")

        _write_state(state_path, {"status": "checking", "progress": 0})

        def progress(value):
            _write_state(
                state_path,
                {"status": "downloading", "progress": int(value)},
            )

        prepared = service.check_and_download(progress)
        if prepared is None:
            _write_state(state_path, {"status": "current", "progress": 100})
            return 0

        _write_state(
            state_path,
            {
                "status": "ready",
                "progress": 100,
                "version": prepared.version,
                "notes_markdown": prepared.notes_markdown,
                "size": prepared.size,
            },
        )
        return 0
    except Exception as exc:
        _write_state(
            state_path,
            {"status": "failed", "error": str(exc)},
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
