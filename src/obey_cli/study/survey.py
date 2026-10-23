"""Survey of public AGENTS.md files.

Sampling: GitHub code search for root-level AGENTS.md files, sliced by file size (one search returns at most
1,000 results), one random results page per slice, forks dropped, then a seeded uniform sample of repositories.
The dataset keeps URLs, commit SHAs, licence ids and derived features only: file contents are fetched at the
pinned commit, analysed in memory and never stored, because their licences vary.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
SEARCH_INTERVAL_S = 6.5  # code search allows 10 requests per minute
CORE_INTERVAL_S = 0.25
SEED = 20261023

# Paths whose presence means the repository already enforces something mechanically.
ENFORCEMENT_MARKERS: dict[str, tuple[str, ...]] = {
    "pre_commit": (".pre-commit-config.yaml", ".pre-commit-config.yml"),
    "husky": (".husky/",),
    "lefthook": ("lefthook.yml", "lefthook.yaml", ".lefthook.yml"),
    "codex_hooks": (".codex/hooks.json",),
    "cursor_hooks": (".cursor/hooks.json",),
    "copilot_hooks": (".github/hooks/",),
    "opencode_plugins": (".opencode/plugins/", ".opencode/plugin/"),
}


def size_slices(count: int = 40, low: int = 120, high: int = 65536) -> list[tuple[int, int]]:
    """Geometric file-size ranges in bytes, so every slice holds a similar share of files."""
    edges = [round(low * (high / low) ** (i / count)) for i in range(count + 1)]
    return [(edges[i], edges[i + 1] - 1) for i in range(count)]


@dataclass
class SampleRecord:
    """One surveyed repository. No field holds file contents (tests assert this)."""

    repo: str
    url: str
    commit_sha: str
    path: str
    blob_sha: str
    license_spdx: str | None
    stars: int
    default_branch: str
    size_slice: str
    tree_truncated: bool
    has_claude_md: bool
    has_gemini_md: bool
    has_cursor_rules: bool
    has_copilot_instructions: bool
    claude_settings_hooks: bool
    gemini_settings_hooks: bool
    enforcement: dict[str, bool] = field(default_factory=dict)


class GitHub:
    def __init__(self, token: str, client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep):
        import httpx

        self._client = client or httpx.Client(timeout=30.0, follow_redirects=True)
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "obey-survey",
        }
        self._sleep = sleep
        self._last: dict[str, float] = {}

    def _pace(self, bucket: str, interval: float) -> None:
        wait = self._last.get(bucket, 0.0) + interval - time.monotonic()
        if wait > 0:
            self._sleep(wait)
        self._last[bucket] = time.monotonic()

    def get(self, url: str, bucket: str = "core", params: dict[str, Any] | None = None) -> Any:
        interval = SEARCH_INTERVAL_S if bucket == "search" else CORE_INTERVAL_S
        for attempt in range(6):
            self._pace(bucket, interval)
            resp = self._client.get(url, headers=self._headers, params=params)
            if resp.status_code in (403, 429) and (
                resp.headers.get("x-ratelimit-remaining") == "0" or "retry-after" in resp.headers
            ):
                reset = float(resp.headers.get("x-ratelimit-reset", time.time() + 60))
                retry = float(resp.headers.get("retry-after", max(5.0, reset - time.time() + 1)))
                self._sleep(min(retry, 900.0))
                continue
            if resp.status_code >= 500 and attempt < 5:
                self._sleep(2.0 * (attempt + 1))
                continue
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"GitHub API kept refusing {url}")

    def raw(self, repo: str, sha: str, path: str) -> str | None:
        self._pace("raw", CORE_INTERVAL_S)
        resp = self._client.get(f"{RAW}/{repo}/{sha}/{path}", headers={"User-Agent": "obey-survey"})
        if resp.status_code != 200:
            return None
        return resp.text


def search_candidates(gh: GitHub, rng: random.Random, slices: list[tuple[int, int]]) -> Iterator[dict[str, Any]]:
    """Yield code-search hits for root AGENTS.md files, one random page per size slice."""
    for lo, hi in slices:
        query = f"filename:AGENTS.md path:/ size:{lo}..{hi}"
        first = gh.get(f"{API}/search/code", "search", {"q": query, "per_page": 100, "page": 1})
        if not first:
            continue
        pages = max(1, min(10, -(-int(first.get("total_count", 0)) // 100)))
        page = rng.randint(1, pages)
        data = (
            first if page == 1 else gh.get(f"{API}/search/code", "search", {"q": query, "per_page": 100, "page": page})
        )
        for item in (data or {}).get("items", []):
            if item.get("path") == "AGENTS.md":
                yield {**item, "_slice": f"{lo}..{hi}"}


def describe_repo(gh: GitHub, hit: dict[str, Any]) -> SampleRecord | None:
    full = hit["repository"]["full_name"]
    meta = gh.get(f"{API}/repos/{full}")
    if not meta or meta.get("fork") or meta.get("private"):
        return None
    branch = meta.get("default_branch") or "main"
    head = gh.get(f"{API}/repos/{full}/commits/{branch}")
    if not head:
        return None
    sha = head["sha"]
    tree = gh.get(f"{API}/repos/{full}/git/trees/{sha}", params={"recursive": "1"}) or {}
    paths = [t["path"] for t in tree.get("tree", []) if "path" in t]
    if "AGENTS.md" not in paths:
        return None
    blob = next((t.get("sha", "") for t in tree.get("tree", []) if t.get("path") == "AGENTS.md"), "")
    enforcement = {
        name: any(p == m or (m.endswith("/") and p.startswith(m)) for p in paths for m in markers)
        for name, markers in ENFORCEMENT_MARKERS.items()
    }
    claude_hooks = ".claude/settings.json" in paths and _has_hooks(gh.raw(full, sha, ".claude/settings.json"))
    gemini_hooks = ".gemini/settings.json" in paths and _has_hooks(gh.raw(full, sha, ".gemini/settings.json"))
    lic = (meta.get("license") or {}).get("spdx_id")
    return SampleRecord(
        repo=full,
        url=meta.get("html_url", f"https://github.com/{full}"),
        commit_sha=sha,
        path="AGENTS.md",
        blob_sha=blob,
        license_spdx=lic,
        stars=int(meta.get("stargazers_count", 0)),
        default_branch=branch,
        size_slice=hit.get("_slice", ""),
        tree_truncated=bool(tree.get("truncated")),
        has_claude_md=any(p.endswith("CLAUDE.md") for p in paths),
        has_gemini_md=any(p.endswith("GEMINI.md") for p in paths),
        has_cursor_rules=any(".cursor/rules/" in p for p in paths) or ".cursorrules" in paths,
        has_copilot_instructions=".github/copilot-instructions.md" in paths
        or any(p.startswith(".github/instructions/") for p in paths),
        claude_settings_hooks=claude_hooks,
        gemini_settings_hooks=gemini_hooks,
        enforcement=enforcement,
    )


def _has_hooks(text: str | None) -> bool:
    if not text:
        return False
    try:
        data = json.loads(text)
    except ValueError:
        return False
    return isinstance(data, dict) and bool(data.get("hooks"))


def collect(token: str, out: Path, target: int = 600, seed: int = SEED, log: Callable[[str], None] = print) -> int:
    """Write `target` sampled repositories to `out` (JSON lines). Returns the number written."""
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not security
    gh = GitHub(token)
    hits: dict[str, dict[str, Any]] = {}
    for hit in search_candidates(gh, rng, size_slices()):
        repo = hit["repository"]
        if not repo.get("fork"):
            hits.setdefault(repo["full_name"], hit)
    log(f"search: {len(hits)} distinct non-fork repositories with a root AGENTS.md")
    order = sorted(hits)
    rng.shuffle(order)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("w", encoding="utf-8") as fh:
        for name in order:
            if written >= target:
                break
            record = describe_repo(gh, hits[name])
            if record is None:
                continue
            fh.write(json.dumps(asdict(record), sort_keys=True) + "\n")
            written += 1
            if written % 50 == 0:
                log(f"described {written}/{target}")
    return written
