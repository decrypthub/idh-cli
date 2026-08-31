from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__
from .models import AppEndpoint


class MCPTransportError(RuntimeError):
    pass


class MCPHTTPClient:
    def __init__(self, endpoint: AppEndpoint, *, timeout: float = 15.0) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self.session_id: str | None = None
        self.initialized = False

    def update_endpoint(self, endpoint: AppEndpoint) -> None:
        if endpoint.mcp_url != self.endpoint.mcp_url:
            self.session_id = None
            self.initialized = False
        self.endpoint = endpoint

    def ensure_initialized(self) -> None:
        if self.initialized:
            return
        response = self.send(
            {
                "jsonrpc": "2.0",
                "id": "idh-initialize",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "idh", "version": __version__},
                },
            }
        )
        if not isinstance(response, dict):
            raise MCPTransportError("remote MCP initialize returned no valid response")
        if "error" in response:
            raise MCPTransportError(
                f"remote MCP initialize failed: {json.dumps(response['error'], ensure_ascii=False)}"
            )
        if not isinstance(response.get("result"), dict):
            raise MCPTransportError("remote MCP initialize response is missing result")
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.initialized = True

    def send(self, message: Any) -> Any | None:
        body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"idh/{__version__}",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = Request(self.endpoint.mcp_url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    self.session_id = session_id
                payload = response.read()
                if response.status in (202, 204) or not payload:
                    return None
                return json.loads(payload)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MCPTransportError(
                f"MCP HTTP {exc.code} ({self.endpoint.mcp_url}): {detail or exc.reason}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise MCPTransportError(f"cannot connect to {self.endpoint.mcp_url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise MCPTransportError(f"device returned invalid JSON: {exc}") from exc


def probe_endpoint(endpoint: AppEndpoint, *, timeout: float = 1.0) -> AppEndpoint:
    panel_path = endpoint.properties.get("panel_path", "/").rstrip("/")
    request = Request(
        f"{endpoint.base_url}{panel_path}/api/stats",
        headers={"Accept": "application/json", "User-Agent": f"idh/{__version__}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            stats = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return endpoint.with_properties({"status": "unreachable"})

    process = stats.get("process") if isinstance(stats, dict) else None
    process = process if isinstance(process, dict) else {}
    values = {
        "status": "online",
        "app_name": process.get("appName") or process.get("processName"),
        "bundle": process.get("bundleId"),
        "pid": process.get("pid"),
        "device_model": process.get("deviceModel"),
        "system_version": process.get("systemVersion"),
        "idh_version": stats.get("version") if isinstance(stats, dict) else None,
    }
    return endpoint.with_properties(values)
