from __future__ import annotations

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from idh.cli import main
from idh.gateway import (
    GatewayServer,
    TransparentProxy,
    is_mutating_tool,
    resolve_live_target,
    serve_stdio,
)
from idh.http_mcp import MCPHTTPClient
from idh.models import AppEndpoint


class RemoteHandler(BaseHTTPRequestHandler):
    methods: ClassVar[list[str]] = []
    tool_arguments: ClassVar[list[dict[str, object]]] = []

    def do_GET(self) -> None:
        if self.path != "/api/stats":
            self.send_error(404)
            return
        body = json.dumps(
            {
                "version": "1.21.0",
                "process": {
                    "appName": "Demo App",
                    "bundleId": "com.example.demo",
                    "pid": 42,
                },
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        message = json.loads(self.rfile.read(length))
        self.methods.append(message.get("method", ""))
        if "id" not in message:
            self.send_response(202)
            self.send_header("Mcp-Session-Id", "test-session")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        method = message.get("method")
        if method == "tools/list":
            result = {
                "tools": [
                    {"name": "get_stats", "inputSchema": {"type": "object"}},
                    {"name": "export_events", "inputSchema": {"type": "object"}},
                    {
                        "name": "clear_events",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                ]
            }
        elif method == "tools/call":
            params = message.get("params", {})
            arguments = params.get("arguments", {})
            self.tool_arguments.append(arguments)
            if params.get("name") == "export_events":
                after = int(arguments.get("after_seq", 0))
                upper = min(int(arguments.get("until_seq", 3)), 3)
                limit = int(arguments.get("limit", 25))
                candidates = [seq for seq in (1, 2, 3) if after < seq <= upper]
                selected = candidates[:limit]
                has_more = len(candidates) > len(selected)
                structured = {
                    "format": "iosdecrypthub.events.v1",
                    "server_version": "1.25.0",
                    "process": {"bundleId": "com.example.demo"},
                    "retention_note": "test retention note",
                    "sensitive_data_warning": "test sensitive warning",
                    "events": [
                        {"seq": seq, "categoryName": "digest", "outputHex": f"{seq:02x}"}
                        for seq in selected
                    ],
                    "cursor": {
                        "snapshot_until_seq": upper,
                        "next_after_seq": selected[-1] if has_more else None,
                        "has_more": has_more,
                    },
                }
                result = {"structuredContent": structured, "isError": False}
            else:
                result = {"content": [{"type": "text", "text": "remote result"}]}
        else:
            result = {"protocolVersion": "2025-03-26", "capabilities": {}}
        body = json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "test-session")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        pass


@pytest.fixture
def remote_endpoint() -> AppEndpoint:
    RemoteHandler.methods.clear()
    RemoteHandler.tool_arguments.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), RemoteHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield AppEndpoint.from_url(f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_http_client_preserves_session_and_notifications(remote_endpoint: AppEndpoint) -> None:
    client = MCPHTTPClient(remote_endpoint)
    response = client.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert response["id"] == 1
    assert client.session_id == "test-session"
    assert client.send({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_live_target_probes_and_filters_offline(remote_endpoint: AppEndpoint) -> None:
    offline = remote_endpoint.with_properties(
        {"id": "offline-host", "bundle": "com.example.demo", "status": "offline"}
    )

    resolved = resolve_live_target([offline], "com.example.demo")

    assert resolved.key == "offline-host"
    assert resolved.properties["status"] == "online"


def test_gateway_instructions_define_agent_workflow_without_semantic_orchestration() -> None:
    gateway = GatewayServer(list)
    initialized = gateway.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        }
    )
    instructions = initialized["result"]["instructions"]
    assert "idh_list_devices" in instructions
    assert "name/bundle field" in instructions
    assert "ask the user" in instructions
    assert "idh_get_tool_schema" in instructions
    assert "same-window co-occurrence" in instructions
    assert "symbolicate.symbol_source" in instructions
    assert "scan.coverage_complete" in instructions
    assert "export_events" in instructions
    assert "cursor.snapshot_until_seq" in instructions
    assert "never assume or invent them" in instructions

    listed = gateway.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = {tool["name"]: tool for tool in listed["result"]["tools"]}
    assert "idh_prepare_analysis" not in tools
    assert "analyze_app" not in tools
    assert "only returns facts" in tools["idh_list_devices"]["description"]
    assert "does not understand natural language" in tools["idh_call_tool"]["description"]


def test_gateway_lists_and_calls_remote_tools(remote_endpoint: AppEndpoint) -> None:
    gateway = GatewayServer(lambda: [remote_endpoint])
    listed = gateway.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "idh_list_tools", "arguments": {"target": "1"}},
        }
    )
    assert listed["result"]["structuredContent"]["tools"][0]["name"] == "get_stats"
    assert "inputSchema" not in listed["result"]["structuredContent"]["tools"][0]

    called = gateway.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "idh_call_tool",
                "arguments": {"target": "1", "name": "get_stats", "arguments": {}},
            },
        }
    )
    assert called["result"]["content"][0]["text"] == "remote result"
    assert RemoteHandler.methods == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]


def test_gateway_returns_full_schema_on_demand(remote_endpoint: AppEndpoint) -> None:
    gateway = GatewayServer(lambda: [remote_endpoint])
    response = gateway.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "idh_get_tool_schema",
                "arguments": {"target": "1", "tool_name": "get_stats"},
            },
        }
    )
    tool = response["result"]["structuredContent"]["tool"]
    assert tool["name"] == "get_stats"
    assert tool["inputSchema"] == {"type": "object"}


