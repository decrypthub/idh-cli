from __future__ import annotations

from idh import __version__, selfupdate
from idh.selfupdate import detect_install_method, is_newer, version_tuple


def test_version_compare() -> None:
    assert version_tuple("0.7.0") == (0, 7, 0)
    assert is_newer("0.7.0", "0.6.9") is True
    assert is_newer("0.6.0", "0.6.0") is False
    assert is_newer("0.10.0", "0.9.9") is True


def test_detect_install_method_env(monkeypatch) -> None:
    monkeypatch.setenv("IDH_INSTALL_METHOD", "uv")
    assert detect_install_method() == "uv"
    monkeypatch.setenv("IDH_INSTALL_METHOD", "pipx")
    assert detect_install_method() == "pipx"


def test_maybe_auto_update_disabled(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IDH_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("IDH_AUTO_UPDATE", "off")
    result = selfupdate.maybe_auto_update()
    assert result["status"] == "disabled"


def test_maybe_auto_update_up_to_date(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IDH_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setattr(selfupdate, "latest_pypi_version", lambda timeout=5.0: __version__)
    result = selfupdate.maybe_auto_update(force=True)
    assert result["status"] == "up-to-date"


def test_maybe_auto_update_upgrades(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("IDH_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("IDH_INSTALL_METHOD", "uv")
    monkeypatch.setattr(selfupdate, "latest_pypi_version", lambda timeout=5.0: "9.9.9")
    calls: list[str] = []

    def fake_upgrade(method: str, *, capture: bool = True):
        calls.append(method)
        return True, "ok"

    monkeypatch.setattr(selfupdate, "run_upgrade", fake_upgrade)
    result = selfupdate.maybe_auto_update(force=True)
    assert result["status"] == "upgraded"
    assert calls == ["uv"]
    assert "new version available" in capsys.readouterr().err
