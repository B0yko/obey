"""Build the run report (JSON), and render it as Markdown, a self-contained HTML page and a shields.io badge."""

from __future__ import annotations

import datetime as _dt
import html
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from obey_cli import __version__
from obey_cli.score import AGENT_NAMES, FOLLOWED_THRESHOLD, RuleScore, pooled, summary_sentence

SCHEMA_ID = "obey-report-v1"


def build_report(
    rules: Sequence[Mapping[str, Any]],
    scores: Sequence[RuleScore],
    agents: Sequence[Mapping[str, Any]],
    *,
    repository: str = "",
    cost_usd: float | None = None,
    runs: int = 0,
    before: Sequence[RuleScore] | None = None,
    hardware: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    by_rule = {str(r["id"]): r for r in rules}
    agent_ids = [str(a["agent"]) for a in agents]
    report: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "obey_version": __version__,
        "generated_at": generated_at or _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "repository": repository,
        "hardware": hardware,
        "agents": [dict(a) for a in agents],
        "summary": [summary_sentence(scores, a) for a in agent_ids],
        "rules": [
            {
                "id": str(r["id"]),
                "text": str(r.get("text", "")),
                "source": dict(r.get("source") or {}),
                "checker": str((r.get("checker") or {}).get("type", "")),
                "status": str(r.get("status", "active")),
            }
            for r in rules
        ],
        "scores": [s.as_dict() for s in scores],
        "pooled": {
            a: {arm: dict(pooled(scores, a, arm)) for arm in ("rule", "baseline", "enforced")} for a in agent_ids
        },
        "suggestions": _suggestions(scores, by_rule),
        "cost": {"total_usd": cost_usd, "runs": runs, "per_run_usd": (cost_usd / runs) if cost_usd and runs else None},
        "compare": None,
    }
    if before is not None:
        report["compare"] = compare(before, scores)
    return report


def compare(before: Iterable[RuleScore], after: Iterable[RuleScore]) -> dict[str, Any]:
    """Per-rule compliance before enforcement (rule arm) and after (enforced arm), with evasions."""
    old = {(s.rule_id, s.agent): s for s in before if s.arm == "rule"}
    new = {(s.rule_id, s.agent): s for s in after if s.arm == "enforced"}
    rows = []
    for key in sorted(set(old) | set(new)):
        b, a = old.get(key), new.get(key)
        rows.append(
            {
                "rule_id": key[0],
                "agent": key[1],
                "before": b.compliance if b else None,
                "before_n": b.exercised if b else 0,
                "after": a.compliance if a else None,
                "after_n": a.exercised if a else 0,
                "blocked_runs": a.blocked_runs if a else 0,
                "evasions": a.evasions if a else 0,
            }
        )
    befores = list(old.values())
    afters = list(new.values())
    return {
        "rows": rows,
        "before": dict(pooled(befores, None, "rule")),
        "after": dict(pooled(afters, None, "enforced")),
    }


