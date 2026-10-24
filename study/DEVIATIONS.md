Every change after the pre-registration (commit `20cef25`) is listed here, with its reason and its effect. The
registered analysis is always reported; where a deviation gives a second analysis, both are shown.

### 1. A command wrapper added to the checkers before the main grid

`corepack` became a recognised command wrapper (`corepack pnpm test` reads as `pnpm test`) eight minutes after the
pre-registration and before the main grid, after a live hook check showed the miss. Effect on the study: none.
Scoring every pilot and main-grid run again with the checkers exactly as registered changes no verdict (0 of 160
and 0 of 2,241; `eval/rescore.py --ref 20cef25`).

### 2. A checker bug found after the main grid: corrected verdicts reported next to the registered ones

The registered `dependency_unchanged` checker read a redirection after an install command as a package name:
`pnpm install --frozen-lockfile 2>&1`, which agents ran to set up the TypeScript repository, counted as adding a
package called `2>&1`. No ts-web run in any condition changed a manifest or added a package. 109 of the 112
ts-web `dependency_unchanged` runs were scored `violated` for this reason alone, in every condition and both
harnesses. The bug was found after the main grid, while looking at which cells part 3 would select; it is fixed
in `72d18f1` with a regression test and a new dev-set case (held-out numbers unchanged).

- The registered analysis uses the verdicts recorded during the runs (`study/results/main.jsonl`).
- The corrected analysis uses the same runs scored again with the fixed checker
  (`study/results/main.rescored.jsonl`, written by `eval/rescore.py --ref 72d18f1 ... --write`); only those
  109 verdicts differ.
- Both are shown in the report. The pre-registered tests reach the same conclusions on both, because the bug hit
  every condition of the same stratum equally; the compliance rates differ (the bug lowered every condition).

### 3. Part 3 as registered selected only the bug's cells, and its runs were invalid

Under the registered verdicts, the cells violated at least once in the imperative condition were exactly the two
ts-web `dependency_unchanged` cells of deviation 2. Their 10 enforcement runs (`study/results/enforce.jsonl`)
measured a hook blocking a harmless `pnpm install --frozen-lockfile`. They were also recorded wrongly for OpenCode:
its adapter logged a blocked command as executed, so every OpenCode run there scored `violated` (fixed in
`d7c4f40`; Claude Code's adapter was correct). These runs are listed in the report and not interpreted.

Under the corrected verdicts no imperative cell was ever violated, so the registered selection is empty.

### 4. Part 3 replacement (exploratory, specified here before any of its runs)

To measure hooks where agents did break rules, two sets of cells are re-run with hooks (`obey enforce` targets
for the run's harness plus the git pre-commit check), selected from the corrected main-grid verdicts:

- **3a, rule present:** every cell violated at least once in a condition that had the rule (prohibition: ts-web
  `path_forbidden` for Claude Code and OpenCode; with a reason: ts-web `path_forbidden` for OpenCode), re-run in
  that condition. 3 cells × 14 trials = 42 runs.
- **3b, hooks without the rule:** every cell violated at least once in the no-rule baseline (15 cells), re-run
  without the rule in AGENTS.md and with the hook. The hook's refusal still quotes the rule, so the agent learns it
  only when it is blocked. 15 cells × 14 trials = 210 runs.

14 trials per cell, as in the main grid, so before (the same cells and condition in the main grid, corrected
verdicts) and after have the same size. Reported per set: compliance before and after with Wilson intervals, the
difference with the stratified permutation test of section 6, and the evasion rate (runs in which a hook denied
at least once and the rule was still violated by the end state) with a Wilson interval. Runs use the code at the
commit that adds this file (with the fixes of deviations 2 and 3); verdicts come from its checkers. Budget: part 3
stays within its $3 cap.
