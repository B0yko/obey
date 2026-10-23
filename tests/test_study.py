from __future__ import annotations

import random
from pathlib import Path

import pytest

from obey_cli.study import analysis
from obey_cli.study import design as d

DESIGN = d.load(Path(__file__).parents[1] / "study" / "design.yaml")


def test_render_conditions() -> None:
    repo = DESIGN["repos"]["ts-web"]
    base, line = d.render(repo, "command_forbidden", "baseline")
    assert line is None and "pnpm for all package operations" not in base
    text, line = d.render(repo, "command_forbidden", "prohibition")
    assert line is not None and text.splitlines()[line - 1] == "- Never use npm or yarn."
    assert text.count("\n- ") == 25 + 3  # 25 rules plus three layout bullets
    assert base.count("\n- ") == 24 + 3
    other, _ = d.render(repo, "no_push", "reason")
    assert "- Use pnpm for all package operations." in other


def test_rule_for_slot_points_at_its_line() -> None:
    rule = d.rule(DESIGN, "py-service", "path_forbidden", "reason")
    _text, line = d.render(DESIGN["repos"]["py-service"], "path_forbidden", "reason")
    assert rule["source"]["lines"] == [line, line]
    assert rule["checker"]["type"] == "path_forbidden"
    assert rule["text"].startswith("Add a new numbered migration")


def test_cells_cover_the_factorial() -> None:
    assert len(d.cells(DESIGN)) == 10 * 2 * 2 * 4


def _rows(effects: dict[str, float], n: int = 30, seed: int = 1) -> list[dict[str, object]]:
    """Exact proportions per stratum (round(p * n) obeyed), shuffled, so a null contrast has effect 0."""
    rng = random.Random(seed)
    rows: list[dict[str, object]] = []
    for slot in ("a", "b", "c", "d", "e"):
        for repo in ("py", "ts"):
            for harness in ("cc", "oc"):
                for cond, p in effects.items():
                    k = round(p * n)
                    verdicts = ["obeyed"] * k + ["violated"] * (n - k)
                    rng.shuffle(verdicts)
                    rows += [
                        {
                            "slot": slot,
                            "repo": repo,
                            "harness": harness,
                            "condition": cond,
                            "status": "ok",
                            "verdict": v,
                        }
                        for v in verdicts
                    ]
    return rows


def test_analysis_detects_a_real_difference_and_not_a_null() -> None:
    rows = _rows({"baseline": 0.3, "imperative": 0.6, "prohibition": 0.6, "reason": 0.9}, n=20)
    result = analysis.analyse(rows, permutations=400, bootstrap=200)
    assert result["rule_present_vs_baseline"]["p"] < 0.01
    by = {(c["a"][0], c["b"][0]): c for c in result["phrasing"]}
    assert by[("reason", "imperative")]["reject"] is True
    assert by[("reason", "imperative")]["effect"] == pytest.approx(0.3, abs=0.1)
    assert by[("prohibition", "imperative")]["reject"] is False
    lo, hi = by[("reason", "imperative")]["ci_low"], by[("reason", "imperative")]["ci_high"]
    assert lo is not None and hi is not None and lo - 1e-9 <= 0.3 <= hi + 1e-9


def test_exclusions_and_holm() -> None:
    rows = [
        {
            "slot": "a",
            "repo": "r",
            "harness": "h",
            "condition": "imperative",
            "status": "ok",
            "verdict": "not_exercised",
        },
        {"slot": "a", "repo": "r", "harness": "h", "condition": "imperative", "status": "error", "verdict": "obeyed"},
    ]
    obs, excluded = analysis.observations(rows)
    assert obs == [] and excluded == {"not_exercised": 1, "incomplete": 1}
    h = analysis.holm([0.01, 0.04, 0.03])
    assert [x["reject"] for x in h] == [True, False, False]
    assert h[0]["p_adj"] == pytest.approx(0.03)


def test_trials_needed_formula() -> None:
    pilot = _rows({"baseline": 0.5, "imperative": 0.75, "prohibition": 0.75, "reason": 0.75}, n=1)
    plan = analysis.trials_needed(pilot)
    assert 0.55 <= plan["p1"] <= 0.95 and plan["trials_per_cell"] >= 1
    assert plan["n_arm"] > 100
