"""obey rule engine: one implementation of every rule check, shared by the checkers and the generated hooks.

Standard library only, Python 3.9+. Vendored into a repository's .obey/hooks/ by `obey enforce`, so that what a
hook blocks is exactly what `obey run` measures. https://github.com/B0yko/obey
"""

from __future__ import annotations

import json
import posixpath
import re
import shlex
from typing import Any, Dict, List, Optional, Tuple

WORKDIR = "/srv/obey/work"  # where `obey run` puts the repository inside the sandbox
DENY_MARK = "obey: this breaks the rule"  # how every refusal starts; the stop hook finds its own refusals by it
STOP_TYPES = {"command_required", "path_required_with", "final_message", "content_required_added"}
DEFAULT_MANIFESTS = [
    "**/package.json",
    "**/pyproject.toml",
    "**/requirements*.txt",
    "**/requirements*.in",
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

# Not followed (a command the engine cannot see is not blocked): `ssh host '...'`, `docker run image cmd`, code
# that spawns processes inside `python -c` / `node -e` (only its file writes are read), `watch`, `flock`, `su -c`
# and `script -c` wrappers, `bash <(...)` / `source <(...)`, `curl ... | sh`, aliases, shell functions, and a
# command word that comes from a variable (`$CMD`).

_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SIMPLE_WRAPPERS = {
    "sudo",
    "time",
    "nohup",
    "exec",
    "command",
    "builtin",
    "nice",
    "doas",
    "stdbuf",
    "caffeinate",
    "corepack",
    "setsid",
}
_SHELL_NAMES = {"bash", "sh", "zsh", "dash", "ksh", "ash", "fish"}
# `<<EOF`, `<<-'EOF'`, `<<"EOF"`, `<<\EOF`, but not the here-string `<<<`. Groups: single-quoted, double-quoted,
# backslash, bare delimiter.
_HEREDOC_RE = re.compile(r"""(?<!<)<<(?!<)-?[ \t]*(?:'([^'\n]*)'|"([^"\n]*)"|(\\?)([^\s;&|<>()'"\\]+))""")
_REDIR_RE = re.compile(r"^(\d+|&)?(>>|>\||>&|>|<<<|<<-|<<|<&|<>|<)(.*)$", re.S)
_RESERVED_RE = re.compile(r"^(?:(?:!|do|then|else|elif|if|while|until|\{)(?:\s+|$))+")
_CLOSERS = {"}", "fi", "done", "esac", "then", "else", "do"}
_CD_NAMES = {"cd", "pushd", "popd"}
_PLAIN_RUN = re.compile(r"""[^\\'"`$<>()#;&|\n]+""")
_WORD_RUN = re.compile(r"""[^\s\\'"`$<>]+""")
_DQ_SPECIAL = re.compile(r"""["\\$`]""")
_PAREN_SPECIAL = re.compile(r"""[()'"\\`<#]""")
_SUBST_SPECIAL = re.compile(r"""['"\\`$<>]""")
_ANSI_SPECIAL = re.compile(r"""[\\']""")


class _Redir(str):
    """A word that starts with an unquoted redirection operator: `>f`, `2>>f`, `&>`, `<<<`, `>|`."""

    __slots__ = ()


def _hd(m: "re.Match[str]") -> Tuple[str, bool]:
    """(delimiter, quoted) of a heredoc operator matched by _HEREDOC_RE."""
    if m.group(1) is not None:
        return m.group(1), True
    if m.group(2) is not None:
        return m.group(2), True
    return m.group(4), bool(m.group(3))


def _terminator(delim: str) -> "re.Pattern[str]":
    return re.compile(r"(?m)^[ \t]*" + re.escape(delim) + r"[ \t]*$")


def _read_dq(s: str, i: int, depth: int = 0) -> Tuple[str, int, bool]:
    """The double-quoted string at s[i]: (its text with escapes resolved, index after it, whether it was closed)."""
    out: List[str] = []
    n = len(s)
    j = i + 1
    while j < n:
        m = _DQ_SPECIAL.search(s, j)
        if m is None:
            out.append(s[j:])
            return "".join(out), n, False
        k = m.start()
        out.append(s[j:k])
        c = s[k]
        if c == '"':
            return "".join(out), k + 1, True
        if c == "\\":
            nxt = s[k + 1 : k + 2]
            if nxt and nxt in '"\\$`':
                out.append(nxt)
                j = k + 2
            elif nxt == "\n":
                j = k + 2
            else:
                out.append("\\")
                j = k + 1
        elif c == "$" and s.startswith("(", k + 1) and depth < 20:
            e = _skip_paren(s, k + 1, depth + 1)
            out.append(s[k:e])  # a command substitution stays as written
            j = e
        elif c == "`":
            e = s.find("`", k + 1)
            e = n if e == -1 else e + 1
            out.append(s[k:e])
            j = e
        else:
            out.append(c)
            j = k + 1
    return "".join(out), n, False


def _skip_ansi(s: str, i: int) -> int:
    """Index after the `$'...'` string at s[i]."""
    n = len(s)
    j = i + 2
    while j < n:
        m = _ANSI_SPECIAL.search(s, j)
        if m is None:
            return n
        if s[m.start()] == "'":
            return m.start() + 1
        j = m.start() + 2
    return n


def _ansi_text(raw: str) -> str:
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t", "r": "\r"}.get(m.group(1), m.group(1)), raw, flags=re.S)


def _skip_paren(s: str, i: int, depth: int = 0) -> int:
    """Index after the `)` that closes the `(` at s[i] (len(s) when it is never closed).

    Quotes, backslashes, nested parentheses and heredoc bodies inside are skipped, so `)` in them does not count.
    """
    n = len(s)
    level = 0
    j = i
    while j < n:
        m = _PAREN_SPECIAL.search(s, j)
        if m is None:
            return n
        j = m.start()
        c = s[j]
        if c == "(":
            level += 1
        elif c == ")":
            level -= 1
            if level == 0:
                return j + 1
        elif c == "'":
            if j > 0 and s[j - 1] == "$":
                j = _skip_ansi(s, j - 1)
                continue
            k = s.find("'", j + 1)
            j = n if k == -1 else k
        elif c == '"':
            if depth >= 20:
                return n
            j = _read_dq(s, j, depth + 1)[1]
            continue
        elif c == "\\":
            j += 1
        elif c == "`":
            k = s.find("`", j + 1)
            j = n if k == -1 else k
        elif c == "<":
            hm = _HEREDOC_RE.match(s, j)
            if hm:
                nl = s.find("\n", hm.end())
                term = _terminator(_hd(hm)[0]).search(s, nl + 1) if nl != -1 else None
                j = term.end() if term else hm.end()
                continue
        elif c == "#" and (j == 0 or s[j - 1] in " \t\n"):
            k = s.find("\n", j)
            j = n if k == -1 else k
            continue
        j += 1
    return n


def _split_top(cmd: str) -> List[Tuple[str, str]]:
    """Split a command line on unquoted separators: [(separator before the part, part)].

    A heredoc body stays attached to its command, also when more commands follow on the line of the operator.
    The parentheses of a subshell come back as the parts ("(", "") and (")", ""), so a caller can scope a `cd`;
    command and process substitutions are not split, and a quoted string or `$(...)` is read as a unit in linear
    time.
    """
    parts: List[Tuple[str, str]] = []
    buf: List[str] = []
    last = ""  # last character in buf ("" when it is empty)
    sep_before = ""
    pending: List[Tuple[int, str]] = []  # heredocs waiting for their body: (index of their part, delimiter)
    i = 0
    n = len(cmd)

    def add(text: str) -> None:
        nonlocal last
        buf.append(text)
        last = text[-1]

    def flush() -> None:
        nonlocal last
        text = "".join(buf).strip()
        if text:
            parts.append((sep_before, text))
        buf.clear()
        last = ""

    while i < n:
        c = cmd[i]
        m = _PLAIN_RUN.match(cmd, i)
        if m:
            add(m.group())
            i = m.end()
        elif c == "\\":
            add(cmd[i : i + 2])
            i += 2
        elif c == "'":
            j = cmd.find("'", i + 1)
            j = n if j == -1 else j + 1
            add(cmd[i:j])
            i = j
        elif c == '"':
            j = _read_dq(cmd, i)[1]
            add(cmd[i:j])
            i = j
        elif c == "`":
            j = cmd.find("`", i + 1)
            j = n if j == -1 else j + 1
            add(cmd[i:j])
            i = j
        elif c == "$":
            if cmd.startswith("$(", i):
                j = _skip_paren(cmd, i + 1)
            elif cmd.startswith("$'", i):
                j = _skip_ansi(cmd, i)
            else:
                j = i + 1
            add(cmd[i:j])
            i = j
        elif c == "#":
            if last == "" or last in " \t\n":
                j = cmd.find("\n", i)
                i = n if j == -1 else j
            else:
                add(c)
                i += 1
        elif c in "<>":
            if cmd.startswith("(", i + 1):
                j = _skip_paren(cmd, i + 1)  # process substitution
                add(cmd[i:j])
                i = j
                continue
            hm = _HEREDOC_RE.match(cmd, i) if c == "<" else None
            if hm:
                add(cmd[i : hm.end()])
                pending.append((len(parts), _hd(hm)[0]))
                i = hm.end()
            else:
                add(c)
                i += 1
        elif c == "(" or c == ")":
            flush()
            parts.append((c, ""))
            sep_before = ""
            i += 1
        else:  # ; & | newline
            two = cmd[i : i + 2]
            if c == "\n" and pending:
                pos = i + 1
                for idx, delim in pending:
                    term = _terminator(delim).search(cmd, pos)
                    if term:
                        attach = "\n" + cmd[pos : term.start()] + delim
                        pos = term.end() + 1
                    else:
                        attach = "\n" + cmd[pos:]
                        pos = n + 1
                    if idx < len(parts):
                        sep, text = parts[idx]
                        parts[idx] = (sep, text + attach)
                    else:
                        add(attach)
                pending.clear()
                flush()
                sep_before = "\n"
                i = min(pos, n)
                continue
            if two in ("&&", "||"):
                sep = two
            elif c == "&" and (two == "&>" or (i > 0 and cmd[i - 1] in "<>")):
                add(c)  # &> file, >&2, <&3
                i += 1
                continue
            elif c == "|" and i > 0 and cmd[i - 1] == ">":
                add(c)  # >| file
                i += 1
                continue
            elif two == "|&":
                sep = two
            else:
                sep = c
            flush()
            sep_before = sep
            i += len(sep)
    flush()
    return parts


def _operator(s: str, i: int) -> str:
    for op in (">>", ">|", ">&", "<<<", "<<-", "<<", "<&", "<>"):
        if s.startswith(op, i):
            return op
    return s[i]


def _lex(seg: str) -> Tuple[List[str], int, Optional[Tuple[str, bool]]]:
    """Words of one simple command with quotes resolved as a POSIX shell does, in linear time.

    Returns (words, where a heredoc body starts or -1, (delimiter, quoted) of that heredoc). A word that starts with
    an unquoted redirection operator is a _Redir (also when the operator is glued to the word before it, as in
    `echo hi>f`); `$(...)`, backticks and `<(...)` stay inside their word as written. Raises ValueError on an
    unterminated quote.
    """
    toks: List[str] = []
    pieces: List[str] = []
    n = len(seg)
    i = 0
    in_word = redir = atoms = False
    plain = ""  # the unquoted plain text of the word so far (an fd number or "&" in front of an operator)
    body = -1
    heredoc: Optional[Tuple[str, bool]] = None

    def flush() -> None:
        nonlocal in_word, redir, atoms, plain
        if in_word:
            word = "".join(pieces)
            toks.append(_Redir(word) if redir else word)
        pieces.clear()
        in_word = redir = atoms = False
        plain = ""

    while i < n:
        c = seg[i]
        if c == "\n":
            flush()
            if heredoc is not None:
                body = i + 1
                break
            i += 1
        elif c.isspace():
            flush()
            i += 1
        elif c == "\\":
            if i + 1 >= n:
                pieces.append("\\")
                i += 1
            elif seg[i + 1] == "\n":  # line continuation
                i += 2
                continue
            else:
                pieces.append(seg[i + 1])
                i += 2
            in_word = atoms = True
        elif c == "'":
            j = seg.find("'", i + 1)
            if j == -1:
                raise ValueError("unterminated quote")
            pieces.append(seg[i + 1 : j])
            in_word = atoms = True
            i = j + 1
        elif c == '"':
            text, j, closed = _read_dq(seg, i)
            if not closed:
                raise ValueError("unterminated quote")
            pieces.append(text)
            in_word = atoms = True
            i = j
        elif c == "$" and seg.startswith(("$(", "$'"), i):
            if seg[i + 1] == "(":
                j = _skip_paren(seg, i + 1)
                pieces.append(seg[i:j])
            else:
                j = _skip_ansi(seg, i)
                pieces.append(_ansi_text(seg[i + 2 : j - 1]))
            in_word = atoms = True
            i = j
        elif c == "`" and seg.find("`", i + 1) != -1:
            j = seg.find("`", i + 1) + 1
            pieces.append(seg[i:j])
            in_word = atoms = True
            i = j
        elif c in "<>":
            if seg.startswith("(", i + 1):
                j = _skip_paren(seg, i + 1)
                pieces.append(seg[i:j])
                in_word = atoms = True
                i = j
                continue
            if in_word and (redir or atoms or not (plain.isdigit() or plain == "&")):
                flush()
            hm = _HEREDOC_RE.match(seg, i) if c == "<" else None
            if hm:
                heredoc = _hd(hm)
            op = _operator(seg, i)
            pieces.append(op)
            in_word = redir = True
            i += len(op)
        else:
            m = _WORD_RUN.match(seg, i)
            run = m.group() if m else c
            pieces.append(run)
            in_word = True
            plain += run
            i += len(run)
    flush()
    return toks, body, heredoc


def _tokens(segment: str) -> Tuple[List[str], int, Optional[Tuple[str, bool]]]:
    try:
        return _lex(segment)
    except ValueError:
        return segment.split(), -1, None


def _split_redirs(tokens: List[str]) -> Tuple[List[str], List[Tuple[str, str, str]], List[str]]:
    """(words without redirections, [(fd or "&", operator, target)], the redirection words as written)."""
    clean: List[str] = []
    redirs: List[Tuple[str, str, str]] = []
    words: List[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        m = _REDIR_RE.match(tok) if isinstance(tok, _Redir) else None
        if m is None:
            clean.append(tok)
        else:
            target = m.group(3)
            words.append(tok)
            if not target and i + 1 < len(tokens) and not isinstance(tokens[i + 1], _Redir):
                i += 1
                target = tokens[i]
                words.append(target)
            redirs.append((m.group(1) or "", m.group(2), target))
        i += 1
    return clean, redirs, words


def _substitutions(text: str, literal: bool = False) -> List[str]:
    """Command text inside $(...), `...`, <(...) and >(...), except in single quotes (`literal`: a heredoc body)."""
    out: List[str] = []
    i = 0
    n = len(text)
    in_dq = False
    while i < n:
        m = _SUBST_SPECIAL.search(text, i)
        if m is None:
            break
        k = m.start()
        c = text[k]
        if c == "\\":
            i = k + 2
        elif c == "'":
            if in_dq or literal:
                i = k + 1
            else:
                e = text.find("'", k + 1)
                i = n if e == -1 else e + 1
        elif c == '"':
            if not literal:
                in_dq = not in_dq
            i = k + 1
        elif c == "`":
            e = text.find("`", k + 1)
            if e == -1:
                break
            out.append(text[k + 1 : e])
            i = e + 1
        elif c == "$" and text.startswith("'", k + 1) and not in_dq and not literal:
            i = _skip_ansi(text, k)
        elif text.startswith("(", k + 1) and (c == "$" or (c in "<>" and not in_dq)):
            e = _skip_paren(text, k + 1)
            out.append(text[k + 2 : e - 1 if text[e - 1 : e] == ")" else e])
            i = e
        else:
            i = k + 1
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


def _env_split(rest: List[str]) -> Optional[List[str]]:
    """The command of `env -S 'cmd args'` (also -S'cmd' and --split-string=...); None without such an option."""
    k = 0
    while k < len(rest):
        tok = rest[k]
        if tok in ("-S", "--split-string") and k + 1 < len(rest):
            value, after = rest[k + 1], rest[k + 2 :]
        elif tok.startswith("--split-string="):
            value, after = tok.split("=", 1)[1], rest[k + 1 :]
        elif tok.startswith("-S") and len(tok) > 2:
            value, after = tok[2:], rest[k + 1 :]
        elif tok in ("-u", "-C"):
            k += 2
            continue
        elif tok.startswith("-") or _ASSIGN_RE.match(tok):
            k += 1
            continue
        else:
            return None
        try:
            return [*shlex.split(value), *after]
        except ValueError:
            return None
    return None


def _unwrap(tokens: List[str]) -> List[List[str]]:
    """Forms of one simple command with wrappers removed: [[as written], [unwrapped], ...]."""
    forms = [tokens]
    t = list(tokens)
    for _ in range(8):
        if not t:
            break
        head = t[0]
        if "/" in head and not _ASSIGN_RE.match(head):
            bare = head.rsplit("/", 1)[-1]  # /usr/bin/npm, ./node_modules/.bin/eslint
            if not bare or bare in (".", ".."):
                break
            t = [bare, *t[1:]]
            forms.append(t)
            continue
        base = head
        if _ASSIGN_RE.match(head):
            t = t[1:]
        elif base == "env":
            split = _env_split(t[1:])
            if split is not None:
                t = split
            else:
                t = [x for x in _drop_opts(t[1:], "env") if not _ASSIGN_RE.match(x)] if len(t) > 1 else []
        elif base == "command" and len(t) > 1 and re.match(r"^-[a-zA-Z]*[vV]", t[1]):
            break  # `command -v x` looks x up, it does not run it
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
    """The script of `bash -c '...'`, `sh -lc "..."` etc. (`bash <<EOF` and `sh <<< '...'` are handled by the caller)."""
    if not tokens:
        return None
    if tokens[0].rsplit("/", 1)[-1] not in _SHELL_NAMES:
        return None
    for i, tok in enumerate(tokens[1:], 1):
        if tok.startswith("-") and "c" in tok[1:] and not tok.startswith("--"):
            rest = [t for t in tokens[i + 1 :] if t != "--"]
            return rest[0] if rest else None
    return None


def _stdin_shell(form: List[str]) -> bool:
    """A shell that reads its script from stdin: `sh`, `bash -s`, but not `bash x.sh` or `bash -c ...`."""
    clean = _split_redirs(form)[0]
    if not clean or clean[0].rsplit("/", 1)[-1] not in _SHELL_NAMES or _script_of(clean) is not None:
        return False
    return all(a.startswith("-") for a in clean[1:])


def _exec_commands(form: List[str]) -> List[List[str]]:
    """Commands that `find ... -exec cmd ... ;` runs (also -execdir, -ok, -okdir)."""
    if not form or form[0].rsplit("/", 1)[-1] != "find":
        return []
    out = []
    i = 0
    while i < len(form):
        if form[i] in ("-exec", "-execdir", "-ok", "-okdir"):
            j = i + 1
            while j < len(form) and form[j] not in (";", "+"):
                j += 1
            if j > i + 1:
                out.append(list(form[i + 1 : j]))
            i = j
        i += 1
    return out


def _git_dirs(form: List[str]) -> List[str]:
    """The directories that `git -C <dir>` options move into, in order."""
    if not form or form[0].rsplit("/", 1)[-1] != "git":
        return []
    out = []
    i = 1
    while i < len(form) and form[i].startswith("-"):
        if form[i] == "-C" and i + 1 < len(form):
            out.append(form[i + 1])
            i += 2
        elif form[i] in ("-c", "--git-dir", "--work-tree", "--namespace"):
            i += 2
        else:
            i += 1
    return out


def _pipe_text(prev: Tuple[List[str], Optional[str]]) -> Optional[str]:
    """The text a command writes into a pipe when it is only echo, printf or cat of literal text (for `... | sh`)."""
    words, body = prev
    clean, redirs, _ = _split_redirs(words)
    if not clean:
        return None
    base = clean[0].rsplit("/", 1)[-1]
    args = [a for a in clean[1:] if not a.startswith("-")]
    if base == "echo":
        return " ".join(args)
    if base == "printf":
        return " ".join(args[1:] if args and "%" in args[0] else args)
    if base == "cat":
        here = [t for _, op, t in redirs if op == "<<<"]
        return here[0] if here else body
    return None


def _cd_join(cwd: str, target: str) -> str:
    """The directory reached by `cd target` from `cwd`; "" is the directory the command line started in."""
    if target.startswith("/"):
        new = posixpath.normpath(target)
    else:
        new = posixpath.normpath(posixpath.join(cwd, target) if cwd else target)
    if new == WORKDIR or new.startswith(WORKDIR + "/"):  # the sandbox's repository is where a run starts
        new = new[len(WORKDIR) + 1 :]
    return "" if new == "." else new


def _next_cwd(cmd: str, args: List[str], cwd: str, dirs: List[str]) -> str:
    """The directory after `cd`, `pushd` or `popd`; a target that is not a plain literal path resets to the start."""
    if cmd == "popd":
        return dirs.pop() if dirs else ""
    i = 0
    while i < len(args) and args[i].startswith("-") and args[i] != "-":
        i += 1
        if args[i - 1] == "--":
            break
    if i >= len(args):
        return ""  # a bare `cd` goes home
    target = args[i]
    if target == "-" or target.startswith(("~", "+")) or any(ch in target for ch in "$`*?[{"):
        return ""
    if cmd == "pushd":
        dirs.append(cwd)
    return _cd_join(cwd, target)


def _is_query(tokens: List[str]) -> bool:
    """`which x`, `type x`, `command -v x`: they look a name up, they do not run it."""
    if tokens[0] in ("type", "which", "whereis", "hash"):
        return True
    return tokens[0] == "command" and len(tokens) > 1 and bool(re.match(r"^-[a-zA-Z]*[vV]", tokens[1]))


_SEG_CACHE: Dict[str, List[Dict[str, Any]]] = {}


def segments(command: str, _depth: int = 0, _cwd: str = "") -> List[Dict[str, Any]]:
    """Simple commands in a shell line, each with its argv and unwrapped views (normalised strings).

    A segment also holds "cwd": the directory (relative to where the line started) it runs in after the `cd` and
    `pushd` commands before it; a `cd` to something that is not a literal path counts as the start directory.
    """
    if _depth == 0 and not _cwd:
        cached = _SEG_CACHE.get(command)
        if cached is None:
            cached = _segments(command, 0, "")
            if len(_SEG_CACHE) >= 16:
                _SEG_CACHE.clear()
            _SEG_CACHE[command] = cached
        return list(cached)
    return _segments(command, _depth, _cwd)


def _segments(command: str, depth: int, start: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if depth > 4:
        return out
    cwd = start
    scopes: List[str] = []  # directories to return to at the `)` of a subshell
    dirs: List[str] = []  # the pushd stack
    prev: Optional[Tuple[List[str], Optional[str]]] = None
    for sep, part in _split_top(command):
        if sep == "(":
            scopes.append(cwd)
            continue
        if sep == ")":
            if scopes:
                cwd = scopes.pop()
            continue
        part = _RESERVED_RE.sub("", part, count=1).strip()  # `then git push`, `! git push`, `do cmd`
        if not part or part in _CLOSERS:
            continue
        tokens, body_start, heredoc = _tokens(part)
        clean, redirs, redir_words = _split_redirs(tokens)
        if tokens and isinstance(tokens[0], _Redir):
            tokens = [*clean, *redir_words]  # `>f cmd` runs like `cmd >f`
        here = cwd
        if clean and clean[0] in _CD_NAMES:
            cwd = _next_cwd(clean[0], clean[1:], cwd, dirs)
        is_cd = bool(clean) and clean[0] == "cd"
        body: Optional[str] = None
        if body_start >= 0:
            body = part[body_start:]
            if heredoc and heredoc[0] and body.endswith(heredoc[0]):
                body = body[: -len(heredoc[0])]
        forms = _unwrap(tokens) if tokens else []
        views: List[str] = []
        for form in forms:
            text = " ".join(form)
            if text and text not in views:
                views.append(text)
        if tokens and _is_query(tokens):
            views = [tokens[0]]
        seg_cwd = here
        for form in forms:
            moved = _git_dirs(form)
            if moved:
                for d in moved:
                    seg_cwd = _cd_join(seg_cwd, d)
                break
        if not is_cd:  # a plain `cd` is not reported as a command, but its substitutions still run
            out.append(
                {
                    "raw": part,
                    "argv": forms[-1] if forms else tokens,
                    "argv_raw": tokens,
                    "views": views,
                    "heredoc": body,
                    "cwd": seg_cwd,
                }
            )
        scripts: List[str] = []
        for form in forms:
            script = _script_of(form)
            if script:
                scripts.append(script)
            elif form and form[0] == "eval" and len(form) > 1:
                scripts.append(" ".join(form[1:]))
            scripts += [shlex.join(inner) for inner in _exec_commands(form)]
        if any(_stdin_shell(form) for form in forms):
            scripts += [target for _, op, target in redirs if op == "<<<"]  # sh <<< 'git push'
            if sep in ("|", "|&") and prev is not None:  # echo 'git push' | sh
                piped = _pipe_text(prev)
                if piped:
                    scripts.append(piped)
        if body is not None and any(f and f[0].rsplit("/", 1)[-1] in _SHELL_NAMES for f in forms):
            scripts.append(body)
        for script in dict.fromkeys(scripts):
            out += _segments(script, depth + 1, seg_cwd)
        subs = _substitutions(part if body_start < 0 else part[: body_start - 1])
        if body is not None and heredoc and not heredoc[1]:
            subs += _substitutions(body, literal=True)  # an unquoted heredoc delimiter lets the body expand
        for sub in subs:
            out += _segments(sub, depth + 1, seg_cwd)
        prev = (tokens, body)
    return out


def matches_command(patterns: List[str], segment: Dict[str, Any]) -> bool:
    return any(re.search(p, v) for p in patterns for v in segment["views"])


def _git_sub(segment: Dict[str, Any]) -> Tuple[str, List[str]]:
    argv = segment["argv"]  # the most unwrapped form has git's global options removed
    if argv and argv[0].rsplit("/", 1)[-1] == "git":
        return (argv[1] if len(argv) > 1 else "", list(argv[2:]))
    for v in reversed(segment["views"]):
        if v.startswith("git "):
            parts = v.split()
            return (parts[1] if len(parts) > 1 else "", parts[2:])
    return ("", [])


def _prefix_of(arg: str, option: str, shortest: int = 4) -> bool:
    """True when `arg` is `option` or an abbreviation of it git still accepts (`--mess`, `--message`)."""
    return len(arg) >= shortest and option.startswith(arg)


def is_git(segment: Dict[str, Any], sub: str) -> bool:
    """True when the segment runs `git <sub>` with any options: an executed attempt counts, even `--dry-run` or
    `--help` (the frozen checker contract: "never push" means never run `git push`)."""
    return _git_sub(segment)[0] == sub


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


def _join_cwd(cwd: str, p: str) -> str:
    """A path as written in a command that ran in `cwd`, relative to the directory the command line started in."""
    if p == "*":
        return p
    while p.startswith("./"):
        p = p[2:]
    if cwd and not p.startswith("/"):
        p = cwd + "/" + p
    if cwd or "//" in p or "/./" in p or ".." in p.split("/"):
        p = posixpath.normpath(p)
    return p


def shell_write_targets(command: str) -> List[Dict[str, str]]:
    """Files a command line writes, creates, deletes or renames: [{"path", "op"}], op in write|delete|rename|unknown.

    Redirections are read from the command text (`echo hi>f`, `cat a >> b`, `&> f`, `2> f`, `>| f`; not `grep '>' f`,
    `2>&1` or `/dev/null`). Paths are relative to the directory the line started in: a literal `cd dir` or `pushd dir`
    before the command is followed.
    """
    found: List[Dict[str, str]] = []
    cwd = ""

    def add(path: str, op: str = "write") -> None:
        p = path.strip().strip("'\"")
        if p and p not in ("-", "{}") and not p.startswith(("&", "/dev/")):
            found.append({"path": _join_cwd(cwd, p), "op": op})

    for seg in segments(command):
        cwd = seg.get("cwd", "")
        clean, redirs, _ = _split_redirs(seg["argv"])
        for _fd, op, target in redirs:
            if op in (">", ">>", ">|") or (op == ">&" and not re.match(r"^(\d+|-)$", target)):
                add(target)
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
        if base.startswith("requirements") and base.endswith((".txt", ".in")):
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
                redirect = _REDIR_RE.match(a)
                if redirect:  # `2>&1`, `>/dev/null`, `> install.log`: output handling, never a package
                    skip = not redirect.group(3)
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


def _readable(regex: str) -> str:
    """A regex as people wrote it (escapes removed), for messages."""
    return re.sub(r"\\(.)", r"\1", regex)


def _verdict(verdict: str, evidence: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {"verdict": verdict, "evidence": evidence or []}


def _norm_path(p: str) -> str:
    p = p.strip().strip("'\"")
    while p.startswith("./"):
        p = p[2:]
    if p.startswith(WORKDIR + "/"):
        p = p[len(WORKDIR) + 1 :]
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
    # Changes made by an allowed command (a generator) are fine; direct edits still violate.
    allow_via = list(params.get("allow_via") or [])
    via = allow_via and any(
        ev.get("exit_code") in (0, None) and matches_command(allow_via, seg) for _, ev, seg in _executed_shell(run)
    )
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
        if via:
            continue
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
    # Any change counts as exercising the rule: a run that did the task without adding a package obeyed it.
    exercised = bool(_changed(run)) or any(glob_match(manifests, f["path"]) for f in _changed(run))
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
            return _verdict(
                "violated",
                [_ev("diff", f"new file {f['path']} lacks {_readable(str(params['regex']))}", path=f["path"])],
            )
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
    return f'{DENY_MARK} "{rule.get("text", "")}"{where}.{detail}'


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


_CAT_HEREDOC_RE = re.compile(r"\$\(\s*cat\s+(?=<<)")


def _resolve_message(text: str) -> str:
    """`$(cat <<'EOF' ... EOF)` inside a commit message becomes the heredoc body, as the shell would run it."""
    out: List[str] = []
    pos = 0
    while True:
        m = _CAT_HEREDOC_RE.search(text, pos)
        if m is None:
            break
        hm = _HEREDOC_RE.match(text, m.end())
        nl = text.find("\n", hm.end()) if hm else -1
        term = _terminator(_hd(hm)[0]).search(text, nl + 1) if hm and nl != -1 else None
        close = text.find(")", term.end()) if term else -1
        if term is None or close == -1:
            out.append(text[pos : m.end()])
            pos = m.end()
            continue
        out.append(text[pos : m.start()])
        out.append(text[nl + 1 : term.start()].rstrip("\n"))
        pos = close + 1
    out.append(text[pos:])
    return "".join(out)


def _commit_messages(command: str) -> List[str]:
    """The messages `git commit` commands in a command line would record (-m, -am, -sm, -mMSG, --message=MSG, -F -)."""
    out = []
    for seg in segments(command):
        if not is_git(seg, "commit"):
            continue
        args = _git_sub(seg)[1]
        msgs: List[str] = []
        i = 0
        while i < len(args):
            a = args[i]
            i += 1
            if a == "--":
                break
            if isinstance(a, _Redir):
                continue
            if a.startswith("--"):
                name, eq, value = a[2:].partition("=")
                if not (_prefix_of("--" + name, "--message", 5) or _prefix_of("--" + name, "--file", 5)):
                    continue
                given = bool(eq)
                if not given and i < len(args):
                    value = args[i]
                    given = True
                    i += 1
                if _prefix_of("--" + name, "--message", 5):
                    if given:
                        msgs.append(value)
                elif value == "-" and seg.get("heredoc") is not None:
                    msgs.append(str(seg["heredoc"]).rstrip("\n"))
            elif a.startswith("-") and len(a) > 1:
                # A cluster of short options: the first that takes a value ends it (-am MSG, -sm MSG, -mMSG).
                for j, ch in enumerate(a[1:], 1):
                    if ch in "mFcCt":
                        value = a[j + 1 :]
                        given = bool(value)
                        if not given and i < len(args):
                            value = args[i]
                            given = True
                            i += 1
                        if ch == "m" and given:
                            msgs.append(value)
                        elif ch == "F" and value == "-" and seg.get("heredoc") is not None:
                            msgs.append(str(seg["heredoc"]).rstrip("\n"))
                        break
                    if ch in "Su":  # optional value glued to the option
                        break
        if msgs:
            out.append(_resolve_message("\n\n".join(msgs)))
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
                given = action.get("targets")  # a hook resolves them against the working directory and symlinks
                if given is None:
                    given = shell_write_targets(str(action.get("command") or ""))
                targets = [t for t in given if t["path"] != "*"]
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


def transcript_recognized(text: str) -> bool:
    """True when the text is a Claude Code transcript (JSON lines that hold `message.content`)."""
    for line in text.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        msg = obj.get("message") if isinstance(obj, dict) else None
        if isinstance(msg, dict) and isinstance(msg.get("content"), (list, str)):
            return True
    return False


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
                    # Only our own hook's refusal counts as one (the agent shows it as an error result); a command whose
                    # output merely mentions a hook being denied or blocked ran.
                    if block.get("is_error") and DENY_MARK in body[:600]:
                        ev2["denied"] = True
                    m = re.search(r"Exit code (\d+)", body)
                    ev2["exit_code"] = (int(m.group(1)) if m else 1) if block.get("is_error") else 0
    return events
