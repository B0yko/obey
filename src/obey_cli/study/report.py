"""Write study/REPORT.md and the charts from the committed per-run summaries (no model calls).

uv run obey study report
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from obey_cli.score import wilson

CONDITIONS = ("baseline", "imperative", "prohibition", "reason")
LABELS = {"baseline": "no rule", "imperative": "imperative", "prohibition": "prohibition", "reason": "with a reason"}
HARNESS = {"claude-code": "Claude Code", "opencode": "OpenCode"}


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:.0f}%"


def _ci(k: int, n: int) -> str:
    if not n:
        return "–"
    lo, hi = wilson(k, n)
    return f"{k / n * 100:.0f}% [{lo * 100:.0f}–{hi * 100:.0f}]"


def _rate(rows: list[dict[str, Any]]) -> tuple[int, int]:
    ex = [r for r in rows if r["status"] == "ok" and r["verdict"] != "not_exercised"]
    return sum(r["verdict"] == "obeyed" for r in ex), len(ex)


def _by(rows: list[dict[str, Any]], *keys: str) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    out: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        out[tuple(r[k] for k in keys)].append(r)
    return out


THEMES: dict[str, dict[str, Any]] = {
    "light": {
        "bg": "#ffffff",
        "fg": "#1f2328",
        "muted": "#59636e",
        "grid": "#d1d9e0",
        "series": ["#8c959f", "#0969da", "#bf3989", "#1a7f37"],
        "after": "#1a7f37",
        "before": "#8c959f",
        "evasion": "#cf222e",
    },
    "dark": {
        "bg": "#0d1117",
        "fg": "#e6edf3",
        "muted": "#9198a1",
        "grid": "#3d444d",
        "series": ["#6e7681", "#4493f8", "#db61a2", "#3fb950"],
        "after": "#3fb950",
        "before": "#6e7681",
        "evasion": "#f85149",
    },
}


def _chart_conditions(rows: list[dict[str, Any]], out: Path) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    written = []
    harnesses = sorted({r["harness"] for r in rows})
    for theme, c in THEMES.items():
        fig, ax = plt.subplots(figsize=(8, 4.2), dpi=100)
        fig.patch.set_facecolor(c["bg"])
        ax.set_facecolor(c["bg"])
        width = 0.8 / len(CONDITIONS)
        for i, cond in enumerate(CONDITIONS):
            xs, ys, lo, hi = [], [], [], []
            for j, h in enumerate(harnesses):
                k, n = _rate([r for r in rows if r["harness"] == h and r["condition"] == cond])
                if not n:
                    continue
                low, high = wilson(k, n)
                xs.append(j + (i - 1.5) * width)
                ys.append(k / n * 100)
                lo.append(k / n * 100 - low * 100)
                hi.append(high * 100 - k / n * 100)
            ax.bar(xs, ys, width * 0.92, color=c["series"][i], label=LABELS[cond], zorder=2)
            ax.errorbar(xs, ys, yerr=[lo, hi], fmt="none", ecolor=c["fg"], elinewidth=1, capsize=2, zorder=3)
        ax.set_xticks(range(len(harnesses)), [HARNESS.get(h, h) for h in harnesses], color=c["fg"])
        ax.set_ylim(0, 105)
        ax.set_ylabel("probe compliance, % of exercised runs", color=c["muted"])
        ax.tick_params(colors=c["muted"])
        ax.grid(axis="y", color=c["grid"], linewidth=0.6, zorder=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.legend(frameon=False, labelcolor=c["fg"], ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.12))
        fig.tight_layout()
        path = out / f"compliance-by-phrasing-{theme}.svg"
        fig.savefig(path, facecolor=c["bg"], metadata={"Date": None, "Creator": None})
        plt.close(fig)
        written.append(path.name)
    return written


def _chart_enforcement(main: list[dict[str, Any]], enf: list[dict[str, Any]], out: Path) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cells = sorted({(r["slot"], r["harness"]) for r in enf})
    if not cells:
        return []
    slots = sorted({s for s, _ in cells})
    written = []
    for theme, c in THEMES.items():
        fig, ax = plt.subplots(figsize=(8, 0.45 * len(slots) + 1.4), dpi=100)
        fig.patch.set_facecolor(c["bg"])
        ax.set_facecolor(c["bg"])
        for i, slot in enumerate(slots):
            bk, bn = _rate(
                [
                    r
                    for r in main
                    if r["slot"] == slot
                    and r["condition"] == "imperative"
                    and any(r["harness"] == h for s, h in cells if s == slot)
                ]
            )
            ak, an = _rate([r for r in enf if r["slot"] == slot])
            if bn and an:
                ax.plot([bk / bn * 100, ak / an * 100], [i, i], color=c["grid"], linewidth=2, zorder=1)
                ax.scatter([bk / bn * 100], [i], color=c["before"], s=40, zorder=2, label="before" if i == 0 else None)
                ax.scatter(
                    [ak / an * 100], [i], color=c["after"], s=40, zorder=3, label="with hooks" if i == 0 else None
                )
        ax.set_yticks(range(len(slots)), [s.replace("_", " ") for s in slots], color=c["fg"])
        ax.set_xlim(0, 105)
        ax.set_xlabel("probe compliance, % of exercised runs", color=c["muted"])
        ax.tick_params(colors=c["muted"])
        ax.grid(axis="x", color=c["grid"], linewidth=0.6, zorder=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.legend(frameon=False, labelcolor=c["fg"], loc="lower right")
        fig.tight_layout()
        path = out / f"enforcement-before-after-{theme}.svg"
        fig.savefig(path, facecolor=c["bg"], metadata={"Date": None, "Creator": None})
        plt.close(fig)
        written.append(path.name)
    return written


def write_report(root: Path, charts: bool = True) -> str:
    from obey_cli.study.analysis import analyse

    results = root / "study" / "results"
    pilot = _rows(results / "pilot.jsonl")
    main = _rows(results / "main.jsonl")
    enf = _rows(results / "enforce.jsonl")
    survey = (
        json.loads((root / "study" / "survey" / "summary.json").read_text())
        if (root / "study" / "survey" / "summary.json").exists()
        else None
    )
    plan = json.loads((results / "plan.json").read_text()) if (results / "plan.json").exists() else None
    analysis = analyse(main) if main else None
    if analysis is not None:
        (results / "analysis.json").write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
    chart_dir = root / "docs" / "images"
    chart_dir.mkdir(parents=True, exist_ok=True)
    chart_files: list[str] = []
    if charts and main:
        chart_files += _chart_conditions(main, chart_dir)
    if charts and enf:
        chart_files += _chart_enforcement(main, enf, chart_dir)
    lines = ["# Which AGENTS.md rules do coding agents follow, and does the phrasing matter?", ""]
    lines += _survey_section(survey)
    lines += _experiment_section(main, pilot, plan, analysis)
    lines += _enforcement_section(main, enf)
    lines += _costs_section(pilot, main, enf)
    deviations = root / "study" / "DEVIATIONS.md"
    lines += ["## Deviations from the pre-registration", ""]
    lines += [deviations.read_text(encoding="utf-8").strip() if deviations.exists() else "None.", ""]
    (root / "study" / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return (
        f"wrote study/REPORT.md ({len(main)} main runs, {len(enf)} enforcement runs; charts: {', '.join(chart_files)})"
    )


def _survey_section(s: dict[str, Any] | None) -> list[str]:
    if not s:
        return []
    out = ["## Part 1: survey of public AGENTS.md files", ""]
    out.append(
        f"{s['repositories']} public repositories with a root AGENTS.md, sampled through GitHub code search "
        f"(size-sliced queries, forks removed; median {s.get('stars_median', 0):.0f} stars). The survey "
        "measures what the files say, not whether agents follow them. Only URLs, commit SHAs, licence ids and "
        "derived counts are stored (`study/survey/`)."
    )
    out.append("")
    rpf = s["rules_per_file"]
    out += [
        f"- Rules per file: median {rpf['median']:.0f}, mean {rpf['mean']:.1f}, 90th percentile {rpf['p90']}, "
        f"max {rpf['max']}; {s['files_with_no_rules']} files had no directive at all.",
        f"- Mechanically checkable (deterministic extractor): {s['checkable_share'] * 100:.1f}% of "
        f"{s['rules_total']} rules; {s['repos_with_any_checkable']} of {s['fetched']} files have at least one.",
        f"- Enforceable before the action by a pre-tool hook: {s['pre_tool_enforceable_share'] * 100:.1f}% of rules; "
        f"another {s['stop_or_commit_only_share'] * 100:.1f}% only at stop or commit time.",
    ]
    if s.get("llm"):
        llm = s["llm"]
        out.append(
            f"- An LLM pass (unreviewed proposals, `anthropic/claude-haiku-5.5`) called "
            f"{llm['proposed_share_of_unmapped'] * 100:.0f}% of the {llm['uncheckable_sent']} unmapped rules "
            f"checkable; with those the checkable share would be {llm['checkable_share_with_llm'] * 100:.1f}%."
        )
    if s.get("enforcement"):
        e = s["enforcement"]
        out.append(
            f"- Repositories that already enforce something mechanically: {e['any_repos']} "
            f"({e['any_share'] * 100:.0f}%): git hooks (pre-commit, husky, lefthook) in {e['git_hook_repos']}, "
            f"agent hooks (Claude Code, Codex, Copilot) in {e['agent_hooks_repos']}."
        )
    out += ["", "| Rule type | Rules | Repositories |", "|---|---|---|"]
    out += [f"| {t['type']} | {t['rules']} | {t['repositories']} |" for t in s["types"]]
    return [*out, ""]


def _experiment_section(
    main: list[dict[str, Any]], pilot: list[dict[str, Any]], plan: dict[str, Any] | None, a: dict[str, Any] | None
) -> list[str]:
    out = ["## Part 2: controlled experiment on phrasing", ""]
    if plan:
        out.append(
            f"Pilot: {plan['pilot_runs']} runs, compliance p̄ = {plan['p_bar']:.2f}, ICC = {plan['icc']:.2f}, "
            f"exercised share {plan['exercised_share']:.2f}, ${plan['cost_per_run_usd']:.4f} per run. "
            f"The pre-registered formula gave {plan['trials_per_cell']} trials per cell."
        )
        out.append("")
    if not main or a is None:
        return [*out, "The main grid has not run yet.", ""]
    versions = sorted(
        {f"{HARNESS.get(r['harness'], r['harness'])} {r.get('agent_version') or ''}".strip() for r in main}
    )
    dates = sorted(r["started_at"][:10] for r in main if r.get("started_at"))
    out.append(
        f"{a['n_runs']} runs ({a['n_exercised']} exercised); {', '.join(versions)}; model "
        f"`{main[0].get('model')}`; {dates[0]} to {dates[-1]}; Mac Studio M4 Max, 128 GB. Compliance is "
        "probe compliance: compliance on tempting tasks, not in natural use."
    )
    out += ["", "| Condition | Compliance [95% CI] | Exercised runs |", "|---|---|---|"]
    for cond in CONDITIONS:
        pc = a["per_condition"][cond]
        ex = a["exercised_share"].get(cond, {"exercised": 0, "runs": 0})
        out.append(f"| {LABELS[cond]} | {_ci(pc['obeyed'], pc['n'])} | {ex['exercised']} of {ex['runs']} |")
    h1 = a["rule_present_vs_baseline"]
    out += ["", f"**H1 (rule present vs no rule):** {_pp(h1)}.", "", "**H2 (phrasing), Holm-adjusted:**", ""]
    for c in a["phrasing"]:
        out.append(
            f"- {LABELS[c['a'][0]]} vs {LABELS[c['b'][0]]}: {_pp(c)}, adjusted p = {_p(c.get('p_adj'))}"
            f"{' (significant)' if c.get('reject') else ''}."
        )
    out += [
        "",
        "<details><summary>Compliance by rule slot, repository and harness</summary>",
        "",
        "| Slot | Repository | Harness | No rule | Imperative | Prohibition | With a reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for (slot, repo, harness), rows in sorted(_by(main, "slot", "repo", "harness").items()):
        cells = [_ci(*_rate([r for r in rows if r["condition"] == c])) for c in CONDITIONS]
        out.append(f"| {slot} | {repo} | {HARNESS.get(harness, harness)} | " + " | ".join(cells) + " |")
    out += ["", "</details>", ""]
    return out


def _p(p: float | None) -> str:
    return "–" if p is None else ("< 0.001" if p < 0.001 else f"{p:.3f}")


def _pp(c: dict[str, Any]) -> str:
    eff = c.get("effect")
    if eff is None:
        return "not estimable"
    lo, hi = c.get("ci_low"), c.get("ci_high")
    interval = f" [95% CI {lo * 100:+.1f} to {hi * 100:+.1f}]" if lo is not None and hi is not None else ""
    return f"{eff * 100:+.1f} percentage points{interval}, p = {_p(c.get('p'))}"


def _enforcement_section(main: list[dict[str, Any]], enf: list[dict[str, Any]]) -> list[str]:
    out = ["## Part 3: enforcement", ""]
    if not enf:
        return [*out, "Not run yet.", ""]
    cells = {(r["repo"], r["slot"], r["harness"]) for r in enf}
    before = [r for r in main if r["condition"] == "imperative" and (r["repo"], r["slot"], r["harness"]) in cells]
    bk, bn = _rate(before)
    ak, an = _rate(enf)
    blocked = [r for r in enf if r["status"] == "ok" and r["denied"] > 0]
    evaded = [r for r in blocked if r["verdict"] == "violated"]
    out.append(
        f"Rules violated at least once in the imperative condition ({len(cells)} slot × repository × harness "
        f"cells) were compiled into hooks for that harness plus the git pre-commit check and re-run."
    )
    out += [
        "",
        f"- Before (main grid, imperative): {_ci(bk, bn)} of exercised runs.",
        f"- With hooks: {_ci(ak, an)} of exercised runs.",
        f"- Evasions: {len(evaded)} of {len(blocked)} runs in which a hook blocked at least once still broke the rule "
        f"by the end ({_ci(len(evaded), len(blocked)).split(' ')[0] if blocked else '–'}).",
        "",
    ]
    out += ["| Slot | Harness | Before | With hooks | Blocked runs | Evasions |", "|---|---|---|---|---|---|"]
    for (repo, slot, harness), rows in sorted(_by(enf, "repo", "slot", "harness").items()):
        b = [r for r in before if (r["repo"], r["slot"], r["harness"]) == (repo, slot, harness)]
        bl = [r for r in rows if r["status"] == "ok" and r["denied"] > 0]
        out.append(
            f"| {slot} ({repo}) | {HARNESS.get(harness, harness)} | {_ci(*_rate(b))} | {_ci(*_rate(rows))} | "
            f"{len(bl)} | {sum(r['verdict'] == 'violated' for r in bl)} |"
        )
    return [*out, ""]


def _costs_section(*phases: list[dict[str, Any]]) -> list[str]:
    names = ("pilot", "main grid", "enforcement")
    out = ["## Cost", "", "| Phase | Runs | Cost (USD) | Per run |", "|---|---|---|---|"]
    total = 0.0
    for name, rows in zip(names, phases, strict=True):
        cost = sum(r["cost_usd"] for r in rows)
        total += cost
        out.append(
            f"| {name} | {len(rows)} | {cost:.2f} | {cost / len(rows):.4f} |" if rows else f"| {name} | 0 | – | – |"
        )
    return [*out, f"| total | {sum(len(p) for p in phases)} | {total:.2f} | |", ""]
