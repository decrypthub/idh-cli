from __future__ import annotations

import os
import json

import pytest

from idh.config import (
    clear_endpoints,
    load_saved_endpoints,
    load_selected,
    remove_endpoint,
    save_endpoint,
    save_endpoint_token,
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


def test_selected_and_session_token_round_trip(tmp_path) -> None:
    path = tmp_path / "connections.json"
    save_endpoint(AppEndpoint.from_url("192.168.1.10:8088").with_kind("device"), path)
    save_endpoint(AppEndpoint.from_url("192.168.1.11:8088").with_kind("device"), path)

    save_selected("http://192.168.1.11:8088/api/mcp", path)
    assert load_selected(path) == "http://192.168.1.11:8088/api/mcp"
    # 无关写（增删端点）不清掉选中
    save_endpoint(AppEndpoint.from_url("192.168.1.12:8088").with_kind("device"), path)
    assert load_selected(path) == "http://192.168.1.11:8088/api/mcp"

    assert save_endpoint_token("192.168.1.11:8088", "tok-abc", path) is True
    assert save_endpoint_token("192.168.1.99:8088", "tok-abc", path) is False
    loaded = {item.mcp_url: item for item in load_saved_endpoints(path)}
    assert loaded["http://192.168.1.11:8088/api/mcp"].properties["session_token"] == "tok-abc"
    assert "session_token" not in loaded["http://192.168.1.10:8088/api/mcp"].properties


def test_invalid_saved_config_is_reported(tmp_path) -> None:
    path = tmp_path / "connections.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot read connection config"):
        load_saved_endpoints(path)
