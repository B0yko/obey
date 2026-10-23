"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from obey_cli import __version__
from obey_cli.config import CONFIG_NAME, ConfigError

Handler = Callable[[argparse.Namespace], int]


def _out(text: str) -> None:
    print(text, flush=True)


def _err(text: str) -> None:
    print(f"obey: {text}", file=sys.stderr, flush=True)


def cmd_extract(args: argparse.Namespace) -> int:
    from obey_cli import config as cfg
    from obey_cli.rules import build_config, counts

    root = Path(args.repo).resolve()
    path = root / args.config
    previous = cfg.load(path) if path.exists() else None
    proposals = []
    if args.llm:
        from obey_cli.discover import discover
        from obey_cli.extract import extract, llm_propose
        from obey_cli.llm import LLMConfig
        from obey_cli.runner.ledger import Ledger

        ledger = Ledger(root / ".obey" / "ledger.jsonl", budget_usd=args.budget)
        proposals = llm_propose(
            extract(discover(root, args.include_local), root), LLMConfig.from_env(args.llm_model), ledger
        )
    config, files = build_config(root, previous, args.include_local, proposals)
    if not files:
        _err(f"no agent instruction files found under {root}")
        return 1
    if args.dry_run:
        _out(cfg.dump(config))
    else:
        cfg.save(path, config)
    c = counts(config["rules"])
    _out(
        f"{len(files)} instruction file(s), {len(config['rules'])} rules: {c.get('active', 0)} active, "
        f"{c.get('uncheckable', 0)} uncheckable, {c.get('proposed', 0)} proposed"
        + ("" if args.dry_run else f" -> {path.relative_to(root) if path.is_relative_to(root) else path}")
    )
    if c.get("proposed"):
        _out("Review the proposed rules and set `status: active` on the ones you want measured.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="obey",
        description="Unit tests for AGENTS.md: measure which rules your coding agent follows, then enforce them.",
    )
    parser.add_argument("--version", action="version", version=f"obey {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    def add(name: str, help_text: str, handler: Handler) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.set_defaults(handler=handler)
        p.add_argument("--repo", default=".", help="repository root (default: current directory)")
        p.add_argument(
            "--config", default=CONFIG_NAME, help="config file relative to the repository (default: obey.yaml)"
        )
        return p

    p = add("extract", "turn instruction files into checkable rules in obey.yaml", cmd_extract)
    p.add_argument("--llm", action="store_true", help="propose checkers for unmapped rules with an LLM (reviewed)")
    p.add_argument("--llm-model", default=None, help="model for --llm (default: $OBEY_LLM_MODEL)")
    p.add_argument("--budget", type=float, default=1.0, help="USD cap for --llm calls (default: 1.0)")
    p.add_argument("--include-local", action="store_true", help="also read CLAUDE.local.md")
    p.add_argument("--dry-run", action="store_true", help="print obey.yaml instead of writing it")

    from obey_cli import commands as c

    p = add("probe", "create a tempting task for each active rule (written into obey.yaml)", c.cmd_probe)
    p.add_argument("--regenerate", action="store_true", help="replace existing probes")

    p = add("run", "run your coding agent on the probes in a sandbox and score each rule", c.cmd_run)
    p.add_argument("--agent", default=None, help="claude-code | codex | opencode | copilot | gemini")
    p.add_argument("--model", default=None, help="model id at your provider, e.g. anthropic/claude-haiku-5.5")
    p.add_argument("--trials", type=int, default=5, help="runs per probe (default: 5)")
    p.add_argument("--baseline-trials", type=int, default=3, help="runs per probe with the rule removed (default: 3)")
    p.add_argument("--no-baseline", action="store_true", help="skip the no-rule baseline arm")
    p.add_argument("--rules", default=None, help="comma-separated rule ids (default: all active rules with probes)")
    p.add_argument("--budget", type=float, default=5.0, help="USD cap enforced by the ledger (default: 5)")
    p.add_argument("--run-cap", type=float, default=0.5, help="USD cap per run, enforced by the gateway (default: 0.5)")
    p.add_argument("--estimate", action="store_true", help="print runs × estimated cost and exit")
    p.add_argument(
        "--compare",
        default=None,
        metavar="BEFORE.json",
        help="re-run broken rules with enforcement on and report before/after and evasions",
    )
    p.add_argument(
        "--targets",
        default="claude,codex,cursor,gemini,copilot,opencode,precommit",
        help="enforcement targets for --compare",
    )
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument(
        "--image", default=None, help="sandbox image (default: sandbox.image in obey.yaml, then obey-sandbox:0.1.0)"
    )
    p.add_argument("--unsafe-local", action="store_true", help="run without a container (see the README first)")
    p.add_argument("--out", default=None, help="output directory (default: .obey/runs/<timestamp>)")
    p.add_argument("--offline-price", action="store_true", help="do not fetch model prices for --estimate")

    p = add("report", "re-score recorded runs with the current checkers and render the report", c.cmd_report)
    p.add_argument("runs", help="runs.jsonl written by `obey run`")
    p.add_argument("--format", choices=["files", "html", "md", "json"], default="files")

    p = add("enforce", "compile rules into hooks for your agents and a git pre-commit check", c.cmd_enforce)
    p.add_argument(
        "--targets",
        default="claude,codex,cursor,gemini,copilot,opencode,precommit",
        help="comma-separated: claude, codex, cursor, gemini, copilot, opencode, precommit",
    )
    p.add_argument(
        "--from",
        dest="from_report",
        default=None,
        metavar="REPORT.json",
        help="only rules broken in this report (for example .obey/report.json)",
    )
    p.add_argument("--rules", default=None, help="comma-separated rule ids")
    p.add_argument("--dry-run", action="store_true", help="print the diff and write nothing")
    p.add_argument("--remove", action="store_true", help="remove obey's entries and files")

    p = add("lint", "check obey.yaml, instruction-file hashes and enforcement sync; write the badge", c.cmd_lint)
    p.add_argument("--no-badge", action="store_true", help="check for obey-badge.json without rewriting it")

    p = add("doctor", "check git, Docker, the sandbox image, the agent CLIs and the API key", c.cmd_doctor)
    p.add_argument("--image", default=None)
    p.add_argument("--build-image", action="store_true", help="build the default sandbox image (a few GB)")

    p = add("init", "extract rules and create probes in one step", c.cmd_init)

    p = add("demo", "replay recorded runs on the bundled demo repository (no API key, no Docker)", c.cmd_demo)
    p.add_argument("--html", default=None, metavar="PATH", help="also write the HTML report here")

    p = add("study", "reproduce the study: survey, run (pilot, main, enforce), plan, report", c.cmd_study)
    p.add_argument("study_command", choices=["survey", "run", "plan", "report"])
    p.add_argument("--collect", action="store_true", help="survey: sample repositories (needs GITHUB_TOKEN)")
    p.add_argument("--analyse", action="store_true", help="survey: compute features at the pinned commits")
    p.add_argument("--llm", action="store_true", help="survey: classify unmapped rules with an LLM")
    p.add_argument("--llm-model", default=None)
    p.add_argument("--target", type=int, default=600)
    p.add_argument("--phase", choices=["pilot", "main", "enforce"], default="pilot")
    p.add_argument("--trials", type=int, default=1)
    p.add_argument("--budget", type=float, default=3.0)
    p.add_argument("--concurrency", type=int, default=6)
    p.add_argument("--image", default=None)
    p.add_argument("--repos", default=None)
    p.add_argument("--slots", default=None)
    p.add_argument("--harnesses", default=None)
    p.add_argument("--estimate", action="store_true")

    p = add("precommit", "run .obey/pre-commit (for the pre-commit framework)", c.cmd_precommit)
    p.add_argument("--commit-msg", action="store_true", help="check the commit message file instead of staged files")
    p.add_argument("files", nargs="*")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        code: int = args.handler(args)
        return code
    except ConfigError as exc:
        _err(str(exc))
        return 1
    except KeyboardInterrupt:
        _err("interrupted")
        return 130
