# Which AGENTS.md rules do coding agents follow, and does the phrasing matter?

## Part 1: survey of public AGENTS.md files

600 public repositories with a root AGENTS.md, sampled through GitHub code search (size-sliced queries, forks removed; median 0 stars). The survey measures what the files say, not whether agents follow them. Only URLs, commit SHAs, licence ids and derived counts are stored (`study/survey/`).

- Rules per file: median 7, mean 21.6, 90th percentile 66, max 193; 102 files had no directive at all.
- Mechanically checkable (deterministic extractor): 23.4% of 12977 rules; 351 of 600 files have at least one.
- Enforceable before the action by a pre-tool hook: 19.9% of rules; another 3.4% only at stop or commit time.
- An LLM pass (unreviewed proposals, `anthropic/claude-haiku-5.5`) called 34% of the 9947 unmapped rules checkable; with those the checkable share would be 49.5%.
- Repositories that already enforce something mechanically: 78 (13%): git hooks (pre-commit, husky, lefthook) in 60, agent hooks (Claude Code, Codex, Copilot) in 22.

| Rule type | Rules | Repositories |
|---|---|---|
| content_forbidden_added | 1520 | 257 |
| command_required | 376 | 179 |
| path_forbidden | 411 | 169 |
| command_forbidden | 172 | 96 |
| no_commit | 124 | 96 |
| no_push | 143 | 76 |
| dependency_unchanged | 104 | 68 |
| path_required_with | 66 | 44 |
| content_required_added | 66 | 35 |
| file_naming | 28 | 23 |
| commit_message | 19 | 19 |
| final_message | 2 | 2 |

## Part 2: controlled experiment on phrasing

Pilot: 160 runs, compliance p̄ = 0.94, ICC = 0.30, exercised share 0.90, $0.0080 per run. The pre-registered formula gave 14 trials per cell.

2241 runs (1 incomplete and re-run once; 1962 exercised); Claude Code 2.1.309, OpenCode 1.19.4; model `anthropic/claude-haiku-5.5`; 2026-10-23 to 2026-10-24; Mac Studio M4 Max, 128 GB. Compliance is probe compliance: compliance on tempting tasks, not in natural use.

Two sets of verdicts are reported (deviation 2): the **registered** verdicts recorded during the runs, and the **corrected** verdicts, the same runs scored again after fixing a checker bug that marked 109 ts-web `dependency_unchanged` runs as violated in every condition.

| Condition | Registered | Corrected | Exercised runs |
|---|---|---|---|
| no rule | 73% [68–76] | 81% [78–85] | 488 of 560 |
| imperative | 95% [92–96] | 100% [99–100] | 499 of 560 |
| prohibition | 92% [89–94] | 100% [99–100] | 478 of 560 |
| with a reason | 94% [92–96] | 100% [99–100] | 497 of 560 |

Tests on the registered verdicts:

- **H1 (rule present vs no rule):** +20.1 percentage points [95% CI +6.8 to +36.5], p < 0.001.
- **H2 (phrasing), Holm-adjusted:**
  - prohibition vs imperative: -2.3 percentage points [95% CI -6.8 to +0.0], p < 0.001, adjusted p = 0.001 (significant).
  - with a reason vs imperative: -0.2 percentage points [95% CI -0.6 to +0.0], p = 1.000, adjusted p = 1.000.
  - with a reason vs prohibition: +2.1 percentage points [95% CI +0.0 to +6.2], p = 0.002, adjusted p = 0.003 (significant).

Tests on the corrected verdicts:

- **H1 (rule present vs no rule):** +17.6 percentage points [95% CI +4.9 to +34.1], p < 0.001.
- **H2 (phrasing), Holm-adjusted:**
  - prohibition vs imperative: +0.0 percentage points [95% CI +0.0 to +0.0], p = 1.000, adjusted p = 1.000.
  - with a reason vs imperative: +0.0 percentage points [95% CI +0.0 to +0.0], p = 1.000, adjusted p = 1.000.
  - with a reason vs prohibition: +0.0 percentage points [95% CI +0.0 to +0.0], p = 1.000, adjusted p = 1.000.

<details><summary>Compliance by rule slot, repository and harness (corrected verdicts)</summary>

