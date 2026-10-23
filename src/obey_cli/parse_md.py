"""Turn instruction-file Markdown into rule candidates.

A candidate is a list item, a table row, or a prose sentence that contains a directive word. Fenced code,
HTML comments and front matter are never candidates. Every candidate keeps its line span and the headings
above it, because a bullet under a "Don't" heading means the opposite of the same bullet under "Do".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

_STRONG_DIRECTIVE_RE = re.compile(
    r"\b(always|never|must|mustn't|must not|shall|should|shouldn't|should not|do not|don't|avoid|prefer|"
    r"required|forbidden|prohibited|not allowed|ensure|make sure|instead of|rather than)\b",
    re.IGNORECASE,
)
_IMPERATIVE_START_RE = re.compile(
    r"^(use|run|add|keep|write|follow|put|name|commit|push|edit|modify|touch|change|prefer|avoid|never|"
    r"always|do|don't|ensure|make|place|create|update|include|end|start|check|format|lint|test|type|import|"
    r"install|document|log|return|wrap|ask|leave|treat|store|limit|stick|rely|mark|annotate|declare)\b",
    re.IGNORECASE,
)
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_LIST_RE = re.compile(r"^(\s*)(?:[-*+]|\d{1,3}[.)])\s+(?:\[[ xX]\]\s+)?(.*)$")
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_TABLE_RE = re.compile(r"^\s*\|(.*)\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z`*_\"'(])")
_CODE_SPAN_RE = re.compile(r"`([^`]+)`")
_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_)(\S(?:.*?\S)?)\1")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_IMPORT_RE = re.compile(r"(?:(?<=\s)|^)@((?:~/|\.{1,2}/|[\w])[\w./~-]*)")


@dataclass
class Candidate:
    """A piece of instruction text that may be a rule."""

    text: str
    raw: str
    line_start: int
    line_end: int
    kind: str  # "list" | "table" | "sentence"
    headings: list[str] = field(default_factory=list)
    code_spans: list[str] = field(default_factory=list)


@dataclass
class ParsedFile:
    frontmatter: dict[str, Any]
    candidates: list[Candidate]
    imports: list[tuple[str, int]]  # (import path as written, line number)
    body_start_line: int


def split_frontmatter(text: str) -> tuple[dict[str, Any], str, int]:
    """Return (front matter, body, line number where the body starts)."""
    if not text.startswith("---"):
        return {}, text, 1
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return {}, text, 1
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            raw = "\n".join(lines[1:i])
            try:
                data = yaml.safe_load(raw) or {}
            except yaml.YAMLError:
                data = _loose_frontmatter(raw)
            if not isinstance(data, dict):
                data = {}
            return data, "\n".join(lines[i + 1 :]), i + 2
    return {}, text, 1


def _loose_frontmatter(raw: str) -> dict[str, Any]:
    # .mdc files often hold unquoted globs such as `globs: *.ts`, which is invalid YAML.
    data: dict[str, Any] = {}
    for line in raw.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            data[key.strip()] = value.strip().strip("\"'")
    return data


def plain(text: str) -> str:
    """Strip inline Markdown while keeping code-span content."""
    out = _LINK_RE.sub(r"\1", text)
    out = _CODE_SPAN_RE.sub(r"\1", out)
    for _ in range(2):
        out = _EMPHASIS_RE.sub(r"\2", out)
    out = re.sub(r"<[^>]+>", "", out)
    return re.sub(r"\s+", " ", out).strip()


def is_directive(text: str) -> bool:
    return bool(_STRONG_DIRECTIVE_RE.search(text) or _IMPERATIVE_START_RE.match(text.lstrip("*_`> ")))


def _blank_comments(text: str) -> str:
    # Replace HTML comments with blank lines so line numbers stay right.
    return _HTML_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def parse(text: str) -> ParsedFile:
    frontmatter, body, start = split_frontmatter(text)
    body = _blank_comments(body)
    lines = body.split("\n")
    candidates: list[Candidate] = []
    imports: list[tuple[str, int]] = []
    headings: list[tuple[int, str]] = []
    in_fence: str | None = None
    para: list[tuple[int, str]] = []
    item: list[tuple[int, str]] = []
    item_indent = 0

    def flush_para() -> None:
        if para:
            _emit_sentences(para, [h for _, h in headings], candidates)
            para.clear()

    def flush_item() -> None:
        if item:
            raw = " ".join(s.strip() for _, s in item)
            _emit(raw, item[0][0], item[-1][0], "list", [h for _, h in headings], candidates)
            item.clear()

    for offset, line in enumerate(lines):
        lineno = start + offset
        fence = _FENCE_RE.match(line)
        if in_fence is not None:
            if fence and fence.group(1)[0] == in_fence[0] and len(fence.group(1)) >= len(in_fence):
                in_fence = None
            continue
        if fence:
            flush_para()
            flush_item()
            in_fence = fence.group(1)
            continue
        for m in _IMPORT_RE.finditer(_strip_code_spans(line)):
            imports.append((m.group(1), lineno))
        if not line.strip():
            flush_para()
            flush_item()
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            flush_para()
            flush_item()
            level = len(heading.group(1))
            headings = [(lvl, h) for lvl, h in headings if lvl < level]
            headings.append((level, plain(heading.group(2))))
            continue
        if _TABLE_RE.match(line):
            flush_para()
            flush_item()
            if not _TABLE_SEP_RE.match(line):
                cells = [c.strip() for c in _TABLE_RE.match(line).group(1).split("|")]  # type: ignore[union-attr]
                raw = " — ".join(c for c in cells if c)
                _emit(raw, lineno, lineno, "table", [h for _, h in headings], candidates)
            continue
        listed = _LIST_RE.match(line)
        if listed:
            flush_para()
            flush_item()
            item_indent = len(listed.group(1))
            item.append((lineno, listed.group(2)))
            continue
        if item and (len(line) - len(line.lstrip())) > item_indent:
            item.append((lineno, line))
            continue
        if line.lstrip().startswith(">"):
            line = line.lstrip()[1:]
        flush_item()
        para.append((lineno, line))
    flush_para()
    flush_item()
    return ParsedFile(frontmatter=frontmatter, candidates=candidates, imports=imports, body_start_line=start)


def _strip_code_spans(line: str) -> str:
    return _CODE_SPAN_RE.sub(lambda m: " " * len(m.group(0)), line)


def _emit(raw: str, start: int, end: int, kind: str, headings: list[str], out: list[Candidate]) -> None:
    text = plain(raw)
    if len(text) < 3 or not re.search(r"[A-Za-z]{2}", text):
        return
    out.append(
        Candidate(
            text=text,
            raw=raw.strip(),
            line_start=start,
            line_end=end,
            kind=kind,
            headings=list(headings),
            code_spans=_CODE_SPAN_RE.findall(raw),
        )
    )


def _emit_sentences(para: list[tuple[int, str]], headings: list[str], out: list[Candidate]) -> None:
    # Join the paragraph, split it into sentences, and map each sentence back to its first line.
    joined = ""
    starts: list[tuple[int, int]] = []  # (char offset, line number)
    for lineno, text in para:
        if joined:
            joined += " "
        starts.append((len(joined), lineno))
        joined += text.strip()
    pos = 0
    for sentence in _SENTENCE_SPLIT_RE.split(joined):
        idx = joined.find(sentence, pos)
        if idx < 0:
            idx = pos
        pos = idx + len(sentence)
        first = max((ln for off, ln in starts if off <= idx), default=para[0][0])
        last = max((ln for off, ln in starts if off < pos), default=first)
        if is_directive(plain(sentence)):
            _emit(sentence, first, last, "sentence", headings, out)
