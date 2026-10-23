"""Read, validate and write obey.yaml."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from obey_cli.resources import schema

CONFIG_NAME = "obey.yaml"
DEFAULT_ALLOW_HOSTS = [
    "registry.npmjs.org",
    "pypi.org",
    "files.pythonhosted.org",
    "proxy.golang.org",
    "sum.golang.org",
    "crates.io",
    "static.crates.io",
    "index.crates.io",
]


class ConfigError(ValueError):
    pass


def normalise_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def rule_id(text: str) -> str:
    """A stable slug of the rule text plus a short hash, e.g. `use-pnpm-for-all-package-operations-3f9a1c`."""
    norm = normalise_text(text)
    slug = re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")[:40].strip("-") or "rule"
    return f"{slug}-{hashlib.sha1(norm.encode()).hexdigest()[:6]}"  # noqa: S324 - an identifier, not security


def validate(data: Any) -> list[str]:
    import jsonschema

    validator = jsonschema.Draft202012Validator(schema("obey-config-v1.json"))
    errors = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{where}: {err.message}")
    ids = [r.get("id") for r in (data.get("rules") or [])] if isinstance(data, dict) else []
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    errors += [f"rules: duplicate id {d}" for d in dupes]
    return errors


def load(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"{path} not found; run `obey extract` first") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    errors = validate(data)
    if errors:
        raise ConfigError(f"{path}: " + "; ".join(errors[:10]))
    assert isinstance(data, dict)
    return data


class _Dumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _str_presenter)


def dump(data: dict[str, Any]) -> str:
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=120)


def save(path: Path, data: dict[str, Any]) -> None:
    errors = validate(data)
    if errors:
        raise ConfigError("refusing to write an invalid obey.yaml: " + "; ".join(errors[:10]))
    path.write_text(dump(data), encoding="utf-8")
