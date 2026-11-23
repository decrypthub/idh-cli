"""Persistent manual endpoint configuration."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from .models import AppEndpoint

CONFIG_VERSION = 1
CONFIG_VERSION_KIND = 2
CONFIG_PATH_ENV = "IDH_CONFIG_PATH"
_KINDS = {"app", "device"}


def config_path() -> Path:
    override = os.environ.get(CONFIG_PATH_ENV)
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return root / "idh" / "connections.json"


def load_saved_endpoints(path: Path | None = None) -> list[AppEndpoint]:
    target = path or config_path()
    if not target.exists():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read connection config {target}: {exc}") from exc
    version = data.get("version") if isinstance(data, dict) else None
    if version not in {CONFIG_VERSION, CONFIG_VERSION_KIND}:
        raise ValueError(f"unsupported connection config format: {target}")
    values = data.get("endpoints")
    if not isinstance(values, list):
        raise ValueError(f"connection config endpoints must be an array: {target}")
    try:
        if data.get("version") == CONFIG_VERSION:
            if not all(isinstance(value, str) for value in values):
                raise ValueError(
                    f"connection config endpoints must be an array of strings: {target}"
                )
            return [AppEndpoint.from_url(value) for value in values]
        loaded: list[AppEndpoint] = []
        for item in values:
            url = item.get("url") if isinstance(item, dict) else None
            if not isinstance(url, str):
                raise ValueError(
                    f"connection config endpoints must be objects with a url: {target}"
                )
            kind = item.get("kind")
            if kind is not None and kind not in _KINDS:
                raise ValueError(f"connection config has an unknown kind: {target}")
            endpoint = AppEndpoint.from_url(url).with_kind(kind if isinstance(kind, str) else None)
            token = item.get("session_token")
            if isinstance(token, str) and token:
                endpoint = endpoint.with_properties({"session_token": token})
            loaded.append(endpoint)
        return loaded
    except ValueError as exc:
        if str(exc).startswith("connection config"):
            raise
        raise ValueError(f"connection config contains an invalid address: {exc}") from exc


def save_endpoint(endpoint: AppEndpoint, path: Path | None = None) -> bool:
    target = path or config_path()
    existing = load_saved_endpoints(target)
    canonical = endpoint.mcp_url.casefold()
    updated: list[AppEndpoint] = []
    found = False
    changed = False
    for item in existing:
        if item.mcp_url.casefold() != canonical:
            updated.append(item)
            continue
        found = True
        kind = endpoint.kind if endpoint.kind in _KINDS else item.kind
        if kind != item.kind:
            changed = True
            item = item.with_kind(kind)
        updated.append(item)
    if not found:
        updated.append(endpoint)
        changed = True
    if not changed:
        return False
    _write_endpoints(updated, target)
    return True


def remove_endpoint(value: str, path: Path | None = None) -> bool:
    target = path or config_path()
    canonical = AppEndpoint.from_url(value).mcp_url.casefold()
    existing = load_saved_endpoints(target)
    remaining = [item for item in existing if item.mcp_url.casefold() != canonical]
    if len(remaining) == len(existing):
        return False
    _write_endpoints(remaining, target)
    return True


def clear_endpoints(path: Path | None = None) -> int:
    target = path or config_path()
    existing = load_saved_endpoints(target)
    if existing or target.exists():
        _write_endpoints([], target)
    return len(existing)


def load_selected(path: Path | None = None) -> str | None:
    target = path or config_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    selected = data.get("selected") if isinstance(data, dict) else None
    return selected if isinstance(selected, str) and selected else None


def save_selected(value: str, path: Path | None = None) -> None:
    target = path or config_path()
    _write_endpoints(load_saved_endpoints(target), target, selected=value)


def save_endpoint_token(value: str, token: str, path: Path | None = None) -> bool:
    target = path or config_path()
    canonical = AppEndpoint.from_url(value).mcp_url.casefold()
    endpoints = load_saved_endpoints(target)
    updated = False
    items: list[AppEndpoint] = []
    for item in endpoints:
        if item.mcp_url.casefold() == canonical:
            item = item.with_properties({"session_token": token})
            updated = True
        items.append(item)
    if not updated:
        return False
    _write_endpoints(items, target)
    return True


def _write_endpoints(
    endpoints: Iterable[AppEndpoint], target: Path, *, selected: str | None = None
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if selected is None and target.exists():
        # 其它写路径不改当前选中，读旧文件保留
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("selected"), str):
                selected = data["selected"]
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    items = sorted(endpoints, key=lambda item: item.mcp_url.casefold())
    if any(item.kind or item.properties.get("session_token") for item in items):
        payload: dict[str, object] = {
            "version": CONFIG_VERSION_KIND,
            "endpoints": [
                {
                    "url": item.mcp_url,
                    **({"kind": item.kind} if item.kind else {}),
                    **({"session_token": item.properties["session_token"]}
                       if item.properties.get("session_token") else {}),
                }
                for item in items
            ],
        }
    else:
        payload = {"version": CONFIG_VERSION, "endpoints": [item.mcp_url for item in items]}
    if selected:
        payload["selected"] = selected
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
