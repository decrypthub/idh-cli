from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from idh.cli import main
from idh.config import load_saved_endpoints, save_endpoint
from idh.gateway import GatewayServer
from idh.http_mcp import probe_endpoint
from idh.models import AppEndpoint


class _HealthHandler(BaseHTTPRequestHandler):
    body: dict[str, object] = {"ok": True, "service": "idhjd", "version": 1, "apps": []}

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        payload = json.dumps(self.body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_: object) -> None:
        pass


@pytest.fixture
def health_endpoint(monkeypatch: pytest.MonkeyPatch) -> AppEndpoint:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield AppEndpoint.from_url(f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_empty_health_is_an_online_device(health_endpoint: AppEndpoint) -> None:
    _HealthHandler.body = {"ok": True, "service": "idhjd", "version": 1, "apps": []}

    probed = probe_endpoint(health_endpoint)

    assert probed.kind == "device"
    assert probed.properties["status"] == "online"
    assert probed.properties["app_count"] == "0"
    assert probed.observed_apps == ()
    assert probed.as_dict()["web"] is None


def test_health_lists_multiple_apps(health_endpoint: AppEndpoint) -> None:
    _HealthHandler.body = {
        "ok": True,
        "service": "idhjd",
        "version": 1,
        "apps": [
            {"bundleId": "com.example.one", "pid": 1, "processGeneration": "a"},
            {"bundleId": "com.example.two", "pid": 2, "processGeneration": "b"},
        ],
    }

    probed = probe_endpoint(health_endpoint)

    assert probed.kind == "device"
    assert probed.observed_apps == ("com.example.one", "com.example.two")
    assert probed.properties["app_count"] == "2"


def test_failed_probe_keeps_saved_kind(health_endpoint: AppEndpoint) -> None:
    offline = health_endpoint.with_kind("device")
    _HealthHandler.body = {"ok": False}

    probed = probe_endpoint(offline, timeout=0.2)

    assert probed.kind == "device"
    assert probed.properties["status"] == "unreachable"


def test_device_panel_url_is_refused(health_endpoint: AppEndpoint) -> None:
    _HealthHandler.body = {"ok": True, "service": "idhjd", "version": 1, "apps": []}
    gateway = GatewayServer(lambda: [health_endpoint])

    reply = gateway.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "idh_get_panel_url", "arguments": {}},
        }
    )

    assert reply["result"]["isError"] is True
    assert reply["result"]["structuredContent"]["error"]["code"] == "device_panel_unavailable"


def test_force_save_keeps_unrecognized_address_until_a_later_probe(
    health_endpoint: AppEndpoint,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "connections.json"
    monkeypatch.setenv("IDH_CONFIG_PATH", str(config))
    _HealthHandler.body = {"ok": True, "service": "idhjd", "version": 1, "apps": []}
    missing = "http://127.0.0.1:9"

    assert main(["connect", missing, "--force"]) == 0
    assert json.loads(config.read_text(encoding="utf-8"))["version"] == 1
    assert load_saved_endpoints(config)[0].kind is None

    assert main(["connect", health_endpoint.base_url]) == 0
    kinds = {item.mcp_url: item.kind for item in load_saved_endpoints(config)}
    assert kinds[health_endpoint.mcp_url] == "device"
    assert kinds[AppEndpoint.from_url(missing).mcp_url] is None

    save_endpoint(health_endpoint.with_kind("device"), config)
    _HealthHandler.body = {"ok": False}
    assert main(["connect", health_endpoint.base_url, "--force"]) == 0
    saved = load_saved_endpoints(config)
    again = next(item for item in saved if item.mcp_url == health_endpoint.mcp_url)
    assert again.kind == "device"
