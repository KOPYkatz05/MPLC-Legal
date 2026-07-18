import os
import subprocess
import sys
import textwrap


def test_authenticated_document_round_trip(tmp_path):
    environment = os.environ.copy()
    environment.update(
        {
            "MISSION_LEGAL_DATA_DIR": str(tmp_path / "database"),
            "MISSIONS_ROOT": str(tmp_path / "documents"),
            "MISSION_LEGAL_SERVER_PROCESS": "1",
        }
    )
    script = textwrap.dedent(
        """
        from pathlib import Path
        from fastapi.testclient import TestClient
        from database.db import init_db
        from server.app import create_app
        from server.security import DeviceCredentialStore, PairingCodeStore

        init_db()
        root = Path(__import__('os').environ['MISSION_LEGAL_DATA_DIR'])
        devices = DeviceCredentialStore(root / 'test-devices.json')
        pairing = PairingCodeStore(root / 'test-pairing.json')
        code = pairing.create()['code']
        client = TestClient(create_app(devices, pairing, manage_lifecycle=False))
        paired = client.post('/pair', json={
            'code': code,
            'device_name': 'Integration client',
            'deferred_confirmation': True,
        })
        assert paired.status_code == 201, paired.text
        credentials = paired.json()
        headers = {
            'X-Device-ID': credentials['device_id'],
            'X-Device-Credential': credentials['credential'],
        }
        confirmed = client.post('/pair/confirm', headers=headers)
        assert confirmed.status_code == 200, confirmed.text
        created = client.post('/v1/missionaries', headers=headers, json={
            'full_name': 'Integration Example',
            'missionary_code': '990004',
        })
        assert created.status_code == 201, created.text
        missionary = created.json()
        uploaded = client.post(
            '/v1/documents/upload',
            headers=headers,
            data={
                'missionary_id': str(missionary['id']),
                'document_type': 'PASSPORT',
                'workflow_stage': 'INTERPOL',
                'ocr_confirmed_data': '{}',
            },
            files={'file': ('passport.pdf', b'%PDF-test', 'application/pdf')},
        )
        assert uploaded.status_code == 201, uploaded.text
        document = uploaded.json()
        content = client.get(
            f"/v1/documents/{document['id']}/content", headers=headers
        )
        assert content.status_code == 200, content.text
        assert content.content == b'%PDF-test'
        updates = client.post(
            f"/v1/documents/{document['id']}/apply-updates",
            headers=headers,
            json={'document_type': 'PASSPORT', 'confirmed_data': {}},
        )
        assert updates.status_code == 200, updates.text
        """
    )

    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
