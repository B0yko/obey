# 9. Study design: pre-registered factorial experiment with a stratified permutation analysis

Date: 2026-10-24 · Status: accepted

## Context

The study asks whether the phrasing of an AGENTS.md rule (imperative, prohibition, imperative with a reason) changes
whether coding agents follow it, and whether a rule in the file helps at all compared with no rule. Earlier work
(McMillan, arXiv 2605.10039) covered instruction-file size and position, so we hold both constant. A study like
this is easy to tune after the fact, so the hypotheses, the rule selection, the analysis and the stopping rules are
committed in `study/PREREGISTRATION.md` before the pilot.

## Decision

- **Design.** Full factorial: 10 rule slots × 2 authored repositories × 2 harnesses × 4 conditions (no-rule
  baseline and three phrasings), with the other 24 rules fixed as distractors. The rule types are chosen
  mechanically from the survey (the ten most common checkable types with a probe template). One cheap model
  (`anthropic/claude-haiku-5.5`) in two OpenRouter-capable harnesses (Claude Code and OpenCode), so the harness
  varies while the model stays fixed.
- **Outcome.** Deterministic checker verdicts on what the agent did; `not_exercised` runs are excluded and counted.
- **Analysis: stratified permutation test plus cluster bootstrap, not a mixed-effects logistic regression.**
  - There are only 20 slot × repository clusters. Random-effect variances are poorly estimated with that few
    clusters, and Wald intervals from a GLMM are optimistic.
  - Several slots are expected near 100% compliance in some conditions, which causes quasi-separation and
    convergence failures in a logistic GLMM.
  - A permutation test within slot × repository × harness strata needs no distributional assumptions: under the
    null, condition labels are exchangeable within a stratum, which is exactly how they were assigned.
  - The cluster bootstrap over slot × repository clusters gives an interval for the stratum-weighted difference
    that respects the clustering the permutation test conditions on.
  - It only needs numpy, so anyone can reproduce it with `uv run obey study report`.
- **Multiplicity.** H1 is one test; the three pairwise phrasing contrasts use Holm–Bonferroni.
- **Sample size.** δ = 10 percentage points; the trial count follows from the pilot's compliance, intra-cluster
  correlation and exercised share through the formula in the pre-registration, capped by the budget, with a
  pre-registered order for shrinking the grid.

## Consequences

- The headline reports probe compliance (on tempting tasks) and says so; a null phrasing result is reported as one.
- The results generalise to these two repositories, these rule types, this model and these agent versions; the
  report states this.
- Deviations from the pre-registration are listed in the report.
