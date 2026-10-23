from __future__ import annotations

from pathlib import Path

import pytest

from obey_cli.config import ConfigError, load, rule_id, save, validate

RULE = {
    "id": "use-pnpm-abc123",
    "text": "Use pnpm.",
    "source": {"file": "AGENTS.md", "lines": [3, 3]},
    "scope": {"paths": ["**"], "agents": None},
    "checker": {"type": "command_forbidden", "params": {"patterns": ["^npm (install|i|add)\\b"], "preferred": "pnpm"}},
    "status": "active",
    "reason": None,
    "origin": "pattern",
    "probes": [],
}


def test_rule_id_is_stable_slug_plus_hash() -> None:
    assert rule_id("Use  pnpm for all package operations.") == rule_id("Use pnpm for all package operations.")
    assert rule_id("Use pnpm for all package operations.").startswith("use-pnpm-for-all-package-operations-")
    assert rule_id("!!!").startswith("rule-")


def test_roundtrip(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "rules": [
            RULE,
            {**RULE, "id": "taste-1", "status": "uncheckable", "checker": None, "reason": "needs judgement"},
        ],
    }
    save(tmp_path / "obey.yaml", data)
    assert load(tmp_path / "obey.yaml") == data


def test_validation_messages() -> None:
    bad = {
        "version": 1,
        "rules": [
            {**RULE, "checker": {"type": "path_forbidden", "params": {}}},
            {**RULE, "status": "uncheckable", "checker": None},
        ],
    }
    errors = validate(bad)
    assert any("globs" in e for e in errors)
    assert any("reason" in e for e in errors) or any("None is not of type 'string'" in e for e in errors)
    assert any("duplicate id" in e for e in errors)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="obey extract"):
        load(tmp_path / "obey.yaml")
