# The study: methods and how to reproduce it

The results are in `study/REPORT.md`; the pre-registration is `study/PREREGISTRATION.md` (committed before the pilot
as `study: preregister`); design decisions are in `docs/adr/0009-study-design.md`.

## Part 1: survey of public AGENTS.md files

- Sample: GitHub code search for files named AGENTS.md at a repository root, split into 40 geometric file-size slices
  (code search returns at most 1,000 results per query and allows 10 requests per minute), one seeded random results
  page per slice, forks removed, then 600 repositories drawn uniformly with a fixed seed. Each record pins the default
  branch's commit SHA at sampling time.
- Features: each AGENTS.md is fetched at its pinned commit, parsed and run through the deterministic extractor in
  memory; only counts are stored (`study/survey/features.jsonl`), never file contents, because the files' licences
  vary. The presence of git hooks (pre-commit, husky, lefthook) and agent hooks (Claude Code, Codex, Cursor, Gemini,
  Copilot, OpenCode) comes from the repository tree.
- LLM pass: rules the patterns did not map were classified by `anthropic/claude-haiku-5.5` into a checker type or "needs
  judgement" (`study/survey/llm.jsonl`, counts only). These are unreviewed proposals and are reported separately.
- Limits: code search ranks by relevance within each slice, so the sample is not a uniform random sample of all
  AGENTS.md files; the extractor's recall on real files is measured only on the authored sets; the survey measures what
  files say, not what agents do.

```bash
GITHUB_TOKEN=... uv run obey study survey --collect --analyse      # sample and features (no model calls)
OPENROUTER_API_KEY=... uv run obey study survey --llm --budget 3    # the LLM pass
```

## Part 2: controlled experiment on phrasing

- Two repositories authored for the study (`study/repos/py-service`, `study/repos/ts-web`), ten rule slots each
  (`study/design.yaml`): a fixed checker, three phrasings (imperative, prohibition, imperative with a reason) and one
  probe, plus 15 fixed distractor rules. Every AGENTS.md has 25 rules in the same order.
- Conditions: no-rule baseline (the slot under test removed) and the three phrasings. Harnesses: Claude Code and
  OpenCode, both with the same inexpensive model through OpenRouter. Each run is a fresh container.
- Outcome: the slot's deterministic checker on what the agent did (commands, diff, commits); runs that never touched the
  rule's domain are excluded and counted.
- Analysis (pre-registered): stratified permutation tests within slot × repository × harness strata, cluster-bootstrap
  intervals over slot × repository clusters, Holm's correction across the three phrasing contrasts.

```bash
OPENROUTER_API_KEY=... uv run obey study run --phase pilot --trials 1 --budget 3
uv run obey study plan                                             # trials per cell from the pilot
OPENROUTER_API_KEY=... uv run obey study run --phase main --trials <T> --budget 20
OPENROUTER_API_KEY=... uv run obey study run --phase enforce --trials 5 --budget 3
uv run obey study report                                           # study/REPORT.md and the charts
```

Runs need Docker (or colima) and the sandbox image (`obey doctor --build-image`). Interrupted phases resume: finished
runs are skipped.

## Part 3: enforcement

Every slot × repository × harness cell that was violated at least once in the imperative condition is compiled into
hooks for that harness plus the git pre-commit check and re-run with the same probe. Reported: compliance before and
after, and evasions (runs in which a hook blocked at least once and the rule was still broken by the end).

## Data

- `study/results/*.jsonl`: one summary per run (condition, verdict, evidence kind, hook denials, tokens, cost, time).
- Raw run records (normalised events, diffs, commits) are attached to the GitHub release as an archive after a scan for
  secrets and paths.
