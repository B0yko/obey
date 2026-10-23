from __future__ import annotations

import pytest

from obey_cli import __version__
from obey_cli.cli import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_prints_help() -> None:
    assert main([]) == 2
