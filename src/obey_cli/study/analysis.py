"""Pre-registered analysis of the phrasing experiment (study/PREREGISTRATION.md).

Unit: one run. Outcome: 1 = obeyed, 0 = violated; runs where the rule was not exercised, and runs that did not
complete, are excluded and counted. Strata: rule slot × repository × harness.

- Effect of a contrast A vs B: the stratum-weighted difference in compliance, weighting each stratum that has
  exercised runs in both conditions by its number of exercised runs in A and B.
- p-value: stratified permutation test (condition labels shuffled within strata), two-sided, 10,000 permutations.
- 95% interval: cluster bootstrap over rule slot × repository clusters (both harnesses resampled together),
  10,000 resamples, percentile interval.
- Phrasing family (three pairwise contrasts): Holm–Bonferroni at α = 0.05.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any

SEED = 20261024
PERMUTATIONS = 10_000
BOOTSTRAP = 10_000
CONTRASTS = (("prohibition", "imperative"), ("reason", "imperative"), ("reason", "prohibition"))


@dataclass
class Obs:
    stratum: tuple[str, str, str]  # slot, repo, harness
    cluster: tuple[str, str]  # slot, repo
    condition: str
    y: int


def observations(rows: Iterable[Mapping[str, Any]]) -> tuple[list[Obs], dict[str, int]]:
    obs: list[Obs] = []
    excluded = {"not_exercised": 0, "incomplete": 0}
    for r in rows:
        if r.get("status") != "ok":
            excluded["incomplete"] += 1
            continue
        if r["verdict"] == "not_exercised":
            excluded["not_exercised"] += 1
            continue
        obs.append(
            Obs(
                (r["slot"], r["repo"], r["harness"]),
                (r["slot"], r["repo"]),
                r["condition"],
                1 if r["verdict"] == "obeyed" else 0,
            )
        )
    return obs, excluded


def _group(
    obs: Sequence[Obs], a: Sequence[str], b: Sequence[str]
) -> dict[tuple[str, str, str], tuple[list[int], list[int]]]:
    groups: dict[tuple[str, str, str], tuple[list[int], list[int]]] = defaultdict(lambda: ([], []))
    for o in obs:
        if o.condition in a:
            groups[o.stratum][0].append(o.y)
        elif o.condition in b:
            groups[o.stratum][1].append(o.y)
    return {k: v for k, v in groups.items() if v[0] and v[1]}


def stratified_difference(groups: Mapping[Any, tuple[Sequence[int], Sequence[int]]]) -> float | None:
    num = 0.0
    den = 0.0
    for ya, yb in groups.values():
        w = len(ya) + len(yb)
        num += w * (sum(ya) / len(ya) - sum(yb) / len(yb))
        den += w
    return num / den if den else None


def permutation_p(
    groups: Mapping[Any, tuple[Sequence[int], Sequence[int]]], n: int = PERMUTATIONS, seed: int = SEED
) -> float | None:
    import numpy as np

    observed = stratified_difference(groups)
    if observed is None:
        return None
    rng = np.random.default_rng(seed)
    pooled = [(np.array(list(ya) + list(yb)), len(ya)) for ya, yb in groups.values()]
    weights = np.array([len(p) for p, _ in pooled], dtype=float)
    hits = 0
    for _ in range(n):
        diffs = []
        for values, na in pooled:
            perm = rng.permutation(values)
            diffs.append(perm[:na].mean() - perm[na:].mean())
        stat = float(np.dot(weights, diffs) / weights.sum())
        if abs(stat) >= abs(observed) - 1e-12:
            hits += 1
    return (hits + 1) / (n + 1)


def bootstrap_ci(
    obs: Sequence[Obs], a: Sequence[str], b: Sequence[str], n: int = BOOTSTRAP, seed: int = SEED
) -> tuple[float | None, float | None]:
    import numpy as np

    clusters: dict[tuple[str, str], list[Obs]] = defaultdict(list)
    for o in obs:
        clusters[o.cluster].append(o)
    keys = sorted(clusters)
    if not keys:
        return (None, None)
    rng = np.random.default_rng(seed)
    stats = []
    for _ in range(n):
        sample: list[Obs] = []
        for i, idx in enumerate(rng.integers(0, len(keys), len(keys))):
            # Relabel resampled clusters so duplicates count as separate strata.
            for o in clusters[keys[int(idx)]]:
                sample.append(Obs((o.stratum[0], o.stratum[1] + f"#{i}", o.stratum[2]), o.cluster, o.condition, o.y))
        diff = stratified_difference(_group(sample, a, b))
        if diff is not None:
            stats.append(diff)
    if not stats:
        return (None, None)
    return (float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5)))


def compliance(obs: Sequence[Obs], conditions: Sequence[str]) -> dict[str, Any]:
    from obey_cli.score import wilson

    ys = [o.y for o in obs if o.condition in conditions]
    lo, hi = wilson(sum(ys), len(ys))
    return {
        "obeyed": sum(ys),
        "n": len(ys),
        "compliance": sum(ys) / len(ys) if ys else None,
        "ci_low": lo if ys else None,
        "ci_high": hi if ys else None,
    }


def contrast(
    obs: Sequence[Obs], a: Sequence[str], b: Sequence[str], permutations: int = PERMUTATIONS, bootstrap: int = BOOTSTRAP
) -> dict[str, Any]:
    groups = _group(obs, a, b)
    lo, hi = bootstrap_ci(obs, a, b, bootstrap)
    return {
        "a": list(a),
        "b": list(b),
        "strata": len(groups),
        "effect": stratified_difference(groups),
        "ci_low": lo,
        "ci_high": hi,
        "p": permutation_p(groups, permutations),
        "a_compliance": compliance(obs, a),
        "b_compliance": compliance(obs, b),
    }


def holm(pvalues: Sequence[float | None], alpha: float = 0.05) -> list[dict[str, Any]]:
    order = sorted((p, i) for i, p in enumerate(pvalues) if p is not None)
    m = len(order)
    out: list[dict[str, Any]] = [{"p_adj": None, "reject": False} for _ in pvalues]
    running = 0.0
    still = True
    for rank, (p, i) in enumerate(order):
        adj = min(1.0, (m - rank) * p)
        running = max(running, adj)
        still = still and p <= alpha / (m - rank)
        out[i] = {"p_adj": running, "reject": still}
    return out


def analyse(
    rows: Sequence[Mapping[str, Any]], permutations: int = PERMUTATIONS, bootstrap: int = BOOTSTRAP
) -> dict[str, Any]:
    obs, excluded = observations(rows)
    rule_present = contrast(obs, ["imperative", "prohibition", "reason"], ["baseline"], permutations, bootstrap)
    phrasing = [contrast(obs, [a], [b], permutations, bootstrap) for a, b in CONTRASTS]
    for c, h in zip(phrasing, holm([c["p"] for c in phrasing]), strict=True):
        c.update(h)
    per_condition = {c: compliance(obs, [c]) for c in ("baseline", "imperative", "prohibition", "reason")}
    exercised: dict[str, dict[str, int]] = defaultdict(lambda: {"exercised": 0, "runs": 0})
    for r in rows:
        if r.get("status") == "ok":
            key = r["condition"]
            exercised[key]["runs"] += 1
            exercised[key]["exercised"] += r["verdict"] != "not_exercised"
    return {
        "n_runs": len(rows),
        "n_exercised": len(obs),
        "excluded": excluded,
        "per_condition": per_condition,
        "exercised_share": dict(exercised),
        "rule_present_vs_baseline": rule_present,
        "phrasing": phrasing,
    }


def trials_needed(
    pilot_rows: Sequence[Mapping[str, Any]],
    *,
    delta: float = 0.10,
    alpha: float = 0.05,
    family: int = 3,
    power: float = 0.80,
    cells: int = 40,
) -> dict[str, Any]:
    """The pre-registered sample-size formula, from the pilot's compliance, clustering and exercised share."""
    obs, _ = observations(pilot_rows)
    present = [o for o in obs if o.condition in ("imperative", "prohibition", "reason")]
    p_bar = sum(o.y for o in present) / len(present) if present else 0.7
    p1 = min(max(p_bar, 0.55), 0.95)
    p2 = max(p1 - delta, 0.01)
    z_a = NormalDist().inv_cdf(1 - alpha / family / 2)
    z_b = NormalDist().inv_cdf(power)
    n_arm = (z_a + z_b) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2)) / delta**2
    # Intra-cluster correlation of the outcome across slot × repository cells (ANOVA estimator), clamped.
    by_cluster: dict[tuple[str, str], list[int]] = defaultdict(list)
    for o in present:
        by_cluster[o.cluster].append(o.y)
    icc = _icc(list(by_cluster.values()))
    ok_rows = [r for r in pilot_rows if r.get("status") == "ok" and r["condition"] != "baseline"]
    exercised_share = (sum(r["verdict"] != "not_exercised" for r in ok_rows) / len(ok_rows)) if ok_rows else 1.0
    e = max(exercised_share, 0.3)
    m = max(n_arm / cells, 1.0)
    deff = 1 + (m - 1) * icc
    trials = math.ceil(n_arm * deff / (cells * e))
    return {
        "p_bar": p_bar,
        "p1": p1,
        "p2": p2,
        "z_alpha": z_a,
        "z_beta": z_b,
        "n_arm": n_arm,
        "icc": icc,
        "design_effect": deff,
        "exercised_share": exercised_share,
        "trials_per_cell": trials,
    }


def _icc(groups: Sequence[Sequence[int]]) -> float:
    groups = [g for g in groups if len(g) >= 1]
    k = len(groups)
    n = sum(len(g) for g in groups)
    if k < 2 or n <= k:
        return 0.0
    grand = sum(sum(g) for g in groups) / n
    ssb = sum(len(g) * (sum(g) / len(g) - grand) ** 2 for g in groups)
    ssw = sum(sum((y - sum(g) / len(g)) ** 2 for y in g) for g in groups)
    msb = ssb / (k - 1)
    msw = ssw / (n - k)
    n0 = (n - sum(len(g) ** 2 for g in groups) / n) / (k - 1)
    icc = (msb - msw) / (msb + (n0 - 1) * msw) if msb + (n0 - 1) * msw > 0 else 0.0
    return min(max(icc, 0.0), 0.3)
