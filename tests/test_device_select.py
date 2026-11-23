from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Queue
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from idh.cli import main

PANEL_SESSION_ID = "fd6eb6bd-021b-4915-b1f7-4de4a4f03a80"


class DeviceHandler(BaseHTTPRequestHandler):
    status_code = 200
    authorization: list[str | None] = []
    revision = "0"
    limits = {"maxRecords": 2000, "maxBytes": 2097152, "recordSeconds": 300}
    settings_posts: list[dict] = []

    def do_GET(self) -> None:
        path, _, query = self.path.partition("?")
        if path == "/api/session-settings":
            self._send(200, json.dumps({
                "ok": True, "revision": self.revision, "deviceSession": self.limits,
            }).encode())
            return
        if path == "/api/sessions" or path.startswith("/api/sessions/"):
            session = {"sessionId": PANEL_SESSION_ID, "bundleId": "com.example.fixture", "count": 40}
            if path == "/api/sessions":
                payload = {"ok": True, "sessions": [session]}
            elif path == f"/api/sessions/{PANEL_SESSION_ID}":
                payload = {"ok": True, "session": session}
            elif path == f"/api/sessions/{PANEL_SESSION_ID}/events" and query == "limit=20&after_seq=20":
                payload = {"ok": True, "events": [{"seq": 21}], "nextAfterSeq": 21, "hasMore": True}
            else:
                self._send(404, b"")
                return
            self._send(200, json.dumps(payload).encode())
            return
        if self.path != "/health":
            self.send_error(404)
            return
        body = json.dumps({"ok": True, "service": "idhjd", "version": 1, "apps": []}).encode()
        self._send(200, body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        message = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/session-settings":
            self.settings_posts.append(message)
            if message["revision"] != self.revision:
                self._send(409, b'{"error":"revision_conflict"}')
            else:
                DeviceHandler.limits = {**self.limits, **message["deviceSession"]}
                DeviceHandler.revision = "next"
                self._send(200, json.dumps({
                    "ok": True, "revision": self.revision, "deviceSession": self.limits,
                }).encode())
            return
        self.authorization.append(self.headers.get("Authorization"))
        if self.status_code == 401:
            self._send(401, b"")
            return
        if "id" not in message:
            self._send(202, b"")
            return
        method = message.get("method")
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "serverInfo": {"name": "idhjd", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {"name": "list_sessions", "inputSchema": {"type": "object"}},
                    {"name": "disassemble", "inputSchema": {"type": "object"}},
                ]
            }
        else:
            result = {
                "content": [{"type": "text", "text": "kept"}],
                "structuredContent": {"ok": True, "sessions": [{"sessionId": "saved"}]},
            }
        self._send(200, json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}).encode())

    def _send(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        pass


@pytest.fixture
def device_url() -> str:
    DeviceHandler.status_code = 200
    DeviceHandler.authorization = []
    DeviceHandler.revision = "0"
    DeviceHandler.limits = {"maxRecords": 2000, "maxBytes": 2097152, "recordSeconds": 300}
    DeviceHandler.settings_posts = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), DeviceHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_empty_device_still_reads_history(
    device_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["call", "list_sessions", "--endpoint", device_url, "--no-saved", "--json"]
    )
    assert code == 0, capsys.readouterr().err
    output = json.loads(capsys.readouterr().out)
    assert output["structuredContent"]["sessions"][0]["sessionId"] == "saved"
    assert DeviceHandler.authorization and set(DeviceHandler.authorization) == {None}


