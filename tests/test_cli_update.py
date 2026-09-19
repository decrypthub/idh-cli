"""idh update/settings command tests (mocked PyPI)."""

from idh import __version__, selfupdate
from idh.cli import main


def test_update_check_only_reports_latest(monkeypatch, capsys) -> None:
    monkeypatch.setattr(selfupdate, "latest_pypi_version", lambda timeout=5.0: "9.9.9")
    assert main(["update", "--check-only"]) == 0
    output = capsys.readouterr().out
    assert "9.9.9" in output
    assert "install method" in output


def test_update_skips_when_latest(monkeypatch, capsys) -> None:
    monkeypatch.setattr(selfupdate, "latest_pypi_version", lambda timeout=5.0: __version__)
    assert main(["update", "--check-only"]) == 0
    assert "already up to date" in capsys.readouterr().out


def test_settings_command_updates_auto_update(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("IDH_SETTINGS_PATH", str(tmp_path / "settings.json"))
    assert main(["settings", "--auto-update", "off", "--json"]) == 0
    assert '"auto_update": false' in capsys.readouterr().out
