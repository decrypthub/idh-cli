"""idh update command tests (mocked network and pip)."""

import json
from unittest import mock

from idh.cli import main


def test_update_check_only_reports_latest(monkeypatch, capsys) -> None:
    payload = json.dumps({"info": {"version": "9.9.9"}}).encode()

    def fake_urlopen(url, timeout):
        return mock.Mock(__enter__=lambda self: self, __exit__=lambda *a: False, read=lambda: payload)

    monkeypatch.setattr("idh.cli.urllib.request.urlopen", fake_urlopen)
    assert main(["update", "--check-only"]) == 0
    assert "9.9.9" in capsys.readouterr().out


def test_update_skips_when_latest(monkeypatch, capsys) -> None:
    from idh import __version__

    payload = json.dumps({"info": {"version": __version__}}).encode()

    def fake_urlopen(url, timeout):
        return mock.Mock(__enter__=lambda self: self, __exit__=lambda *a: False, read=lambda: payload)

    monkeypatch.setattr("idh.cli.urllib.request.urlopen", fake_urlopen)
    assert main(["update", "--check-only"]) == 0
    assert "already up to date" in capsys.readouterr().out
