from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from obey_cli import llm
from obey_cli.runner.ledger import BudgetExceeded, Entry, Ledger, Price, usage_from_response


def test_ledger_budget(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl", budget_usd=1.0)
    ledger.record(Entry(ts=0, run_id="a", kind="agent", model="m", cost_usd=0.6))
    ledger.record(Entry(ts=0, run_id="b", kind="agent", model="m", cost_usd=0.3))
    assert ledger.spent() == pytest.approx(0.9)
    assert ledger.spent("a") == pytest.approx(0.6)
    ledger.check(0.05)
    with pytest.raises(BudgetExceeded):
        ledger.check(0.2)


def test_usage_normalisation_and_price() -> None:
    openai = usage_from_response(
        {"usage": {"prompt_tokens": 1000, "completion_tokens": 50, "prompt_tokens_details": {"cached_tokens": 800}}}
    )
    assert openai == {"input_tokens": 1000, "output_tokens": 50, "cache_read_tokens": 800, "cache_write_tokens": 0}
    anthropic = usage_from_response(
        {
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_input_tokens": 90,
                "cache_creation_input_tokens": 0,
            }
        }
    )
    assert anthropic["input_tokens"] == 100 and anthropic["cache_read_tokens"] == 90
    price = Price(prompt=1e-6, completion=2e-6, cache_read=1e-7)
    assert price.cost(openai) == pytest.approx(200 * 1e-6 + 50 * 2e-6 + 800 * 1e-7)


def test_chat_json_validates_and_retries(tmp_path: Path, monkeypatch: Any) -> None:
    replies = iter(["not json", '{"rules": [{"id": "x"}]}'])

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": next(replies)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
            },
        )

    transport = httpx.MockTransport(handler)
    real_post = httpx.post
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: httpx.Client(transport=transport).post(*a, **kw))
    ledger = Ledger(tmp_path / "l.jsonl", budget_usd=1)
    schema = {"type": "object", "required": ["rules"], "properties": {"rules": {"type": "array"}}}
    cfg = llm.LLMConfig("https://llm.example.com/v1", "k", "m")
    assert llm.chat_json(cfg, "s", "u", schema, ledger=ledger) == {"rules": [{"id": "x"}]}
    assert ledger.spent() == pytest.approx(0.002)
    assert httpx.post is not real_post


def test_config_requires_key(monkeypatch: Any) -> None:
    monkeypatch.delenv("OBEY_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(llm.LLMError):
        llm.LLMConfig.from_env("m")
