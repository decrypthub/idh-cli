import json
import os
from pathlib import Path
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest


@pytest.fixture
def app():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"version": "1.28.28", "process": {"pid": 42, "bundleId": "com.example.app", "appName": "Example"}}).encode())

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if "id" not in data:
                self.send_response(202)
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "fixture", "version": "1"}} if data["method"] == "initialize" else {"tools": [{"name": "get_stats", "inputSchema": {"type": "object"}}]}
            self.wfile.write(json.dumps({"jsonrpc": "2.0", "id": data["id"], "result": result}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


def run(tmp_path, *args):
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
           "IDH_CONFIG_PATH": str(tmp_path / "connections.json"), "IDH_SETTINGS_PATH": str(tmp_path / "settings.json"),
           "IDH_AUTO_UPDATE": "off", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "-m", "idh", *args], env=env, capture_output=True, text=True, encoding="utf-8", timeout=15)


def test_status_identifies_the_live_app_without_mutating_saved_connections(tmp_path, app):
    result = run(tmp_path, "status", "--endpoint", app, "--no-saved", "--json")
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["component"] == "idh" and status["schemaVersion"] == 1
    assert status["connections"][0]["online"] is True
    assert status["targets"][0]["bundle"] == "com.example.app"
    assert status["targets"][0]["pid"] == "42"
    assert not (tmp_path / "connections.json").exists()


def test_offline_status_and_live_tool_discovery(tmp_path, app):
    result = run(tmp_path, "status", "--endpoint", "127.0.0.1:1", "--no-saved", "--timeout", "0.1", "--json")
    assert json.loads(result.stdout)["connections"][0]["online"] is False
    result = run(tmp_path, "tools", "--endpoint", app, "--no-saved", "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["tools"][0]["name"] == "get_stats"
