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
        proposals = llm_propose(extract(discover(root, args.include_local)), LLMConfig.from_env(args.llm_model), ledger)
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


def _not_yet(name: str) -> Handler:
    def handler(args: argparse.Namespace) -> int:
        _err(f"`obey {name}` is not available in this build")
        return 2

    return handler


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