def test_device_error_is_not_an_empty_history(
    device_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    DeviceHandler.status_code = 401
    code = main(["call", "list_sessions", "--endpoint", device_url, "--no-saved", "--json"])
    assert code == 1
    assert "401" in capsys.readouterr().err


def test_device_tools_returns_device_list(
    device_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["tools", "--endpoint", device_url, "--no-saved", "--json"])
    assert code == 0, capsys.readouterr().err
    names = [tool["name"] for tool in json.loads(capsys.readouterr().out)["tools"]]
    assert names == ["list_sessions", "disassemble"]


def test_status_lists_a_device_with_no_apps(device_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["status", "--endpoint", device_url, "--no-saved", "--json"])
    assert code == 0, capsys.readouterr().err
    payload = json.loads(capsys.readouterr().out)
    assert payload["connections"][0]["kind"] == "device"
    assert payload["connections"][0]["online"] is True
    assert payload["targets"][0]["apps"] == []


def test_two_devices_require_an_address(
    device_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    extra = ThreadingHTTPServer(("127.0.0.1", 0), DeviceHandler)
    thread = threading.Thread(target=extra.serve_forever, daemon=True)
    thread.start()
    other = f"http://127.0.0.1:{extra.server_port}"
    try:
        code = main(
            ["call", "list_sessions", "--endpoint", device_url, "--endpoint", other, "--no-saved"]
        )
        assert code == 1
        assert "connections online" in capsys.readouterr().err
    finally:
        extra.shutdown()
        extra.server_close()
        thread.join()


def test_device_calls_send_no_credential(
    device_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    for tool, arguments in (
        ("get_process_identity", '{"bundleId": "com.example.app"}'),
        ("list_sessions", None),
        ("disassemble", '{"bundleId": "com.example.app", "address": "0x1"}'),
    ):
        DeviceHandler.authorization = []
        command = ["call", tool, "--endpoint", device_url, "--no-saved", "--json"]
        if arguments is not None:
            command += ["--arguments", arguments]
        code = main(command)
        assert code == 0, capsys.readouterr().err
        assert set(DeviceHandler.authorization) == {None}


def test_panel_reads_history_independently_of_online_apps(
    device_url: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel_servers: Queue[ThreadingHTTPServer] = Queue()
    serve_forever = ThreadingHTTPServer.serve_forever

    def publish_server(server: ThreadingHTTPServer) -> None:
        panel_servers.put(server)
        serve_forever(server)

    monkeypatch.setattr(ThreadingHTTPServer, "serve_forever", publish_server)
    args = ["--no-auto-update", "panel", "--endpoint", device_url, "--no-saved", "--bind", "127.0.0.1:0"]
    thread = threading.Thread(target=main, args=(args,), daemon=True)
    thread.start()
    panel = panel_servers.get(timeout=5)
    base = f"http://127.0.0.1:{panel.server_port}"
    try:
        with urlopen(base + "/", timeout=3) as response:
            page = response.read().decode()
            assert "id='idh-session'" in page and "id='tabbar'" in page
            assert "class='splitter'" in page and 'class="hdr-raven"' in page
        with urlopen(base + "/panel-device.js", timeout=3) as response:
            assert b"IDHDevicePanel" in response.read()
        with urlopen(base + "/wechat-follow.png", timeout=3) as response:
            assert response.read(8) == b"\x89PNG\r\n\x1a\n"
        with urlopen(base + "/health", timeout=3) as response:
            assert json.load(response)["apps"] == []
        with urlopen(base + "/api/sessions", timeout=3) as response:
            session = json.load(response)["sessions"][0]
            assert session["sessionId"] == PANEL_SESSION_ID
        detail = f"{base}/api/sessions/{PANEL_SESSION_ID}"
        with urlopen(detail, timeout=3) as response:
            assert json.load(response)["session"] == session
        with urlopen(detail + "/events?limit=20&after_seq=20", timeout=3) as response:
            result = json.load(response)
            assert result["events"] == [{"seq": 21}] and result["nextAfterSeq"] == 21
        for path in ("/api/sessions/missing", f"/api/sessions/{PANEL_SESSION_ID}/unknown", "/api/stats"):
            with pytest.raises(HTTPError) as error:
                urlopen(base + path, timeout=3)
            assert error.value.code == 404
        with urlopen(base + "/health", timeout=3) as response:
            assert json.load(response)["ok"] is True
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + "/api/sessions", headers={"Host": "unknown.example"}), timeout=3)
        assert error.value.code == 400
        settings = base + "/api/session-settings"
        with urlopen(settings, timeout=3) as response:
            config = json.load(response)
        assert config["deviceSession"] == DeviceHandler.limits
        data = json.dumps({"revision": config["revision"], "deviceSession": {"maxRecords": 8}}).encode()
        headers = {"Content-Type": "application/json", "Origin": base}
        with pytest.raises(HTTPError) as error:
            urlopen(Request(settings, data=data, headers={**headers, "Origin": "http://unknown.example"}), timeout=3)
        assert error.value.code == 403 and DeviceHandler.settings_posts == []
        with urlopen(Request(settings, data=data, headers=headers), timeout=3) as response:
            changed = json.load(response)
        assert changed["revision"] == "next" and changed["deviceSession"]["maxRecords"] == 8
        with pytest.raises(HTTPError) as error:
            urlopen(Request(settings, data=data, headers=headers), timeout=3)
        assert error.value.code == 409
        assert json.load(error.value)["error"] == "revision_conflict"
    finally:
        panel.shutdown()
        thread.join(timeout=5)


def test_panel_accepts_a_lan_address(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def online(endpoint, timeout=1.0):
        return endpoint.with_kind("device").with_properties({"status": "online", "app_count": "0"})

    monkeypatch.setattr("idh.cli.probe_endpoint", online)
    code = main(["panel", "--endpoint", "http://10.0.0.8:8088", "--no-saved"])
    # 不可达是传输错误，不再被「只允许 127.0.0.1 转发」拦下
    assert code == 2
    assert "127.0.0.1" not in capsys.readouterr().err


def test_lan_address_is_used_directly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def online(endpoint, timeout=1.0):
        return endpoint.with_kind("device").with_properties({"status": "online", "app_count": "0"})

    monkeypatch.setattr("idh.cli.probe_endpoint", online)
    code = main(
        ["call", "10.0.0.8:8088", "list_sessions", "--endpoint", "http://10.0.0.8:8088", "--no-saved"]
    )
    # 不可达是传输错误，不再被「只允许 127.0.0.1 转发」拦下
    assert code == 1
    assert "127.0.0.1" not in capsys.readouterr().err
