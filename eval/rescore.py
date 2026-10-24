"""Score recorded study runs again with the checkers of another commit, and list the verdicts that change.

    uv run python eval/rescore.py --ref 20cef25 --raw raw/main.jsonl --summaries study/results/main.jsonl
    uv run python eval/rescore.py --ref <commit> --raw raw/main.jsonl --summaries study/results/main.jsonl \
        --write study/results/main.rescored.jsonl

The study records each run's verdict when the run finishes. This script answers "would the verdicts be the same with
the checkers as registered?": it exports `src/` and `study/design.yaml` at `--ref` with `git archive`, imports that
copy in a separate interpreter, rebuilds each run's rule from the design and checks the raw record again.
"""

from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCORER = r"""
import json, sys
sys.path.insert(0, sys.argv[1] + "/src")
import obey_cli
assert obey_cli.__file__.startswith(sys.argv[1]), obey_cli.__file__
from pathlib import Path
from obey_cli.checkers import check
from obey_cli.study import design as d
spec = d.load(Path(sys.argv[1]) / "study" / "design.yaml")
for line in open(sys.argv[2], encoding="utf-8"):
    record = json.loads(line)
    _, repo, slot, condition = record["study_key"].split("|")[:4]
    rule = d.rule(spec, repo, slot, condition)
    v = check(rule["checker"], record)
    kind = v.evidence[0]["kind"] if v.evidence else None
    print(json.dumps({"run_id": record["run_id"], "verdict": v.verdict, "evidence_kind": kind}))
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True, help="commit whose checkers score the runs")
    parser.add_argument("--raw", type=Path, required=True, help="raw run records (obey-run-v1, one per line)")
    parser.add_argument("--summaries", type=Path, required=True, help="the run summaries with the recorded verdicts")
    parser.add_argument("--write", type=Path, help="also write the summaries with the rescored verdicts here")
    args = parser.parse_args()
    recorded = {}
    for line in args.summaries.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        recorded[row["run_id"]] = row
    with tempfile.TemporaryDirectory(prefix="obey-rescore-") as tmp:
        archive = subprocess.run(
            ["git", "archive", args.ref, "src", "study/design.yaml"], cwd=ROOT, capture_output=True, check=True
        ).stdout
        subprocess.run(["tar", "-x", "-C", tmp], input=archive, check=True)
        out = subprocess.run(
            [sys.executable, "-c", SCORER, tmp, str(args.raw)], capture_output=True, text=True, check=True
        ).stdout
    changed = []
    rescored = {}
    for line in out.splitlines():
        row = json.loads(line)
        rescored[row["run_id"]] = row
        before = recorded.get(row["run_id"])
        if before is not None and before["verdict"] != row["verdict"]:
            changed.append((before["slot"], before["repo"], before["run_id"], before["verdict"], row["verdict"]))
    scored = len(out.splitlines())
    print(f"{scored} runs scored with the checkers at {args.ref}; {len(changed)} verdicts differ from the recorded")
    for (slot, repo), n in sorted(collections.Counter((c[0], c[1]) for c in changed).items()):
        print(f"  {slot} / {repo}: {n}")
    for c in changed:
        print(f"  {c[2]}: recorded {c[3]}, at {args.ref} {c[4]}")
    if args.write:
        rows = []
        for line in args.summaries.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            new = rescored.get(row["run_id"])
            if new is not None and row.get("status") == "ok":
                row = {**row, "verdict": new["verdict"], "evidence_kind": new["evidence_kind"]}
            rows.append(json.dumps(row, sort_keys=True))
        args.write.write_text("\n".join(rows) + "\n", encoding="utf-8")
        print(f"wrote {args.write}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
