from server import networking


def test_discovery_prefers_routed_private_address_and_deduplicates_resolution():
    def route_probe(target):
        return "192.168.108.50" if target == networking._ROUTE_PROBES[0] else None

    def resolver(_name, _port, _family, _kind):
        return [
            (None, None, None, None, ("192.168.108.50", 0)),
            (None, None, None, None, ("10.0.0.12", 0)),
            (None, None, None, None, ("127.0.0.1", 0)),
        ]

    assert networking.discover_lan_ipv4_addresses(
        "mission-server",
        route_probe=route_probe,
        resolver=resolver,
    ) == ("192.168.108.50", "10.0.0.12")


def test_discovery_excludes_public_loopback_and_link_local_addresses():
    def resolver(_name, _port, _family, _kind):
        return [
            (None, None, None, None, ("8.8.8.8", 0)),
            (None, None, None, None, ("127.0.0.1", 0)),
            (None, None, None, None, ("169.254.20.4", 0)),
        ]

    assert networking.discover_lan_ipv4_addresses(
        "mission-server",
        route_probe=lambda _target: None,
        resolver=resolver,
    ) == ()


def test_preferred_server_url_uses_lan_ip_then_hostname_fallback():
    assert networking.preferred_server_url(
        8765,
        hostname="MISSION-SERVER",
        addresses=("192.168.108.50",),
    ) == "https://192.168.108.50:8765"
    assert networking.preferred_server_url(
        8765,
        hostname="MISSION-SERVER",
        addresses=(),
    ) == "https://MISSION-SERVER:8765"
