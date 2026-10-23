"""Minimal client for any OpenAI-compatible chat endpoint, returning schema-validated JSON.

Configuration comes from the environment: OBEY_LLM_BASE_URL (default OpenRouter), OBEY_LLM_API_KEY (falls back
to OPENROUTER_API_KEY) and OBEY_LLM_MODEL. Every call is written to the spend ledger.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from obey_cli.runner.ledger import Entry, Ledger, Price, now, provider_cost, usage_from_response

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class LLMError(RuntimeError):
    pass


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str

    @classmethod
    def from_env(cls, model: str | None = None) -> LLMConfig:
        key = os.environ.get("OBEY_LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or ""
        if not key:
            raise LLMError("set OBEY_LLM_API_KEY (or OPENROUTER_API_KEY) to use --llm")
        chosen = model or os.environ.get("OBEY_LLM_MODEL")
        if not chosen:
            raise LLMError("set OBEY_LLM_MODEL or pass --llm-model")
        return cls(os.environ.get("OBEY_LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/"), key, chosen)


def _first_json_object(text: str) -> Any:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except ValueError:
        pass
    for open_, close in (("{", "}"), ("[", "]")):
        start = text.find(open_)
        end = text.rfind(close)
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except ValueError:
                continue
    raise ValueError("no JSON object in the response")


def chat_json(
    config: LLMConfig,
    system: str,
    user: str,
    schema: dict[str, Any],
    ledger: Ledger | None = None,
    price: Price | None = None,
    run_id: str = "llm",
    max_tokens: int = 2000,
    attempts: int = 2,
    normalize: Any = None,
) -> dict[str, Any]:
    """Ask for a JSON object and validate it against `schema`; retries once with the validation error.

    `normalize`, when given, maps the parsed JSON (object or array) to the object the schema describes.
    """
    import httpx
    import jsonschema

    messages: list[dict[str, str]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last_error = ""
    for _ in range(attempts):
        if ledger is not None:
            ledger.check()
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "usage": {"include": True},
        }
        resp = httpx.post(
            f"{config.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=120.0,
        )
        if resp.status_code >= 400:
            raise LLMError(f"model endpoint returned HTTP {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        usage = usage_from_response(body)
        cost = provider_cost(body)
        if ledger is not None:
            ledger.record(
                Entry(
                    ts=now(),
                    run_id=run_id,
                    kind="llm",
                    model=config.model,
                    cost_usd=cost if cost is not None else (price.cost(usage) if price else 0.0),
                    cost_source="provider" if cost is not None else "price_table",
                    **usage,
                )
            )
        try:
            content = body["choices"][0]["message"]["content"] or ""
            data = _first_json_object(content)
            if normalize is not None:
                data = normalize(data)
            jsonschema.validate(data, schema)
            if not isinstance(data, dict):
                raise ValueError("top-level JSON value is not an object")
            return data
        except (KeyError, IndexError, ValueError, jsonschema.ValidationError) as exc:
            last_error = str(exc)[:500]
            messages = [
                *messages,
                {"role": "assistant", "content": str(body.get("choices", [{}])[0].get("message", {}).get("content"))},
                {"role": "user", "content": f"That was not valid: {last_error}. Reply with the JSON object only."},
            ]
    raise LLMError(f"no valid JSON after {attempts} attempts: {last_error}")
