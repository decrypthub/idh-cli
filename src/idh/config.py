"""Persistent manual endpoint configuration."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from .models import AppEndpoint

CONFIG_VERSION = 1
CONFIG_PATH_ENV = "IDH_CONFIG_PATH"


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
    if not isinstance(data, dict) or data.get("version") != CONFIG_VERSION:
        raise ValueError(f"unsupported connection config format: {target}")
    values = data.get("endpoints")
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError(f"connection config endpoints must be an array of strings: {target}")
    try:
        return [AppEndpoint.from_url(value) for value in values]
    except ValueError as exc:
        raise ValueError(f"connection config contains an invalid address: {exc}") from exc


def save_endpoint(endpoint: AppEndpoint, path: Path | None = None) -> bool:
    target = path or config_path()
    existing = load_saved_endpoints(target)
    canonical = endpoint.mcp_url
    if any(item.mcp_url.casefold() == canonical.casefold() for item in existing):
        return False
    _write_endpoints([*existing, endpoint], target)
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


def _write_endpoints(endpoints: Iterable[AppEndpoint], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CONFIG_VERSION,
        "endpoints": sorted({endpoint.mcp_url for endpoint in endpoints}, key=str.casefold),
    }
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