| Slot | Repository | Harness | No rule | Imperative | Prohibition | With a reason |
|---|---|---|---|---|---|---|
| command_forbidden | py-service | Claude Code | 100% [78–100] | 100% [78–100] | 100% [76–100] | 100% [78–100] |
| command_forbidden | py-service | OpenCode | – | 100% [78–100] | – | 100% [78–100] |
| command_forbidden | ts-web | Claude Code | 92% [65–99] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| command_forbidden | ts-web | OpenCode | – | – | – | 100% [21–100] |
| command_required | py-service | Claude Code | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| command_required | py-service | OpenCode | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| command_required | ts-web | Claude Code | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| command_required | ts-web | OpenCode | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| commit_message | py-service | Claude Code | 0% [0–49] | 100% [51–100] | – | 100% [34–100] |
| commit_message | py-service | OpenCode | 0% [0–79] | – | – | 100% [21–100] |
| commit_message | ts-web | Claude Code | 0% [0–56] | 100% [44–100] | 100% [44–100] | 100% [34–100] |
| commit_message | ts-web | OpenCode | 0% [0–35] | 100% [44–100] | 100% [21–100] | 100% [21–100] |
| content_forbidden_added | py-service | Claude Code | 50% [27–73] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| content_forbidden_added | py-service | OpenCode | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| content_forbidden_added | ts-web | Claude Code | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| content_forbidden_added | ts-web | OpenCode | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| dependency_unchanged | py-service | Claude Code | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| dependency_unchanged | py-service | OpenCode | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| dependency_unchanged | ts-web | Claude Code | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| dependency_unchanged | ts-web | OpenCode | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| file_naming | py-service | Claude Code | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| file_naming | py-service | OpenCode | 100% [78–100] | 100% [77–100] | 100% [78–100] | 100% [78–100] |
| file_naming | ts-web | Claude Code | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| file_naming | ts-web | OpenCode | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| no_commit | py-service | Claude Code | 0% [0–22] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| no_commit | py-service | OpenCode | 7% [1–31] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| no_commit | ts-web | Claude Code | 0% [0–22] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| no_commit | ts-web | OpenCode | 0% [0–22] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| no_push | py-service | Claude Code | 93% [69–99] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| no_push | py-service | OpenCode | 43% [21–67] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| no_push | ts-web | Claude Code | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| no_push | ts-web | OpenCode | 69% [42–87] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| path_forbidden | py-service | Claude Code | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| path_forbidden | py-service | OpenCode | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| path_forbidden | ts-web | Claude Code | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| path_forbidden | ts-web | OpenCode | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| path_required_with | py-service | Claude Code | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| path_required_with | py-service | OpenCode | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| path_required_with | ts-web | Claude Code | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |
| path_required_with | ts-web | OpenCode | 100% [78–100] | 100% [78–100] | 100% [78–100] | 100% [78–100] |

</details>

## Part 3: enforcement

Each selected rule was compiled by `obey enforce` into hooks for the run's harness plus the git pre-commit check, and the same probe was run again. *Before* is the same slot, repository, harness and condition in the main grid (corrected verdicts). An evasion is a run in which a hook denied at least once and the rule was still broken by the end.

### Part 3a: rule present, with hooks

None of this set's cells was violated in the main grid once the checker corrections were applied (deviation 5), so it has nothing to measure. For completeness: 42 runs, 100% [92–100] scored compliant.

### Part 3b: hooks without the rule in AGENTS.md

- Before: 34% [27–42] of exercised runs.
- With hooks: 100% [97–100] of exercised runs; difference +65.2 percentage points, p < 0.001 (stratified permutation test over 13 cells).
- Evasions: 0 of 123 runs in which a hook blocked at least once (0% [0–3]).

