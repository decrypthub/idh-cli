"""Remote prompt/skill registry with a local cache.

The MCP gateway instructions and the reusable reverse-engineering skills live
outside the Python package. They can be updated independently of an idh
release: ``idh`` refreshes this cache on a throttle and the gateway serves the
latest content on the next MCP session.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from importlib.resources import files
from pathlib import Path
from typing import Any

from . import __version__
from .settings import load_settings, update_settings

PROMPT_CACHE_ENV = "IDH_PROMPT_CACHE"
INDEX_VERSION = 1

BUNDLED_INSTRUCTIONS = (
    "AI Agent protocol — use idh_list_devices first to resolve the target_id, "
    "then idh_list_tools / idh_get_tool_schema to discover remote tools. "
    "Never assume or invent tool names. Cite every fact with its source tool "
    "and event id; label inference explicitly. Read-only tools may run "
    "autonomously; state-changing tools require explicit user intent and "
    "allow_mutation=true. Use idh_list_skills / idh_get_skill for the current "
    "reverse-engineering playbooks."
)


def prompt_cache_dir() -> Path:
    override = os.environ.get(PROMPT_CACHE_ENV)
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return root / "idh" / "prompts"


def _bundled_path(relative: str):
    return files("idh").joinpath("prompts").joinpath(relative)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _read_json(path: Path) -> dict[str, Any] | None:
    text = _read_text(path)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


class PromptStore:
    def __init__(self, cache: Path | None = None) -> None:
        self.cache = cache or prompt_cache_dir()

    def _cached_index(self) -> dict[str, Any] | None:
        return _read_json(self.cache / "index.json")

    def _bundled_index(self) -> dict[str, Any] | None:
        try:
            text = _bundled_path("index.json").read_text(encoding="utf-8")
        except (OSError, UnicodeError, FileNotFoundError):
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def index(self) -> dict[str, Any]:
        data = self._cached_index() or self._bundled_index() or {}
        skills = data.get("skills")
        return {
            "version": data.get("version", INDEX_VERSION),
            "updated_at": data.get("updated_at", ""),
            "instructions": data.get("instructions", "instructions.md"),
            "skills": skills if isinstance(skills, list) else [],
        }

    def instructions(self) -> str:
        cached = _read_text(self.cache / "instructions.md")
        if cached and cached.strip():
            return cached.strip()
        try:
            bundled = _bundled_path("instructions.md").read_text(encoding="utf-8")
        except (OSError, UnicodeError, FileNotFoundError):
            return BUNDLED_INSTRUCTIONS
        return bundled.strip() or BUNDLED_INSTRUCTIONS

    def list_skills(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in self.index()["skills"]:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name:
                continue
            result.append(
                {
                    "name": name,
                    "title": item.get("title", name),
                    "description": item.get("description", ""),
                }
            )
        return result

    def get_skill(self, name: str) -> str | None:
        if not name or "/" in name or "\\" in name or name.startswith("."):
            return None
        cached = _read_text(self.cache / "skills" / f"{name}.md")
        if cached and cached.strip():
            return cached.strip()
        try:
            bundled = _bundled_path("skills").joinpath(f"{name}.md").read_text(encoding="utf-8")
        except (OSError, UnicodeError, FileNotFoundError):
            return None
        return bundled.strip() or None

    def update(self, *, timeout: float = 5.0) -> dict[str, Any]:
        settings = load_settings()
        registry = str(settings.get("prompt_registry") or "").strip()
        if not registry:
            return {"status": "no-registry"}
        try:
            request = urllib.request.Request(
                registry,
                headers={"User-Agent": f"idh/{__version__}"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw_index = response.read()
        except Exception as exc:  # noqa: BLE001 - prompt refresh must not break idh
            return {"status": "network-error", "error": str(exc)}
        try:
            index = json.loads(raw_index.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            return {"status": "invalid-index", "error": str(exc)}
        if not isinstance(index, dict):
            return {"status": "invalid-index", "error": "index is not an object"}

        updated: list[str] = []
        instructions_name = index.get("instructions", "instructions.md")
        if isinstance(instructions_name, str) and instructions_name:
            content = self._fetch_text(registry, instructions_name, timeout)
            if content is not None:
                _atomic_write(self.cache / "instructions.md", content)
                updated.append("instructions")

        skills = index.get("skills")
        if isinstance(skills, list):
            for item in skills:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                file_name = item.get("file")
                if not isinstance(name, str) or not name or not isinstance(file_name, str):
                    continue
                content = self._fetch_text(registry, file_name, timeout)
                if content is None:
                    continue
                digest = item.get("sha256")
                if isinstance(digest, str) and digest:
                    actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    if actual.casefold() != digest.casefold():
                        continue
                _atomic_write(self.cache / "skills" / f"{name}.md", content)
                updated.append(f"skills/{name}")

        _atomic_write(self.cache / "index.json", json.dumps(index, ensure_ascii=False, indent=2))
        update_settings(last_prompt_check=time.time())
        return {"status": "updated", "updated": updated, "updated_at": index.get("updated_at", "")}

    @staticmethod
    def _fetch_text(registry: str, relative: str, timeout: float) -> str | None:
        url = urllib.parse.urljoin(registry, relative)
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": f"idh/{__version__}"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except Exception:  # noqa: BLE001
            return None


def maybe_update_prompts(
    *,
    force: bool = False,
    timeout: float = 3.0,
    stream: Any = None,
) -> dict[str, Any]:
    if stream is None:
        stream = sys.stderr
    settings = load_settings()
    now = time.time()
    last = float(settings.get("last_prompt_check") or 0.0)
    interval = float(settings.get("prompt_interval") or 0.0)
    if not force and last and now - last < interval:
        return {"status": "throttled", "last_check": last}
    result = PromptStore().update(timeout=timeout)
    if result.get("status") == "updated":
        updated = result.get("updated") or []
        if updated:
            print(f"idh: refreshed prompts/skills ({', '.join(updated)})", file=stream)
    return result
