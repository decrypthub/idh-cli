"""User settings for idh: auto-update policy and prompt/skill registry."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

SETTINGS_VERSION = 1
SETTINGS_PATH_ENV = "IDH_SETTINGS_PATH"

DEFAULT_PROMPT_REGISTRY = (
    "https://raw.githubusercontent.com/decrypthub/idh-cli/main/src/idh/prompts/index.json"
)

DEFAULTS: dict[str, Any] = {
    "version": SETTINGS_VERSION,
    "auto_update": True,
    "update_interval": 24 * 3600,
    "last_update_check": 0.0,
    "last_update_version": "",
    "prompt_registry": DEFAULT_PROMPT_REGISTRY,
    "prompt_interval": 6 * 3600,
    "last_prompt_check": 0.0,
    "prompt_etag": "",
}


def settings_path() -> Path:
    override = os.environ.get(SETTINGS_PATH_ENV)
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return root / "idh" / "settings.json"


def _env_bool(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None:
        return None
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _env_float(name: str) -> float | None:
    value = os.environ.get(name)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _apply_env_overrides(settings: dict[str, Any]) -> dict[str, Any]:
    auto = _env_bool("IDH_AUTO_UPDATE")
    if auto is not None:
        settings["auto_update"] = auto
    interval = _env_float("IDH_UPDATE_INTERVAL")
    if interval is not None:
        settings["update_interval"] = max(0.0, interval)
    prompt_interval = _env_float("IDH_PROMPT_INTERVAL")
    if prompt_interval is not None:
        settings["prompt_interval"] = max(0.0, prompt_interval)
    registry = os.environ.get("IDH_PROMPT_REGISTRY")
    if registry:
        settings["prompt_registry"] = registry.strip()
    return settings


def load_settings(path: Path | None = None) -> dict[str, Any]:
    """Load settings, merging defaults and environment overrides.

    A missing or unreadable file is not an error: idh must keep working with
    the built-in defaults so that auto-update can repair a broken config.
    """

    target = path or settings_path()
    settings = dict(DEFAULTS)
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            for key, default in DEFAULTS.items():
                value = data.get(key, default)
                if isinstance(default, bool):
                    settings[key] = bool(value)
                elif isinstance(default, float):
                    try:
                        settings[key] = float(value)
                    except (TypeError, ValueError):
                        settings[key] = default
                else:
                    settings[key] = value if isinstance(value, type(default)) else default
    settings["version"] = SETTINGS_VERSION
    return _apply_env_overrides(settings)


def save_settings(settings: dict[str, Any], path: Path | None = None) -> None:
    target = path or settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: settings.get(key, default) for key, default in DEFAULTS.items()}
    payload["version"] = SETTINGS_VERSION
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


def update_settings(path: Path | None = None, **changes: Any) -> dict[str, Any]:
    settings = load_settings(path)
    for key, value in changes.items():
        if key in DEFAULTS:
            settings[key] = value
    save_settings(settings, path)
    return settings
