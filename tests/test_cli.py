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


def test_extract_writes_and_merges(tmp_path: object) -> None:
    from pathlib import Path

    import yaml

    root = Path(str(tmp_path))
    (root / "AGENTS.md").write_text("# Rules\n\n- Use pnpm; never npm.\n- Write clean code.\n")
    assert main(["extract", "--repo", str(root)]) == 0
    data = yaml.safe_load((root / "obey.yaml").read_text())
    assert [r["status"] for r in data["rules"]] == ["active", "uncheckable"]
    assert data["sources"][0]["file"] == "AGENTS.md"
    # A person disables the first rule; re-extraction keeps that decision.
    data["rules"][0]["status"] = "disabled"
    data["rules"][0]["reason"] = "not relevant here"
    (root / "obey.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    assert main(["extract", "--repo", str(root)]) == 0
    again = yaml.safe_load((root / "obey.yaml").read_text())
    assert again["rules"][0]["status"] == "disabled"


def test_extract_without_instruction_files(tmp_path: object) -> None:
    assert main(["extract", "--repo", str(tmp_path)]) == 1
