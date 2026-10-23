"""Map instruction-file candidates to checkable rules with a deterministic pattern library.

Each candidate (a bullet, table row or directive sentence) is first classified as a rule or not. A rule is matched
against rule families in priority order (push, commit, commit message, final message, file naming, paired paths,
required content, dependencies, commands, forbidden paths, forbidden content). The first family that recognises it
produces a checker with parameters; a rule no family recognises is `uncheckable` with a reason. Optional LLM
extraction (`llm_propose`) only ever adds rules with `status: proposed`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from obey_cli.config import rule_id
from obey_cli.discover import InstructionFile
from obey_cli.parse_md import Candidate, is_directive

NEG = (
    r"(?:never|do\s+not|don['’]?t|dont|must\s+not|mustn['’]t|should\s+not|shouldn['’]t|may\s+not|no|not|avoid|"
    r"without|forbidden|prohibited|isn['’]t\s+allowed|is\s+not\s+allowed|are\s+not\s+allowed|stop)"
)
_NEG_RE = re.compile(rf"\b{NEG}\b", re.IGNORECASE)
_TASTE_RE = re.compile(
    r"\b(clean|readable|idiomatic|maintainable|elegant|simple|small|short|concise|brief|clear|careful|thoughtful|"
    r"consistent|meaningful|sensible|reasonable|appropriate|best practices?|good|nice|focused|minimal|tidy|"
    r"understand|think|consider|prefer|explain|intent|why|behaviou?r)\b",
    re.IGNORECASE,
)
_PATHY_RE = re.compile(r"^(?:\.{0,2}/)?[\w.*@\-\[\]{}]+(?:/[\w.*@\-\[\]{}]*)*/?$")
_EXT_LANG = {
    "py": ["**/*.py"],
    "ts": ["**/*.ts", "**/*.tsx"],
    "js": ["**/*.js", "**/*.jsx", "**/*.mjs", "**/*.cjs", "**/*.ts", "**/*.tsx", "**/*.vue", "**/*.svelte"],
    "go": ["**/*.go"],
    "rs": ["**/*.rs"],
}


@dataclass
class Extracted:
    candidate: Candidate
    file: InstructionFile
    status: str
    checker: dict[str, Any] | None
    reason: str | None = None
    origin: str = "pattern"
    extra_scope: list[str] = field(default_factory=list)

    def as_rule(self) -> dict[str, Any]:
        text = self.candidate.text
        return {
            "id": rule_id(f"{self.file.path}:{text}"),
            "text": text,
            "source": {"file": self.file.path, "lines": [self.candidate.line_start, self.candidate.line_end]},
            "scope": {"paths": list(self.file.scope_paths), "agents": None},
            "checker": self.checker,
            "status": self.status,
            "reason": self.reason,
            "origin": self.origin,
            "probes": [],
        }


# --------------------------------------------------------------------------------------------- helpers


def _lower(c: Candidate) -> str:
    return c.text.lower()


def _negated(text: str) -> bool:
    return bool(_NEG_RE.search(text))


def _spans(c: Candidate) -> list[str]:
    return [s.strip() for s in c.code_spans if s.strip()]


_FILE_EXT = (
    r"\.(py|pyi|ts|tsx|js|jsx|mjs|cjs|json|ya?ml|toml|md|mdx|rst|txt|sql|go|mod|sum|rs|lock|lockb|cfg|ini|"
    r"sh|bash|html|css|scss|proto|graphql|env|xml|csv|ipynb|java|kt|rb|php|c|h|cpp|swift|tf|lua)$"
)


def _path_spans(c: Candidate) -> list[str]:
    out = []
    for s in _spans(c):
        if " " in s or s.startswith("-") or "(" in s or "=" in s:
            continue
        if ("/" in s or re.search(_FILE_EXT, s) or s.endswith("*")) and _PATHY_RE.match(s):
            out.append(s[2:] if s.startswith("./") else s)
    if not out:
        for m in re.finditer(r"(?<![\w`])((?:[\w.-]+/)+[\w.*-]*)", c.text):
            if not m.group(1).startswith(("http", "www.")):
                out.append(m.group(1))
    return out


def _glob(path: str) -> str:
    p = path.strip().rstrip(",;:.") if not path.endswith("/") else path.strip()
    if p.startswith("/"):
        p = p[1:]
    if p.endswith("/**") or "*" in p.split("/")[-1]:
        return p
    if p.endswith("/"):
        return p + "**"
    if "." not in p.split("/")[-1]:
        return p + "/**"
    return p


def _dirs_in_text(c: Candidate) -> list[str]:
    """Directories a rule is limited to ("in `src/`", "under app/")."""
    dirs: list[str] = []
    for m in re.finditer(
        r"\b(?:in|under|inside|within|from|to)\s+`?([\w.-]+(?:/[\w.-]+)*/)`?((?:\s*(?:,|or|and)\s*`?"
        r"[\w.-]+(?:/[\w.-]+)*/`?)*)",
        c.raw,
    ):
        dirs.append(m.group(1))
        dirs += re.findall(r"([\w.-]+(?:/[\w.-]+)*/)", m.group(2) or "")
    return list(dict.fromkeys(dirs))


def _lang_globs(text: str, spans: Sequence[str]) -> list[str]:
    t = text.lower()
    for key, words in (
        ("py", ("python", ".py", "pytest", "print(", "type: ignore", "noqa", "mypy", "django", "flask")),
        ("ts", ("typescript", ".ts", "tsx", "@ts-", " any", "`any`", "tsc", "react")),
        ("js", ("javascript", ".js", "console.", "eslint", "node", "jsx", "innerhtml", "document.")),
        ("go", (" go ", "golang", ".go", "fmt.print", "panic(")),
        ("rs", ("rust", ".rs", "unwrap(", "cargo", "clippy", "unsafe")),
    ):
        if any(w in t for w in words) or any(w in " ".join(spans).lower() for w in words):
            return list(_EXT_LANG[key])
    return ["**"]


def _scoped(globs: list[str], dirs: list[str]) -> list[str]:
    if not dirs:
        return globs
    out = []
    for d in dirs:
        base = d.rstrip("/")
        for g in globs:
            tail = g[3:] if g.startswith("**/") else g
            out.append(f"{base}/**" if tail in ("**", "*") else f"{base}/**/{tail}")
    return out


# --------------------------------------------------------------------------------------------- families

Family = Callable[[Candidate], "dict[str, Any] | None"]


def fam_no_push(c: Candidate) -> dict[str, Any] | None:
    t = _lower(c)
    if not re.search(r"\bpush(es|ing)?\b|git push", t) or "push notification" in t:
        return None
    plain_push = re.search(
        r"(never|not|don['’]?t|no)\b[^.;]{0,25}\b(run )?git push\b|\bpush(ing)? to (the |any |a )?"
        r"(remote|origin|main|github)",
        t,
    )
    if re.search(r"force[- ]push|--force|push -f\b|push --force", t) and not plain_push:
        if _negated(t):
            return {"type": "command_forbidden", "params": {"patterns": [r"^git push\b.*(\s-f\b|\s--force\b|\s\+)"]}}
        return None
    if _negated(t) or re.search(r"leave pushing|pushing is done|pushes? (is|are) done|maintainers? push", t):
        return {"type": "no_push", "params": {}}
    return None


def fam_no_commit(c: Candidate) -> dict[str, Any] | None:
    t = _lower(c)
    if not re.search(r"\bcommit(s|ted|ting)?\b", t) or re.search(r"commit (message|subject|title)s?", t):
        return None
    if re.search(r"\bcommit only when (asked|requested|told)|only commit when", t):
        return {"type": "no_commit", "params": {}}
    if re.search(r"commits are (made|created|done) by|leave (the )?changes (uncommitted|in the working tree)", t):
        return {"type": "no_commit", "params": {}}
    if _negated(t) and re.search(rf"\b{NEG}\b[^.;]{{0,40}}\b(commit|git commit|create commits?|make commits?)\b", t):
        return {"type": "no_commit", "params": {}}
    if re.search(
        r"\bcommits?\b[^.;]{0,30}\b(must not|mustn't|should not|may not|shall not|is not to|are not to)\b"
        r"[^.;]{0,20}\b(be )?(created|made)\b",
        t,
    ):
        return {"type": "no_commit", "params": {}}
    return None


CONVENTIONAL = r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([\w./, -]+\))?!?: \S"


def fam_commit_message(c: Candidate) -> dict[str, Any] | None:
    t = _lower(c)
    if not re.search(r"commit (message|subject|title)s?|commits? (should|must)? ?(start|begin|follow|use|look)", t):
        return None
    if "conventional commit" in t or re.search(r"type\(scope\)|`?type: ?summary`?|feat:|fix:", t):
        types = re.findall(r"`(\w+)(?:\([^)]*\))?:`?", c.raw)
        explicit = [
            x
            for x in types
            if x.lower()
            in {"feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert"}
        ]
        if explicit and re.search(r"\b(start|begin)", t) and "conventional" not in t:
            alt = "|".join(sorted(set(explicit)))
            return {"type": "commit_message", "params": {"regex": rf"^({alt})(\([\w./, -]+\))?!?: \S"}}
        regex = CONVENTIONAL
        if re.search(r"lower[- ]case type", t):
            regex = CONVENTIONAL
        if re.search(r"package as (the )?scope|with (a|the) scope|scope is required", t):
            regex = r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)\([\w./-]+\)!?: \S"
        return {"type": "commit_message", "params": {"regex": regex}}
    m = re.search(r"\b(start|begin|prefix)\w*\b.*?\bwith\b.*?`([^`]+)`", c.raw, re.IGNORECASE)
    if m:
        example = m.group(2)
        ticket = re.match(r"([A-Z][A-Z0-9]+)-\d+", example)
        if ticket or re.search(r"ticket|issue|jira", t):
            prefix = ticket.group(1) if ticket else r"[A-Z][A-Z0-9]+"
            return {"type": "commit_message", "params": {"regex": rf"^\[?{prefix}-\d+\]?:? \S"}}
        spans = [s for s in _spans(c) if s.endswith(":")]
        if spans:
            alt = "|".join(re.escape(s[:-1]) for s in spans)
            return {"type": "commit_message", "params": {"regex": rf"^({alt})(\([\w./, -]+\))?: \S"}}
    if re.search(r"capital letter", t) or re.search(r"(\d+) characters", t):
        parts = []
        if "capital letter" in t:
            parts.append(r"(?=[A-Z])")
        limit = re.search(r"(\d+) characters", t)
        body = rf"[^\n]{{1,{limit.group(1)}}}" if limit else r"[^\n]+"
        tail = r"(?<!\.)" if re.search(r"(not|never) end with a (period|full stop|\.)", t) else ""
        return {"type": "commit_message", "params": {"regex": "^" + "".join(parts) + body + tail + r"(\n|$)"}}
    return None


def fam_final_message(c: Candidate) -> dict[str, Any] | None:
    t = _lower(c)
    first_sentence = re.split(r"(?<=[.!?])\s", t, maxsplit=1)[0]
    if not re.search(r"\b(final|last|closing|reply|answer|response|message)\b", first_sentence):
        return None
    if not re.search(
        r"\b(final|last|closing) (message|reply|answer|response)\b|\b(end|finish|close) (your|every|each) "
        r"(reply|answer|response|message)",
        t,
    ):
        return None
    spans = _spans(c)
    if re.search(r"emoji", t) and _negated(t):
        return {"type": "final_message", "params": {"forbidden": r"[\U0001F300-\U0001FAFF☀-➿]"}}
    if spans:
        first = spans[0]
        alts = [re.escape(s) for s in spans if s and len(s) < 60]
        alt = "|".join(alts)
        line_rule = re.search(r"line (starting|that starts|beginning)|under a line|a line ", t)
        if re.search(r"\bend", t) and line_rule:
            return {"type": "final_message", "params": {"required": rf"(^|\n)\s*({alt})[^\n]*\s*$"}}
        if line_rule:
            return {"type": "final_message", "params": {"required": rf"(^|\n)\s*({alt})"}}
        if re.search(r"\bstart", t):
            return {"type": "final_message", "params": {"required": rf"^\s*({alt})"}}
        if re.search(r"\bend", t):
            return {"type": "final_message", "params": {"required": rf"({alt})\s*$"}}
        return {"type": "final_message", "params": {"required": re.escape(first)}}
    return None


_CASES = {
    "kebab": r"[a-z0-9]+(-[a-z0-9]+)*",
    "snake": r"[a-z0-9]+(_[a-z0-9]+)*",
    "pascal": r"[A-Z][a-zA-Z0-9]*",
    "camel": r"[a-z][a-zA-Z0-9]*",
}


def fam_file_naming(c: Candidate) -> dict[str, Any] | None:
    t = _lower(c)
    if not re.search(r"\b(name|names|named|naming|file ?names?|filenames?)\b", t):
        return None
    if re.search(r"variable|function|class|branch|commit|env(ironment)? var", t) and not re.search(r"file", t):
        return None
    case = next((k for k in _CASES if re.search(rf"\b{k}[- _]?case\b", t)), None)
    spans = _spans(c)
    ext = None
    for s in spans:
        m = re.search(r"\.([A-Za-z0-9]{1,5})$", s)
        if m:
            ext = m.group(1)
            break
    if re.search(r"\btest files?\b|\btests? (are|is) named|\bname test", t):
        pattern = next((s for s in spans if "<" in s or "*" in s or "test" in s.lower()), None)
        if not pattern:
            return None
        rx = re.escape(pattern)
        rx = re.sub(r"\\<[^>]*\\>|<[^>]*>", r"[A-Za-z0-9_.-]+", rx).replace(r"\*", r"[A-Za-z0-9_.-]+")
        dirs = _dirs_in_text(c)
        suffix = re.search(r"\.[A-Za-z0-9]+$", pattern)
        if suffix and suffix.group(0) in (".py",):
            globs = [f"{d.rstrip('/')}/**/*.py" for d in dirs] if dirs else ["tests/**/*.py", "test/**/*.py"]
            if pattern.startswith("test_"):
                globs = [g for g in globs]
        elif suffix:
            ending = suffix.group(0)
            if pattern.endswith((".test.ts", ".spec.ts", ".test.tsx", ".test.js")):
                ending = "." + ".".join(pattern.split(".")[-2:])
                globs = [f"**/*{ending.replace('.test', '').replace('.spec', '')}"]
                globs = [g for g in globs]
                globs = ["**/*test*" + ending[ending.rfind(".") :], "**/*spec*" + ending[ending.rfind(".") :]]
                globs = [f"{d.rstrip('/')}/{g[3:]}" if g.startswith("**/") else g for d in dirs for g in globs] or globs
            else:
                globs = [f"**/*{ending}"]
        else:
            return None
        return {"type": "file_naming", "params": {"globs": globs, "pattern": rx}}
    if case is None:
        return None
    base = _CASES[case]
    lang = f"**/*.{ext}" if ext else None
    globs = [lang] if lang else _lang_globs(c.text, spans)
    if globs == ["**"]:
        globs = ["**/*"]
    if re.search(r"\b(module|modules)\b", t) and not ext:
        globs = ["**/*.py"]
    if re.search(r"component", t):
        globs = ["**/components/**/*.tsx", "**/components/**/*.jsx"] if not ext else [f"**/components/**/*.{ext}"]
        if re.search(r"src/components", c.raw):
            globs = [f"src/components/**/*.{ext or 'tsx'}"]
    dirs = _dirs_in_text(c)
    if dirs and not re.search(r"component", t):
        globs = _scoped(globs, dirs)
    pattern = base + r"(\.[A-Za-z0-9]+)+"
    if re.search(r"\b(page|guide|doc)", t) and not ext:
        globs = _scoped(["**/*.md", "**/*.mdx"], dirs) if dirs else ["**/*.md", "**/*.mdx"]
    return {"type": "file_naming", "params": {"globs": globs, "pattern": pattern}}


_TEST_GLOBS = [
    "tests/**",
    "test/**",
    "**/tests/**",
    "**/test_*.py",
    "**/*_test.py",
    "**/*_test.go",
    "**/*.test.ts",
    "**/*.test.tsx",
    "**/*.test.js",
    "**/*.spec.ts",
    "**/*.spec.tsx",
    "**/*.spec.js",
    "**/__tests__/**",
]


def fam_path_required_with(c: Candidate) -> dict[str, Any] | None:
    t = _lower(c)
    paths = _path_spans(c)
    tests = re.search(r"\btests?\b|spec", t)
    if (
        re.search(
            r"\b(when|whenever|if)\b.*\b(change|edit|modify|touch|add)\w*\b.*\b(update|add|change|include|"
            r"bump|regenerate|edit)\b",
            t,
        )
        or re.search(
            r"\b(change|changes|edit|edits)\b.*\b(needs?|requires?|must (come|be accompanied)|come with|accompanied by|"
            r"should come)\b",
            t,
        )
        or re.search(r"\bnew (modules?|files?|functions?|code)\b.*\bneeds? (a |an )?(unit )?test", t)
        or re.search(r"\b(add|write|include) (unit )?tests? (for|with) (every|each|any|all|new)\b", t)
    ):
        if len(paths) >= 2:
            when, require = paths[0], paths[1]
            return {"type": "path_required_with", "params": {"when": [_glob(when)], "require": [_glob(require)]}}
        if len(paths) == 1 and tests:
            p = paths[0]
            if re.search(r"tests?/", p):
                return {"type": "path_required_with", "params": {"when": ["src/**"], "require": [_glob(p)]}}
            return {"type": "path_required_with", "params": {"when": [_glob(p)], "require": list(_TEST_GLOBS)}}
        if tests and re.search(r"code|source|change|module|feature|function", t):
            return {
                "type": "path_required_with",
                "params": {"when": ["src/**", "lib/**", "app/**"], "require": list(_TEST_GLOBS)},
            }
    return None


def fam_content_required(c: Candidate) -> dict[str, Any] | None:
    t = _lower(c)
    if not re.search(r"\bnew\b|\bevery\b|\beach\b|\ball\b", t):
        return None
    if not re.search(
        r"\b(start|starts|begin|begins|open|opens|first line|header|heading|front ?matter|docstring|"
        r"copyright|licen[cs]e|spdx)\b",
        t,
    ):
        return None
    if not re.search(r"\b(file|files|module|modules|page|pages|script|scripts|source)\b|\.[a-z]{1,4}`", t):
        return None
    spans = _spans(c)
    regex = None
    spans = [x for x in spans if not re.match(r"^[\w.-]+(/[\w.-]*)+/?$", x)]  # paths say where, not what
    span = next((s for s in spans if "spdx" in s.lower() or "copyright" in s.lower() or "license" in s.lower()), None)
    if span:
        regex = re.escape(span)
    elif "spdx" in t:
        regex = r"SPDX-License-Identifier:"
    elif "docstring" in t:
        regex = r'^\s*[rRuU]?("""|\'\'\')'
    elif "front matter" in t or "frontmatter" in t:
        field_ = next((s for s in spans if s.endswith(":")), None)
        regex = rf"^\s*{re.escape(field_)}\s*\S" if field_ else r"^---\s*$"
    elif re.search(r"\bh1\b|single h1|# heading|top-level heading", t):
        regex = r"^# \S"
    elif spans:
        regex = re.escape(spans[0])
    if regex is None:
        return None
    globs: list[str] = []
    for s in spans:
        m = re.match(r"^\*?\.([a-z0-9]{1,5})$", s)
        if m:
            globs.append(f"**/*.{m.group(1)}")
    if not globs:
        if re.search(r"\b(page|pages|guide|guides|docs?)\b", t):
            globs = ["**/*.md", "**/*.mdx"]
        elif (re.search(r"\bpython\b|module|\.py\b", t) and "docstring" in t) or re.search(r"\bpython file", t):
            globs = ["**/*.py"]
        else:
            globs = _lang_globs(c.text, spans)
            if globs == ["**"]:
                globs = ["**/*"]
    if re.search(r"\.(rs)\b|rust", t):
        globs = ["**/*.rs"]
    if re.search(r"\bscripts?\b", t) and "scripts/" not in c.raw and globs == ["**/*"]:
        globs = ["**/*.py", "**/*.sh", "**/*.mjs", "**/*.js", "**/*.ts"]
    dirs = [d for d in _dirs_in_text(c)]
    if dirs:
        globs = _scoped(globs, dirs)
    first = 10
    if re.search(r"first line|on the first line|line 1", t):
        first = 1
    return {
        "type": "content_required_added",
        "params": {"regex": regex, "globs": globs, "scope": "new_files", "first_lines": first},
    }


