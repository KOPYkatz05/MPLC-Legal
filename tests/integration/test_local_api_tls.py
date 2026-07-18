import os
import socket
import ssl
import subprocess
import sys
import time

import httpx


def _free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def test_server_main_serves_health_over_verified_tls(tmp_path):
    port = _free_port()
    environment = os.environ.copy()
    environment.update(
        {
            "MISSION_LEGAL_DATA_DIR": str(tmp_path / "database"),
            "MISSIONS_ROOT": str(tmp_path / "documents"),
            "MISSION_LEGAL_SERVER_PROCESS": "1",
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-B",
            "server_main.py",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=os.getcwd(),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    ca_certificate = (
        tmp_path
        / "database"
        / "Configuration"
        / "tls"
        / "mission-legal-ca.pem"
    )
    url = f"https://127.0.0.1:{port}/health"
    try:
        deadline = time.monotonic() + 20
        last_error = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            if ca_certificate.exists():
                try:
                    response = httpx.get(
                        url,
                        verify=ssl.create_default_context(
                            cafile=str(ca_certificate)
                        ),
                        timeout=1,
                    )
                    if response.status_code == 200:
                        assert response.json()["status"] == "ok"
                        return
                    last_error = AssertionError(response.text)
                except Exception as exc:
                    last_error = exc
            time.sleep(0.2)
        stdout, stderr = process.communicate(timeout=2)
        raise AssertionError(
            f"TLS server did not become healthy: {last_error}\n{stdout}\n{stderr}"
        )
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
