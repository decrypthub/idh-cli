import pytest

from idh.gateway import TargetResolutionError, resolve_target
from idh.models import AppEndpoint


def endpoint(**properties: str) -> AppEndpoint:
    return AppEndpoint(
        service_name="Demo-A1._idh-mcp._tcp.local.",
        server="iphone.local",
        addresses=("fe80::1", "192.168.1.8"),
        port=8088,
        properties=properties,
    )


def test_endpoint_prefers_ipv4_and_builds_urls() -> None:
    item = endpoint(bundle="com.example.demo", app_name="Demo")
    assert item.primary_address == "192.168.1.8"
    assert item.panel_url == "http://192.168.1.8:8088/"
    assert item.mcp_url == "http://192.168.1.8:8088/api/mcp"
    assert item.as_dict()["target_id"] == item.key


def test_endpoint_properties_can_be_refreshed() -> None:
    item = endpoint(status="unreachable")
    assert item.with_properties({"status": "online"}).properties["status"] == "online"


def test_manual_endpoint_accepts_mcp_url() -> None:
    item = AppEndpoint.from_url("http://127.0.0.1:9000/prefix/api/mcp")
    assert item.panel_url == "http://127.0.0.1:9000/prefix/"
    assert item.mcp_url == "http://127.0.0.1:9000/prefix/api/mcp"


def test_resolve_target_by_bundle_and_index() -> None:
    first = endpoint(bundle="com.example.first")
    second = AppEndpoint(
        service_name="Other._idh-mcp._tcp.local.",
        server="ipad.local",
        addresses=("192.168.1.9",),
        port=8088,
        properties={"bundle": "com.example.second"},
    )
    assert resolve_target([first, second], "com.example.second") is second
    assert resolve_target([first, second], "1") is first


def test_resolve_target_returns_structured_candidates_for_ambiguity() -> None:
    first = endpoint(bundle="com.example.same", app_name="Same")
    second = AppEndpoint(
        service_name="Other._idh-mcp._tcp.local.",
        server="ipad.local",
        addresses=("192.168.1.9",),
        port=8088,
        properties={"id": "other-id", "bundle": "com.example.same", "app_name": "Same"},
    )
    with pytest.raises(TargetResolutionError) as raised:
        resolve_target([first, second], "com.example.same")

    assert raised.value.code == "ambiguous_target"
    assert {item["target_id"] for item in raised.value.candidates} == {first.key, "other-id"}


