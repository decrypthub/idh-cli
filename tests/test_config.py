from __future__ import annotations

import os
import json

import pytest

from idh.config import (
    clear_endpoints,
    load_saved_endpoints,
    load_selected,
    remove_endpoint,
    replace_endpoint,
    save_endpoint,
    save_selected,
)
from idh.models import AppEndpoint


def test_saved_endpoints_round_trip_and_deduplicate(tmp_path) -> None:
    path = tmp_path / "connections.json"
    endpoint = AppEndpoint.from_url("192.168.100.65:8088")

    assert save_endpoint(endpoint, path) is True
    assert save_endpoint(endpoint, path) is False
    assert [item.mcp_url for item in load_saved_endpoints(path)] == [
        "http://192.168.100.65:8088/api/mcp"
    ]
    assert json.loads(path.read_text())["version"] == 1
    # Windows does not represent POSIX permission bits; its user ACL is separate.
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_remove_and_clear_saved_endpoints(tmp_path) -> None:
    path = tmp_path / "connections.json"
    first = AppEndpoint.from_url("192.168.1.10:8088")
    second = AppEndpoint.from_url("192.168.1.11:8088")
    save_endpoint(first, path)
    save_endpoint(second, path)

    assert remove_endpoint("192.168.1.10:8088", path) is True
    assert remove_endpoint("192.168.1.10:8088", path) is False
    assert clear_endpoints(path) == 1
    assert load_saved_endpoints(path) == []


def test_same_address_updates_kind_and_keeps_old_files(tmp_path) -> None:
    path = tmp_path / "connections.json"
    path.write_text(
        json.dumps({"version": 1, "endpoints": ["http://192.168.100.65:8088/api/mcp"]}),
        encoding="utf-8",
    )
    loaded = load_saved_endpoints(path)
    assert loaded[0].kind is None

    assert save_endpoint(loaded[0].with_kind("device"), path) is True
    assert save_endpoint(loaded[0].with_kind("device"), path) is False
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["version"] == 2
    assert saved["endpoints"] == [
        {"url": "http://192.168.100.65:8088/api/mcp", "kind": "device"}
    ]
    assert load_saved_endpoints(path)[0].kind == "device"

    assert save_endpoint(AppEndpoint.from_url("192.168.100.65:8088"), path) is False
    assert load_saved_endpoints(path)[0].kind == "device"


def test_selected_round_trip(tmp_path) -> None:
    path = tmp_path / "connections.json"
    save_endpoint(AppEndpoint.from_url("192.168.1.10:8088").with_kind("device"), path)
    save_endpoint(AppEndpoint.from_url("192.168.1.11:8088").with_kind("device"), path)

    save_selected("http://192.168.1.11:8088/api/mcp", path)
    assert load_selected(path) == "http://192.168.1.11:8088/api/mcp"
    # 无关写（增删端点）不清掉选中
    save_endpoint(AppEndpoint.from_url("192.168.1.12:8088").with_kind("device"), path)
    assert load_selected(path) == "http://192.168.1.11:8088/api/mcp"


def test_invalid_saved_config_is_reported(tmp_path) -> None:
    path = tmp_path / "connections.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot read connection config"):
        load_saved_endpoints(path)


def test_replace_endpoint_moves_address_and_selected(tmp_path) -> None:
    """USB 转发口漂移：重连后一条写入换掉旧地址，并带走 selected 指针。"""
    path = tmp_path / "connections.json"
    old = AppEndpoint.from_url("http://127.0.0.1:28001").with_kind("device")
    other = AppEndpoint.from_url("http://127.0.0.1:28002").with_kind("device")
    save_endpoint(old, path)
    save_endpoint(other, path)
    save_selected(old.mcp_url, path)

    new = AppEndpoint.from_url("http://127.0.0.1:28501").with_kind("device")
    assert replace_endpoint(old.mcp_url, new, path) is True

    saved = load_saved_endpoints(path)
    assert {item.mcp_url for item in saved} == {new.mcp_url, other.mcp_url}
    # 旧地址不能残留，selected 跟着新地址走
    assert old.mcp_url not in {item.mcp_url for item in saved}
    assert load_selected(path) == new.mcp_url


def test_replace_endpoint_deduplicates_and_keeps_other_selection(tmp_path) -> None:
    path = tmp_path / "connections.json"
    old = AppEndpoint.from_url("http://127.0.0.1:28001").with_kind("device")
    existing = AppEndpoint.from_url("http://127.0.0.1:28009").with_kind("device")
    save_endpoint(old, path)
    save_endpoint(existing, path)
    save_selected(existing.mcp_url, path)

    # 新地址本来就在列表里：只留一条，且 selected 不该被搬到别处
    assert replace_endpoint(old.mcp_url, existing, path) is True
    saved = load_saved_endpoints(path)
    assert [item.mcp_url for item in saved] == [existing.mcp_url]
    assert load_selected(path) == existing.mcp_url

    # 不存在的条目：什么都不写
    assert replace_endpoint("http://127.0.0.1:28100", old, path) is False
    assert [item.mcp_url for item in load_saved_endpoints(path)] == [existing.mcp_url]


def test_replace_endpoint_keeps_kind_when_probe_lost_it(tmp_path) -> None:
    """重连探活失败时 probed.kind 为空，不能把 device 降级成未知条目。"""
    path = tmp_path / "connections.json"
    old = AppEndpoint.from_url("http://127.0.0.1:28001").with_kind("device")
    save_endpoint(old, path)

    blind = AppEndpoint.from_url("http://127.0.0.1:28501")  # 没有 kind，模拟探活失败
    assert replace_endpoint(old.mcp_url, blind, path) is True
    saved = load_saved_endpoints(path)
    assert [item.mcp_url for item in saved] == ["http://127.0.0.1:28501/api/mcp"]
    assert saved[0].kind == "device"


def test_usb_identity_survives_a_reload(tmp_path) -> None:
    """USB 条目必须记住 udid，否则重启后 resolve_endpoint 无法重建转发口。"""
    path = tmp_path / "connections.json"
    usb = AppEndpoint.from_url("http://127.0.0.1:29001").with_kind("device").with_properties(
        {"transport": "usb", "usb_udid": "00008110-000A1C2E0A88801E"}
    )
    save_endpoint(usb, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["endpoints"][0]["usb"] == "00008110-000A1C2E0A88801E"

    loaded = load_saved_endpoints(path)[0]
    assert loaded.properties.get("usb_udid") == "00008110-000A1C2E0A88801E"
    assert loaded.properties.get("transport") == "usb"
    assert loaded.kind == "device"