_DEP_WORDS = (
    r"(dependenc(y|ies)|packages?|librar(y|ies)|third[- ]party (modules?|code|libraries)|modules?|deps|crates?|gems?|"
    r"npm packages?|pip packages?)"
)


def fam_dependency(c: Candidate) -> dict[str, Any] | None:
    t = _lower(c)
    if not re.search(_DEP_WORDS, t):
        return None
    if re.search(r"\bimport", t) and not re.search(r"\badd", t):
        return None
    if re.search(r"(managed|manage) (with|by)|lockfile|lock file", t) and not re.search(
        r"approval|without|new depend", t
    ):
        return None
    if re.search(r"\bmodules?\b", t) and not re.search(
        r"third[- ]party|external|go\.mod|dependenc|package|librar|"
        r"npm|pip|crate",
        t,
    ):
        return None
    add = re.search(r"\b(add|adding|added|introduce|introducing|install|installing|pull in|bring in|new)\b", t)
    gate = re.search(
        r"approv|ask (first|before)|without (asking|approval|discussion)|need(s)? (approval|sign[- ]off)|"
        r"permission|only after|check with|discuss|agreed|agreement|sign[- ]off|signed off",
        t,
    )
    pm_in_code = any(_PM_RE.search(s) for s in _spans(c)) or re.search(
        r"\b(pip|npm|yarn|pnpm|poetry|uv|conda) "
        r"(install|add|i)\b",
        t,
    )
    if pm_in_code and not gate and not re.search(r"new (runtime |third[- ]party )?(dependenc|package|librar)", t):
        return None
    banned = (
        _negated(t)
        or re.search(r"\b(zero|no) (runtime |new |third[- ]party )?dependenc", t)
        or re.search(r"standard library only|stdlib only|use the standard library", t)
    )
    only = re.search(r"\bonly\b.*\bmay be added\b|\bmay add\b", t)
    if not (add and (gate or banned or only)):
        return None
    allow = []
    if re.search(r"\b(only|except|may add|may be added|you may)\b", t):
        allow = [
            s
            for s in _spans(c)
            if re.match(r"^[A-Za-z0-9_.@/-]+$", s)
            and "/" not in s.strip("@")
            and not s.endswith((".txt", ".json", ".toml", ".mod", ".lock", ".yaml"))
        ]
    params: dict[str, Any] = {}
    manifests = [
        s
        for s in _spans(c)
        if re.search(
            r"(package\.json|pyproject\.toml|requirements[\w.-]*\.txt|go\.mod|"
            r"Cargo\.toml|setup\.cfg|Pipfile)$",
            s,
        )
    ]
    if manifests:
        params["manifests"] = [m if "/" in m else f"**/{m}" if m != m.split("/")[-1] else m for m in manifests]
    if re.search(r"\bgo\.mod\b", t) and "manifests" not in params:
        params["manifests"] = ["go.mod"]
    if allow:
        params["allow"] = allow
    return {"type": "dependency_unchanged", "params": params}


