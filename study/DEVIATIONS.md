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
  (`node scripts/gen-types.mjs`). Agents ran the same generator through its package script, `pnpm gen:types`;
  every one of the 27 runs scored as violated did so, and none edited the generated files by hand. 25 runs. The
  slot's `allow_via` now also matches the package script (`study/design.yaml`), and `obey extract` adds such
  aliases for users (`14ad972`).
- **c.** The same slot required the generator's whole command line to exit 0; in the 2 remaining runs
  `pnpm gen:types && …; pnpm lint` failed at lint after the generator had run. A generator that ran now counts
  (`ffc6813`). 2 runs.

b and c were found after the part 3 runs of deviation 4, while reading why those runs had no hook denials.

- The registered analysis uses the verdicts recorded during the runs (`study/results/main.jsonl`).
- The corrected analysis uses the same runs scored again with the fixed checkers
  (`study/results/main.rescored.jsonl`, written by `eval/rescore.py --ref <commit> ... --write`); exactly these
  136 verdicts differ.
- The two analyses agree on H1 and disagree on H2: on the registered verdicts the prohibition phrasing is followed
  about 2 points less often than the other two (significant after Holm's correction); on the corrected verdicts no
  rule was broken in any condition that had the rule, so there is no phrasing difference to find. Every violation
  behind the registered H2 result is one of the false positives of b.

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
- Budget: part 3 stays within its $3 cap; 3b's own cap was raised from $2.0 to the remaining part 3 budget when the
  measured cost per run (about $0.012) turned out higher than the main grid's.
