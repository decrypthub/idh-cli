from __future__ import annotations

import json

from idh.prompts import PromptStore


def test_bundled_prompt_store(tmp_path) -> None:
    store = PromptStore(cache=tmp_path / "empty-cache")
    instructions = store.instructions()
    assert "idh_list_devices" in instructions
    assert "idh_list_skills" in instructions

    skills = store.list_skills()
    assert any(item["name"] == "static-linked-crypto" for item in skills)
    body = store.get_skill("static-linked-crypto")
    assert body is not None
    assert "capture_memory" in body


def test_prompt_store_update_from_registry(monkeypatch, tmp_path) -> None:
    registry = tmp_path / "registry"
    (registry / "skills").mkdir(parents=True)
    (registry / "index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": "2026-09-19T00:00:00Z",
                "instructions": "instructions.md",
                "skills": [{"name": "demo", "file": "skills/demo.md"}],
            }
        ),
        encoding="utf-8",
    )
    (registry / "instructions.md").write_text("REMOTE INSTRUCTIONS", encoding="utf-8")
    (registry / "skills" / "demo.md").write_text("REMOTE SKILL", encoding="utf-8")

    monkeypatch.setenv("IDH_PROMPT_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("IDH_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("IDH_PROMPT_REGISTRY", f"{registry.as_uri()}/index.json")

    store = PromptStore()
    result = store.update()
    assert result["status"] == "updated"
    assert store.instructions() == "REMOTE INSTRUCTIONS"
    assert store.get_skill("demo") == "REMOTE SKILL"


def test_prompt_store_rejects_path_traversal(tmp_path) -> None:
    store = PromptStore(cache=tmp_path)
    assert store.get_skill("../secret") is None
    assert store.get_skill("..") is None
