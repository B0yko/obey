from __future__ import annotations

import itertools
import json
from dataclasses import fields
from pathlib import Path
from typing import Any

import httpx
import jsonschema

from obey_cli.study import survey

SCHEMA = json.loads((Path(__file__).parents[1] / "schemas" / "survey-record-v1.json").read_text())
CONTENT_WORDS = ("content", "text", "body", "excerpt", "snippet", "lines")
IDENTIFIER_FIELDS = {"repo", "url", "commit_sha", "path", "blob_sha", "license_spdx", "default_branch", "size_slice"}


def test_dataset_schema_has_no_content_fields() -> None:
    names = set(SCHEMA["properties"]) | {f.name for f in fields(survey.SampleRecord)}
    assert not [n for n in names if any(w in n for w in CONTENT_WORDS)]
    assert SCHEMA["additionalProperties"] is False
    # Only identifiers may be strings; everything else is a number or a boolean.
    strings = {n for n, p in SCHEMA["properties"].items() if "string" in str(p.get("type", "string"))}
    assert strings == IDENTIFIER_FIELDS
    assert SCHEMA["properties"]["enforcement"]["additionalProperties"] == {"type": "boolean"}


def test_size_slices_are_contiguous() -> None:
    slices = survey.size_slices(10, 100, 10000)
    assert slices[0][0] == 100
    assert all(a[1] + 1 == b[0] for a, b in itertools.pairwise(slices))


def _fake_api(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "/search/code" in url:
        items = [
            {"path": "AGENTS.md", "repository": {"full_name": "acme/app", "fork": False}},
            {"path": "docs/AGENTS.md", "repository": {"full_name": "acme/docs", "fork": False}},
            {"path": "AGENTS.md", "repository": {"full_name": "someone/app", "fork": True}},
        ]
        return httpx.Response(200, json={"total_count": 3, "items": items}, headers={"x-ratelimit-remaining": "9"})
    if url.endswith("/repos/acme/app"):
        return httpx.Response(
            200,
            json={
                "fork": False,
                "default_branch": "main",
                "license": {"spdx_id": "MIT"},
                "stargazers_count": 7,
                "html_url": "https://github.com/acme/app",
            },
        )
    if "/commits/main" in url:
        return httpx.Response(200, json={"sha": "a" * 40})
    if "/git/trees/" in url:
        tree = [{"path": p, "sha": "b" * 40} for p in ("AGENTS.md", ".pre-commit-config.yaml", ".claude/settings.json")]
        return httpx.Response(200, json={"tree": tree, "truncated": False})
    if url.startswith(survey.RAW) and url.endswith(".claude/settings.json"):
        return httpx.Response(200, text='{"hooks": {"PreToolUse": []}}')
    return httpx.Response(404)


def test_collect_writes_schema_valid_records(tmp_path: Path, monkeypatch: Any) -> None:
    client = httpx.Client(transport=httpx.MockTransport(_fake_api))
    real = survey.GitHub

    def make(token: str) -> survey.GitHub:
        return real(token, client=client, sleep=lambda s: None)

    monkeypatch.setattr(survey, "GitHub", make)
    monkeypatch.setattr(survey, "size_slices", lambda: [(100, 200)])
    out = tmp_path / "sample.jsonl"
    assert survey.collect("t", out, target=5, log=lambda m: None) == 1
    (record,) = [json.loads(line) for line in out.read_text().splitlines()]
    jsonschema.validate(record, SCHEMA)
    assert record["repo"] == "acme/app" and record["license_spdx"] == "MIT"
    assert record["enforcement"]["pre_commit"] is True
    assert record["claude_settings_hooks"] is True


def test_rate_limit_is_respected() -> None:
    slept: list[float] = []
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(403, headers={"x-ratelimit-remaining": "0", "retry-after": "30"})
        return httpx.Response(200, json={"ok": True})

    gh = survey.GitHub("t", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=slept.append)
    assert gh.get("https://api.github.com/search/code", "search") == {"ok": True}
    assert 30.0 in slept
