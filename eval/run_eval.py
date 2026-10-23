"""Evaluate rule extraction and checkers on the authored and held-out sets.

    uv run python eval/run_eval.py                       # all sections, both splits
    uv run python eval/run_eval.py --section extraction --split dev --verbose

Writes eval/results/<section>.json and prints a summary. Held-out sets are frozen (see MANIFEST.sha256); label
corrections go through CHANGES.md only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from obey_cli.discover import discover
from obey_cli.extract import extract
from obey_cli.score import wilson

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
RESULTS = ROOT / "eval" / "results"


def verify_manifest(directory: Path) -> bool:
    manifest = directory / "MANIFEST.sha256"
    if not manifest.exists():
        return False
    for line in manifest.read_text().splitlines():
        digest, _, rel = line.partition("  ")
        if rel.lstrip("./") == "MANIFEST.sha256":
            continue  # written while the manifest was being created; not data
        path = directory / rel
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            return False
    return True


def _ratio(k: int, n: int) -> dict[str, Any]:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "value": (k / n) if n else None, "ci_low": lo if n else None, "ci_high": hi if n else None}


# --------------------------------------------------------------------------------------------- extraction


def eval_extraction(split: str, verbose: bool = False) -> dict[str, Any]:
    base = FIXTURES / "extraction" / split
    labels_total = 0
    found = 0
    active_labels = 0
    active_found = 0
    extracted_total = 0
    extracted_matched = 0
    extracted_active = 0
    params_checked = 0
    params_ok = 0
    per_type: dict[str, Counter[str]] = defaultdict(Counter)
    misses: list[str] = []
    false_pos: list[str] = []
    for case in sorted(p for p in base.iterdir() if p.is_dir()):
        spec = yaml.safe_load((case / "labels.yaml").read_text())
        files = discover(case)
        rules = [x.as_rule() for x in extract(files, case)]
        used: set[int] = set()
        for label in spec["rules"]:
            labels_total += 1
            is_active = label["status"] == "active"
            active_labels += is_active
            ltype = label.get("type", "uncheckable")
            per_type[ltype]["labels"] += 1
            # The rule covering the label line that starts closest to it (sentences can share a line).
            covering = [
                (rule["source"]["lines"][0], i)
                for i, rule in enumerate(rules)
                if rule["source"]["file"] == label["file"]
                and rule["source"]["lines"][0] <= label["line"] <= rule["source"]["lines"][1]
                and i not in used
            ]
            match = max(covering)[1] if covering else None
            if match is None:
                misses.append(f"{case.name}:{label['file']}:{label['line']} {ltype} (not extracted)")
                continue
            used.add(match)
            rule = rules[match]
            got_type = (rule.get("checker") or {}).get("type") if rule["status"] == "active" else "uncheckable"
            if rule["status"] == label["status"] and (not is_active or got_type == ltype):
                found += 1
                per_type[ltype]["found"] += 1
                if is_active:
                    active_found += 1
                    ok = check_params(rule, label)
                    if ok is not None:
                        params_checked += 1
                        params_ok += ok
                        per_type[ltype]["params_ok"] += ok
                        if not ok and verbose:
                            misses.append(
                                f"{case.name}:{label['line']} {ltype} params wrong: "
                                f"{json.dumps(rule['checker']['params'])[:200]}"
                            )
            else:
                misses.append(
                    f"{case.name}:{label['file']}:{label['line']} want {ltype} got {got_type}: {rule['text'][:90]}"
                )
        for i, rule in enumerate(rules):
            extracted_total += 1
            extracted_active += rule["status"] == "active"
            if i in used:
                extracted_matched += 1
            else:
                false_pos.append(
                    f"{case.name}:{rule['source']['file']}:{rule['source']['lines'][0]} "
                    f"{(rule.get('checker') or {}).get('type', rule['status'])}: {rule['text'][:90]}"
                )
    result = {
        "split": split,
        "cases": len([p for p in base.iterdir() if p.is_dir()]),
        "labels": labels_total,
        "recall_all": _ratio(found, labels_total),
        "precision_all": _ratio(extracted_matched, extracted_total),
        "recall_active": _ratio(active_found, active_labels),
        "precision_active": _ratio(active_found, extracted_active),
        "params_correct": _ratio(params_ok, params_checked),
        "per_type": {k: dict(v) for k, v in sorted(per_type.items())},
        "frozen_manifest_ok": verify_manifest(base) if split == "heldout" else None,
    }
    if verbose:
        result["misses"] = misses
        result["false_positives"] = false_pos
    return result


def check_params(rule: dict[str, Any], label: dict[str, Any]) -> bool | None:
    """True when the extracted checker classifies the label's samples correctly (None: no samples or no engine)."""
    try:
        from obey_cli.checkers.samples import classify_sample
    except ImportError:
        return None
    samples = [(s, True) for s in label.get("violates") or []] + [(s, False) for s in label.get("obeys") or []]
    if not samples:
        return None
    return all(classify_sample(rule["checker"], s) == want for s, want in samples)


