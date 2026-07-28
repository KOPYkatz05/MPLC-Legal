import json

from services import lan_discovery


def test_discovery_rejects_non_object_json_without_crashing():
    responder = lan_discovery.LanDiscoveryResponder(
        enabled_provider=lambda: True,
        ca_certificate_provider=lambda: "",
        port_provider=lambda: 8765,
    )

    for payload in (b"[]", b"null", b'"text"', b"123"):
        assert responder._query_nonce(payload) is None


def test_discovery_offer_uses_packet_source_ip_and_stays_small():
    nonce = "a" * 32
    fingerprint = "b" * 64
    packet = json.dumps(
        {
            "type": "mission-legal-server",
            "protocol": lan_discovery.DISCOVERY_PROTOCOL,
            "nonce": nonce,
            "server_id": fingerprint,
            "name": "Secretary Laptop",
            "port": 8765,
            "ca_sha256": fingerprint,
        },
        separators=(",", ":"),
    ).encode("utf-8")

    offer = lan_discovery._parse_response(packet, "192.168.108.50", nonce)

    assert len(packet) < 512
    assert offer.server_url == "https://192.168.108.50:8765"
    assert offer.server_id == fingerprint


def test_discovery_offer_rejects_wrong_nonce_and_public_source():
    nonce = "a" * 32
    fingerprint = "b" * 64
    packet = json.dumps(
        {
            "type": "mission-legal-server",
            "protocol": lan_discovery.DISCOVERY_PROTOCOL,
            "nonce": "c" * 32,
            "server_id": fingerprint,
            "name": "Secretary Laptop",
            "port": 8765,
            "ca_sha256": fingerprint,
        }
    ).encode("utf-8")

    assert lan_discovery._parse_response(packet, "192.168.108.50", nonce) is None
    correct_packet = packet.replace(("c" * 32).encode(), ("a" * 32).encode())
    assert (
        lan_discovery._parse_response(
            correct_packet,
            "8.8.8.8",
            "a" * 32,
        )
        is None
    )


def test_bootstrap_certificate_must_match_advertised_fingerprint(monkeypatch):
    certificate = (
        "-----BEGIN CERTIFICATE-----\nPUBLIC CA\n-----END CERTIFICATE-----\n"
    )
    fingerprint = lan_discovery.certificate_sha256(certificate)
    offer = lan_discovery._DiscoveredOffer(
        server_id=fingerprint,
        name="Secretary Laptop",
        server_url="https://192.168.108.50:8765",
        ca_sha256=fingerprint,
    )

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "server_id": fingerprint,
                "ca_sha256": fingerprint,
                "ca_certificate_pem": certificate,
            }

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["verify"] is False
            assert kwargs["trust_env"] is False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, path):
            assert path == "/pair/bootstrap"
            return Response()

    monkeypatch.setattr(lan_discovery.httpx, "Client", Client)

    discovered = lan_discovery._fetch_pairing_certificate(offer, timeout=1)

    assert discovered.ca_sha256 == fingerprint
    assert discovered.ca_certificate_pem == certificate
