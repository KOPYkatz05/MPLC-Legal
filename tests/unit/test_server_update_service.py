import base64
import hashlib
import json
import shutil
import tempfile
import uuid
from io import BytesIO
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.server_update_service import (
    ServerUpdateConfig,
    ServerUpdateError,
    ServerUpdateService,
    load_server_update_config,
)


@pytest.fixture
def tmp_path():
    path = Path(tempfile.gettempdir()) / f"mission-legal-updater-{uuid.uuid4().hex}"
    path.mkdir(mode=0o777)
    try:
        yield path
    finally:
        shutil.rmtree(path)


class Response(BytesIO):
    def __init__(self, value):
        super().__init__(value)
        self.headers = {"Content-Length": str(len(value))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def update_fixture(tmp_path, *, tamper_signature=False):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    installer = b"verified server installer"
    digest = hashlib.sha256(installer).hexdigest()
    manifest = json.dumps(
        {
            "app_version": "0.2.2",
            "filename": "MissionLegalServerSetup-0.2.2.exe",
            "sha256": digest,
            "size": len(installer),
        },
        separators=(",", ":"),
    ).encode()
    signature = private.sign(manifest)
    if tamper_signature:
        signature = bytes([signature[0] ^ 1]) + signature[1:]
    urls = {
        "https://manifest": manifest,
        "https://signature": base64.b64encode(signature),
        "https://installer": installer,
    }
    release = [
        {
            "tag_name": "v0.2.2",
            "draft": False,
            "prerelease": False,
            "body": "Safe update",
            "assets": [
                {
                    "name": "MissionLegalServerSetup-0.2.2.exe",
                    "size": len(installer),
                    "browser_download_url": "https://installer",
                },
                {
                    "name": "MissionLegalServerSetup-0.2.2.json",
                    "browser_download_url": "https://manifest",
                },
                {
                    "name": "MissionLegalServerSetup-0.2.2.json.sig",
                    "browser_download_url": "https://signature",
                },
            ],
        }
    ]

    def opener(request, timeout=0):
        _ = timeout
        url = request.full_url
        if "api.github.com" in url:
            return Response(json.dumps(release).encode())
        return Response(urls[url])

    config = ServerUpdateConfig(
        repository="KOPYkatz05/MPLC-Legal",
        public_key=public,
    )
    return ServerUpdateService(
        config,
        current_version="0.2.1",
        staging_root=tmp_path,
        opener=opener,
    )


def test_checks_downloads_and_verifies_signed_server_release(tmp_path):
    service = update_fixture(tmp_path)
    update = service.check_for_update()

    assert update.version == "0.2.2"
    prepared = service.download_update(update)

    assert prepared.installer_path.read_bytes() == b"verified server installer"
    assert prepared.version == "0.2.2"
    assert service.prepared_update == prepared


def test_rejects_tampered_release_manifest_signature(tmp_path):
    service = update_fixture(tmp_path, tamper_signature=True)
    update = service.check_for_update()

    with pytest.raises(ServerUpdateError, match="signature is invalid"):
        service.download_update(update)

    assert not list(tmp_path.rglob("*.exe"))


def test_ignores_drafts_prereleases_and_non_newer_versions(tmp_path):
    service = update_fixture(tmp_path)

    def opener(request, timeout=0):
        _ = request, timeout
        releases = [
            {"tag_name": "0.2.1", "draft": False, "assets": []},
            {"tag_name": "0.3.0", "draft": True, "assets": []},
            {"tag_name": "0.4.0", "prerelease": True, "assets": []},
        ]
        return Response(json.dumps(releases).encode())

    service._opener = opener
    assert service.check_for_update() is None


def test_frozen_configuration_is_loaded_from_pyinstaller_resource_root(
    tmp_path, monkeypatch
):
    from services import server_update_service

    payload = {
        "repository": "KOPYkatz05/MPLC-Legal",
        "channel": "stable",
        "allowPrerelease": False,
        "manifestPublicKey": base64.b64encode(
            Ed25519PrivateKey.generate().public_key().public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            )
        ).decode("ascii"),
    }
    (tmp_path / "server_release.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(server_update_service.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        server_update_service.sys, "_MEIPASS", str(tmp_path), raising=False
    )

    config = load_server_update_config()

    assert config.repository == "KOPYkatz05/MPLC-Legal"
