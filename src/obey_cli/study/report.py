"""Write study/REPORT.md and the charts from the committed per-run summaries (no model calls).

uv run obey study report
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from obey_cli.score import wilson

CONDITIONS = ("baseline", "imperative", "prohibition", "reason")
LABELS = {"baseline": "no rule", "imperative": "imperative", "prohibition": "prohibition", "reason": "with a reason"}
HARNESS = {"claude-code": "Claude Code", "opencode": "OpenCode"}
# For agents whose stream does not report a version: the version pinned in the sandbox image the study used.
IMAGE_VERSIONS = {"opencode": "1.19.4"}


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
                lo.append(max(0.0, k / n * 100 - low * 100))  # rounding can put a Wilson bound past the estimate
                hi.append(max(0.0, high * 100 - k / n * 100))
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


def _chart_enforcement(main: list[dict[str, Any]], sets: dict[str, list[dict[str, Any]]], out: Path) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows_spec = []  # (label, before rows, after rows)
    measured = {name: _measurable(main, sets.get(name) or [])[0] for name, _, _ in ENFORCE_SETS}
    several = sum(bool(v) for v in measured.values()) > 1
    for name, after in measured.items():
        for slot in sorted({r["slot"] for r in after}):
            mine = [r for r in after if r["slot"] == slot]
            label = slot.replace("_", " ") + (f" ({name})" if several else "")
            rows_spec.append((label, _before(main, mine), mine))
    if not rows_spec:
        return []
    written = []
    for theme, c in THEMES.items():
        fig, ax = plt.subplots(figsize=(8, 0.42 * len(rows_spec) + 1.4), dpi=100)
        fig.patch.set_facecolor(c["bg"])
        ax.set_facecolor(c["bg"])
        for i, (_, before, after) in enumerate(rows_spec):
            bk, bn = _rate(before)
            ak, an = _rate(after)
            if bn and an:
                ax.plot([bk / bn * 100, ak / an * 100], [i, i], color=c["grid"], linewidth=2, zorder=1)
                ax.scatter([bk / bn * 100], [i], color=c["before"], s=40, zorder=2, label="before" if i == 0 else None)
                ax.scatter(
                    [ak / an * 100], [i], color=c["after"], s=40, zorder=3, label="with hooks" if i == 0 else None
                )
        ax.set_yticks(range(len(rows_spec)), [label for label, _, _ in rows_spec], color=c["fg"])
        ax.invert_yaxis()
        ax.set_xlim(0, 105)
        ax.set_xlabel("probe compliance, % of exercised runs", color=c["muted"])
        ax.tick_params(colors=c["muted"])
        ax.grid(axis="x", color=c["grid"], linewidth=0.6, zorder=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.legend(frameon=False, labelcolor=c["fg"], ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.0))
        fig.tight_layout()
        path = out / f"enforcement-before-after-{theme}.svg"
        fig.savefig(path, facecolor=c["bg"], metadata={"Date": None, "Creator": None})
        plt.close(fig)
        written.append(path.name)
    return written


def _phase_rows(results: Path, phase: str) -> list[dict[str, Any]]:
    """A phase's summaries, rescored with the current checkers when that file exists (study/DEVIATIONS.md)."""
    rescored = results / f"{phase}.rescored.jsonl"
    return _rows(rescored if rescored.exists() else results / f"{phase}.jsonl")


# Part 3 as run (study/DEVIATIONS.md, deviation 4): the registered phase, then the replacement sets.
ENFORCE_SETS = (
    ("3a", "rule present, with hooks", ("enforce-prohibition", "enforce-reason")),
    ("3b", "hooks without the rule in AGENTS.md", ("enforce-baseline",)),
)