# --------------------------------------------------------------------------------------------- checkers


def eval_checkers(split: str, verbose: bool = False) -> dict[str, Any]:
    from obey_cli.checkers import check

    base = FIXTURES / "checkers" / split
    stats: dict[str, Counter[str]] = defaultdict(Counter)
    errors: list[str] = []
    for path in sorted(base.glob("*/*.json")):
        case = json.loads(path.read_text())
        ctype = case["rule"]["type"]
        got = check(case["rule"], case["run"]).verdict
        want = case["expected"]
        s = stats[ctype]
        s["cases"] += 1
        s[f"want_{want}"] += 1
        if got == want:
            s["correct"] += 1
        if want == "violated" and got == "violated":
            s["tp"] += 1
        elif want != "violated" and got == "violated":
            s["fp"] += 1
        elif want == "violated" and got != "violated":
            s["fn"] += 1
        for tag in case.get("tags", []):
            s[f"tag_{tag}"] += 1
            if got == want:
                s[f"tag_{tag}_correct"] += 1
        if got != want:
            errors.append(f"{path.relative_to(FIXTURES)}: want {want} got {got} ({case.get('note', '')[:100]})")
    per_type = {}
    for ctype, s in sorted(stats.items()):
        per_type[ctype] = {
            "cases": s["cases"],
            "accuracy": _ratio(s["correct"], s["cases"]),
            "precision": _ratio(s["tp"], s["tp"] + s["fp"]),
            "recall": _ratio(s["tp"], s["tp"] + s["fn"]),
            "evasion_recall": _ratio(s["tag_evasion_correct"], s["tag_evasion"]),
            "counts": {k: v for k, v in s.items() if k.startswith("want_")},
        }
    out = {
        "split": split,
        "cases": sum(s["cases"] for s in stats.values()),
        "per_type": per_type,
        "frozen_manifest_ok": verify_manifest(base) if split == "heldout" else None,
    }
    if verbose:
        out["errors"] = errors
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--section", choices=["extraction", "checkers", "all"], default="all")
    parser.add_argument("--split", choices=["dev", "heldout", "both"], default="both")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    splits = ["dev", "heldout"] if args.split == "both" else [args.split]
    sections = ["extraction", "checkers"] if args.section == "all" else [args.section]
    RESULTS.mkdir(parents=True, exist_ok=True)
    for section in sections:
        results = {}
        for split in splits:
            if not (FIXTURES / section / split).exists():
                continue
            fn = eval_extraction if section == "extraction" else eval_checkers
            results[split] = fn(split, args.verbose)
        if not args.no_write and args.split == "both" and not args.verbose:
            (RESULTS / f"{section}.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
        print(json.dumps(results, indent=2)[:20000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
