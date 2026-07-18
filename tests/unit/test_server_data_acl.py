import ctypes
import json
import os
import stat
from pathlib import Path
from unittest import mock

import pytest

from server import data_acl, tls


REPO_ROOT = Path(__file__).resolve().parents[2]


def _is_elevated_windows():
    return os.name == "nt" and bool(ctypes.windll.shell32.IsUserAnAdmin())


def test_public_ca_path_is_a_deliberate_copy_under_public_directory(tmp_path):
    assert data_acl.public_ca_path(tmp_path) == (
        tmp_path.resolve() / "Public" / "mission-legal-ca.pem"
    )


def test_windows_sensitive_policy_uses_only_well_known_sid_script(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(data_acl, "_is_windows", lambda: True)
    monkeypatch.setattr(
        data_acl,
        "_invoke_windows_acl",
        lambda mode, paths: calls.append((mode, tuple(paths))),
    )

    result = data_acl.protect_sensitive_server_data(tmp_path)

    assert result == tmp_path.resolve()
    assert calls == [
        (
            "ProtectSensitive",
            (
                tmp_path.resolve(),
                tmp_path.resolve() / "Public",
            ),
        )
    ]
    script = data_acl._WINDOWS_ACL_SCRIPT
    assert data_acl.SYSTEM_SID in script
    assert data_acl.ADMINISTRATORS_SID in script
    assert data_acl.USERS_SID in script
    assert "AreAccessRulesProtected" in script
    assert "SetAccessRuleProtection($true, $false)" in script
    assert "unexpected SID" in script
    assert "Administrators:F" not in script
    assert "SYSTEM:F" not in script
    assert "USERNAME" not in script


def test_private_keys_use_fail_closed_windows_acl_without_user_grant(
    tmp_path,
    monkeypatch,
):
    first = tmp_path / "ca-key.pem"
    second = tmp_path / "server-key.pem"
    first.write_text("private", encoding="utf-8")
    second.write_text("private", encoding="utf-8")
    calls = []
    monkeypatch.setattr(data_acl, "_is_windows", lambda: True)
    monkeypatch.setattr(
        data_acl,
        "_invoke_windows_acl",
        lambda mode, paths: calls.append((mode, tuple(paths))),
    )

    data_acl.protect_private_key_files(first, second)

    assert calls == [
        ("ProtectPrivate", (first.resolve(), second.resolve()))
    ]


def test_private_key_policy_refuses_missing_file(tmp_path):
    with pytest.raises(data_acl.ServerDataAclError, match="missing or unsafe"):
        data_acl.protect_private_key_files(tmp_path / "missing-key.pem")


def test_public_ca_publication_is_atomic_and_reapplies_sensitive_policy(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "Configuration" / "tls" / "mission-legal-ca.pem"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"-----BEGIN CERTIFICATE-----\nfixture\n")
    calls = []

    def invoke(mode, paths):
        paths = tuple(Path(path) for path in paths)
        calls.append((mode, paths))
        if mode == "ProtectSensitive":
            tmp_path.mkdir(parents=True, exist_ok=True)
        elif mode == "PreparePublic":
            paths[2].mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(data_acl, "_is_windows", lambda: True)
    monkeypatch.setattr(data_acl, "_invoke_windows_acl", invoke)

    published = data_acl.publish_public_ca(source, tmp_path)

    assert published == tmp_path / "Public" / "mission-legal-ca.pem"
    assert published.read_bytes() == source.read_bytes()
    assert not published.with_name(".mission-legal-ca.pem.tmp").exists()
    assert [mode for mode, _paths in calls] == [
        "ProtectSensitive",
        "PreparePublic",
        "ProtectPublic",
    ]


def test_public_ca_source_must_stay_inside_sensitive_root(tmp_path):
    source = tmp_path.parent / "outside-ca.pem"
    source.write_text("certificate", encoding="utf-8")
    try:
        with pytest.raises(data_acl.ServerDataAclError, match="inside the protected"):
            data_acl.publish_public_ca(source, tmp_path)
    finally:
        source.unlink(missing_ok=True)


def test_windows_acl_process_failure_is_not_ignored(monkeypatch, tmp_path):
    completed = mock.Mock(returncode=9, stderr="access denied", stdout="")
    monkeypatch.setattr(data_acl, "_powershell_executable", lambda: "powershell.exe")
    monkeypatch.setattr(data_acl.subprocess, "run", mock.Mock(return_value=completed))

    with pytest.raises(data_acl.ServerDataAclError, match="access denied"):
        data_acl._invoke_windows_acl("ProtectSensitive", (tmp_path, tmp_path / "Public"))

    run = data_acl.subprocess.run
    assert run.call_args.kwargs["check"] is False
    assert run.call_args.args[0][-2:] == ["-Command", data_acl._WINDOWS_ACL_SCRIPT]
    assert run.call_args.kwargs["env"]["MISSION_LEGAL_ACL_MODE"] == "ProtectSensitive"


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell 5.1 contract")
def test_windows_powershell_json_paths_are_flattened():
    paths = (r"C:\Mission Legal\First", r"C:\Mission Legal\Second")

    output = data_acl._invoke_windows_acl("ValidatePaths", paths)

    assert json.loads(output) == list(paths)


def test_tls_reuse_reprotects_both_private_keys(monkeypatch, tmp_path):
    paths = {
        "ca_cert": tmp_path / "ca.pem",
        "ca_key": tmp_path / "ca-key.pem",
        "server_cert": tmp_path / "server.pem",
        "server_key": tmp_path / "server-key.pem",
    }
    for path in paths.values():
        path.write_bytes(b"existing")
    protected = []
    monkeypatch.setattr(tls, "default_tls_paths", lambda: paths)
    monkeypatch.setattr(tls, "_protect_keys", lambda *values: protected.append(values))

    assert tls.generate_local_tls() == paths
    assert protected == [(paths["ca_key"], paths["server_key"])]


def test_setup_installer_and_vm_harness_share_the_sid_acl_contract():
    setup = (REPO_ROOT / "server_setup.py").read_text(encoding="utf-8")
    actions = (
        REPO_ROOT / "deployment" / "installer" / "server_installer_actions.ps1"
    ).read_text(encoding="utf-8")
    harness = (
        REPO_ROOT
        / "deployment"
        / "installer"
        / "validate_server_installer_vm.ps1"
    ).read_text(encoding="utf-8")

    setup_main = setup.split("def main():", 1)[1]
    assert setup_main.index("protect_sensitive_server_data(app_data_dir)") < setup_main.index(
        "_handle_existing_database("
    )
    assert setup_main.index("generate_local_tls(") < setup_main.index(
        "published_ca = publish_public_ca("
    )
    assert 'settings.setValue("server/ca_certificate", str(published_ca))' in setup_main
    assert "Client CA certificate: {published_ca}" in setup_main

    install_action = actions.split('"InstallOrUpdate" {', 1)[1].split(
        '"StartAndVerify" {', 1
    )[0]
    initialization = actions.split("switch ($Action)", 1)[0]
    assert initialization.index("Protect-MissionLegalServerData") < initialization.index(
        "Beginning installer service action"
    )
    assert "Install-OrUpdateService" in install_action
    assert "Publish-MissionLegalPublicCa -AllowMissing" in install_action
    start_action = actions.split('"StartAndVerify" {', 1)[1].split(
        '"StartOnly" {', 1
    )[0]
    assert "Publish-MissionLegalPublicCa" in start_action
    for sid in (
        data_acl.SYSTEM_SID,
        data_acl.ADMINISTRATORS_SID,
        data_acl.USERS_SID,
    ):
        assert sid in actions
        assert sid in harness
    assert "USERNAME" not in actions
    assert "Invoke-StandardUserServerDataProbe" in harness
    for protected_name in (
        "app.db",
        "devices.json",
        "mission-legal-ca-key.pem",
        "mission-legal-server-key.pem",
        "Public\\mission-legal-ca.pem",
    ):
        assert protected_name in harness


@pytest.mark.skipif(
    not _is_elevated_windows(),
    reason="real Windows DACL validation requires elevation",
)
def test_real_windows_acl_application_and_publication(tmp_path):
    root = tmp_path / "server-data"
    tls_root = root / "Configuration" / "tls"
    backups = root / "Backups"
    tls_root.mkdir(parents=True)
    backups.mkdir()
    (root / "app.db").write_bytes(b"sqlite fixture")
    ca_certificate = tls_root / "mission-legal-ca.pem"
    ca_key = tls_root / "mission-legal-ca-key.pem"
    server_key = tls_root / "mission-legal-server-key.pem"
    ca_certificate.write_bytes(b"-----BEGIN CERTIFICATE-----\nfixture\n")
    ca_key.write_bytes(b"private ca")
    server_key.write_bytes(b"private server")

    data_acl.protect_sensitive_server_data(root)
    data_acl.protect_private_key_files(ca_key, server_key)
    published = data_acl.publish_public_ca(ca_certificate, root)

    assert published.read_bytes() == ca_certificate.read_bytes()


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode semantics")
def test_portable_policy_keeps_sensitive_private_and_public_ca_readable(tmp_path):
    source = tmp_path / "Configuration" / "tls" / "mission-legal-ca.pem"
    private_key = source.with_name("mission-legal-ca-key.pem")
    source.parent.mkdir(parents=True)
    source.write_text("certificate", encoding="utf-8")
    private_key.write_text("private", encoding="utf-8")

    data_acl.protect_sensitive_server_data(tmp_path)
    published = data_acl.publish_public_ca(source, tmp_path)

    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert stat.S_IMODE(private_key.stat().st_mode) == 0o600
    assert stat.S_IMODE(published.parent.stat().st_mode) == 0o755
    assert stat.S_IMODE(published.stat().st_mode) == 0o644
