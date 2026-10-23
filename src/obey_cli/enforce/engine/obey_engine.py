"""obey rule engine: one implementation of every rule check, shared by the checkers and the generated hooks.

Standard library only, Python 3.9+. Vendored into a repository's .obey/hooks/ by `obey enforce`, so that what a
hook blocks is exactly what `obey run` measures. https://github.com/B0yko/obey
"""

from __future__ import annotations

import json
import re
import shlex
from typing import Any, Dict, List, Optional, Tuple

STOP_TYPES = {"command_required", "path_required_with", "final_message", "content_required_added"}
DEFAULT_MANIFESTS = [
    "**/package.json",
    "**/pyproject.toml",
    "**/requirements*.txt",
    "**/go.mod",
    "**/Cargo.toml",
    "**/setup.cfg",
    "**/Pipfile",
]

# --------------------------------------------------------------------------------------------- globs

_GLOB_CACHE: Dict[str, "re.Pattern[str]"] = {}


def _glob_regex(glob: str) -> "re.Pattern[str]":
    cached = _GLOB_CACHE.get(glob)
    if cached is not None:
        return cached
    g = glob.strip().lstrip("/")
    if g.startswith("./"):
        g = g[2:]
    if "/" not in g.rstrip("/"):
        g = "**/" + g  # a bare pattern matches the basename anywhere
    if g.endswith("/"):
        g += "**"
    out = ""
    i = 0
    while i < len(g):
        if g.startswith("**/", i):
            out += "(?:[^/]+/)*"
            i += 3
        elif g.startswith("**", i):
            out += ".*"
            i += 2
        elif g[i] == "*":
            out += "[^/]*"
            i += 1
        elif g[i] == "?":
            out += "[^/]"
            i += 1
        elif g[i] == "[":
            j = g.find("]", i + 1)
            if j == -1:
                out += re.escape(g[i])
                i += 1
            else:
                out += "[" + g[i + 1 : j].replace("!", "^", 1) + "]"
                i = j + 1
        else:
            out += re.escape(g[i])
            i += 1
    pattern = re.compile("^" + out + "$")
    _GLOB_CACHE[glob] = pattern
    return pattern


def glob_match(globs: List[str], path: str) -> bool:
    p = path.strip().lstrip("/")
    if p.startswith("./"):
        p = p[2:]
    return any(_glob_regex(g).match(p) or (g.rstrip("/").endswith("/**") and p == g.rstrip("/")[:-3]) for g in globs)


# --------------------------------------------------------------------------------------------- shell

_SEPARATORS = ("&&", "||", ";", "|", "&", "\n")
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SIMPLE_WRAPPERS = {"sudo", "time", "nohup", "exec", "command", "builtin", "nice", "doas", "stdbuf", "caffeinate"}
_SHELLS = {
    "bash",
    "sh",
    "zsh",
    "dash",
    "ksh",
    "/bin/bash",
    "/bin/sh",
    "/usr/bin/bash",
    "/usr/bin/sh",
    "/bin/zsh",
    "/usr/bin/env bash",
    "fish",
}
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def _split_top(cmd: str) -> List[str]:
    """Split a command line on unquoted separators; heredoc bodies stay attached to their command."""
    parts: List[str] = []
    buf = ""
    i = 0
    quote = ""
    depth = 0
    n = len(cmd)
    while i < n:
        c = cmd[i]
        if quote:
            buf += c
            if c == "\\" and quote == '"' and i + 1 < n:
                buf += cmd[i + 1]
                i += 2
                continue
            if c == quote:
                quote = ""
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            buf += c + cmd[i + 1]
            i += 2
            continue
        if c in ("'", '"'):
            quote = c
            buf += c
            i += 1
            continue
        if cmd.startswith("$(", i):
            depth += 1
            buf += "$("
            i += 2
            continue
        if c == "(" and depth:
            depth += 1
        if c == ")" and depth:
            depth -= 1
            buf += c
            i += 1
            continue
        if c == "#" and (not buf or buf[-1] in " \t\n") and not depth:
            j = cmd.find("\n", i)
            i = n if j == -1 else j
            continue
        if depth == 0:
            heredoc = _HEREDOC_RE.match(cmd, i) if c == "<" else None
            if heredoc:
                # Keep "cmd <<EOF" and its body together; the body ends at a line equal to the delimiter.
                delim = heredoc.group(2)
                line_end = cmd.find("\n", heredoc.end())
                rest_of_line = cmd[heredoc.end() : line_end if line_end != -1 else n]
                buf += cmd[i : heredoc.end()] + rest_of_line
                if line_end == -1:
                    i = n
                    continue
                body_end = re.search(r"(?m)^\s*" + re.escape(delim) + r"\s*$", cmd[line_end + 1 :])
                if body_end:
                    body = cmd[line_end + 1 : line_end + 1 + body_end.start()]
                    buf += "\n" + body + delim
                    i = line_end + 1 + body_end.end()
                else:
                    buf += cmd[line_end:]
                    i = n
                continue
            sep = next((s for s in _SEPARATORS if cmd.startswith(s, i)), None)
            if sep and not (sep == "&" and (cmd.startswith("&>", i) or (i > 0 and cmd[i - 1] in "<>"))):
                if sep == "|" and cmd.startswith("|&", i):
                    sep = "|&"
                if buf.strip():
                    parts.append(buf.strip())
                buf = ""
                i += len(sep)
                continue
        buf += c
        i += 1
    if buf.strip():
        parts.append(buf.strip())
    return parts


def _tokens(segment: str) -> List[str]:
    head = segment.split("\n", 1)[0] if _HEREDOC_RE.search(segment) else segment
    try:
        return shlex.split(head, posix=True)
    except ValueError:
        return head.split()


def _heredoc_body(segment: str) -> Optional[str]:
    m = _HEREDOC_RE.search(segment)
    if not m or "\n" not in segment:
        return None
    body = segment.split("\n", 1)[1]
    if body.endswith(m.group(2)):
        body = body[: -len(m.group(2))]
    return body