# Package managers and the commands that count as using them.
_PMS: dict[str, dict[str, Any]] = {
    "npm": {
        "forbid": [
            r"^npm(\s+(?!(-v|--version|-h|--help|help|view|v|info|show|ls|list|outdated|whoami|config get)"
            r"\b)\S+|\s*$)"
        ],
        "eco": "js",
    },
    "npx": {"forbid": [r"^npx\b"], "eco": "js"},
    "yarn": {"forbid": [r"^yarn(\s+(?!(-v|--version|--help|help|info|why|list)\b)\S+|\s*$)"], "eco": "js"},
    "pnpm": {
        "forbid": [r"^pnpm(\s+(?!(-v|--version|--help|help|view|info|why|ls|list|outdated)\b)\S+|\s*$)"],
        "eco": "js",
    },
    "bun": {"forbid": [r"^bun\s+(add|install|i|remove|rm|update|pm|link)\b", r"^bunx\b"], "eco": "js"},
    "pip": {
        "forbid": [r"^pip3?\s+(install|uninstall|download)\b", r"^python3?(\.\d+)? -m pip\s+(install|uninstall)\b"],
        "eco": "py",
    },
    "pip3": {"forbid": [r"^pip3?\s+(install|uninstall|download)\b"], "eco": "py"},
    "poetry": {"forbid": [r"^poetry\s+(add|install|remove|update|lock)\b"], "eco": "py"},
    "pipenv": {"forbid": [r"^pipenv\b"], "eco": "py"},
    "conda": {"forbid": [r"^conda\s+(install|create|update|env)\b"], "eco": "py"},
    "mamba": {"forbid": [r"^(micro)?mamba\s+(install|create|update)\b"], "eco": "py"},
    "uv": {"forbid": [r"^uv\s+(add|remove|pip|sync|lock)\b"], "eco": "py"},
    "easy_install": {"forbid": [r"^easy_install\b"], "eco": "py"},
}
_PREFERRED = {
    "npm": r"^npm\b",
    "yarn": r"^yarn\b",
    "pnpm": r"^pnpm\b",
    "bun": r"^bunx?\b",
    "pip": r"^pip3?\b",
    "poetry": r"^poetry\b",
    "pipenv": r"^pipenv\b",
    "uv": r"^uvx?\b",
    "conda": r"^conda\b",
}
_LOCKFILES = {
    "js": ["package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock", "npm-shrinkwrap.json"],
    "py": ["poetry.lock", "uv.lock", "Pipfile.lock"],
}
_OWN_LOCK = {
    "npm": "package-lock.json",
    "yarn": "yarn.lock",
    "pnpm": "pnpm-lock.yaml",
    "bun": "bun.lock",
    "poetry": "poetry.lock",
    "uv": "uv.lock",
    "pipenv": "Pipfile.lock",
}
_PM_RE = re.compile(
    r"\b(npm|npx|yarn|pnpm|bunx?|pip3?|poetry|pipenv|conda|mamba|uv|easy_install)\b(?![-.](lock|workspace|yaml|json|toml))",
    re.IGNORECASE,
)


