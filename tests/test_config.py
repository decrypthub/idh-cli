from __future__ import annotations

import json

import pytest

from idh.config import clear_endpoints, load_saved_endpoints, remove_endpoint, save_endpoint
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


def test_invalid_saved_config_is_reported(tmp_path) -> None:
    path = tmp_path / "connections.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot read connection config"):
        load_saved_endpoints(path)