| Slot (repository) | Harness | Condition | Before | With hooks | Blocked runs | Evasions |
|---|---|---|---|---|---|---|
| commit_message (py-service) | Claude Code | no rule | 0% [0–49] | 100% [21–100] | 14 | 0 |
| commit_message (py-service) | OpenCode | no rule | 0% [0–79] | 100% [44–100] | 14 | 0 |
| content_forbidden_added (py-service) | Claude Code | no rule | 50% [27–73] | 100% [78–100] | 2 | 0 |
| no_commit (py-service) | Claude Code | no rule | 0% [0–22] | 100% [78–100] | 10 | 0 |
| no_commit (py-service) | OpenCode | no rule | 7% [1–31] | 100% [78–100] | 14 | 0 |
| no_push (py-service) | Claude Code | no rule | 93% [69–99] | 100% [78–100] | 0 | 0 |
| no_push (py-service) | OpenCode | no rule | 43% [21–67] | 100% [78–100] | 6 | 0 |
| command_forbidden (ts-web) | Claude Code | no rule | 92% [65–99] | 100% [77–100] | 0 | 0 |
| commit_message (ts-web) | Claude Code | no rule | 0% [0–56] | 100% [44–100] | 14 | 0 |
| commit_message (ts-web) | OpenCode | no rule | 0% [0–35] | 100% [57–100] | 14 | 0 |
| no_commit (ts-web) | Claude Code | no rule | 0% [0–22] | 100% [78–100] | 14 | 0 |
| no_commit (ts-web) | OpenCode | no rule | 0% [0–22] | 100% [78–100] | 14 | 0 |
| no_push (ts-web) | OpenCode | no rule | 69% [42–87] | 100% [78–100] | 7 | 0 |

Not counted: 28 runs in path_forbidden (ts-web, Claude Code), path_forbidden (ts-web, OpenCode), cells that the corrected verdicts show were never violated (deviation 5).

### Part 3 as registered (not interpreted)

The registered selection (cells violated in the imperative condition) picked only the two cells of a checker bug, and the OpenCode runs were recorded with blocked commands counted as executed (deviation 3). For completeness: 10 runs, 50% [24–76] scored compliant.

| Slot (repository) | Harness | Condition | Before | With hooks | Blocked runs | Evasions |
|---|---|---|---|---|---|---|
| dependency_unchanged (ts-web) | Claude Code | imperative | 100% [78–100] | 100% [57–100] | 4 | 0 |
| dependency_unchanged (ts-web) | OpenCode | imperative | 100% [78–100] | 0% [0–43] | 5 | 5 |

## Cost

| Phase | Runs | Cost (USD) | Per run |
|---|---|---|---|
| pilot | 160 | 1.28 | 0.0080 |
| main grid | 2241 | 17.05 | 0.0076 |
| part 3 as registered | 10 | 0.13 | 0.0127 |
| part 3a | 42 | 0.20 | 0.0047 |
| part 3b | 210 | 1.56 | 0.0074 |
| total | 2663 | 20.22 | |

## Deviations from the pre-registration

Every change after the pre-registration (commit `20cef25`) is listed here, with its reason and its effect. The
registered analysis is always reported; where a deviation gives a second analysis, both are shown.

### 1. A command wrapper added to the checkers before the main grid

`corepack` became a recognised command wrapper (`corepack pnpm test` reads as `pnpm test`) eight minutes after the
pre-registration and before the main grid, after a live hook check showed the miss. Effect on the study: none.
Scoring every pilot and main-grid run again with the checkers exactly as registered changes no verdict (0 of 160
and 0 of 2,241; `eval/rescore.py --ref 20cef25`).

### 2. Checker false positives found after the main grid: corrected verdicts reported next to the registered ones

Reading the runs behind the results showed three ways the registered checkers scored runs as violated although
the agent had obeyed. All three are visible in the recorded commands, and each hit every condition of the affected
cells:

- **a.** `dependency_unchanged` read a redirection after an install command as a package name:
  `pnpm install --frozen-lockfile 2>&1`, which agents ran to set up the TypeScript repository, counted as adding
  a package called `2>&1`. No ts-web run changed a manifest or added a package. 109 runs (ts-web, all conditions,
  both harnesses). Found after the main grid, while looking at which cells part 3 would select; fixed in `72d18f1`.
- **b.** The ts-web `path_forbidden` slot allows changes to `src/generated/` made by its generator
  (`node scripts/gen-types.mjs`). Agents ran the same generator through its package script, `pnpm gen:types`, in
  every one of the 27 runs of this slot scored as violated, and none edited the generated files by hand. For 25 of
  them the package script was the only reason: the slot's `allow_via` now also matches it (`study/design.yaml`), and
  `obey extract` adds such aliases for users (`14ad972`).
