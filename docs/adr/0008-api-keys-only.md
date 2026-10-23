# 8. API keys, not subscription logins, for published runs

Date: 2026-10-23 · Status: accepted

## Context

Running agents headless many times is automated use. Anthropic's Consumer Terms of Service forbid accessing its
services through automated or non-human means except with an API key or where Anthropic explicitly permits it;
other vendors have their own terms.

## Decision

obey uses the API keys the user provides (OpenRouter or the vendor's own). Keys never enter the sandbox: agents get
a dummy token and a base URL pointing at obey's model gateway, which runs outside the agent's container, holds the
key, pins the model, records usage and enforces per-run and batch caps. The published study used OpenRouter API
keys only and no subscription logins.

The README asks users who want to run with a subscription login to check their vendor's terms first.

## Consequences

- Every published number has a measured dollar cost.
- A prompt-injected agent cannot read the key from its environment or files.