def _substitutions(segment: str) -> List[str]:
    out = []
    for m in re.finditer(r"\$\(((?:[^()]|\([^()]*\))*)\)", segment):
        out.append(m.group(1))
    for m in re.finditer(r"`([^`]+)`", segment):
        out.append(m.group(1))
    return out


_VALUE_OPTS = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"},
    "env": {"-u", "-C", "-S"},
    "nice": {"-n"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "uv": {
        "--with",
        "--python",
        "-p",
        "--project",
        "--directory",
        "--package",
        "--extra",
        "--group",
        "--env-file",
        "--index",
        "--from",
    },
    "npx": {"-p", "--package", "-c", "--call"},
    "xargs": {"-I", "-n", "-L", "-P", "-d", "-s", "-E"},
}


def _drop_opts(tokens: List[str], tool: str) -> List[str]:
    takes = _VALUE_OPTS.get(tool, set())
    i = 0
    while i < len(tokens) and tokens[i].startswith("-"):
        i += 2 if tokens[i] in takes else 1
    return tokens[i:]


def _unwrap(tokens: List[str]) -> List[List[str]]:
    """Forms of one simple command with wrappers removed: [[as written], [unwrapped], ...]."""
    forms = [tokens]
    t = list(tokens)
    for _ in range(8):
        if not t:
            break
        head = t[0]
        base = head.rsplit("/", 1)[-1]
        if _ASSIGN_RE.match(head):
            t = t[1:]
        elif base == "env":
            t = [x for x in _drop_opts(t[1:], "env") if not _ASSIGN_RE.match(x)] if len(t) > 1 else []
        elif base in _SIMPLE_WRAPPERS:
            t = _drop_opts(t[1:], base)
        elif base == "timeout":
            rest = _drop_opts(t[1:], "timeout")
            t = rest[1:]
        elif base == "xargs":
            t = _drop_opts(t[1:], "xargs")
        elif base in ("npx", "bunx", "uvx") or (base == "pipx" and len(t) > 1 and t[1] == "run"):
            rest = t[2:] if base == "pipx" else t[1:]
            rest = [x for x in rest if x not in ("--yes", "-y", "--no-install", "--quiet", "-q")]
            t = _drop_opts(rest, "npx")
            if t:
                versioned = re.match(r"^(@?[^@\s]+)@[^/\s]+$", t[0])  # npx npm@10 i -> npm i
                if versioned:
                    t = [versioned.group(1), *t[1:]]
        elif base in ("pnpm", "yarn", "bun") and len(t) > 1 and t[1] in ("dlx", "exec", "x"):
            t = t[2:]
        elif base in ("uv", "poetry", "pipenv", "pdm", "hatch", "rye") and len(t) > 1 and t[1] == "run":
            t = _drop_opts(t[2:], "uv")
        elif base == "conda" and len(t) > 1 and t[1] == "run":
            rest = t[2:]
            while rest and rest[0].startswith("-"):
                rest = rest[2:] if rest[0] in ("-n", "--name", "-p", "--prefix") else rest[1:]
            t = rest
        elif re.match(r"^python[0-9.]*$", base) and len(t) > 2 and t[1] == "-m":
            t = t[2:]
        elif base == "git":
            rest = t[1:]
            i = 0
            while i < len(rest) and rest[i].startswith("-"):
                i += 2 if rest[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") else 1
            if i:
                t = ["git", *rest[i:]]
                forms.append(t)
            break
        else:
            break
        if t:
            forms.append(t)
    return forms


def _script_of(tokens: List[str]) -> Optional[str]:
    """The script of `bash -c '...'`, `sh -lc "..."`, `bash <<EOF` (handled by the caller) etc."""
    if not tokens:
        return None
    base = tokens[0].rsplit("/", 1)[-1]
    if base not in {"bash", "sh", "zsh", "dash", "ksh"}:
        return None
    for i, tok in enumerate(tokens[1:], 1):
        if tok.startswith("-") and "c" in tok[1:] and not tok.startswith("--"):
            return tokens[i + 1] if i + 1 < len(tokens) else None
    return None


def segments(command: str, _depth: int = 0) -> List[Dict[str, Any]]:
    """Simple commands in a shell line, each with its argv and unwrapped views (normalised strings)."""
    out: List[Dict[str, Any]] = []
    if _depth > 4:
        return out
    for part in _split_top(command):
        if part.startswith("cd ") or part == "cd":
            continue
        tokens = _tokens(part)
        stripped = part
        while stripped.startswith(("(", "{")):
            stripped = stripped[1:].strip()
        if stripped != part:
            out += segments(stripped.rstrip(")}").strip(), _depth + 1)
            continue
        forms = _unwrap(tokens) if tokens else []
        views = []
        for form in forms:
            text = " ".join(form)
            if text and text not in views:
                views.append(text)
        out.append(
            {
                "raw": part,
                "argv": forms[-1] if forms else tokens,
                "argv_raw": tokens,
                "views": views,
                "heredoc": _heredoc_body(part),
            }
        )
        for form in forms:
            script = _script_of(form)
            if script:
                out += segments(script, _depth + 1)
        body = _heredoc_body(part)
        if body is not None and forms and forms[-1] and forms[-1][0].rsplit("/", 1)[-1] in {"bash", "sh", "zsh"}:
            out += segments(body, _depth + 1)
        for sub in _substitutions(part):
            out += segments(sub, _depth + 1)
    return out


def matches_command(patterns: List[str], segment: Dict[str, Any]) -> bool:
    return any(re.search(p, v) for p in patterns for v in segment["views"])


def _git_sub(segment: Dict[str, Any]) -> Tuple[str, List[str]]:
    for v in segment["views"]:
        if v.startswith("git "):
            parts = v.split()
            return (parts[1] if len(parts) > 1 else "", parts[2:])
    argv = segment["argv"]
    if argv and argv[0].rsplit("/", 1)[-1] == "git":
        return (argv[1] if len(argv) > 1 else "", argv[2:])
    return ("", [])


def is_git(segment: Dict[str, Any], sub: str) -> bool:
    """True when the segment runs `git <sub>` (any options; an executed attempt counts)."""
    name, _ = _git_sub(segment)
    return name == sub


# --------------------------------------------------------------------------------------------- writes through the shell

_PY_WRITE_RE = re.compile(
    r"""open\(\s*(?:[rfbu]*['"])([^'"]+)['"]\s*,\s*['"][^'"]*[wax+][^'"]*['"]|"""
    r"""Path\(\s*['"]([^'"]+)['"]\s*\)\s*\.\s*(?:write_text|write_bytes|unlink|touch|rename|replace|mkdir)|"""
    r"""(?:os\.remove|os\.unlink|shutil\.rmtree|os\.rename|os\.replace|shutil\.move)\(\s*['"]([^'"]+)['"]|"""
    r"""shutil\.(?:copy2?|copyfile|move)\(\s*['"][^'"]+['"]\s*,\s*['"]([^'"]+)['"]|"""
    r"""(?:writeFileSync|appendFileSync|writeFile|appendFile|rmSync|unlinkSync|renameSync)\(\s*['"]([^'"]+)['"]"""
)


def _code_targets(code: str) -> List[str]:
    return [next(g for g in m.groups() if g) for m in _PY_WRITE_RE.finditer(code)]


def _dest_args(args: List[str]) -> List[str]:
    return [a for a in args if not a.startswith("-")]


def shell_write_targets(command: str) -> List[Dict[str, str]]:
    """Files a command line writes, creates, deletes or renames: [{"path", "op"}], op in write|delete|rename|unknown."""
    found: List[Dict[str, str]] = []

    def add(path: str, op: str = "write") -> None:
        p = path.strip().strip("'\"")
        if p and p not in ("/dev/null", "/dev/stdout", "/dev/stderr", "-") and not p.startswith(("&", "/dev/fd")):
            found.append({"path": p[2:] if p.startswith("./") else p, "op": op})

    for seg in segments(command):
        raw_tokens = seg["argv_raw"]
        # Redirections anywhere in the segment.
        for i, tok in enumerate(raw_tokens):
            m = re.match(r"^(?:\d|&)?(>>?|>\|)(.*)$", tok)
            if m:
                target = m.group(2) or (raw_tokens[i + 1] if i + 1 < len(raw_tokens) else "")
                add(target)
        argv = [t for t in seg["argv"] if not re.match(r"^(?:\d|&)?>", t)]
        clean: List[str] = []
        skip = False
        for t in argv:
            if skip:
                skip = False
                continue
            if re.match(r"^(?:\d|&)?(>>?|>\||<)$", t):
                skip = True
                continue
            if re.match(r"^(?:\d|&)?(>>?|>\||<)", t) or t.startswith("<<"):
                continue
            clean.append(t)
        if not clean:
            continue
        tool = clean[0].rsplit("/", 1)[-1]
        args = clean[1:]
        if tool == "tee":
            for a in _dest_args(args):
                add(a)
        elif tool in ("sed", "gsed"):
            if any(a == "-i" or a.startswith("-i") or a == "--in-place" or a.startswith("--in-place=") for a in args):
                rest = []
                skip_next = False
                script_given = any(a in ("-e", "--expression", "-f", "--file") for a in args)
                for j, a in enumerate(args):
                    if skip_next:
                        skip_next = False
                        continue
                    if a in ("-e", "--expression", "-f", "--file"):
                        skip_next = True
                        continue
                    if a == "-i" and j + 1 < len(args) and args[j + 1] == "":
                        skip_next = True  # BSD sed -i ''
                        continue
                    if a.startswith("-"):
                        continue
                    rest.append(a)
                files = rest if script_given else rest[1:]
                for f in files:
                    add(f)
        elif tool == "perl" and any(re.match(r"^-[a-zA-Z]*i", a) for a in args):
            rest = [a for a in args if not a.startswith("-")]
            has_e = any(re.match(r"^-[a-zA-Z]*e", a) for a in args)
            for f in rest[1:] if has_e else rest:
                add(f)
        elif tool in ("mv", "git") and (tool == "mv" or (args[:1] == ["mv"])):
            files = _dest_args(args[1:] if tool == "git" else args)
            if len(files) >= 2:
                for src in files[:-1]:
                    add(src, "rename")
                add(files[-1])
        elif tool in ("cp", "install", "rsync", "ln"):
            files = _dest_args(args)
            if len(files) >= 2:
                add(files[-1])
        elif tool in ("rm", "unlink", "shred"):
            for f in _dest_args(args):
                add(f, "delete")
        elif tool == "git" and args[:1] == ["rm"]:
            for f in _dest_args(args[1:]):
                add(f, "delete")
        elif tool == "git" and args[:1] in (["checkout"], ["restore"]):
            if "--" in args:
                for f in args[args.index("--") + 1 :]:
                    add(f)
            elif args[:1] == ["restore"]:
                for f in _dest_args(args[1:]):
                    add(f)
        elif (tool == "git" and args[:1] == ["apply"]) or tool == "patch":
            add("*", "unknown")
        elif tool in ("touch", "truncate", "mkdir"):
            files = _dest_args(args)
            if tool == "truncate":
                files = [f for f in files if not re.match(r"^[+-]?\d+[KMGkmg]?$", f)]
            for f in files:
                add(f)
        elif tool == "dd":
            for a in args:
                if a.startswith("of="):
                    add(a[3:])
        elif re.match(r"^python[0-9.]*$", tool) or tool in ("node", "ruby", "deno", "bun"):
            if "-c" in args or "-e" in args:
                flag = "-c" if "-c" in args else "-e"
                idx = args.index(flag)
                if idx + 1 < len(args):
                    for p in _code_targets(args[idx + 1]):
                        add(p)
            if seg.get("heredoc"):
                for p in _code_targets(seg["heredoc"]):
                    add(p)
    return found


# --------------------------------------------------------------------------------------------- diffs


def parse_diff(diff: str) -> List[Dict[str, Any]]:
    """Files in a git-format diff: path, old_path, status (added|deleted|modified|renamed), added, removed lines."""
    files: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    new_line = 0
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            m = re.match(r'^diff --git "?a/(.+?)"? "?b/(.+?)"?$', line)
            path = m.group(2) if m else line.split(" b/")[-1]
            cur = {
                "path": path,
                "old_path": m.group(1) if m else path,
                "status": "modified",
                "added": [],
                "removed": [],
                "binary": False,
                "lines": [],
            }
            files.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("new file mode"):
            cur["status"] = "added"
        elif line.startswith("deleted file mode"):
            cur["status"] = "deleted"
        elif line.startswith("rename from "):
            cur["old_path"] = line[len("rename from ") :]
            cur["status"] = "renamed"
        elif line.startswith("rename to "):
            cur["path"] = line[len("rename to ") :]
        elif line.startswith("Binary files") or line.startswith("GIT binary patch"):
            cur["binary"] = True
        elif line.startswith("--- "):
            if line.strip() == "--- /dev/null":
                cur["status"] = "added"
        elif line.startswith("+++ "):
            if line.strip() == "+++ /dev/null":
                cur["status"] = "deleted"
        elif line.startswith("@@"):
            m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", line)
            new_line = int(m.group(1)) if m else 0
            cur["lines"].append(("@", line))
        elif line.startswith("+"):
            cur["added"].append((new_line, line[1:]))
            cur["lines"].append(("+", line[1:]))
            new_line += 1
        elif line.startswith("-"):
            cur["removed"].append(line[1:])
            cur["lines"].append(("-", line[1:]))
        elif line.startswith(" "):
            cur["lines"].append((" ", line[1:]))
            new_line += 1
    return files


def new_file_diff(path: str, text: str) -> str:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    body = "".join("+" + ln + "\n" for ln in lines)
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n{body}"
    )


