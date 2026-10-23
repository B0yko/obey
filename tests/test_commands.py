from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from obey_cli.cli import main
from obey_cli.runner.ledger import Ledger
from obey_cli.runner.orchestrate import PlannedRun, estimate, execute_all, plan_runs

DEMO = Path(__file__).parents[1] / "study" / "repos" / "ts-web"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(DEMO, root)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert main(["init", "--repo", str(root)]) == 0
    return root


def test_run_estimate_without_key_or_docker(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "run",
            "--repo",
            str(repo),
            "--estimate",
            "--offline-price",
            "--model",
            "vendor/model",
            "--trials",
            "2",
            "--baseline-trials",
            "1",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0 and "runs ×" in out


def test_run_requires_a_model(repo: Path) -> None:
    assert main(["run", "--repo", str(repo), "--estimate", "--offline-price"]) == 2


def test_enforce_dry_run_remove_and_lint(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["enforce", "--repo", str(repo), "--dry-run", "--targets", "claude"]) == 0
    assert "+++ b/.claude/settings.json" in capsys.readouterr().out
    assert not (repo / ".claude" / "settings.json").exists()
    assert main(["enforce", "--repo", str(repo), "--targets", "claude,precommit"]) == 0
    assert (repo / ".claude" / "settings.json").exists() and (repo / ".obey" / "pre-commit").exists()
    assert main(["lint", "--repo", str(repo)]) == 0
    assert json.loads((repo / "obey-badge.json").read_text())["schemaVersion"] == 1
    # Changing the instruction file makes lint fail until obey extract runs again.
    agents = repo / "AGENTS.md"
    agents.write_text(agents.read_text() + "- Never run `make deploy`.\n")
    assert main(["lint", "--repo", str(repo)]) == 1
    assert "run `obey extract`" in capsys.readouterr().out
    assert main(["enforce", "--repo", str(repo), "--remove"]) == 0
    assert not (repo / ".claude" / "settings.json").exists() and not (repo / ".obey" / "pre-commit").exists()


def test_plan_runs_arms(repo: Path) -> None:
    import yaml

    config = yaml.safe_load((repo / "obey.yaml").read_text())
    rules = [r for r in config["rules"] if r["status"] == "active" and r["probes"]][:2]
    planned = plan_runs(repo, rules, trials=3, baseline_trials=2)
    assert len(planned) == 2 * (3 + 2)
    baseline = next(p for p in planned if p.arm == "baseline")
    removed = baseline.overrides["AGENTS.md"]
    assert baseline.rule["text"].split()[0] in (repo / "AGENTS.md").read_text() and len(removed) < len(
        (repo / "AGENTS.md").read_text()
    )
    enforced = plan_runs(repo, rules, trials=2, baseline_trials=0, enforced={"x": "y"}, only_enforced=True)
    assert {p.arm for p in enforced} == {"enforced"} and len(enforced) == 4
    est = estimate(planned, "claude-code", {"prompt": 1e-7, "completion": 5e-7, "cache_read": 1e-8})
    assert est["runs"] == 10 and est["total_usd"] > 0


def test_execute_all_stops_at_the_budget(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl", budget_usd=0.05)
    rule: dict[str, Any] = {"id": "r", "checker": {"type": "no_push", "params": {}}}
    planned = [PlannedRun(f"run-{i}", rule, {"id": "p", "instruction": "x"}, "rule", i) for i in range(10)]

    def fake(run: PlannedRun) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "rule_id": "r",
            "arm": "rule",
            "status": "ok",
            "model": "m",
            "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_tokens": 0, "cost_usd": 0.02},
        }

    result = execute_all(
        planned,
        fake,
        ledger=ledger,
        per_run_estimate=0.02,
        concurrency=1,
        out=tmp_path / "runs.jsonl",
        progress=lambda m: None,
    )
    assert result.stopped and "budget" in result.stopped
    assert len(result.records) == 2 and ledger.spent() == pytest.approx(0.04)
