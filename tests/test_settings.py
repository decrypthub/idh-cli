from __future__ import annotations

from idh.settings import load_settings, save_settings


def test_settings_defaults_and_round_trip(tmp_path) -> None:
    path = tmp_path / "settings.json"
    settings = load_settings(path)
    assert settings["auto_update"] is True
    assert settings["update_interval"] == 24 * 3600

    save_settings({**settings, "auto_update": False, "update_interval": 60}, path)
    loaded = load_settings(path)
    assert loaded["auto_update"] is False
    assert loaded["update_interval"] == 60
    assert path.stat().st_mode & 0o777 == 0o600


def test_settings_env_override(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IDH_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("IDH_AUTO_UPDATE", "off")
    monkeypatch.setenv("IDH_UPDATE_INTERVAL", "120")
    monkeypatch.setenv("IDH_PROMPT_INTERVAL", "30")

    settings = load_settings()
    assert settings["auto_update"] is False
    assert settings["update_interval"] == 120
    assert settings["prompt_interval"] == 30