def _segment_pattern(cmd: str) -> str:
    words = cmd.strip().split()
    if not words:
        return ""
    return "^" + r"\s+".join(re.escape(w) for w in words) + r"\b"


def fam_command_forbidden(c: Candidate) -> dict[str, Any] | None:
    t = _lower(c)
    raw = c.raw
    pm_ban = re.search(
        rf"\b{NEG}\b[^.;]{{0,15}}\b(run|use|call|invoke)\b[^.;]{{0,12}}\b(npm|npx|yarn|pnpm|pip3?|poetry|bunx?|conda|uv)\b",
        t,
    )
    lock_edit = any(re.search(r"lock(b)?$|\.lock\b|-lock\.", s) for s in _spans(c)) and re.search(
        rf"\b{_EDIT_VERB}\b", t
    )
    if not pm_ban and (re.search(r"by hand|manually|hand-edit|hand edit", t) or lock_edit):
        return None  # "bun.lock MUST NOT be edited by hand" is about a path
    mentions = [m.group(1).lower() for m in _PM_RE.finditer(raw)]
    if not mentions and not re.search(rf"\b{NEG}\b.*`[^`]+`", raw, re.IGNORECASE):
        return None
    if mentions:
        positive: list[str] = []
        negative: list[str] = []
        splitter = (
            r"[;.]\s+|,\s+(?=(?:so|but|and\s+(?:never|not|do not|don't)|never|not|don|do not)\b)|\bso\b|"
            r"\binstead of\b|\brather than\b|\bover\b"
        )
        for clause in re.split(splitter, raw):
            cl = clause.lower()
            names = [m.group(1).lower() for m in _PM_RE.finditer(clause)]
            if not names:
                continue
            if _negated(cl) or re.search(r"creates? conflicting|conflict", cl):
                negative += names
            else:
                positive += names
        m = re.search(r"\b(?:instead of|rather than|over)\b(.*)", raw, re.IGNORECASE)
        if m:
            negative += [n.group(1).lower() for n in _PM_RE.finditer(m.group(1))]
            positive = [p for p in positive if p not in negative]
        managed = re.search(
            r"managed with|managed by|for (all|every|each)? ?(package|dependenc)|use \S+ for|"
            r"\bonly\b|for everything|for installs|for dependency",
            t,
        )
        positive = [p for p in dict.fromkeys(positive) if p not in ("npx",)]
        negative = list(dict.fromkeys(negative))
        if not negative and positive and not managed and not re.search(r"^\W*use\b", t):
            return None
        if not negative and positive:
            eco = _PMS.get(positive[0], {}).get("eco")
            skip = {"pip3", "easy_install", "mamba"}
            if not re.search(r"\bevery\b|\ball\b|\beverything\b|\bany\b", t):
                skip.add("npx")
            negative = [pm for pm, info in _PMS.items() if info["eco"] == eco and pm not in positive and pm not in skip]
            if eco == "py" and positive[0] == "pip":
                negative = [pm for pm in negative if pm != "uv"]
        if not negative:
            return None
        patterns: list[str] = []
        for pm in negative:
            for p in _PMS.get(pm, {}).get("forbid", []):
                if positive and positive[0] == "uv" and pm == "pip":
                    pass
                patterns.append(p)
        if "pip" in negative or "pip3" in negative:
            patterns.append(r"^python3?(\.\d+)? -m pip\s+(install|uninstall)\b")
        params: dict[str, Any] = {"patterns": list(dict.fromkeys(patterns))}
        if positive:
            pref = positive[0]
            params["preferred"] = pref
            if pref in _PREFERRED:
                params["preferred_patterns"] = [_PREFERRED[pref]]
            eco = _PMS.get(pref, {}).get("eco")
            if eco and pref in _OWN_LOCK:
                params["manual_edit_paths"] = [lf for lf in _LOCKFILES[eco] if lf != _OWN_LOCK[pref]]
        return {"type": "command_forbidden", "params": params}
    # "Do not run `make deploy`", "Never call rustc directly".
    verb = re.search(rf"\b{NEG}\b[^.;]{{0,30}}\b(run|use|call|invoke|execute)\b", t)
    if verb:
        spans = _spans(c) or [w for w in re.findall(r"\b[a-z][\w.-]+\b", t) if w in _KNOWN_CLIS]
        cmds = [
            s
            for s in spans
            if re.match(r"^[a-z][\w.-]*(\s+[\w./:=-]+)*$", s)
            and not s.startswith(("git commit", "git push"))
            and "/" not in s.split()[0]
            and ((verb.group(1) in ("run", "execute", "invoke") and " " in s) or s.split()[0] in _KNOWN_CLIS)
        ]
        if cmds:
            return {"type": "command_forbidden", "params": {"patterns": [_segment_pattern(x) for x in cmds]}}
    return None


