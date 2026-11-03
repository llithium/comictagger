from __future__ import annotations

from unittest.mock import Mock

import pytest

from comictaggerlib.main import App
from comictaggerlib.resulttypes import Action


@pytest.fixture
def app(config, monkeypatch):
    application = App()
    application.config = config
    application.config_load_success = True
    application.talkers = {"test": Mock()}
    application.config[0].Runtime_Options__no_gui = True
    monkeypatch.setattr("comictaggerlib.main.importlib_metadata.distributions", lambda: [])
    monkeypatch.setattr("comictaggerlib.main.signal.signal", Mock())
    monkeypatch.setattr("comictaggerlib.main.comicapi.utils.load_publishers", Mock())
    return application


def test_cli_exception_exits_with_failure(app, monkeypatch):
    app.config[0].Commands__command = Action.print
    cli = Mock()
    cli.run.side_effect = RuntimeError("failed action")
    monkeypatch.setattr("comictaggerlib.main.cli.CLI", Mock(return_value=cli))

    with pytest.raises(SystemExit) as error:
        app.main()

    assert error.value.code == 1


@pytest.mark.parametrize("saved", [True, False])
def test_save_config_reports_the_save_result(app, monkeypatch, capsys, saved):
    app.config[0].Commands__command = Action.save_config
    monkeypatch.setattr("comictaggerlib.main.ctsettings.save_file", lambda *args: saved)

    if saved:
        app.main()
        assert capsys.readouterr().out.strip() == "Settings saved"
    else:
        with pytest.raises(SystemExit) as error:
            app.main()
        assert error.value.code == 1
        assert "Settings saved" not in capsys.readouterr().out
