"""idh self-update: PyPI version check and install-method-aware upgrade."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from . import __version__
from .settings import load_settings, settings_path, update_settings

PYPI_JSON_URL = "https://pypi.org/pypi/ios-decrypt-hub/json"
PACKAGE_NAME = "ios-decrypt-hub"


def version_tuple(value: str) -> tuple[int, ...]:
    """Convert a version string to a comparable integer tuple.

    This intentionally avoids a runtime dependency on packaging. Pre-release
    suffixes (``0.7.0rc1``) are treated as the numeric part, which is enough
    for the PyPI stable releases idh publishes.
    """

    numbers = [int(part) for part in re.findall(r"\d+", value or "")]
    return tuple(numbers) if numbers else (0,)


def is_newer(latest: str, current: str) -> bool:
    left = version_tuple(latest)
    right = version_tuple(current)
    length = max(len(left), len(right))
    left = left + (0,) * (length - len(left))
    right = right + (0,) * (length - len(right))
    return left > right


def latest_pypi_version(timeout: float = 5.0) -> str | None:
    try:
        with urllib.request.urlopen(PYPI_JSON_URL, timeout=timeout) as response:
            payload = json.load(response)
    except Exception:  # noqa: BLE001 - network failures must never break idh
        return None
    info = payload.get("info") if isinstance(payload, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    return version if isinstance(version, str) and version else None


def detect_install_method() -> str:
    override = os.environ.get("IDH_INSTALL_METHOD")
    if override:
        return override.strip().casefold()
    candidates = [Path(sys.executable).resolve()]
    script = shutil.which("idh")
    if script:
        candidates.append(Path(script).resolve())
    for candidate in candidates:
        text = str(candidate).casefold()
        if "uv" in text and "tools" in text:
            return "uv"
        if "pipx" in text and "venvs" in text:
            return "pipx"
        if "pipx" in text:
            return "pipx"
    return "pip"


def upgrade_command(method: str) -> list[str]:
    if method == "uv":
        return ["uv", "tool", "upgrade", PACKAGE_NAME]
    if method == "pipx":
        return ["pipx", "upgrade", PACKAGE_NAME]
    return [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE_NAME]


def run_upgrade(method: str, *, capture: bool = True) -> tuple[bool, str]:
    command = upgrade_command(method)
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=capture,
            text=True,
        )
    except OSError as exc:
        return False, str(exc)
    output = ""
    if capture:
        output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        return False, output.strip() or f"command failed: {' '.join(command)}"
    return True, output.strip()


@contextlib.contextmanager
def _update_lock() -> Iterator[bool]:
    """Best-effort inter-process lock so two idh invocations do not upgrade together."""

    lock_path = settings_path().with_suffix(".update.lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "w", encoding="utf-8")  # noqa: SIM115 - held across yield
    except OSError:
        yield True
        return
    with handle:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            yield True
            return
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


def check_for_update(timeout: float = 5.0) -> dict[str, Any]:
    latest = latest_pypi_version(timeout=timeout)
    return {
        "current": __version__,
        "latest": latest,
        "update_available": bool(latest and is_newer(latest, __version__)),
    }


def maybe_auto_update(
    *,
    force: bool = False,
    allow_upgrade: bool = True,
    stream: Any = None,
) -> dict[str, Any]:
    """Check PyPI on a throttle and optionally upgrade the installed package."""

    if stream is None:
        stream = sys.stderr
    settings = load_settings()
    if not settings.get("auto_update", True) and not force:
        return {"status": "disabled"}
    now = time.time()
    last_check = float(settings.get("last_update_check") or 0.0)
    interval = float(settings.get("update_interval") or 0.0)
    if not force and last_check and now - last_check < interval:
        return {"status": "throttled", "last_check": last_check}

    latest = latest_pypi_version()
    if not latest:
        return {"status": "network-error"}
    update_settings(last_update_check=now, last_update_version=latest)
    if not is_newer(latest, __version__):
        return {"status": "up-to-date", "current": __version__, "latest": latest}

    print(
        f"idh: new version available: {__version__} -> {latest}",
        file=stream,
    )
    if not allow_upgrade:
        return {"status": "available", "current": __version__, "latest": latest}

    with _update_lock() as locked:
        if not locked:
            return {"status": "locked", "current": __version__, "latest": latest}
        method = detect_install_method()
        ok, output = run_upgrade(method)
    if ok:
        print(f"idh: upgraded to {latest}; restart idh to use it", file=stream)
        return {"status": "upgraded", "current": __version__, "latest": latest, "method": method}
    print(f"idh: auto-update failed ({method}): {output}", file=stream)
    return {
        "status": "failed",
        "current": __version__,
        "latest": latest,
        "method": method,
        "error": output,
    }