def _suggestions(scores: Iterable[RuleScore], rules: Mapping[str, Mapping[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for s in scores:
        if s.arm != "rule":
            continue
        if s.compliance is None:
            out.append(
                {
                    "rule_id": s.rule_id,
                    "agent": s.agent,
                    "kind": "never_exercised",
                    "text": "This rule was never exercised by its probe; edit the probe or check the rule's scope.",
                }
            )
        elif s.compliance < FOLLOWED_THRESHOLD and (rules.get(s.rule_id, {}).get("checker") or {}).get("type"):
            out.append(
                {
                    "rule_id": s.rule_id,
                    "agent": s.agent,
                    "kind": "enforce",
                    "text": "Broken in some exercised runs; `obey enforce` can compile it into hooks.",
                }
            )
    return out


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.0f}%"


def _ci(s: Mapping[str, Any]) -> str:
    if s.get("compliance") is None:
        return "not exercised"
    return f"{_pct(s['compliance'])} [{_pct(s['ci_low'])}–{_pct(s['ci_high'])}]"


def _evidence_text(s: Mapping[str, Any]) -> str:
    example = s.get("violation_example") or {}
    evidence = (example.get("evidence") or [{}])[0]
    text = str(evidence.get("text", "")).strip().splitlines()
    return text[0][:120] if text else ""


def render_markdown(report: Mapping[str, Any]) -> str:
    rules = {r["id"]: r for r in report["rules"]}
    lines = [f"# obey report{' — ' + report['repository'] if report.get('repository') else ''}", ""]
    for sentence in report["summary"]:
        lines.append(f"**{sentence}.**")
    lines.append("")
    lines.append("Compliance is obeyed ÷ exercised runs on tempting tasks, with a Wilson 95% interval.")
    lines.append("")
    for agent in report["agents"]:
        name = AGENT_NAMES.get(agent["agent"], agent["agent"])
        lines += [f"## {name} {agent.get('version') or ''} · {agent.get('model') or ''}".rstrip(" ·"), ""]
        lines.append(
            "| Rule | Source | Compliance [95% CI] | Exercised | Baseline (rule removed) | Example violation |"
        )
        lines.append("|---|---|---|---|---|---|")
        mine = [s for s in report["scores"] if s["agent"] == agent["agent"]]
        base = {s["rule_id"]: s for s in mine if s["arm"] == "baseline"}
        for s in (s for s in mine if s["arm"] == "rule"):
            rule = rules.get(s["rule_id"], {})
            src = rule.get("source") or {}
            where = f"{src.get('file', '')}:{(src.get('lines') or [''])[0]}"
            b = base.get(s["rule_id"])
            lines.append(
                f"| {_md(rule.get('text', s['rule_id']))} | `{where}` | {_ci(s)} | {s['exercised']}/{s['runs']} | "
                f"{_ci(b) if b else '–'} | {_md(_evidence_text(s))} |"
            )
        lines.append("")
    if report.get("compare"):
        lines += _compare_markdown(report["compare"], rules)
    if report.get("suggestions"):
        lines += ["## Suggestions", ""]
        for item in report["suggestions"]:
            lines.append(f"- `{item['rule_id']}`: {item['text']}")
        lines.append("")
    cost = report.get("cost") or {}
    if cost.get("total_usd") is not None:
        lines.append(f"Cost: ${cost['total_usd']:.2f} for {cost['runs']} runs.")
    lines.append(f"Generated {report['generated_at']} by obey {report['obey_version']}.")
    return "\n".join(lines) + "\n"


def _compare_markdown(cmp: Mapping[str, Any], rules: Mapping[str, Any]) -> list[str]:
    b, a = cmp["before"], cmp["after"]
    lines = ["## Before and after enforcement", ""]
    lines.append(
        f"Pooled compliance went from {_pct(b.get('compliance'))} (n={b.get('exercised')}) to "
        f"{_pct(a.get('compliance'))} (n={a.get('exercised')}). "
        f"Evasions: {a.get('evasions', 0)} of {a.get('blocked_runs', 0)} blocked runs still broke the rule."
    )
    lines += ["", "| Rule | Agent | Before | After | Blocked runs | Evasions |", "|---|---|---|---|---|---|"]
    for row in cmp["rows"]:
        text = rules.get(row["rule_id"], {}).get("text", row["rule_id"])
        lines.append(
            f"| {_md(text)} | {AGENT_NAMES.get(row['agent'], row['agent'])} | {_pct(row['before'])} "
            f"(n={row['before_n']}) | {_pct(row['after'])} (n={row['after_n']}) | {row['blocked_runs']} | "
            f"{row['evasions']} |"
        )
    return [*lines, ""]


def _md(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


_CSS = """
:root{--bg:#ffffff;--fg:#1f2328;--muted:#59636e;--line:#d1d9e0;--ok:#1a7f37;--bad:#cf222e;--mid:#9a6700;
--card:#f6f8fa}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;--line:#3d444d;
--ok:#3fb950;--bad:#f85149;--mid:#d29922;--card:#151b23}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",
Helvetica,Arial,sans-serif;margin:0;padding:24px 16px}
main{max-width:1100px;margin:0 auto}h1{font-size:24px}h2{font-size:18px;margin-top:32px}
.summary{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:14px}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace}
.bar{display:inline-block;height:8px;border-radius:4px;background:var(--line);width:80px;vertical-align:middle;
position:relative}.bar i{position:absolute;left:0;top:0;bottom:0;border-radius:4px}
.ok{color:var(--ok)}.bad{color:var(--bad)}.mid{color:var(--mid)}.muted{color:var(--muted)}
.wrap{overflow-x:auto}
"""


def _cls(value: float | None) -> str:
    if value is None:
        return "muted"
    return "ok" if value >= FOLLOWED_THRESHOLD else ("mid" if value >= 0.5 else "bad")


def _bar(value: float | None) -> str:
    if value is None:
        return ""
    colour = {"ok": "var(--ok)", "mid": "var(--mid)", "bad": "var(--bad)"}[_cls(value)]
    return f'<span class="bar"><i style="width:{value * 100:.0f}%;background:{colour}"></i></span> '


def render_html(report: Mapping[str, Any]) -> str:
    esc = html.escape
    rules = {r["id"]: r for r in report["rules"]}
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>obey report</title><style>{_CSS}</style></head><body><main>",
        f"<h1>obey report{(' — ' + esc(report['repository'])) if report.get('repository') else ''}</h1>",
        '<div class="summary">',
    ]
    parts += [f"<p><strong>{esc(s)}.</strong></p>" for s in report["summary"]]
    parts.append(
        '<p class="muted">Compliance = obeyed ÷ exercised runs on tempting tasks, Wilson 95% interval. '
        "Baseline = the same task with the rule removed from the instruction file.</p></div>"
    )
    for agent in report["agents"]:
        name = AGENT_NAMES.get(agent["agent"], agent["agent"])
        parts.append(
            f'<h2>{esc(name)} <span class="muted">{esc(str(agent.get("version") or ""))} · '
            f"{esc(str(agent.get('model') or ''))}</span></h2>"
        )
        parts.append(
            '<div class="wrap"><table><tr><th>Rule</th><th>Compliance [95% CI]</th><th>Exercised</th>'
            "<th>Baseline</th><th>Example violation</th></tr>"
        )
        mine = [s for s in report["scores"] if s["agent"] == agent["agent"]]
        base = {s["rule_id"]: s for s in mine if s["arm"] == "baseline"}
        for s in (s for s in mine if s["arm"] == "rule"):
            rule = rules.get(s["rule_id"], {})
            src = rule.get("source") or {}
            b = base.get(s["rule_id"])
            parts.append(
                f'<tr><td>{esc(str(rule.get("text", s["rule_id"])))}<br><code class="muted">'
                f"{esc(str(src.get('file', '')))}:{esc(str((src.get('lines') or [''])[0]))}</code></td>"
                f'<td class="{_cls(s["compliance"])}">{_bar(s["compliance"])}{esc(_ci(s))}</td>'
                f"<td>{s['exercised']}/{s['runs']}</td><td>{esc(_ci(b)) if b else '–'}</td>"
                f"<td><code>{esc(_evidence_text(s))}</code></td></tr>"
            )
        parts.append("</table></div>")
    cmp = report.get("compare")
    if cmp:
        parts.append("<h2>Before and after enforcement</h2>")
        b, a = cmp["before"], cmp["after"]
        parts.append(
            f"<p>Pooled compliance {_pct(b.get('compliance'))} → {_pct(a.get('compliance'))}. "
            f"{a.get('evasions', 0)} of {a.get('blocked_runs', 0)} blocked runs still broke the rule another way.</p>"
        )
        parts.append(
            '<div class="wrap"><table><tr><th>Rule</th><th>Agent</th><th>Before</th><th>After</th>'
            "<th>Blocked</th><th>Evasions</th></tr>"
        )
        for row in cmp["rows"]:
            text = rules.get(row["rule_id"], {}).get("text", row["rule_id"])
            parts.append(
                f"<tr><td>{esc(str(text))}</td><td>{esc(AGENT_NAMES.get(row['agent'], row['agent']))}</td>"
                f'<td class="{_cls(row["before"])}">{_pct(row["before"])}</td>'
                f'<td class="{_cls(row["after"])}">{_pct(row["after"])}</td>'
                f"<td>{row['blocked_runs']}</td><td>{row['evasions']}</td></tr>"
            )
        parts.append("</table></div>")
    if report.get("suggestions"):
        parts.append("<h2>Suggestions</h2><ul>")
        parts += [f"<li><code>{esc(i['rule_id'])}</code>: {esc(i['text'])}</li>" for i in report["suggestions"]]
        parts.append("</ul>")
    parts.append(
        f'<p class="muted">Generated {esc(report["generated_at"])} by obey {esc(report["obey_version"])}.'
        "</p></main></body></html>"
    )
    return "\n".join(parts) + "\n"


def badge(report: Mapping[str, Any] | None, rules_total: int | None = None) -> dict[str, Any]:
    """shields.io endpoint JSON: https://img.shields.io/endpoint?url=<raw URL of obey-badge.json>."""
    if report and report.get("scores"):
        rule_scores = [s for s in report["scores"] if s["arm"] == "rule" and s["compliance"] is not None]
        followed = sum(1 for s in rule_scores if s["compliance"] >= FOLLOWED_THRESHOLD)
        share = followed / len(rule_scores) if rule_scores else 0.0
        colour = "brightgreen" if share >= 0.9 else "yellow" if share >= 0.6 else "orange" if share >= 0.3 else "red"
        return {
            "schemaVersion": 1,
            "label": "AGENTS.md rules followed",
            "message": f"{followed}/{len(rule_scores)}",
            "color": colour,
        }
    return {"schemaVersion": 1, "label": "AGENTS.md rules", "message": f"{rules_total or 0} checkable", "color": "blue"}