_KNOWN_CLIS = {
    "rustc",
    "gcc",
    "g++",
    "clang",
    "cc",
    "python",
    "python3",
    "node",
    "deno",
    "tsc",
    "docker",
    "kubectl",
    "terraform",
    "helm",
    "make",
    "curl",
    "wget",
    "sudo",
    "rm",
    "chmod",
    "ssh",
    "scp",
    "brew",
    "apt",
    "apt-get",
    "yum",
    "dnf",
    "gofmt",
    "go",
    "cargo",
    "rustup",
    "black",
    "isort",
    "autopep8",
    "prettier",
    "eslint",
    "jest",
    "mocha",
    "tox",
    "pre-commit",
    "alembic",
    "flask",
    "django-admin",
    "psql",
    "mysql",
    "sqlite3",
    "redis-cli",
    "aws",
    "gcloud",
    "az",
    "firebase",
    "vercel",
    "netlify",
    "heroku",
    "gh",
    "hub",
    "npx",
    "bunx",
    "uvx",
    "pipx",
    "conda",
    "pip",
    "pip3",
}


_TEST_CMD = (
    r"\b(pytest|py\.test|vitest|jest|mocha|go test|cargo test|tox|nox|unittest|bun test|deno test|"
    r"(npm|pnpm|yarn|bun)( run)? test|make (test|check)|manage\.py test|phpunit|rspec)\b"
)


def fam_command_required(c: Candidate) -> dict[str, Any] | None:
    t = _lower(c)
    if _negated(t) and not re.search(r"\b(before|after|until)\b", t):
        return None
    if not re.search(r"\b(run|execute|make sure|ensure|check that|must pass|should pass|pass(es)?)\b", t):
        return None
    if not re.search(
        r"\b(before|after|when|once|whenever|until|every time|at the end|pass|passes|green|done|finish)", t
    ):
        return None
    spans = [s for s in _spans(c) if re.match(r"^[a-z][\w.:-]*(\s+[^\s`]+)*$", s) and not s.endswith("/")]
    spans += [m.group(1) for m in re.finditer(r'"([a-z][\w.-]*(?: [\w./:=-]+)*)"', c.raw)]
    pattern = None
    if spans:
        pattern = "|".join(_core_pattern(s) for s in spans[:3])
    elif re.search(r"\btests?\b|test suite", t):
        pattern = _TEST_CMD
    elif re.search(r"\blint", t):
        pattern = r"\b(ruff|eslint|flake8|pylint|golangci-lint|clippy|(npm|pnpm|yarn|bun)( run)? lint|make lint)\b"
    elif re.search(r"type ?check|mypy|tsc|pyright", t):
        pattern = r"\b(mypy|pyright|tsc|(npm|pnpm|yarn|bun)( run)? typecheck|make typecheck)\b"
    if not pattern:
        return None
    params: dict[str, Any] = {"pattern": pattern}
    edit_globs = _edit_globs(c)
    if edit_globs:
        params["edit_globs"] = edit_globs
    return {"type": "command_required", "params": params}


def _core_pattern(cmd: str) -> str:
    words = cmd.split()
    wrappers = {
        "uv": {"run"},
        "poetry": {"run"},
        "pipenv": {"run"},
        "npx": set(),
        "pnpm": {"exec", "dlx"},
        "bunx": set(),
        "uvx": set(),
    }
    while words and words[0] in wrappers:
        sub = wrappers[words[0]]
        if sub and len(words) > 1 and words[1] in sub:
            words = words[2:]
        elif not sub:
            words = words[1:]
        else:
            break
    if len(words) >= 3 and words[0].startswith("python") and words[1] == "-m":
        words = words[2:]
    if words and words[0] in ("npm", "pnpm", "yarn", "bun") and len(words) >= 2:
        script = words[2] if words[1] == "run" and len(words) > 2 else words[1]
        return rf"^{words[0]}\s+(run\s+)?{re.escape(script)}\b"
    # Every word counts ("cargo clippy --all-targets -- -D warnings" is not satisfied by "cargo clippy").
    core = [w for w in words if w not in (".", "./...", "./")] or words[:1]
    body = r"\s+".join(re.escape(w) for w in core)
    return "^" + body + (r"\b" if re.search(r"\w$", core[-1]) else "")


