"""Locate data that ships with obey: schemas, the demo repository and recorded runs, hook templates.

In an installed wheel the data lives under `obey_cli/_data/` (hatchling force-include). In a source checkout it
is read from the repository root, so the same code works in both.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

_PACKAGE = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE.parent.parent


# In a source checkout the demo repository is the study's TypeScript repository.
_SOURCE_ALIASES = {("demo", "repo"): ("study", "repos", "ts-web")}


def data_path(*parts: str) -> Path:
    installed = _PACKAGE.joinpath("_data", *parts)
    if installed.exists():
        return installed
    for alias, target in _SOURCE_ALIASES.items():
        if parts[: len(alias)] == alias:
            return _REPO_ROOT.joinpath(*target, *parts[len(alias) :])
    return _REPO_ROOT.joinpath(*parts)


@cache
def schema(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(data_path("schemas", name).read_text(encoding="utf-8"))
    return data
