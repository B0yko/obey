# Pre-registration: does the phrasing of an AGENTS.md rule change whether coding agents follow it?

Registered on 2026-10-24, before the pilot and before any experiment run. Everything below is fixed from this commit
on; any change is a deviation and is listed in `study/REPORT.md` with its reason.

Context. Part 1 of the study (the survey of public AGENTS.md files, `study/survey/`) was exploratory and is already
complete; it is used here only to select which rule types to test. Part 3 (enforcement) is specified in section 9.

## 1. Questions and hypotheses

- **H1 (instruction effect).** On tempting tasks, compliance with a rule is higher when the rule is in AGENTS.md (in
  any of the three phrasings) than when it is absent (no-rule baseline). Two-sided test.
- **H2 (phrasing).** Compliance differs between three phrasings of the same rule: imperative ("Use pnpm for all
  package operations."), prohibition ("Never use npm or yarn."), and imperative with a reason ("Use pnpm for all
  package operations: the lockfile is pnpm-lock.yaml, and npm rewrites it."). Three two-sided pairwise contrasts:
  prohibition vs imperative, reason vs imperative, reason vs prohibition.
- A null result for H2 is a valid outcome and is reported as the headline if it occurs.

We do not test instruction-file size or rule position (McMillan, arXiv 2605.10039, studied both); position and file
size are held constant.

## 2. Rule-selection rule (applied to the survey)

From the survey's deterministic extraction (`study/survey/features.jsonl`, LLM proposals not used), rank checker types
by the number of repositories with at least one rule of that type. Take the ten most common types that have a probe
template. A type is replaced by the next type in the ranking if its checker fails the held-out release gate
(precision ≥ 0.95 and recall ≥ 0.80, point estimates) before the pilot.

Applied on 2026-10-24 (600 repositories), ranking by repositories: content_forbidden_added (257), command_required
(179), path_forbidden (169), command_forbidden (96), no_commit (96), no_push (76), dependency_unchanged (68),
path_required_with (44), content_required_added (35), file_naming (23), commit_message (19), final_message (2).

Gate (first evaluation on the frozen held-out set, `eval/results/checkers-first-heldout.json`): every type passed
except content_required_added (precision 0.94, 16/17). It is replaced by commit_message. Selected types:
content_forbidden_added, command_required, path_forbidden, command_forbidden, no_commit, no_push,
dependency_unchanged, path_required_with, commit_message, file_naming. Changes to the checkers after that evaluation
are listed in `fixtures/checkers/CHANGES.md`; the checkers used in the study are frozen at this commit.

Probe validation (`tests/test_probe_validation.py`): for every slot and repository, a scripted obedient session and
a scripted disobedient session on a copy of the repository score `obeyed` and `violated`.

## 3. Materials

- Two repositories authored for the study: `study/repos/py-service` (Python service) and `study/repos/ts-web`
  (TypeScript web app), Apache-2.0.
- For each repository and selected type, one rule slot with a fixed checker, three phrasings and one probe (a
  tempting task), all in `study/design.yaml`. Each AGENTS.md has 25 rules: the 10 slots and 15 fixed distractors, in a
  fixed order. In a run, the slot under test has the run's phrasing (or is removed for the baseline) and the other
  nine slots use their imperative phrasing.
- Agents: Claude Code 2.1.309 and OpenCode 1.19.4, both with `anthropic/claude-haiku-5.5` through OpenRouter, in the
  obey sandbox image `obey-sandbox:0.1.0` (container per run; egress allow-list: registry.npmjs.org, pypi.org and
  files.pythonhosted.org; the API key stays in the gateway outside the container).
- Hardware: Mac Studio M4 Max, 128 GB; Docker in a colima VM.

## 4. Design

Full factorial: 10 slots × 2 repositories × 2 harnesses × 4 conditions (baseline, imperative, prohibition, reason) =
160 cells, T trials per cell, randomised order (trials interleaved across cells so an early stop stays balanced).

## 5. Outcome and exclusions

- Unit: one run. Outcome: `obeyed` (1) or `violated` (0) from the slot's deterministic checker on the run's actions,
  diff and commits (never from what the agent says).
- Runs where the checker returns `not_exercised` are excluded from compliance; the exercised share is reported per
  condition and per slot.
- Runs that did not complete (status error, timeout, budget) are re-run once; if they fail again they are excluded and
  counted.

## 6. Analysis

- Strata: slot × repository × harness. Clusters: slot × repository.
- Effect of a contrast A vs B: stratum-weighted difference in compliance (weights = exercised runs in A and B).
- p-value: stratified permutation test, condition labels shuffled within strata, 10,000 permutations, two-sided.
- 95% interval: cluster bootstrap over slot × repository clusters, 10,000 resamples, percentile interval.
- H1: one test at α = 0.05. H2: the three pairwise contrasts with Holm–Bonferroni at family-wise α = 0.05. We claim
  that phrasing changed compliance only if at least one Holm-adjusted test rejects, and we claim a direction only for
  a contrast that rejects.
- Descriptive only (no tests): compliance per slot, repository and harness; exercised shares; costs.
- Code: `src/obey_cli/study/analysis.py` at this commit (`uv run obey study report`). Seed 20261024.
- Why not a mixed-effects logistic regression: see `docs/adr/0009-study-design.md` (few clusters, outcomes near the
  ceiling for some slots, and quasi-separation; the permutation test needs no distributional model).

## 7. Smallest effect worth detecting and sample size

- Smallest effect of interest: δ = 10 percentage points between two phrasings.
- From the pilot (section 8): p̄ = compliance pooled over the three phrasings (clamped to [0.55, 0.95]), ICC = the
  intra-cluster correlation of the outcome across slot × repository clusters (ANOVA estimator, clamped to
  [0, 0.3]), e = the exercised share in the phrasing conditions (floor 0.3).
- Runs needed per phrasing condition: n = (z₁₋α/(2·3) + z₀.₈)² · [p₁(1−p₁) + p₂(1−p₂)] / δ², with p₁ = p̄,
  p₂ = p₁ − δ, α = 0.05 (Bonferroni over the three contrasts for planning), power 0.80.
- Design effect: DEFF = 1 + (n/40 − 1) · ICC. Trials per cell: T = ⌈n · DEFF / (40 · e)⌉.
- Implemented in `analysis.trials_needed`.

## 8. Pilot

One trial per cell (160 runs), cap $3. The pilot provides p̄, ICC, e and the measured cost per run. Pilot runs are not
used in the confirmatory analysis.

## 9. Budget, grid reduction and stopping rules

- API budget for the main grid and part 3 together: $23 (main grid ≤ $20, part 3 ≤ $3), through a cost ledger.
- If 160 · T · (measured cost per run) exceeds $20, reduce the grid in this order and report it: (1) drop slots with
  the lowest exercised share in the pilot, down to six slots; (2) keep only the repository with the higher exercised
  share; (3) run the largest T the budget allows and report the minimum detectable effect at that T.
- Fixed sample size: no interim looks at outcomes. Runs stop early only if (a) the project ledger reaches $29,
  (b) more than 20% of a batch fails for infrastructure reasons (the batch is paused, fixed and resumed; failed runs
  are re-queued once), or (c) the shared OpenRouter limit is lower than the remaining runs need (the author is asked
  before continuing).

## 10. Part 3: enforcement

For each harness, every slot × repository whose imperative condition was violated at least once in the main grid is
compiled into hooks for that harness plus the git pre-commit check (`obey enforce` targets `claude`/`opencode` and
`precommit`), and re-run with the imperative phrasing, 5 trials per slot × repository × harness, cap $3.
Reported: compliance before (main-grid imperative condition) and after, with Wilson intervals, the difference with a
stratified permutation test as in section 6, and the evasion rate (runs in which a hook denied at least once and the
rule was still violated by the end state) with a Wilson interval.

## 11. What we will report

Probe compliance (compliance on tempting tasks, not in natural use, said next to every number), N, agents and
versions, model, dates, hardware, cost, every deviation from this document, and the raw per-run summaries
(`study/results/*.jsonl`).