def _edit_globs(c: Candidate) -> list[str]:
    t = _lower(c)
    globs: list[str] = []
    for d in _dirs_in_text(c):
        globs.append(d.rstrip("/") + "/**")
    for m in re.finditer(r"`([^`]*\.[a-z]{1,4})`\s+files?|any\s+`?\*?\.([a-z]{1,4})`?\s+file", c.raw):
        ext = (m.group(1) or m.group(2)).lstrip("*").lstrip(".")
        if "/" not in ext:
            globs.append(f"**/*.{ext.split('.')[-1]}")
    if not globs:
        if re.search(r"python (code|files?)|\.py\b", t):
            globs = ["**/*.py"]
        elif re.search(r"\btest files?\b", t):
            globs = ["**/*.test.ts", "**/*.test.tsx", "**/*.spec.ts", "**/test_*.py", "tests/**"]
        elif re.search(r"docs? change|documentation", t):
            globs = ["docs/**", "**/*.md", "**/*.mdx"]
        elif re.search(r"\bgo (code|files?)\b|\.go\b", t):
            globs = ["**/*.go"]
    return globs


_EDIT_VERB = (
    r"(edit|edited|editing|modify|modified|modifying|change|changed|changing|touch|touched|write|writing|"
    r"written|alter|altered|hand-edit|hand edit|update|updated|rewrite|rewritten|delete|remove)"
)


def fam_path_forbidden(c: Candidate) -> dict[str, Any] | None:
    t = _lower(c)
    paths = _path_spans(c)
    if not paths and re.search(r"\bmigrations?\b", t) and re.search(rf"\b{_EDIT_VERB}\b", t) and _negated(t):
        existing = bool(re.search(r"\b(existing|applied|merged|already|old|previous)\b", t))
        return {
            "type": "path_forbidden",
            "params": {"globs": ["**/migrations/**"], "existing_only": existing}
            if existing
            else {"globs": ["**/migrations/**"]},
        }
    if not paths:
        return None
    # "Do not write `export default` in `src/`" forbids code, not the directory.
    code_objects = [x for x in _spans(c) if x not in paths and not re.match(r"^[\w.-]+(/[\w.-]*)*/?$", x)]
    if code_objects and re.search(r"\b(write|use|add|call|import|leave|put)\b", t):
        return None
    generated = re.search(
        r"\b(generated|regenerated|build output|produced by|vendored|immutable|read-only|"
        r"auto-?generated|do not edit|don't edit)\b",
        t,
    )
    edit = re.search(rf"\b{_EDIT_VERB}\b", t)
    if not ((_negated(t) and edit) or (generated and (_negated(t) or "never" in t))):
        return None
    if re.search(r"\b(when|whenever|if) you (change|edit)|\bneeds?\b|\bmust come\b", t) and len(paths) >= 2:
        return None
    existing = bool(
        re.search(
            r"\b(existing|applied|merged|already|once (merged|applied|committed|released)|"
            r"previous|old)\b",
            t,
        )
    )
    globs = [_glob(p) for p in paths if not re.match(r"^(go|npm|pnpm|uv|python|make|cargo)\b", p)]
    globs = [g for g in globs if not g.endswith((".py/**",)) and g not in ("**",)]
    if re.search(r"run `|regenerat|produced by|instead", t) and len(globs) > 1:
        # "Never edit `internal/gen/`; it is produced by `tools/gen.py`": the second path is the generator.
        generator = [
            g for g in globs if re.search(r"\.(py|sh|mjs|js|ts|go)$", g) or g.startswith(("tools/", "scripts/"))
        ]
        globs = [g for g in globs if g not in generator] or globs
    if not globs:
        return None
    params: dict[str, Any] = {"globs": globs}
    if existing:
        params["existing_only"] = True
    return {"type": "path_forbidden", "params": params}


# Known code constructs: (trigger regex on the rule text, added-line regex, language).
_CONSTRUCTS: list[tuple[str, str, str]] = [
    (r"\bany\b", r"(:\s*any\b|\bas\s+any\b|<any>|\bany\[\]|Array<any>|\(any\)|=\s*any\b|,\s*any\b|<any,|\bany>)", "ts"),
    (r"console\.log", r"\bconsole\.log\s*\(", "js"),
    (r"console\.\*|`console`|any console", r"\bconsole\.\w+\s*\(", "js"),
    (r"print\(\)|`print`|print statements?|\bprint\b", r"(^|[^\w.])print\s*\(", "py"),
    (r"type:\s*ignore", r"#\s*type:\s*ignore", "py"),
    (r"noqa", r"#\s*noqa\b", "py"),
    (r"eslint-disable", r"eslint-disable", "js"),
    (r"@ts-ignore|@ts-nocheck|@ts-expect-error", "@ts-directives", "ts"),
    (r"\btodo\b|\bfixme\b|\bxxx\b|\bhack\b", "markers", "*"),
    (r"wildcard imports?|import \*", r"^\s*from\s+\S+\s+import\s+\*|import\s+\*\s+as\b", "py"),
    (
        r"test\.skip|it\.skip|describe\.skip|\.skip\b|xit\b",
        r"\b(it|test|describe)\.skip\s*\(|\bx(it|describe)\s*\(",
        "ts",
    ),
    (r"pytest\.mark\.skip|@skip", r"@pytest\.mark\.skip|@unittest\.skip", "py"),
    (r"dangerouslysetinnerhtml", r"\bdangerouslySetInnerHTML\b", "ts"),
    (r"document\.write|innerhtml", r"document\.write\s*\(|\.innerHTML\s*=", "js"),
    (r"\.unwrap\(\)|unwrap\b", r"\.unwrap\s*\(\s*\)", "rs"),
    (r"\bunsafe\b", r"\bunsafe\s*(\{|fn\b|impl\b|trait\b)", "rs"),
    (r"fmt\.print", r"\bfmt\.Print(ln|f)?\s*\(", "go"),
    (r"\bpanic\(", r"\bpanic\s*\(", "go"),
    (r"\bvar\b", r"(^|[^\w.])var\s+\w", "js"),
    (r"export default|default exports?", r"\bexport\s+default\b", "ts"),
    (r"\benums?\b", r"(^|\s)(const\s+)?enum\s+\w+", "ts"),
    (r"non-null assertion", r"\w!\.|\w!\)|\w!;|\w!\s*$", "ts"),
    (r"\bassert\b statements?|bare assert", r"^\s*assert\b", "py"),
    (r"\beval\(", r"\beval\s*\(", "*"),
    (r"breakpoint\(\)|pdb", r"\bbreakpoint\s*\(|\bpdb\.set_trace\s*\(", "py"),
    (r"debugger", r"\bdebugger\s*;?", "js"),
    (r"bare except", r"^\s*except\s*:", "py"),
    (r"\bdatetime\.now\(\)|datetime\.utcnow", r"\bdatetime\.(utc)?now\s*\(", "py"),
    (r"\bfetch\(\)|`fetch`", r"\bfetch\s*\(", "js"),
    (r"\bsetTimeout\b", r"\bsetTimeout\s*\(", "js"),
    (r"\brequire\(\)|`require`", r"\brequire\s*\(", "js"),
    (r"\bos\.system\b", r"\bos\.system\s*\(", "py"),
    (r"\bsubprocess\b.*shell=true|shell=True", r"shell\s*=\s*True", "py"),
]


