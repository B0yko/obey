# obey

**Unit tests for AGENTS.md.** obey turns the rules in your agent instruction files into checks, runs your coding agent
on small tempting tasks in a sandbox, measures which rules it actually follows from what it did, and compiles the ones it
ignores into hooks for Claude Code, Codex CLI, Cursor, Gemini CLI, Copilot CLI and OpenCode.

[![CI](https://github.com/B0yko/obey/actions/workflows/ci.yml/badge.svg)](https://github.com/B0yko/obey/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/B0yko/obey)](https://github.com/B0yko/obey/releases)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

**On tempting tasks, Claude Haiku 5.5 in Claude Code and OpenCode followed the rule under test in all 1,474 exercised
runs where it was in AGENTS.md, against 81% without it (+17.6 points [95% CI 4.9–34.1]); the phrasing (imperative,
prohibition, or with a reason) made no difference. Hooks without the rule raised compliance from 34% to 100% for
the rules agents broke, and in 0 of 123 blocked runs did the agent break the rule another way.** This is probe
compliance, measured after correcting 136 checker false positives (94% before the correction); see
[how it was measured](study/REPORT.md).

<picture>
  <img alt="obey demo replaying recorded runs: per-rule compliance and the before/after table with hooks" src="docs/images/demo.svg">
</picture>

```bash
uvx --from git+https://github.com/B0yko/obey obey demo
```

The demo needs no API key and no Docker: it replays agent runs recorded in the study and scores them again.

## Quickstart

In your repository (Python 3.10+, git, [uv](https://docs.astral.sh/uv/)):

```bash
uvx --from git+https://github.com/B0yko/obey obey init      # extract rules into obey.yaml and create probes
uvx --from git+https://github.com/B0yko/obey obey lint      # no agent runs: checks rules, hashes, enforcement; writes the badge
```

Read `obey.yaml`: every rule has a checker, or a status that says why not (`uncheckable` for rules that need taste,
`proposed` for LLM suggestions you have to approve). Then either measure or enforce:

```bash
# enforce now, no runs needed: hooks for every agent plus a git pre-commit check
uvx --from git+https://github.com/B0yko/obey obey enforce --dry-run
uvx --from git+https://github.com/B0yko/obey obey enforce

# measure: needs Docker (or colima) and an OpenRouter key; the key never enters the sandbox
uvx --from git+https://github.com/B0yko/obey obey doctor --build-image          # once: the sandbox image, a few GB
export OPENROUTER_API_KEY=...
uvx --from git+https://github.com/B0yko/obey obey run --estimate --model anthropic/claude-haiku-5.5
uvx --from git+https://github.com/B0yko/obey obey run --model anthropic/claude-haiku-5.5 --budget 2
uvx --from git+https://github.com/B0yko/obey obey enforce --from .obey/report.json   # hooks for the rules it broke
cp .obey/report.json before.json
uvx --from git+https://github.com/B0yko/obey obey run --compare before.json --model anthropic/claude-haiku-5.5
```

### Test your AGENTS.md in 10 minutes

```bash
uvx --from git+https://github.com/B0yko/obey obey run --model anthropic/claude-haiku-5.5 --trials 3 --baseline-trials 1 --budget 2
```

On the demo repository (11 checkable rules with probes) this made 44 runs of Claude Code 2.1.309 in 9 min 20 s and
cost $0.38 (measured on 2026-10-24 on a Mac Studio M4 Max, 128 GB, Docker in colima, 4 runs at a time). It prints
one line per rule and writes `report.html`, `report.md` and `report.json`. The defaults (5 runs per rule plus 3 with
the rule removed) double the runs and narrow the intervals.

## How it works

```mermaid
flowchart LR
  A["AGENTS.md, CLAUDE.md, GEMINI.md,<br/>.cursor/rules, Copilot files"] --> B["obey extract<br/>pattern library (+ reviewed LLM proposals)"]
  B --> C["obey.yaml<br/>rules with checkers"]
  C --> D["obey probe<br/>a tempting task per rule"]
  D --> E["obey run"]
  subgraph S["sandbox (one container per run)"]
    E --> F["coding agent, headless"]
    F -->|"model calls, dummy token"| G["gateway<br/>holds the key, meters cost"]
    F -->|"npm, PyPI only"| H["egress proxy"]
  end
  F --> I["commands, diff, commits"]
  I --> J["deterministic checkers"]
  J --> K["report: compliance per rule,<br/>no-rule baseline, evasions"]
  C --> L["obey enforce"]
  L --> M["hooks for 6 agents<br/>+ git pre-commit"]
  M --> E
```

- **Extract.** obey reads AGENTS.md (nested files apply to their directory), CLAUDE.md with `@imports`, GEMINI.md,
  Cursor `.mdc` rules (globs, `alwaysApply`) and Copilot instruction files (`applyTo`), and maps each rule to one of
  twelve deterministic checkers: forbidden or required commands, forbidden paths, paired paths (tests with code), new
  dependencies, forbidden or required content in added lines, commit messages, commits, pushes, file names and the
  final message. Rules that need judgement stay `uncheckable`. `--llm` asks any OpenAI-compatible model about the rest
  and writes its answers as `proposed`.
- **Probe.** Each rule gets a small task where breaking it is the easy route: add a package (package manager rule),
  rename a column (migration rule), type an untyped payload (`any` rule), "let me know when it's done" (tests rule).
- **Run.** The agent runs headless several times per probe, plus a no-rule baseline arm with the rule removed, in a
  fresh container. Only `git ls-files` enters the container. Egress goes through an allow-listing proxy; the model key
  stays in a gateway outside the container, which enforces per-run and total spend caps.
- **Score.** Checkers read what the agent did (commands, diff, commits), never what it said. A run that never touched
  a rule's domain is `not_exercised` and excluded; compliance comes with a Wilson 95% interval and the exercised share.
- **Enforce.** `obey enforce` writes hooks that call one standard-library rule engine, the same code the checkers use,
  so a hook blocks exactly what the checker measures. `obey run --compare` measures again and counts evasions: runs
  where a hook blocked the direct route and the rule was still broken another way.

## What obey supports

| | Claude Code | Codex CLI | OpenCode | Copilot CLI | Gemini CLI | Cursor |
|---|---|---|---|---|---|---|
| Version verified (2026-10-23) | 2.1.309 | 0.164.0 | 1.19.4 | 1.0.103 | 0.65.0 | docs only |
| Instruction files it reads | CLAUDE.md, AGENTS.md if there is no CLAUDE.md | AGENTS.md | AGENTS.md, else CLAUDE.md | AGENTS.md, CLAUDE.md, GEMINI.md, Copilot files | GEMINI.md | `.cursor/rules`, AGENTS.md |
| `obey run` (headless, sandboxed) | yes, live | yes, live | yes, live | yes, live (bring your own key) | yes, needs a paid Gemini key; not run | no: no custom endpoint |
| Rules loaded, decoy global config ignored | verified live | verified live | verified live | verified live | — | — |
| Enforcement written by `obey enforce` | `.claude/settings.json` | `.codex/hooks.json` | `.opencode/plugins/obey.ts` | `.github/hooks/obey.json` | `.gemini/settings.json` | `.cursor/hooks.json` |
| Hook blocks a shell command | live | live | live | live | contract tests | contract tests |
| Can block finishing (tests, paired paths) | yes | yes | no (advisory) | yes | yes | no (advisory) |

"Live" means verified with the real CLI in the sandbox (`eval/contract_check.py`); "contract tests" means the generated
hook was tested against payloads written from the vendor's documentation. Every target also gets the git pre-commit
check. Codex CLI loads project hooks only after you trust them (`/hooks`); Copilot CLI's prompt mode needs
`--trust-folder` or `GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS=true`.

Details, flags and isolation checks: [docs/agents.md](docs/agents.md). Checker definitions:
[docs/checkers.md](docs/checkers.md). Enforcement targets: [docs/enforce.md](docs/enforce.md).

## Configuration

`obey.yaml` is the reviewed list of rules ([reference](docs/config.md)). Environment variables:

| Variable | Used by | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` or `OBEY_API_KEY` | `obey run` | provider key; stays in the gateway, outside the sandbox |
| `OBEY_LLM_API_KEY`, `OBEY_LLM_BASE_URL`, `OBEY_LLM_MODEL` | `obey extract --llm` | any OpenAI-compatible endpoint |
| `OBEY_DOCKER` | `obey run` | docker command (for example `podman`) |
| `GITHUB_TOKEN` | `obey study survey` | GitHub code search |

### In CI and pre-commit

```yaml
# .github/workflows/obey.yml: lint mode needs no secrets
permissions:
  contents: read
jobs:
  obey:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1
      - uses: B0yko/obey@v0.1.0
```

`mode: run` (with `api-key`, `model` and `budget`) runs the agent; it spends money and needs a secret, so the action
refuses it on pull requests: run it on `workflow_dispatch` or a schedule only.

```yaml
# .pre-commit-config.yaml (after `obey enforce --targets precommit`)
repos:
  - repo: https://github.com/B0yko/obey
    rev: v0.1.0
    hooks:
      - id: obey
      - id: obey-commit-msg
```

The badge: `obey lint` and `obey run` write `obey-badge.json` in the
[shields.io endpoint format](https://shields.io/badges/endpoint-badge). Commit it and use
`https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/<you>/<repo>/main/obey-badge.json`.

## Results

All numbers below come from runs made for this release on 2026-10-23 and 2026-10-24 (Mac Studio M4 Max, 128 GB;
Docker in colima), with `anthropic/claude-haiku-5.5` through OpenRouter in Claude Code 2.1.309 and OpenCode 1.19.4.
Full report: [study/REPORT.md](study/REPORT.md). Pre-registration: [study/PREREGISTRATION.md](study/PREREGISTRATION.md).
Every change after it: [study/DEVIATIONS.md](study/DEVIATIONS.md).

### What public AGENTS.md files say (600 repositories)

- Median 7 rules per file (mean 21.6, 90th percentile 66, max 193); 102 of 600 files contain no directive at all.
- 23.4% of 12,977 rules are mechanically checkable by obey's deterministic extractor; 19.9% could be enforced before
  the action by a pre-tool hook, another 3.4% only at stop or commit time. An LLM pass (unreviewed proposals) would
  raise the checkable share to 49.5%.
- 13% of the repositories (78) already enforce something mechanically: git hooks in 60, agent hooks in 22.

### Does the agent follow the rule, and does phrasing matter? (2,241 runs)

Two repositories authored for the study, ten rule types, each tested with the rule removed (no rule) and in three
phrasings, 14 runs per cell. This is **probe compliance**: on small tasks built so that breaking the rule is the easy
route, not compliance in everyday use.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/compliance-by-phrasing-dark.svg">
  <img alt="Probe compliance by phrasing and harness: about 80% with no rule, 100% with the rule in any phrasing" src="docs/images/compliance-by-phrasing-light.svg">
</picture>

| Condition | As registered | Corrected | Exercised runs |
|---|---|---|---|
| no rule | 73% [68–76] | 81% [78–85] | 488 of 560 |
| imperative ("Use pnpm …") | 95% [92–96] | 100% [99–100] | 499 of 560 |
| prohibition ("Never …") | 92% [89–94] | 100% [99–100] | 478 of 560 |
| imperative with a reason | 94% [92–96] | 100% [99–100] | 497 of 560 |

- **The rule works when it is there.** With the rule in AGENTS.md the agents broke it in none of 1,474 exercised runs
  (corrected verdicts); without it, compliance was 81%. Pre-registered test: +17.6 percentage points [95% CI +4.9 to
  +34.1], p < 0.001. The rules that changed behaviour were the ones agents break by default: commit messages (0% →
  100%), "leave changes uncommitted" (2% → 100%), "leave pushing to the maintainers" (76% → 100%), and the bans on
  `print()` and `: any` in new code (88% → 100%). Five of the ten probes tempted nobody: agents followed those rules
  in every run even when they were absent.
- **Phrasing did not matter** on the corrected verdicts: every phrasing was followed in every exercised run. On the
  verdicts as registered, the prohibition scored about 2 points lower (significant after Holm's correction), but every
  violation behind that result was a checker false positive (below).
- **The checkers were wrong 136 times.** Reading the runs showed two false-positive patterns in the registered
  checkers: `pnpm install --frozen-lockfile 2>&1` read as adding a package called `2>&1` (109 runs), and the generator
  of `src/generated/` run through its package script `pnpm gen:types` scored as a hand edit (27 runs). The checkers
  scored 1.0 precision on the authored held-out cases, which did not contain these forms. Both analyses are in the
  report; the fixes are in this release.

### Do hooks hold when the rule is not there? (182 runs counted)

Every rule type that agents broke without the rule was compiled by `obey enforce` into a hook for that agent plus the
git pre-commit check, and the same probes were run again, still without the rule in AGENTS.md: the agent learns the
rule only when a hook refuses it.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/enforcement-before-after-dark.svg">
  <img alt="Probe compliance without the rule, before and with hooks, for the five rule types agents broke" src="docs/images/enforcement-before-after-light.svg">
</picture>

- In the 13 cells (rule type × repository × agent) that agents broke without the rule, compliance went from 34%
  [27–42] to 100% [97–100] with hooks (+65 points, p < 0.001, stratified permutation test).
- **Evasions: 0 of 123** runs in which a hook blocked at least once broke the rule another way by the end
  (0% [0–3]). The agents took the refusal, which quotes the rule, and changed course. In the commit-message cells,
  12 of 56 runs ended with a conforming commit and 44 with no commit at all; blocked commits and pushes were not
  retried another way.
- Because no rule was ever broken while it was in AGENTS.md (corrected verdicts), the pre-registered version of this
  measurement, hooks on top of the rule, had nothing to measure. 28 further runs in two cells that only a checker
  false positive had selected are listed in the report and not counted.

### The tool itself

- Rule extraction, held-out set of 15 authored files (136 labelled rules, evaluated once): recall 0.70 [0.60–0.79],
  precision 0.96 [0.88–0.98] for active rules; parameters right for 0.77 [0.65–0.85]. On the 25 development files:
  recall 0.98, precision 1.0.
- Checkers, held-out set of 442 labelled runs (frozen before the checkers existed): precision and recall 1.0 for every
  type at release; the first evaluation found three bugs (`content_required_added` precision 0.94,
  `dependency_unchanged` recall 0.94), fixed and listed in `fixtures/checkers/CHANGES.md`. See the false positives
  above for what authored cases miss.
- Live checks with the real CLIs in the sandbox: each of Claude Code, Codex CLI, OpenCode and Copilot CLI loaded the
  repository's AGENTS.md, ignored a decoy global instruction file, and was stopped by a pre-tool hook installed in the
  files and format that `obey enforce` writes (`eval/contract_check.py`, 8 of 8 probes, $0.013). The hooks that
  `obey enforce` generates ran in the study's enforcement runs for Claude Code and OpenCode. Locally, Claude Code
  2.1.308 with an `obey enforce` hook was refused `npm install date-fns` in 14 ms and left `~/.claude` untouched
  (`eval/results/live-claude-code.json`).
- Hook overhead: each hook call is a fresh Python process. 95th percentile 31 ms with Python 3.14 and 44 ms with
  macOS's system Python 3.9 (200 calls per agent format, 11 rules, Mac Studio M4 Max, `eval/hook_latency.py`).
- Cost of the study: $20.22 for 2,663 agent runs (pilot $1.28, main grid $17.05, part 3 $1.88), plus $0.34 for
  the survey's LLM pass, all metered by obey's gateway.

Reproduce: `uv run obey study report` rebuilds the report and charts from the committed summaries;
`uv run python eval/rescore.py` re-scores the raw runs (attached to the release); `uv run python eval/run_eval.py`
re-runs the extraction and checker evaluations. Running the study again needs Docker, an OpenRouter key and about
$22 (`docs/study.md`).

## Privacy and security

- **During `obey run`, your repository's tracked files and the probe tasks go to the model provider you configure**
  (by default OpenRouter, which routes to the model's vendor). `.env` files, ignored files and anything not tracked by
  git never enter a run.
- The key stays in obey's gateway, outside the agent's container; agents get a dummy token. The gateway accepts only
  that token, forwards only the model endpoints of each API, pins the model, and stops a run at its spend cap.
- Agent containers have no route to the internet except an allow-listing proxy (by default npm, PyPI, Go and crates
  registries) and the gateway; every egress attempt is logged. No host path is mounted.
- `--unsafe-local` (for machines without Docker) runs the agent directly on your machine in a temporary copy with an
  empty `HOME`, no git remotes, no credential variables and no git credential helpers, with the agent's own sandbox
  switched on where it has one (Claude Code, Codex CLI, Gemini CLI). Commands the agent runs can still reach the network
  and anything your user can read, so obey prints a warning and refuses "never commit" and "never push" probes there.
- Subscription logins: obey's study used API keys only. Anthropic's Consumer Terms forbid accessing its services
  "through automated or non-human means" except with an API key or where Anthropic explicitly permits it
  ([terms](https://www.anthropic.com/legal/consumer-terms)); check your vendor's terms before running agents on a
  subscription login.
- `obey enforce` writes only inside your repository. Generated hooks use only the Python standard library and fail
  open (with a visible warning) on internal errors.

## Limitations

- Two demo repositories, ten rule types, one inexpensive model in two harnesses, specific agent versions and dates.
  Other models, agents and repositories may behave differently.
- Probe compliance is compliance on tempting tasks written to make breaking the rule easy. It is not the compliance you
  would see in everyday use.
- With the rule present, compliance was at the ceiling (100%) for every phrasing, so the phrasing experiment cannot
  tell phrasings apart for this model and these rules; a model or rule that is broken more often might show a
  difference. Five of the ten probes did not tempt the agent even without the rule.
- The corrected verdicts were decided after the outcomes were known (study/DEVIATIONS.md). Each correction is a false
  positive visible in the recorded commands, and the registered analysis is reported next to it.
- Checkers can be wrong on real runs in ways authored test cases miss: the study found 136 false positives (6% of
  runs) in two patterns. Read the evidence obey prints for a violation before acting on it.
- In the enforcement runs the hook's refusal quotes the rule, so "hooks without the rule" still tells the agent the
  rule at the moment it is blocked.
- Extraction recall on real instruction files is measured only on the authored sets (held-out recall 0.70). Read
  `obey.yaml` before trusting it; the survey's "checkable" share depends on the same extractor.
- The survey reflects what public AGENTS.md files say, sampled through GitHub code search (relevance-ranked within
  size slices), not what agents do with them.
- Checkers see actions, so rules about taste, design or communication stay `uncheckable`, and some checkers read the end
  state only: an edit made and reverted inside one run does not count for content rules.
- Hooks are a guardrail, not a security boundary: an agent can still change files through routes a pre-tool hook does
  not see. `obey run --compare` measures exactly that as evasions; the pre-commit check and the stop hooks catch some of
  it at the end.
- Linux and macOS only. Windows is not supported in 0.1.

## Alternatives

obey is not the first tool to compile instruction files into checks or to test them; this is how the closest ones
differ (checked on 2026-10-23):

- [hookify](https://github.com/anthropics/claude-code/tree/main/plugins/hookify) (Anthropic's Claude Code plugin)
  writes regex rules that warn or block tool calls, from an instruction or from corrections mined from a conversation.
  It does not measure compliance.
- [claudecode-rule2hook](https://github.com/zxdxjtu/claudecode-rule2hook) turns plain-English rules, or rules read
  from CLAUDE.md, into Claude Code hook configuration. No measurement.
- [ContextCov](https://arxiv.org/abs/2603.00822) compiles AGENTS.md, CLAUDE.md and Copilot instructions into source,
  import-graph, LLM-reviewed and command checks, and reports 88.3% constraint compliance on SWE-bench Lite against
  67.0% for a prompt-only baseline. It evaluates on SWE-bench tasks rather than per-rule tempting tasks.
- [AgentGuard](https://arxiv.org/abs/2609.16287) learns guardrail rules from failure traces of coding agents rather
  than from your instruction file.
- [nunchi](https://github.com/seob717/nunchi) ([article](https://braindetox.kr/en/posts/claude_md_hooks_compile_2026.html))
  compiles CLAUDE.md rules into trigger-bound rules that a hook re-delivers when an action fires.
- [agents-md-evals](https://github.com/vltansky/agents-md-evals) A/B tests a Claude instruction file present versus
  removed, using assertions from the repository's history.
- [ruleProb](https://github.com/canblmz1/ruleProb) extracts rules from CLAUDE.md, AGENTS.md and Cursor rules, builds
  sandbox scenarios, runs a provider against each and scores commands, protected writes and code patterns; it is the
  closest in purpose. obey differs in its probes-as-temptations with a no-rule baseline, per-rule rates with intervals
  from actions across five agent CLIs, enforcement for six agents from the same engine, and evasion counts.
- [rulecheck](https://github.com/Atlas-RD-Research/rulecheck) tests what a model says it would do in written
  scenarios, not its actions.
- Static linters such as [agnix](https://github.com/agent-sh/agnix),
  [agentlinter](https://github.com/seojoonkim/agentlinter), [alint](https://github.com/alint-dev/alint),
  [agent-compass](https://github.com/YoavLax/agent-compass), [agent-ready](https://github.com/agent-next/agent-ready)
  and [Factory Agent Readiness](https://docs.factory.com/agent-readiness/overview) check instruction and configuration
  files without running an agent.
- For "tests pass" and "deployed" claims in Claude Code,
  [proof-of-done](https://github.com/B0yko/proof-of-done) is a fuller stop-hook check than obey's
  `command_required` hook.

## Roadmap

- Antigravity CLI, once it has a documented headless mode with an API key.
- Cursor CLI runs (it has no custom model endpoint today, so the key would have to enter the sandbox).
- More probe templates per rule type, and probes adapted to the repository with `--llm`.
- Judging uncheckable rules is out of scope for 0.1 on purpose; obey stays deterministic.

## License

Apache-2.0. Copyright 2026 Andrii Boiko.
