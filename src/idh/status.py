"""Bounded, read-only inventory for the desktop and command-line Agents."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import __version__
from .http_mcp import probe_endpoint
from .models import AppEndpoint


def status(endpoints: list[AppEndpoint], *, timeout: float = 3.0) -> dict:
    with ThreadPoolExecutor(max_workers=max(1, min(8, len(endpoints)))) as pool:
        checked = list(pool.map(lambda endpoint: probe_endpoint(endpoint, timeout=timeout), endpoints))
    connections = []
    targets = []
    for endpoint in checked:
        online = endpoint.properties.get("status") == "online"
        connections.append({"endpoint": endpoint.mcp_url, "online": online, "kind": endpoint.kind,
                            "version": endpoint.properties.get("idh_version"),
                            "error": None if online else endpoint.properties.get("error", "unreachable")})
        if not online:
            continue
        if endpoint.kind == "device":
            targets.append({"id": endpoint.key, "name": "idhjd", "kind": "device",
                            "endpoint": endpoint.mcp_url, "online": True,
                            "apps": list(endpoint.observed_apps), "device": endpoint.device_key})
            continue
        targets.append({"id": endpoint.key, "name": endpoint.app_name, "kind": endpoint.kind or "app",
                        "endpoint": endpoint.mcp_url, "online": True,
                        "bundle": endpoint.bundle_id, "pid": endpoint.properties.get("pid"),
                        "device": endpoint.device_key})
    return {"schemaVersion": 1, "component": "idh", "version": __version__,
            "checkedAt": datetime.now(timezone.utc).isoformat(), "connections": connections, "targets": targets}