def write_report(root: Path, charts: bool = True) -> str:
    from obey_cli.study.analysis import analyse

    results = root / "study" / "results"
    pilot = _rows(results / "pilot.jsonl")
    main = _rows(results / "main.jsonl")
    corrected = _rows(results / "main.rescored.jsonl")
    enf = _rows(results / "enforce.jsonl")
    sets = {name: [r for phase in phases for r in _phase_rows(results, phase)] for name, _, phases in ENFORCE_SETS}
    survey = (
        json.loads((root / "study" / "survey" / "summary.json").read_text())
        if (root / "study" / "survey" / "summary.json").exists()
        else None
    )
    plan = json.loads((results / "plan.json").read_text()) if (results / "plan.json").exists() else None
    analysis = analyse(main) if main else None
    if analysis is not None:
        (results / "analysis.json").write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
    analysis_c = analyse(corrected) if corrected else None
    if analysis_c is not None:
        (results / "analysis.rescored.json").write_text(json.dumps(analysis_c, indent=2) + "\n", encoding="utf-8")
    chart_dir = root / "docs" / "images"
    chart_dir.mkdir(parents=True, exist_ok=True)
    chart_files: list[str] = []
    if charts and (corrected or main):
        chart_files += _chart_conditions(corrected or main, chart_dir)
    if charts and any(sets.values()):
        chart_files += _chart_enforcement(corrected or main, sets, chart_dir)
    lines = ["# Which AGENTS.md rules do coding agents follow, and does the phrasing matter?", ""]
    lines += _survey_section(survey)
    design_file = root / "study" / "design.yaml"
    design = yaml.safe_load(design_file.read_text(encoding="utf-8")) if design_file.exists() else None
    lines += _experiment_section(main, pilot, plan, analysis, corrected, analysis_c, design)
    lines += _enforcement_section(corrected or main, enf, sets)
    lines += _costs_section(
        [("pilot", pilot), ("main grid", main), ("part 3 as registered", enf)]
        + [(f"part {name}", sets[name]) for name, _, _ in ENFORCE_SETS]
    )
    deviations = root / "study" / "DEVIATIONS.md"
    lines += ["## Deviations from the pre-registration", ""]
    lines += [deviations.read_text(encoding="utf-8").strip() if deviations.exists() else "None.", ""]
    (root / "study" / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    n_sets = sum(len(v) for v in sets.values())
    return (
        f"wrote study/REPORT.md ({len(main)} main runs, {len(enf) + n_sets} enforcement runs; "
        f"charts: {', '.join(chart_files)})"
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
    main: list[dict[str, Any]],
    pilot: list[dict[str, Any]],
    plan: dict[str, Any] | None,
    a: dict[str, Any] | None,
    corrected: list[dict[str, Any]] | None = None,
    ac: dict[str, Any] | None = None,
    design: dict[str, Any] | None = None,
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
        {
            f"{HARNESS.get(r['harness'], r['harness'])} "
            f"{r.get('agent_version') or IMAGE_VERSIONS.get(r['harness'], '')}".strip()
            for r in main
        }
    )
    dates = sorted(r["started_at"][:10] for r in main if r.get("started_at"))
    incomplete = a["excluded"]["incomplete"]
    out.append(
        f"{a['n_runs']} runs ({incomplete} incomplete and re-run once; {a['n_exercised']} exercised); "
        f"{', '.join(versions)}; model `{main[0].get('model')}`; {dates[0]} to {dates[-1]}; Mac Studio M4 Max, "
        "128 GB. Compliance is probe compliance: compliance on tempting tasks, not in natural use."
    )
    if ac is not None:
        out += [
            "",
            "Two sets of verdicts are reported (deviation 2): the **registered** verdicts recorded during the runs, "
            "and the **corrected** verdicts, the same runs scored again after fixing a checker bug that marked 109 "
            "ts-web `dependency_unchanged` runs as violated in every condition.",
        ]
        out += ["", "| Condition | Registered | Corrected | Exercised runs |", "|---|---|---|---|"]
    else:
        out += ["", "| Condition | Compliance [95% CI] | Exercised runs |", "|---|---|---|"]
    for cond in CONDITIONS:
        pc = a["per_condition"][cond]
        ex = a["exercised_share"].get(cond, {"exercised": 0, "runs": 0})
        cells = [_ci(pc["obeyed"], pc["n"])]
        if ac is not None:
            pcc = ac["per_condition"][cond]
            cells.append(_ci(pcc["obeyed"], pcc["n"]))
        out.append(f"| {LABELS[cond]} | " + " | ".join(cells) + f" | {ex['exercised']} of {ex['runs']} |")
    for title, an in (("registered", a), ("corrected", ac)):
        if an is None:
            continue
        h1 = an["rule_present_vs_baseline"]
        out += ["", f"Tests on the {title} verdicts:", "", f"- **H1 (rule present vs no rule):** {_pp(h1)}."]
        out.append("- **H2 (phrasing), Holm-adjusted:**")
        for c in an["phrasing"]:
            out.append(
                f"  - {LABELS[c['a'][0]]} vs {LABELS[c['b'][0]]}: {_pp(c)}, adjusted p {_padj(c.get('p_adj'))}"
                f"{' (significant)' if c.get('reject') else ''}."
            )
    detail = corrected if corrected else main
    final = ac if ac is not None else a
    quoted: set[tuple[str, str]] = set()
    for c in final["phrasing"]:
        if c.get("reject"):
            text, rules = _drivers(detail, c["a"][0], c["b"][0])
            out += [
                "",
                f"Cells where {LABELS[c['a'][0]]} and {LABELS[c['b'][0]]} differ"
                + (" (corrected verdicts)" if corrected else "")
                + f": {text}. A pooled difference that comes from few cells is why the cluster bootstrap interval "
                "reaches zero while the permutation test rejects.",
            ]
            quoted |= rules
    for repo, slot in sorted(quoted):
        spec = ((design or {}).get("repos", {}).get(repo, {}).get("slots", {}) or {}).get(slot)
        if spec:
            out += ["", f"The phrasings of that rule ({slot}, {repo}):", ""]
            out += [f"- {LABELS[cond]}: {spec[cond]}" for cond in ("imperative", "prohibition", "reason")]
            out += ["", f"Its probe: {spec['probe']}"]
    out += [
        "",
        "<details><summary>Compliance by rule slot, repository and harness"
        + (" (corrected verdicts)" if corrected else "")
        + "</summary>",
        "",
        "| Slot | Repository | Harness | No rule | Imperative | Prohibition | With a reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for (slot, repo, harness), rows in sorted(_by(detail, "slot", "repo", "harness").items()):
        cells = [_ci(*_rate([r for r in rows if r["condition"] == c])) for c in CONDITIONS]
        out.append(f"| {slot} | {repo} | {HARNESS.get(harness, harness)} | " + " | ".join(cells) + " |")
    out += ["", "</details>", ""]
    return out


def _p(p: float | None) -> str:
    return "–" if p is None else ("< 0.001" if p < 0.001 else f"{p:.3f}")


def _padj(p: float | None) -> str:
    text = _p(p)
    return text if text.startswith("<") else f"= {text}"


def _drivers(rows: list[dict[str, Any]], a: str, b: str) -> tuple[str, set[tuple[str, str]]]:
    """The cells in which conditions `a` and `b` differ, for reading a pooled phrasing effect, and their rules."""
    parts = []
    rules = set()
    for (slot, repo, harness), cell in sorted(_by(rows, "slot", "repo", "harness").items()):
        ka, na = _rate([r for r in cell if r["condition"] == a])
        kb, nb = _rate([r for r in cell if r["condition"] == b])
        if na and nb and ka * nb != kb * na:
            parts.append(
                f"{slot} ({repo}, {HARNESS.get(harness, harness)}): {LABELS[a]} {ka}/{na}, {LABELS[b]} {kb}/{nb}"
            )
            rules.add((repo, slot))
    return ("; ".join(parts) if parts else "none"), rules


def _pp(c: dict[str, Any]) -> str:
    eff = c.get("effect")
    if eff is None:
        return "not estimable"
    lo, hi = c.get("ci_low"), c.get("ci_high")
    interval = f" [95% CI {lo * 100:+.1f} to {hi * 100:+.1f}]" if lo is not None and hi is not None else ""
    p = _p(c.get("p"))
    return f"{eff * 100:+.1f} percentage points{interval}, p {p if p.startswith('<') else '= ' + p}"


def _cells(rows: list[dict[str, Any]]) -> set[tuple[str, str, str, str]]:
    return {(r["repo"], r["slot"], r["harness"], r["condition"]) for r in rows}


def _measurable(
    main: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(runs in cells the main grid's verdicts show violated, the other runs): only those cells measure anything."""
    broken = {c for c in _cells(rows) if any(r["verdict"] == "violated" for r in _before(main, [_cell_row(c)]))}
    keep = [r for r in rows if (r["repo"], r["slot"], r["harness"], r["condition"]) in broken]
    return keep, [r for r in rows if (r["repo"], r["slot"], r["harness"], r["condition"]) not in broken]


def _cell_row(cell: tuple[str, str, str, str]) -> dict[str, Any]:
    return dict(zip(("repo", "slot", "harness", "condition"), cell, strict=True))


def _before(main: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cells = _cells(after)
    return [r for r in main if (r["repo"], r["slot"], r["harness"], r["condition"]) in cells]


def _evasions(rows: list[dict[str, Any]]) -> tuple[int, int]:
    blocked = [r for r in rows if r["status"] == "ok" and r["denied"] > 0]
    return sum(r["verdict"] == "violated" for r in blocked), len(blocked)


def _cell_table(main: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[str]:
    out = [
        "| Slot (repository) | Harness | Condition | Before | With hooks | Blocked runs | Evasions |",
        "|---|---|---|---|---|---|---|",
    ]
    for (repo, slot, harness, cond), rows in sorted(_by(after, "repo", "slot", "harness", "condition").items()):
        before = [
            r for r in main if (r["repo"], r["slot"], r["harness"], r["condition"]) == (repo, slot, harness, cond)
        ]
        ev, bl = _evasions(rows)
        out.append(
            f"| {slot} ({repo}) | {HARNESS.get(harness, harness)} | {LABELS[cond]} | {_ci(*_rate(before))} | "
            f"{_ci(*_rate(rows))} | {bl} | {ev} |"
        )
    return out


def _enforcement_section(
    main: list[dict[str, Any]], enf: list[dict[str, Any]], sets: dict[str, list[dict[str, Any]]] | None = None
) -> list[str]:
    from obey_cli.study.analysis import enforcement_contrast

    out = ["## Part 3: enforcement", ""]
    sets = sets or {}
    if not enf and not any(sets.values()):
        return [*out, "Not run yet.", ""]
    out.append(
        "Each selected rule was compiled by `obey enforce` into hooks for the run's harness plus the git pre-commit "
        "check, and the same probe was run again. *Before* is the same slot, repository, harness and condition in "
        "the main grid (corrected verdicts). An evasion is a run in which a hook denied at least once and the rule "
        "was still broken by the end."
    )
    out.append("")
    for name, title, _ in ENFORCE_SETS:
        rows = sets.get(name) or []
        if not rows:
            continue
        after, excluded = _measurable(main, rows)
        out += [f"### Part {name}: {title}", ""]
        if not after:
            ek, en = _rate(rows)
            out += [
                f"None of this set's cells was violated in the main grid once the checker corrections were applied "
                f"(deviation 5), so it has nothing to measure. For completeness: {len(rows)} runs, {_ci(ek, en)} "
                "scored compliant.",
                "",
            ]
            continue
        before = _before(main, after)
        bk, bn = _rate(before)
        ak, an = _rate(after)
        ev, bl = _evasions(after)
        c = enforcement_contrast(before, after)
        out += [
            f"- Before: {_ci(bk, bn)} of exercised runs.",
            f"- With hooks: {_ci(ak, an)} of exercised runs; difference {_pp(c)} "
            f"(stratified permutation test over {c['cells']} cells).",
            f"- Evasions: {ev} of {bl} runs in which a hook blocked at least once ({_ci(ev, bl) if bl else '–'}).",
            "",
        ]
        out += [*_cell_table(main, after), ""]
        if excluded:
            cells = sorted({(r["slot"], r["repo"], HARNESS.get(r["harness"], r["harness"])) for r in excluded})
            out += [
                f"Not counted: {len(excluded)} runs in "
                + ", ".join(f"{slot} ({repo}, {h})" for slot, repo, h in cells)
                + ", cells that the corrected verdicts show were never violated (deviation 5).",
                "",
            ]
    if enf:
        ek, en = _rate(enf)
        out += [
            "### Part 3 as registered (not interpreted)",
            "",
            f"The registered selection (cells violated in the imperative condition) picked only the two cells of a "
            f"checker bug, and the OpenCode runs were recorded with blocked commands counted as executed "
            f"(deviation 3). For completeness: {len(enf)} runs, {_ci(ek, en)} scored compliant.",
            "",
            *_cell_table(main, enf),
            "",
        ]
    return out


def _costs_section(phases: list[tuple[str, list[dict[str, Any]]]]) -> list[str]:
    out = ["## Cost", "", "| Phase | Runs | Cost (USD) | Per run |", "|---|---|---|---|"]
    total = 0.0
    for name, rows in phases:
        cost = sum(r["cost_usd"] for r in rows)
        total += cost
        out.append(
            f"| {name} | {len(rows)} | {cost:.2f} | {cost / len(rows):.4f} |" if rows else f"| {name} | 0 | – | – |"
        )
    return [*out, f"| total | {sum(len(rows) for _, rows in phases)} | {total:.2f} | |", ""]