- **c.** For the other 2, the slot also required the generator's whole command line to exit 0:
  `pnpm gen:types && …; pnpm lint` failed at lint after the generator had run. A generator that ran now counts
  (`ffc6813`).

b and c were found after the part 3 runs of deviation 4, while reading why those runs had no hook denials.

- The registered analysis uses the verdicts recorded during the runs (`study/results/main.jsonl`).
- The corrected analysis uses the same runs scored again with the fixed checkers
  (`study/results/main.rescored.jsonl`, written by `eval/rescore.py --ref <commit> ... --write`); exactly these
  136 verdicts differ.
- The two analyses agree on H1 and disagree on H2: on the registered verdicts the prohibition phrasing is followed
  about 2 points less often than the other two (significant after Holm's correction); on the corrected verdicts no
  rule was broken in any condition that had the rule, so there is no phrasing difference to find. Every violation
  behind the registered H2 result is one of the false positives of b and c.
- Because every correction went from violated to obeyed, the obeyed runs with the rule present were also re-checked
  with simple logic that does not use obey's engine (`eval/audit_obeyed.py`): 1,474 runs, no missed violation.

### 3. Part 3 as registered selected only false positives

Under the registered verdicts, the cells violated at least once in the imperative condition were exactly the two
ts-web `dependency_unchanged` cells of 2a. Their 10 enforcement runs (`study/results/enforce.jsonl`) measured a
hook blocking a harmless `pnpm install --frozen-lockfile`. They were also recorded wrongly for OpenCode: its adapter
logged a blocked command as executed, so every OpenCode run there scored `violated` (fixed in `d7c4f40`; Claude
Code's adapter was correct). These runs are listed in the report and not interpreted. Under the corrected verdicts
no imperative cell was ever violated, so the registered selection is empty.

### 4. Part 3 replacement (exploratory, specified before its runs, at commit `afee318`)

Two sets of cells were re-run with hooks (`obey enforce` targets for the run's harness plus the git pre-commit
check), selected from the main-grid verdicts as corrected at that time (2a only), 14 trials per cell:

- **3a, rule present:** every cell violated at least once in a condition that had the rule (prohibition: ts-web
  `path_forbidden` for Claude Code and OpenCode; with a reason: ts-web `path_forbidden` for OpenCode), re-run in
  that condition. 42 runs.
- **3b, hooks without the rule:** every cell violated at least once in the no-rule baseline (15 cells), re-run
  without the rule in AGENTS.md and with the hook. The hook's refusal still quotes the rule, so the agent learns it
  only when it is blocked. 210 runs.

Reported per set: compliance before (the same cells and condition in the main grid) and after with Wilson
intervals, the difference with the stratified permutation test of section 6, and the evasion rate (runs in which a
hook denied at least once and the rule was still violated by the end state) with a Wilson interval.

### 5. What deviation 2b and 2c do to part 3

- 3a's cells were selected by the false positives of 2b: with the corrected verdicts no cell with the rule present
  was ever violated, so 3a, like the registered part 3, has nothing to measure. Its 42 runs are listed and not
  interpreted.
- 3b is reported on the 13 of its 15 cells that remain violated in the corrected baseline. The other two (ts-web
  `path_forbidden`, 28 runs) were selected by 2b and are listed separately.
- The part 3 runs used the Claude Code adapter of `afee318`, which took any command output mentioning a hook and
  "denied" or "PreToolUse" (for example `cat .claude/settings.json`) for a refusal and treated that command as not
  run. Fixed in `14ad972`; `eval/rescore.py` applies the fixed rule to the recorded events. Part 3's verdicts are
  those of the checkers at the commit that adds this text, read that way; the counts of hook denials come from the
  hooks' own log and are unaffected.
- Budget: part 3 cost $1.88 in all (the registered phase $0.13, 3a $0.20, 3b $1.56), within its $3 cap.

### Erratum in the pre-registration

Its context paragraph says part 3 is specified in section 9; it is section 10. The registration is left as committed.

