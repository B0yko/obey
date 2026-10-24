"""Render .github/social-preview.png (1280x640): name, what obey does, and real numbers from the study.

    uv run python eval/make_social_preview.py --out .github/social-preview.png

Every number is read from the committed run summaries (study/results/*.rescored.jsonl), so the image can be rebuilt
from the data. PNG text chunks are not written; strip anything else with `exiftool -all= -overwrite_original <file>`.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
W, H = 1280, 640
BG, PANEL, BORDER = "#0b0f17", "#121925", "#263041"
FG, MUTED, FAINT = "#e8eef5", "#93a1b3", "#5d6b7e"
GREEN, RED, BLUE = "#3fb950", "#f0616d", "#58a6ff"
SANS, MONO = "DejaVu Sans", "DejaVu Sans Mono"


def _rows(name: str) -> list[dict[str, Any]]:
    path = ROOT / "study" / "results" / name
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _rate(rows: list[dict[str, Any]], keep: Callable[[dict[str, Any]], bool]) -> tuple[int, int]:
    ex = [r for r in rows if r["status"] == "ok" and r["verdict"] != "not_exercised" and keep(r)]
    return sum(r["verdict"] == "obeyed" for r in ex), len(ex)


def numbers() -> dict[str, tuple[int, int]]:
    main = _rows("main.rescored.jsonl")
    hooks = _rows("enforce-baseline.rescored.jsonl")
    blocked = [r for r in hooks if r["status"] == "ok" and r["denied"] > 0 and r["slot"] != "path_forbidden"]
    with_rule = _rate(main, lambda r: r["condition"] != "baseline")
    return {
        "with_rule": with_rule,
        "without_rule": _rate(main, lambda r: r["condition"] == "baseline"),
        "evasions": (sum(r["verdict"] == "violated" for r in blocked), len(blocked)),
        "pm": _rate(main, lambda r: r["slot"] == "command_forbidden" and r["condition"] != "baseline"),
        "tests": _rate(main, lambda r: r["slot"] == "command_required" and r["condition"] != "baseline"),
        "commits": _rate(main, lambda r: r["slot"] == "commit_message" and r["condition"] != "baseline"),
        "generated": _rate(main, lambda r: r["slot"] == "path_forbidden" and r["condition"] != "baseline"),
        "uncommitted_no_rule": _rate(main, lambda r: r["slot"] == "no_commit" and r["condition"] == "baseline"),
        "uncommitted_hook": _rate(hooks, lambda r: r["slot"] == "no_commit"),
    }


def _pct(k: int, n: int) -> str:
    return f"{round(100 * k / n)}%"


def render(out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import to_rgb
    from matplotlib.patches import Circle, FancyBboxPatch

    n = numbers()
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")

    # Background: near-black with two soft glows.
    yy, xx = np.mgrid[0:H, 0:W]
    img = np.ones((H, W, 3)) * np.array(to_rgb(BG))
    for cx, cy, r, color, a in ((1080, 560, 520, GREEN, 0.16), (120, 40, 560, BLUE, 0.14)):
        g = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r**2)))[..., None] * a
        img = img * (1 - g) + np.array(to_rgb(color)) * g
    ax.imshow(img, extent=(0, W, 0, H), origin="lower", zorder=0)

    def text(x: float, y: float, s: str, size: float, color: str = FG, **kw: Any) -> None:
        kw.setdefault("family", SANS)
        ax.text(x, y, s, fontsize=size, color=color, va="baseline", zorder=3, **kw)

    # Left: what it is, in plain words.
    text(62, 500, "obey", 60, weight="bold")
    text(64, 452, "Unit tests for your AGENTS.md", 21, GREEN, weight="bold")
    for i, line in enumerate(
        (
            "Find out which rules your coding agent",
            "actually follows. Turn the ones it breaks",
            "into hooks it cannot skip.",
        )
    ):
        text(64, 404 - i * 30, line, 15.5, FG)
    chip = FancyBboxPatch(
        (64, 252), 526, 46, boxstyle="round,pad=0,rounding_size=10", fc="#0f1622", ec=BORDER, lw=1.2, zorder=2
    )
    ax.add_patch(chip)
    text(84, 268, "$ obey demo", 14, BLUE, family=MONO, weight="bold")
    text(222, 269, "a recorded demo: no API key, no Docker", 12, MUTED)

    k, total = n["with_rule"]
    text(64, 162, f"{k:,}/{total:,}", 27, FG, weight="bold")
    text(64, 134, "test runs followed a rule", 11.5, MUTED)
    text(64, 114, "that was in AGENTS.md", 11.5, MUTED)
    ev, blocked = n["evasions"]
    text(392, 162, f"{ev}/{blocked}", 27, FG, weight="bold")
    text(392, 134, "workarounds once a hook", 11.5, MUTED)
    text(392, 114, "blocked the agent", 11.5, MUTED)
    text(64, 50, "github.com/B0yko/obey", 12.5, FAINT)

    # Right: a report card with study numbers.
    x0, y0, w, h = 676, 92, 540, 470
    ax.add_patch(
        FancyBboxPatch((x0, y0), w, h, boxstyle="round,pad=0,rounding_size=18", fc=PANEL, ec=BORDER, lw=1.4, zorder=2)
    )
    for i, c in enumerate(("#f0616d", "#e3b341", "#3fb950")):
        ax.add_patch(Circle((x0 + 30 + i * 22, y0 + h - 30), 6.5, color=c, zorder=3))
    text(x0 + 104, y0 + h - 35, "obey report  Claude Code, OpenCode", 11, MUTED, family=MONO)
    rows = [
        ("Use the project's package manager", n["pm"], True),
        ("Run the tests before you finish", n["tests"], True),
        ("Write Conventional Commit messages", n["commits"], True),
        ("Never hand-edit generated files", n["generated"], True),
        ("Leave changes uncommitted", n["uncommitted_no_rule"], False),
    ]
    top = y0 + h - 94
    for i, (label, (rk, rn), ok) in enumerate(rows):
        y = top - i * 56
        text(x0 + 28, y, "✓" if ok else "✗", 17, GREEN if ok else RED, weight="bold")
        text(x0 + 60, y + 1, label, 12.5, FG)
        text(x0 + w - 28, y + 1, _pct(rk, rn), 14, GREEN if ok else RED, weight="bold", ha="right")
        if not ok:
            text(x0 + 60, y - 20, "rule missing from AGENTS.md", 10, MUTED)
    hk, hn = n["uncommitted_hook"]
    y = top - len(rows) * 56 - 10
    ax.add_patch(
        FancyBboxPatch(
            (x0 + 20, y - 18),
            w - 40,
            46,
            boxstyle="round,pad=0,rounding_size=10",
            fc="#12261a",
            ec="#2e6b3a",
            lw=1.2,
            zorder=2,
        )
    )
    text(x0 + 40, y, "→  with a hook from obey enforce", 12.5, GREEN, weight="bold")
    text(x0 + w - 40, y, _pct(hk, hn), 14, GREEN, weight="bold", ha="right")
    text(x0 + 28, y0 + 22, "probe compliance in the study's 2,663 runs; see the README", 9.5, FAINT)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=BG, metadata={"Software": None})
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / ".github" / "social-preview.png")
    args = parser.parse_args()
    render(args.out)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