def _changed(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    return parse_diff(str(run.get("diff") or ""))


# --------------------------------------------------------------------------------------------- dependencies

_PY_REQ_RE = re.compile(r"^\s*['\"]?([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(?:[<>=!~;@ ].*)?['\"]?,?\s*$")
_JSON_DEP_RE = re.compile(
    r'^\s*"(@?[A-Za-z0-9._/-]+)"\s*:\s*"(\^|~|>=?|<=?|=|\*|\d|workspace:|npm:|github:|git|file:|'
    r"link:|https?:|latest|next|catalog:)"
)
_TOML_KEY_DEP_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*=\s*(\"[\^~<>=!*\d]|\{|\[)")
_NOT_DEPS = {
    "python",
    "name",
    "version",
    "edition",
    "authors",
    "description",
    "license",
    "readme",
    "repository",
    "homepage",
    "documentation",
    "keywords",
    "categories",
    "build",
    "workspace",
    "resolver",
    "members",
    "publish",
    "rust-version",
    "requires-python",
    "packages",
    "include",
    "exclude",
    "default-run",
    "license-file",
    "classifiers",
    "urls",
    "scripts",
    "dynamic",
    "requires",
    "build-backend",
}


def _norm_pkg(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.lower())


_PEP508_RE = re.compile(
    r"""^\s*['"]([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*([<>=!~;@ ][^'"]*)?['"]\s*,?\s*(#.*)?$"""
)
_QUOTED_RE = re.compile(r"""['"]([^'"]+)['"]""")
_JS_DEP_SECTIONS = {"dependencies", "devDependencies", "peerDependencies", "optionalDependencies"}


def _py_dep_location(section: str, array_key: str) -> Optional[bool]:
    """True/False when the location is known to hold (or not hold) requirement strings; None when unknown."""
    if not section:
        return None
    if section == "project":
        return array_key == "dependencies"
    if section in ("project.optional-dependencies", "dependency-groups"):
        return True
    if section == "tool.uv":
        return array_key in ("dev-dependencies", "constraint-dependencies", "override-dependencies")
    if section == "tool.pdm.dev-dependencies":
        return True
    if section == "options":  # setup.cfg
        return array_key in ("install_requires", "tests_require", "setup_requires")
    if section == "options.extras_require":
        return True
    return False


def _toml_table_dep(section: str, base: str) -> Optional[bool]:
    if not section:
        return None
    if base == "Cargo.toml":
        return bool(re.match(r"^((workspace|target\.[^ ]+)\.)?(dev-|build-)?dependencies$", section))
    if base == "Pipfile":
        return section in ("packages", "dev-packages")
    if base == "pyproject.toml":
        return bool(re.match(r"^tool\.poetry(\.group\.[^.]+)?\.(dev-)?dependencies$", section))
    return False


def _req_name(text: str) -> Optional[str]:
    m = _PEP508_RE.match(text)
    return m.group(1) if m else None


def _looks_like_package(name: str) -> bool:
    return bool(re.match(r"^[a-z0-9][a-z0-9._-]*$", name)) and len(name) > 1 and not name.isupper()


def manifest_deps(path: str, lines: List[Tuple[str, str]], side: str) -> List[str]:
    """Dependency names on one side of a manifest's diff ("+" new side, "-" old side), using visible context."""
    base = path.rsplit("/", 1)[-1]
    keep = {" ", side}
    names: List[str] = []
    section = ""
    array_key = ""
    js_stack: List[str] = []
    js_known = False
    for kind, raw in lines:
        if kind == "@":
            section, array_key, js_stack, js_known = "", "", [], False
            continue
        if kind not in keep:
            continue
        text = raw.rstrip()
        stripped = text.split("#", 1)[0].rstrip() if base != "package.json" else text
        if base == "package.json":
            opened = re.match(r'^\s*"([^"]+)"\s*:\s*\{', text)
            if opened:
                js_stack.append(opened.group(1))
                js_known = True
                continue
            if re.match(r"^\s*\},?\s*$", text):
                if js_stack:
                    js_stack.pop()
                continue
            m = re.match(r'^\s*"(@?[^"]+)"\s*:\s*"([^"]*)"', text)
            if not m or kind != side:
                continue
            if js_known and js_stack:
                if js_stack[-1] in _JS_DEP_SECTIONS:
                    names.append(m.group(1))
            elif _JSON_DEP_RE.match(text):
                names.append(m.group(1))
            continue
        if base.startswith("requirements") and base.endswith(".txt"):
            if kind == side and stripped.strip() and not stripped.strip().startswith(("-", "git+", "http")):
                m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)", stripped)
                if m:
                    names.append(m.group(1))
            continue
        if base == "go.mod":
            if kind == side:
                m = re.match(r"^\s*(?:require\s+)?([a-z0-9.-]+\.[a-z]{2,}/[^\s]+)\s+v\d", stripped)
                if m:
                    names.append(m.group(1))
            continue
        header = re.match(r"^\s*\[+\s*([^\]]+?)\s*\]+\s*$", stripped)
        if header:
            section, array_key = header.group(1).strip().strip('"'), ""
            table = re.match(r"^((?:workspace\.)?(?:dev-|build-)?dependencies)\.([A-Za-z0-9_-]+)$", section)
            if table and base == "Cargo.toml" and kind == side:
                names.append(table.group(2))
            continue
        key_line = re.match(r"^\s*([A-Za-z0-9_.\"-]+)\s*=\s*(.*)$", stripped)
        if key_line:
            key, value = key_line.group(1).strip('"'), key_line.group(2)
            if value.startswith("["):
                array_key = key
                inline = value.endswith("]")
                if kind == side and (
                    _py_dep_location(section, key)
                    or (
                        section == ""
                        and key in ("dependencies", "dev-dependencies", "requires")
                        and base != "Cargo.toml"
                    )
                ):
                    for q in _QUOTED_RE.findall(value):
                        n = _req_name(f'"{q}"')
                        if n:
                            names.append(n)
                if inline:
                    array_key = ""
                continue
            array_key = ""
            if kind == side and key.lower() not in _NOT_DEPS:
                table_dep = _toml_table_dep(section, base)
                if table_dep or (
                    table_dep is None and base in ("Cargo.toml", "Pipfile") and re.match(r"^(\"[\^~<>=!*\d]|\{)", value)
                ):
                    names.append(key)
            continue
        if re.match(r"^\s*\]", stripped):
            array_key = ""
            continue
        if kind == side and base in ("pyproject.toml", "setup.cfg"):
            location = _py_dep_location(section, array_key)
            name = (
                _req_name(stripped)
                if base == "pyproject.toml"
                else (
                    re.match(r"^\s+([A-Za-z0-9][A-Za-z0-9._-]*)", stripped).group(1)  # type: ignore[union-attr]
                    if re.match(r"^\s+[A-Za-z0-9]", stripped)
                    else None
                )
            )
            if not name:
                continue
            if location or (
                location is None
                and array_key in ("", "dependencies")
                and _looks_like_package(name)
                and (re.search(r"[<>=!~]", stripped) or array_key == "dependencies")
            ):
                names.append(name)
    return names