def test_gateway_requires_confirmation_for_mutating_tool(remote_endpoint: AppEndpoint) -> None:
    gateway = GatewayServer(lambda: [remote_endpoint])
    blocked = gateway.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "idh_call_tool",
                "arguments": {
                    "target": "1",
                    "tool_name": "clear_events",
                    "tool_arguments": {},
                },
            },
        }
    )
    assert blocked["result"]["isError"] is True
    error = blocked["result"]["structuredContent"]["error"]
    assert error["code"] == "mutation_confirmation_required"
    assert RemoteHandler.methods == []

    allowed = gateway.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "idh_call_tool",
                "arguments": {
                    "target": "1",
                    "tool_name": "clear_events",
                    "tool_arguments": {},
                    "allow_mutation": True,
                },
            },
        }
    )
    assert allowed["result"]["content"][0]["text"] == "remote result"


def test_future_mutating_tool_prefix_is_guarded() -> None:
    assert is_mutating_tool("set_future_option") is True
    assert is_mutating_tool("clear_future_cache") is True
    assert is_mutating_tool("get_stats") is False


def test_stdio_transparent_proxy(remote_endpoint: AppEndpoint) -> None:
    proxy = TransparentProxy(lambda: [remote_endpoint], "1")
    source = io.StringIO(
        '{"jsonrpc":"2.0","id":7,"method":"initialize","params":{}}\n'
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
    )
    output = io.StringIO()
    serve_stdio(proxy.handle, input_stream=source, output_stream=output)
    lines = output.getvalue().splitlines()
    assert len(lines) == 1
    initialized = json.loads(lines[0])
    assert initialized["id"] == 7
    assert "scan.coverage_complete" in initialized["result"]["instructions"]


def test_transparent_proxy_requires_confirmation_for_mutating_tool(
    remote_endpoint: AppEndpoint,
) -> None:
    proxy = TransparentProxy(lambda: [remote_endpoint], "1")
    listed = proxy.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tools = {tool["name"]: tool for tool in listed["result"]["tools"]}
    clear_schema = tools["clear_events"]["inputSchema"]
    assert "allow_mutation" in clear_schema["properties"]
    assert "allow_mutation" in clear_schema["required"]
    assert tools["clear_events"]["annotations"]["destructiveHint"] is True
    assert "allow_mutation" not in tools["get_stats"]["inputSchema"].get("properties", {})

    RemoteHandler.methods.clear()
    blocked = proxy.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "clear_events", "arguments": {}},
        }
    )
    assert blocked["result"]["isError"] is True
    assert blocked["result"]["structuredContent"]["error"]["code"] == (
        "mutation_confirmation_required"
    )
    assert RemoteHandler.methods == []

    allowed = proxy.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "clear_events",
                "arguments": {"allow_mutation": True},
            },
        }
    )
    assert allowed["result"]["content"][0]["text"] == "remote result"
    assert RemoteHandler.tool_arguments[-1] == {}


def test_cli_call_invokes_remote_tool(
    remote_endpoint: AppEndpoint, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "call",
            "1",
            "get_stats",
            "--endpoint",
            remote_endpoint.base_url,
            "--no-saved",
            "--json",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["content"][0]["text"] == "remote result"


def test_cli_connect_persists_endpoint_for_other_commands(
    remote_endpoint: AppEndpoint,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "connections.json"
    monkeypatch.setenv("IDH_CONFIG_PATH", str(config))

    assert main(["connect", remote_endpoint.base_url]) == 0
    assert "connected and saved" in capsys.readouterr().out

    assert main(["devices", "--json"]) == 0
    devices = json.loads(capsys.readouterr().out)
    assert devices["devices"][0]["apps"][0]["bundle"] == "com.example.demo"

    assert main(["disconnect", remote_endpoint.base_url]) == 0
    assert "removed" in capsys.readouterr().out
    assert json.loads(config.read_text())["endpoints"] == []


def test_call_without_target_uses_single_online_device(
    remote_endpoint: AppEndpoint, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        ["call", None, "get_stats", "--endpoint", remote_endpoint.base_url, "--no-saved", "--json"]
    )
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["content"][0]["text"] == "remote result"


def test_cli_export_streams_all_pages_to_json(
    remote_endpoint: AppEndpoint,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "events.json"

    exit_code = main(
        [
            "export",
            "1",
            "--endpoint",
            remote_endpoint.base_url,
            "--no-saved",
            "--output",
            str(output),
            "--page-size",
            "2",
        ]
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    captured = capsys.readouterr()
    assert exit_code == 0
    assert result["format"] == "iosdecrypthub.export.v1"
    assert result["start_after_seq"] == 0
    assert result["snapshot_until_seq"] == 3
    assert result["count"] == 3
    assert [event["seq"] for event in result["events"]] == [1, 2, 3]
    assert "exported 3 event(s)" in captured.out
    assert "may contain keys" in captured.err
    export_arguments = [args for args in RemoteHandler.tool_arguments if "max_blob_bytes" in args]
    assert [args["after_seq"] for args in export_arguments] == [0, 2]
    assert export_arguments[1]["until_seq"] == 3


def test_cli_export_refuses_to_overwrite_without_force(
    remote_endpoint: AppEndpoint,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "events.json"
    output.write_text("keep", encoding="utf-8")

    exit_code = main(
        [
            "export",
            "1",
            "--endpoint",
            remote_endpoint.base_url,
            "--no-saved",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 2
    assert output.read_text(encoding="utf-8") == "keep"
    assert "--force" in capsys.readouterr().err
