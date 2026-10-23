"""Render .github/social-preview.png (1280x640): name, one-line value and the headline number.

    uv run python eval/make_social_preview.py --headline "On tempting tasks ..." --out .github/social-preview.png

PNG text chunks are not written; strip anything else with `exiftool -all= -overwrite_original <file>`.
"""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    parser = argparse.ArgumentParser()
    parser.add_argument("--headline", required=True)
    parser.add_argument("--out", type=Path, default=Path(".github/social-preview.png"))
    args = parser.parse_args()
    bg, fg, muted, accent = "#0d1117", "#e6edf3", "#9198a1", "#3fb950"
    fig = plt.figure(figsize=(12.8, 6.4), dpi=100)
    fig.patch.set_facecolor(bg)
    fig.text(0.07, 0.78, "obey", fontsize=76, fontweight="bold", color=fg, family="DejaVu Sans")
    fig.text(0.07, 0.66, "Unit tests for AGENTS.md", fontsize=30, color=accent, family="DejaVu Sans")
    lines = textwrap.wrap(args.headline, 62)
    for i, line in enumerate(lines[:4]):
        fig.text(0.07, 0.50 - i * 0.075, line, fontsize=23, color=fg, family="DejaVu Sans")
    fig.text(
        0.07,
        0.08,
        "Measure which rules your coding agent follows from what it did, then enforce the rest with hooks.",
        fontsize=16,
        color=muted,
        family="DejaVu Sans",
    )
    fig.text(0.93, 0.88, "github.com/B0yko/obey", fontsize=16, color=muted, ha="right", family="DejaVu Sans")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, facecolor=bg, metadata={"Software": None})
    plt.close(fig)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