def fam_content_forbidden(c: Candidate) -> dict[str, Any] | None:
    t = _lower(c)
    prefer = re.search(r"\bprefer\b.*\bover\b(.*)|\binstead of\b(.*)|\brather than\b(.*)", t)
    if not (_negated(t) or prefer or re.search(r"has no place|not welcome|(is|are) banned", t)):
        return None
    if re.search(r"\b(commit|push|depend|package|install|migration)", t) and not _spans(c):
        return None
    if prefer and not _negated(t):
        # "Prefer named exports over default exports": the forbidden thing is what comes after "over".
        tail = next(g for g in prefer.groups() if g is not None)
        c = Candidate(
            text=tail,
            raw=tail,
            line_start=c.line_start,
            line_end=c.line_end,
            kind=c.kind,
            headings=c.headings,
            code_spans=[s for s in c.code_spans if s.lower() in tail],
        )
        t = tail
    # Code named in the positive part ("...; use tracing", "use logx instead") is not forbidden.
    negative_part = re.split(r"[;.:]\s*(?:use|prefer|instead)\b|,\s*use\b|\binstead\b", c.raw, maxsplit=1)[0]
    spans = [x for x in _spans(c) if x in negative_part] or _spans(c)
    quoted_words = re.findall(r'"([^"\s]{2,30})"', c.raw)
    regex = None
    lang = "*"
    for trigger, rx, lng in _CONSTRUCTS:
        hay = t + " " + " ".join(s.lower() for s in spans)
        if re.search(trigger, hay, re.IGNORECASE):
            if trigger == r"\bany\b" and not (
                re.search(r"`any`|\bany\b type|type `?any|\bany\b\W*(type|;|\.|$)", hay) or "typescript" in hay
            ):
                continue
            if trigger.startswith(r"\bvar\b") and "`var`" not in hay:
                continue
            if trigger.startswith(r"print") and not re.search(r"print", " ".join(spans).lower() + t):
                continue
            regex, lang = rx, lng
            if trigger == r"\bany\b" and re.search(r"console", hay):
                continue
            if rx == "@ts-directives":
                names = sorted(set(re.findall(r"@ts-(ignore|nocheck|expect-error)", hay)))
                regex = r"@ts-(" + "|".join(names) + r")\b"
            elif rx == "markers":
                names = [m.upper() for m in ("todo", "fixme", "xxx", "hack") if re.search(rf"\b{m}\b", hay)]
                regex = r"\b(" + "|".join(names) + r")\b"
            break
    if regex is None:
        code = [
            s
            for s in spans
            if not re.search(r"/$", s)
            and len(s) <= 40
            and not re.match(r"^[\w-]+/[\w/-]*$", s)
            and not re.match(r"^(git|npm|pnpm|yarn|pip|uv|poetry|make|cargo|go|docker|python3?)\b", s)
        ]
        if not code and quoted_words:
            regex = r"(?i)\b(" + "|".join(re.escape(w) for w in quoted_words) + r")\b"
            lang = "*"
        if regex is None and (
            not code
            or not (
                prefer
                or re.search(
                    r"\b(use|uses|add|call|calls|write|leave|import|commit|put|introduce|"
                    r"silence|skip|avoid|never|no|place|assign)\b",
                    t,
                )
            )
        ):
            return None
        if regex is None:
            regex = "|".join(_code_regex(x) for x in code)
            lang = "*"
    globs = list(_EXT_LANG.get(lang, ["**"])) if lang != "*" else _lang_globs(c.text, spans)
    if lang == "js" and re.search(r"typescript|\.ts\b|tsx", t):
        globs = ["**/*.ts", "**/*.tsx"]
    dirs = _dirs_in_text(c)
    if dirs:
        globs = _scoped(globs, dirs)
    return {"type": "content_forbidden_added", "params": {"regex": regex, "globs": globs}}


def _code_regex(code: str) -> str:
    """A regex for a code fragment named in a rule: `foo()` matches calls, `...` is a wildcard, words get bounds."""
    text = code.strip()
    if text.endswith("()"):
        return re.escape(text[:-2]) + r"\s*\("
    parts = [re.escape(p) for p in re.split(r"\.\.\.|…", text)]
    rx = r".*?".join(parts)
    rx = re.sub(r"(\\ )+", r"\\s*", rx)
    if re.match(r"^\w", text):
        rx = r"\b" + rx
    if re.search(r"\w$", text):
        rx += r"\b"
    return rx


FAMILIES: list[Family] = [
    fam_no_push,
    fam_no_commit,
    fam_commit_message,
    fam_final_message,
    fam_file_naming,
    fam_path_required_with,
    fam_content_required,
    fam_dependency,
    fam_command_forbidden,
    fam_command_required,
    fam_path_forbidden,
    fam_content_forbidden,
]

# --------------------------------------------------------------------------------------------- rule-ness

_NOT_RULE_START = re.compile(r"^(`[^`]+`|[\w./-]+/)\s*(holds?|contains?|is|are|has|have|—|-|:|\()", re.IGNORECASE)
_HEADING_RULES = re.compile(
    r"\b(rules?|do|don['’]?t|dos|donts|never|always|must|conventions?|guidelines?|policy|"
    r"policies|requirements?|constraints?|guardrails?|expectations?|standards?|checklist)\b",
    re.IGNORECASE,
)


def is_rule(c: Candidate) -> bool:
    text = c.text.strip()
    if len(text) < 6:
        return False
    if text.endswith(":") and len(text) < 60:
        return False
    if _NOT_RULE_START.match(text) and not re.search(
        r"\b(never|do not|don't|must|should|always)\b", text, re.IGNORECASE
    ):
        return False
    if re.match(r"^(see|read|for more|more in|details in|this (project|repo|repository|file))\b", text, re.IGNORECASE):
        return False
    if re.search(r"(are|is) to be interpreted as described in|rfc ?2119|bcp ?14", text, re.IGNORECASE):
        return False
    if is_directive(text):
        return True
    if re.match(r"^no\s+\S", text, re.IGNORECASE):
        return True
    if c.kind == "list" and c.headings and _HEADING_RULES.search(c.headings[-1]):
        return bool(
            re.search(r"\b(commit|push|edit|use|run|add|name|test|depend|import|log)\w*\b", text, re.IGNORECASE)
        )
    return False


def classify(c: Candidate) -> tuple[str, dict[str, Any] | None, str | None]:
    """(status, checker, reason) for one rule candidate."""
    # A "Don't" heading turns a bare bullet into a prohibition.
    heading = c.headings[-1].lower() if c.headings else ""
    probe = c
    if re.search(r"\b(don['’]?t|never|avoid|forbidden|not allowed)\b", heading) and not _negated(c.text):
        probe = Candidate(
            text="Never " + c.text[0].lower() + c.text[1:],
            raw="Never " + c.raw,
            line_start=c.line_start,
            line_end=c.line_end,
            kind=c.kind,
            headings=c.headings,
            code_spans=c.code_spans,
        )
    for family in FAMILIES:
        checker = family(probe)
        if checker is not None:
            return "active", checker, None
    if _TASTE_RE.search(c.text):
        return "uncheckable", None, "needs judgement; no deterministic check"
    return "uncheckable", None, "no deterministic pattern matched; review or rephrase"


_GLOB_KEYS = ("globs", "when", "require", "edit_globs")