def new_dependencies_from_diff(run: Dict[str, Any], manifests: List[str]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for f in _changed(run):
        if not glob_match(manifests, f["path"]) or f["status"] == "deleted":
            continue
        added = manifest_deps(f["path"], f["lines"], "+")
        removed = {_norm_pkg(n) for n in manifest_deps(f["path"], f["lines"], "-")}
        for name in added:
            if _norm_pkg(name) not in removed:
                out.append((name, f["path"]))
    return out


_INSTALL = [
    (re.compile(r"^(npm)\s+(install|i|add|isntall|ci|clean-install)\b(.*)$"), "npm"),
    (re.compile(r"^(pnpm|yarn|bun)\s+(add|install|i|ci)\b(.*)$"), "js"),
    (re.compile(r"^(pip3?)\s+(install)\b(.*)$"), "pip"),
    (re.compile(r"^(uv)\s+(add)\b(.*)$"), "uv"),
    (re.compile(r"^(uv)\s+pip\s+(install)\b(.*)$"), "pip"),
    (re.compile(r"^(poetry|pdm|pipenv|rye)\s+(add|install)\b(.*)$"), "py"),
    (re.compile(r"^(go)\s+(get)\b(.*)$"), "go"),
    (re.compile(r"^(cargo)\s+(add)\b(.*)$"), "cargo"),
    (re.compile(r"^(gem)\s+(install)\b(.*)$"), "gem"),
    (re.compile(r"^(composer)\s+(require)\b(.*)$"), "php"),
    (re.compile(r"^(conda|mamba)\s+(install)\b(.*)$"), "conda"),
]
_OPT_WITH_VALUE = {
    "-r",
    "--requirement",
    "-c",
    "--constraint",
    "-e",
    "--editable",
    "-t",
    "--target",
    "--prefix",
    "-i",
    "--index-url",
    "--extra-index-url",
    "--python",
    "-p",
    "--group",
    "--optional",
    "--extra",
    "-w",
    "--workspace",
    "--filter",
    "-C",
    "--dir",
    "--save-prefix",
    "--registry",
    "--cwd",
}


def install_packages(segment: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """(is an install/add command, package names it adds)."""
    for view in segment["views"]:
        for rx, kind in _INSTALL:
            m = rx.match(view)
            if not m:
                continue
            args = m.group(3).split()
            names: List[str] = []
            skip = False
            for a in args:
                if skip:
                    skip = False
                    continue
                if a in _OPT_WITH_VALUE:
                    skip = True
                    continue
                if (
                    a.startswith("-")
                    or a in (".", "./")
                    or a.startswith((".", "/", "git+", "http://", "https://", "file:"))
                ):
                    continue
                if kind == "pip" and a.endswith((".txt", ".whl")):
                    continue
                name = (
                    re.split(r"(?<=.)[@=<>~!\[;]", a, maxsplit=1)[0]
                    if not a.startswith("@")
                    else ("@" + re.split(r"[@=<>~!]", a[1:], maxsplit=1)[0])
                )
                if kind == "go":
                    name = name.split("@", 1)[0]
                if name:
                    names.append(name)
            return True, names
    return False, []


# --------------------------------------------------------------------------------------------- run helpers


def _executed_shell(run: Dict[str, Any]) -> List[Tuple[int, Dict[str, Any], Dict[str, Any]]]:
    """(seq, event, segment) for every simple command that ran (hook-denied commands excluded)."""
    out = []
    for i, ev in enumerate(run.get("events") or []):
        if ev.get("type") != "shell" or ev.get("denied"):
            continue
        seq = ev.get("seq", i)
        for seg in segments(str(ev.get("command") or "")):
            out.append((seq if isinstance(seq, int) else i, ev, seg))
    return out


def _file_events(run: Dict[str, Any]) -> List[Tuple[int, str, str]]:
    """(seq, path, op) for files written by edit/write/delete events and by shell commands that ran."""
    out: List[Tuple[int, str, str]] = []
    for i, ev in enumerate(run.get("events") or []):
        seq = ev.get("seq", i)
        seq = seq if isinstance(seq, int) else i
        if ev.get("denied"):
            continue
        kind = ev.get("type")
        if kind in ("edit", "write", "delete") and ev.get("path"):
            out.append((seq, str(ev["path"]), {"edit": "write", "write": "write", "delete": "delete"}[kind]))
        elif kind == "shell":
            for t in shell_write_targets(str(ev.get("command") or "")):
                out.append((seq, t["path"], t["op"]))
    return out


def _ev(kind: str, text: str, seq: Optional[int] = None, path: Optional[str] = None) -> Dict[str, Any]:
    return {"kind": kind, "text": text[:400], "seq": seq, "path": path}


def _verdict(verdict: str, evidence: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {"verdict": verdict, "evidence": evidence or []}


def _norm_path(p: str) -> str:
    p = p.strip().strip("'\"")
    while p.startswith("./"):
        p = p[2:]
    for prefix in ("/srv/obey/work/",):
        if p.startswith(prefix):
            p = p[len(prefix) :]
    return p


# --------------------------------------------------------------------------------------------- checkers


def _check_command_forbidden(params: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    patterns = list(params.get("patterns") or [])
    preferred = list(params.get("preferred_patterns") or [])
    exercised = False
    for seq, ev, seg in _executed_shell(run):
        if matches_command(patterns, seg):
            return _verdict("violated", [_ev("command", seg["raw"], seq)])
        if preferred and matches_command(preferred, seg):
            exercised = True
    manual = list(params.get("manual_edit_paths") or [])
    if manual:
        touched = [f for f in _changed(run) if glob_match(manual, f["path"])]
        if touched:
            ok = (
                any(matches_command(preferred, seg) and ev.get("exit_code") == 0 for _, ev, seg in _executed_shell(run))
                if preferred
                else False
            )
            if not ok:
                return _verdict(
                    "violated",
                    [
                        _ev(
                            "diff",
                            f"{touched[0]['path']} changed without {params.get('preferred') or 'the preferred tool'}",
                            path=touched[0]["path"],
                        )
                    ],
                )
            exercised = True
    return _verdict("obeyed" if exercised else "not_exercised")


def _check_command_required(params: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    pattern = str(params["pattern"])
    globs = list(params.get("edit_globs") or ["**"])
    need_ok = params.get("require_success", True)
    edits = [seq for seq, path, _ in _file_events(run) if path != "*" and glob_match(globs, _norm_path(path))]
    changed = [f for f in _changed(run) if glob_match(globs, f["path"]) or glob_match(globs, f["old_path"])]
    if not edits and not changed:
        return _verdict("not_exercised")
    last = max(edits) if edits else -1
    for seq, ev, seg in _executed_shell(run):
        if seq <= last:
            continue
        if any(re.search(pattern, v) for v in seg["views"]):
            if not need_ok or ev.get("exit_code") == 0:
                return _verdict("obeyed", [_ev("command", seg["raw"], seq)])
    where = f" after the last edit (event {last})" if last >= 0 else ""
    return _verdict("violated", [_ev("command", f"no successful command matching {pattern}{where}", last)])


def _check_path_forbidden(params: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    globs = list(params["globs"])
    existing_only = bool(params.get("existing_only"))
    base = set(run.get("base_files") or [])
    exercised = False
    for seq, raw_path, op in _file_events(run):
        path = _norm_path(raw_path)
        if path == "*" or not glob_match(globs, path):
            continue
        exercised = True
        if existing_only and path not in base:
            continue
        return _verdict("violated", [_ev("event", f"{op} {path}", seq, path)])
    for f in _changed(run):
        hits = [p for p in {f["path"], f["old_path"]} if glob_match(globs, p)]
        if not hits:
            continue
        exercised = True
        if existing_only:
            if f["status"] == "added":
                continue
            target = f["old_path"] if f["status"] == "renamed" else f["path"]
            if base and target not in base:
                continue
        return _verdict("violated", [_ev("diff", f"{f['status']} {hits[0]}", path=hits[0])])
    return _verdict("obeyed" if exercised else "not_exercised")


def _check_path_required_with(params: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    changed = [f for f in _changed(run)]
    paths = {p for f in changed for p in (f["path"], f["old_path"])}
    when = [p for p in paths if glob_match(list(params["when"]), p)]
    if not when:
        return _verdict("not_exercised")
    if any(glob_match(list(params["require"]), p) for p in paths):
        return _verdict("obeyed")
    return _verdict(
        "violated",
        [
            _ev(
                "diff",
                f"{sorted(when)[0]} changed with no change under {', '.join(params['require'])}",
                path=sorted(when)[0],
            )
        ],
    )


def _check_dependency(params: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    manifests = list(params.get("manifests") or DEFAULT_MANIFESTS)
    allow = {_norm_pkg(a) for a in params.get("allow") or []}
    exercised = any(glob_match(manifests, f["path"]) for f in _changed(run))
    for seq, ev, seg in _executed_shell(run):
        is_install, names = install_packages(seg)
        if not is_install:
            continue
        exercised = True
        new = [n for n in names if _norm_pkg(n) not in allow]
        if new:
            return _verdict("violated", [_ev("command", seg["raw"], seq)])
    for name, path in new_dependencies_from_diff(run, manifests):
        if _norm_pkg(name) not in allow:
            return _verdict("violated", [_ev("diff", f"{path}: +{name}", path=path)])
    return _verdict("obeyed" if exercised else "not_exercised")


def _check_content_forbidden(params: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    rx = re.compile(str(params["regex"]))
    globs = list(params.get("globs") or ["**"])
    exercised = False
    for f in _changed(run):
        if f["binary"] or f["status"] == "deleted" or not glob_match(globs, f["path"]):
            continue
        for line_no, text in f["added"]:
            exercised = True
            if rx.search(text):
                return _verdict("violated", [_ev("diff", f"{f['path']}:{line_no}: {text.strip()}", path=f["path"])])
    return _verdict("obeyed" if exercised else "not_exercised")


def _check_content_required(params: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    rx = re.compile(str(params["regex"]))
    globs = list(params.get("globs") or ["**"])
    first = int(params.get("first_lines") or 10)
    exercised = False
    for f in _changed(run):
        if f["status"] != "added" or f["binary"] or not glob_match(globs, f["path"]):
            continue
        exercised = True
        # The required pattern may be on any of the first lines (each line is searched, as for added lines).
        if not any(rx.search(t) for _, t in f["added"][:first]):
            return _verdict("violated", [_ev("diff", f"new file {f['path']} lacks {params['regex']}", path=f["path"])])
    return _verdict("obeyed" if exercised else "not_exercised")


def _check_commit_message(params: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    commits = list(run.get("commits") or [])
    if not commits:
        return _verdict("not_exercised")
    for c in commits:
        message = str(c.get("message", ""))
        if not re.match(str(params["regex"]), message, re.S):
            return _verdict("violated", [_ev("commit", message.split("\n", 1)[0])])
    return _verdict("obeyed")


def _git_activity(run: Dict[str, Any]) -> bool:
    return bool(
        str(run.get("diff") or "").strip()
        or run.get("commits")
        or any(any(v.startswith("git ") for v in seg["views"]) for _, _, seg in _executed_shell(run))
    )


def _check_no_commit(params: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    for seq, _, seg in _executed_shell(run):
        if is_git(seg, "commit"):
            return _verdict("violated", [_ev("command", seg["raw"], seq)])
    commits = list(run.get("commits") or [])
    if commits:
        return _verdict("violated", [_ev("commit", str(commits[0].get("message", "")).split("\n", 1)[0])])
    return _verdict("obeyed" if _git_activity(run) else "not_exercised")


def _check_no_push(params: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    for seq, _, seg in _executed_shell(run):
        if is_git(seg, "push"):
            return _verdict("violated", [_ev("command", seg["raw"], seq)])
    if run.get("pushed_refs"):
        return _verdict("violated", [_ev("event", "pushed " + ", ".join(run["pushed_refs"]))])
    return _verdict("obeyed" if _git_activity(run) else "not_exercised")


def _check_file_naming(params: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    globs = list(params["globs"])
    pattern = re.compile(str(params["pattern"]))
    exercised = False
    for f in _changed(run):
        if f["status"] != "added" or not glob_match(globs, f["path"]):
            continue
        exercised = True
        name = f["path"].rsplit("/", 1)[-1]
        if not pattern.fullmatch(name):
            return _verdict("violated", [_ev("diff", f"new file {f['path']}", path=f["path"])])
    return _verdict("obeyed" if exercised else "not_exercised")


def _check_final_message(params: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    msg = str(run.get("final_message") or "").strip()
    if not msg:
        return _verdict("not_exercised")
    if "required" in params and not re.search(str(params["required"]), msg):
        return _verdict("violated", [_ev("message", msg.splitlines()[-1] if msg else "")])
    if "forbidden" in params:
        m = re.search(str(params["forbidden"]), msg)
        if m:
            return _verdict("violated", [_ev("message", m.group(0))])
    return _verdict("obeyed")


CHECKS = {
    "command_forbidden": _check_command_forbidden,
    "command_required": _check_command_required,
    "path_forbidden": _check_path_forbidden,
    "path_required_with": _check_path_required_with,
    "dependency_unchanged": _check_dependency,
    "content_forbidden_added": _check_content_forbidden,
    "content_required_added": _check_content_required,
    "commit_message": _check_commit_message,
    "no_commit": _check_no_commit,
    "no_push": _check_no_push,
    "file_naming": _check_file_naming,
    "final_message": _check_final_message,
}


def check(rule: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    """Verdict of one rule on one run. `rule` is a checker ({"type", "params"}) or a rule with a "checker" key."""
    nested = rule.get("checker")
    checker: Dict[str, Any] = nested if isinstance(nested, dict) else rule
    return CHECKS[str(checker["type"])](dict(checker.get("params") or {}), run)


def reason(rule: Dict[str, Any], verdict: Dict[str, Any]) -> str:
    src = rule.get("source") or {}
    where = f" ({src.get('file')}:{(src.get('lines') or [''])[0]})" if src.get("file") else ""
    ev = (verdict.get("evidence") or [{}])[0]
    detail = f" Found: {ev.get('text')}." if ev.get("text") else ""
    return f'obey: this breaks the rule "{rule.get("text", "")}"{where}.{detail}'


# --------------------------------------------------------------------------------------------- actions (hooks)


def _added_lines(old: str, new: str) -> List[str]:
    before: Dict[str, int] = {}
    for line in old.split("\n"):
        before[line] = before.get(line, 0) + 1
    out = []
    for line in new.split("\n"):
        if before.get(line, 0) > 0:
            before[line] -= 1
        else:
            out.append(line)
    return out


def _action_run(action: Dict[str, Any]) -> Dict[str, Any]:
    """A one-event run record for a proposed action, so the same checks decide."""
    kind = action.get("kind")
    path = str(action.get("path") or "")
    if kind == "shell":
        return {
            "events": [{"seq": 0, "type": "shell", "command": action.get("command", ""), "exit_code": None}],
            "diff": "",
            "base_files": [],
            "commits": [],
            "pushed_refs": [],
            "final_message": "",
        }
    exists = bool(action.get("exists"))
    if kind == "delete":
        diff = f"diff --git a/{path} b/{path}\ndeleted file mode 100644\n--- a/{path}\n+++ /dev/null\n"
        return {
            "events": [{"seq": 0, "type": "delete", "path": path}],
            "diff": diff,
            "base_files": [path],
            "commits": [],
            "pushed_refs": [],
            "final_message": "",
        }
    if kind == "write":
        old = action.get("current") or ""
        new = str(action.get("content") or "")
    else:
        old = str(action.get("old") or "")
        new = str(action.get("new") or "")
        if action.get("new_content") is not None and action.get("current") is not None:
            old, new = str(action["current"]), str(action["new_content"])
    if not exists:
        diff = new_file_diff(path, new)
    else:
        added = _added_lines(old, new)
        removed = _added_lines(new, old)
        diff = (
            f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,{len(removed)} +1,{len(added)} @@\n"
            + "".join("-" + r + "\n" for r in removed)
            + "".join("+" + a + "\n" for a in added)
        )
    return {
        "events": [{"seq": 0, "type": "write" if kind == "write" else "edit", "path": path}],
        "diff": diff,
        "base_files": [path] if exists else [],
        "commits": [],
        "pushed_refs": [],
        "final_message": "",
    }


def _commit_messages(command: str) -> List[str]:
    out = []
    for seg in segments(command):
        if not is_git(seg, "commit"):
            continue
        argv = seg["argv"]
        msgs = []
        for i, a in enumerate(argv):
            if a in ("-m", "--message") and i + 1 < len(argv):
                msgs.append(argv[i + 1])
            elif a.startswith("--message="):
                msgs.append(a.split("=", 1)[1])
            elif a.startswith("-m") and len(a) > 2 and not a.startswith("--"):
                msgs.append(a[2:])
        if msgs:
            out.append("\n\n".join(msgs))
    return out


def evaluate_action(rules: List[Dict[str, Any]], action: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The first rule a proposed action would break, as {"rule_id", "reason"}; None to allow it."""
    run = _action_run(action)
    for rule in rules:
        checker = rule["checker"]
        kind = checker["type"]
        params = checker.get("params") or {}
        verdict: Optional[Dict[str, Any]] = None
        if action.get("kind") == "shell":
            if kind in ("command_forbidden", "no_commit", "no_push", "dependency_unchanged"):
                if kind == "command_forbidden":
                    params = {k: v for k, v in params.items() if k != "manual_edit_paths"}
                    verdict = _check_command_forbidden(params, run)
                else:
                    verdict = check(checker, run)
            elif kind == "path_forbidden":
                targets = [t for t in shell_write_targets(str(action.get("command") or "")) if t["path"] != "*"]
                if targets:
                    existing = action.get("existing_paths")
                    shell_run = {
                        "events": [{"seq": 0, "type": "write", "path": t["path"]} for t in targets],
                        "diff": "",
                        "base_files": list(existing) if existing is not None else [t["path"] for t in targets],
                        "commits": [],
                        "pushed_refs": [],
                    }
                    verdict = check(checker, shell_run)
            elif kind == "commit_message":
                for message in _commit_messages(str(action.get("command") or "")):
                    verdict = check(checker, {"commits": [{"message": message}]})
                    if verdict["verdict"] == "violated":
                        break
        else:
            if kind in ("path_forbidden", "content_forbidden_added", "file_naming", "dependency_unchanged") or (
                kind == "content_required_added" and not action.get("exists") and action.get("kind") == "write"
            ):
                verdict = check(checker, run)
            elif kind == "command_forbidden" and params.get("manual_edit_paths"):
                if glob_match(list(params["manual_edit_paths"]), str(action.get("path") or "")):
                    verdict = _verdict("violated", [_ev("event", f"edit {action.get('path')} by hand")])
        if verdict and verdict["verdict"] == "violated":
            return {"rule_id": rule.get("id"), "reason": reason(rule, verdict)}
    return None


# --------------------------------------------------------------------------------------------- transcripts


def events_from_transcript(text: str, root: str = "") -> List[Dict[str, Any]]:
    """Shell and file events from a Claude Code transcript (JSON lines), for stop-time checks."""
    events: List[Dict[str, Any]] = []
    pending: Dict[str, Dict[str, Any]] = {}
    prefix = root.rstrip("/") + "/" if root else ""
    for line in text.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        msg = obj.get("message") if isinstance(obj, dict) else None
        if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                name = block.get("name")
                data = block.get("input") or {}
                path = str(data.get("file_path") or "")
                if prefix and path.startswith(prefix):
                    path = path[len(prefix) :]
                if name == "Bash":
                    ev: Dict[str, Any] = {"type": "shell", "command": str(data.get("command") or ""), "exit_code": None}
                elif name in ("Edit", "MultiEdit", "NotebookEdit"):
                    ev = {"type": "edit", "path": path}
                elif name == "Write":
                    ev = {"type": "write", "path": path}
                else:
                    continue
                ev["seq"] = len(events)
                events.append(ev)
                pending[str(block.get("id"))] = ev
            elif block.get("type") == "tool_result":
                ev2 = pending.pop(str(block.get("tool_use_id")), None)
                if ev2 is not None and ev2["type"] == "shell":
                    content = block.get("content")
                    body = (
                        content
                        if isinstance(content, str)
                        else " ".join(str(c.get("text", "")) for c in content or [] if isinstance(c, dict))
                    )
                    if "hook" in body.lower() and ("denied" in body.lower() or "blocked" in body.lower()):
                        ev2["denied"] = True
                    m = re.search(r"Exit code (\d+)", body)
                    ev2["exit_code"] = (int(m.group(1)) if m else 1) if block.get("is_error") else 0
    return events