def _base_dir(f: InstructionFile) -> str:
    """The directory a nested instruction file speaks for ("" at the root and for path-scoped rule files)."""
    if (
        f.kind in ("agents_md", "claude_md", "gemini_md", "claude_local_md", "claude_import")
        and len(f.scope_paths) == 1
    ):
        scope = f.scope_paths[0]
        if scope.endswith("/**") and scope != "**":
            return scope[:-3]
    return ""


def _rebase(glob: str, base: str, top_dirs: set[str] | None) -> str:
    if base:
        if glob.startswith(base + "/"):
            return glob
        if glob.startswith("**/"):
            return f"{base}/{glob}"
        if "/" not in glob:
            return f"{base}/**/{glob}"
        return f"{base}/{glob}"
    if top_dirs is not None and "/" in glob and not glob.startswith(("**", "*")):
        first = glob.split("/", 1)[0]
        if first not in top_dirs:
            return f"**/{glob}"  # "internal/pb/" in a monorepo root file means any service's internal/pb
    return glob


def extract(files: Iterable[InstructionFile], root: Any = None) -> list[Extracted]:
    from pathlib import Path

    from obey_cli.discover import list_files

    top_dirs: set[str] | None = None
    if root is not None:
        listed = list_files(Path(root))
        top_dirs = {p.split("/", 1)[0] for p in listed if "/" in p}
    out: list[Extracted] = []
    for f in files:
        base = _base_dir(f)
        for cand in f.parsed.candidates:
            if not is_rule(cand):
                continue
            status, checker, reason = classify(cand)
            if checker is not None:
                params = checker["params"]
                for key in _GLOB_KEYS:
                    if isinstance(params.get(key), list):
                        params[key] = list(dict.fromkeys(_rebase(g, base, top_dirs) for g in params[key]))
            out.append(Extracted(candidate=cand, file=f, status=status, checker=checker, reason=reason))
    return out


# --------------------------------------------------------------------------------------------- optional LLM

LLM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["rules"],
    "properties": {
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["index", "checkable"],
                "properties": {
                    "index": {"type": "integer", "minimum": 0},
                    "checkable": {"type": "boolean"},
                    "type": {
                        "enum": [
                            "command_forbidden",
                            "command_required",
                            "path_forbidden",
                            "path_required_with",
                            "dependency_unchanged",
                            "content_forbidden_added",
                            "content_required_added",
                            "commit_message",
                            "no_commit",
                            "no_push",
                            "file_naming",
                            "final_message",
                        ]
                    },
                    "params": {"type": "object"},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}

LLM_SYSTEM = (
    "You map coding-agent instructions to deterministic checkers. For each numbered instruction decide whether a "
    "program could check it from the agent's shell commands, file edits, git diff, commits and final message. If it "
    "can, give the checker type and params exactly as documented; otherwise checkable=false with a short reason. "
    "Checker types and params: command_forbidden{patterns:[regex on one shell command]}, command_required{pattern, "
    "edit_globs?}, path_forbidden{globs, existing_only?}, path_required_with{when:[glob], require:[glob]}, "
    "dependency_unchanged{allow?:[name]}, content_forbidden_added{regex, globs}, content_required_added{regex, globs, "
    "scope:'new_files'}, commit_message{regex}, no_commit{}, no_push{}, file_naming{globs, pattern}, "
    "final_message{required|forbidden: regex}. Reply with one JSON object only, exactly in this shape: "
    '{"rules": [{"index": 0, "checkable": true, "type": "no_push", "params": {}}, '
    '{"index": 1, "checkable": false, "reason": "needs judgement"}]}'
)


def _normalize_llm(data: Any) -> dict[str, Any]:
    rows = data if isinstance(data, list) else (data.get("rules") if isinstance(data, dict) else None)
    if not isinstance(rows, list):
        return data if isinstance(data, dict) else {}
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        checker: dict[str, Any] = row["checker"] if isinstance(row.get("checker"), dict) else {}
        item: dict[str, Any] = {"index": row.get("index", row.get("id")), "checkable": bool(row.get("checkable"))}
        kind = row.get("type") or checker.get("type")
        if kind:
            item["type"] = kind
            item["params"] = row.get("params") or checker.get("params") or {}
        if row.get("reason"):
            item["reason"] = str(row["reason"])
        out.append(item)
    return {"rules": out}


LLM_TYPES_SYSTEM = (
    "You classify coding-agent instructions. For each numbered instruction say which deterministic checker type could "
    "verify it from the agent's shell commands, file edits, git diff, commits and final message, or null when it needs "
    "human judgement. Types: command_forbidden, command_required, path_forbidden, path_required_with, "
    "dependency_unchanged, content_forbidden_added, content_required_added, commit_message, no_commit, no_push, "
    'file_naming, final_message. Reply with one JSON object only: {"rules": [{"index": 0, "checkable": true, '
    '"type": "no_push"}, {"index": 1, "checkable": false}]}'
)


def llm_classify(
    texts: Sequence[str], config: Any, ledger: Any = None, run_id: str = "extract-llm", types_only: bool = False
) -> list[dict[str, Any] | None]:
    """One LLM call for a batch of rule texts; returns a checker proposal (or None) per text.

    `types_only` asks for the checker type alone, which is enough for counting and much cheaper.
    """
    from obey_cli.llm import chat_json

    out: list[dict[str, Any] | None] = [None] * len(texts)
    if not texts:
        return out
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(texts))
    data = chat_json(
        config,
        LLM_TYPES_SYSTEM if types_only else LLM_SYSTEM,
        numbered,
        LLM_SCHEMA,
        ledger=ledger,
        run_id=run_id,
        max_tokens=min(12000, 1200 + (40 if types_only else 160) * len(texts)),
        normalize=_normalize_llm,
    )
    for row in data.get("rules", []):
        idx = row.get("index")
        if isinstance(idx, int) and 0 <= idx < len(texts) and row.get("checkable") and row.get("type"):
            out[idx] = {"type": row["type"], "params": row.get("params") or {}}
    return out


def llm_propose(items: Sequence[Extracted], config: Any, ledger: Any = None) -> list[Extracted]:
    """Ask an LLM about rules the patterns left uncheckable. Results are `proposed`, never `active`."""
    from obey_cli.config import validate

    pending = [x for x in items if x.status == "uncheckable"]
    if not pending:
        return []
    proposals: list[Extracted] = []
    for idx, checker_ in enumerate(llm_classify([x.candidate.text for x in pending], config, ledger)):
        if checker_ is None:
            continue
        base = pending[idx]
        row = checker_
        checker = {"type": row["type"], "params": row["params"]}
        candidate = Extracted(
            candidate=base.candidate,
            file=base.file,
            status="proposed",
            checker=checker,
            origin="llm",
            reason="proposed by --llm; review before setting status: active",
        )
        rule = candidate.as_rule()
        if validate({"version": 1, "rules": [rule]}):
            continue
        try:
            for key in ("patterns",):
                for rx in checker["params"].get(key, []):
                    re.compile(rx)
            for key in ("pattern", "regex", "required", "forbidden"):
                if key in checker["params"]:
                    re.compile(checker["params"][key])
        except re.error:
            continue
        proposals.append(candidate)
    return proposals
