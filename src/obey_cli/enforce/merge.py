"""JSON-preserving, idempotent merges of obey's hook entries into agents' settings files.

obey's entries are recognised by their command, which always runs `.obey/hooks/obey_hook.py`, so no extra marker
key is needed. Merging replaces obey's previous entries and keeps every other key and entry in its original order.
Removing deletes only obey's entries; if what remains equals the backed-up original, the original bytes come back.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

MARKER = ".obey/hooks/obey_hook.py"
BACKUP_DIR = ".obey/backup"


def is_obey_entry(entry: Any) -> bool:
    return MARKER in json.dumps(entry)


def _strip(value: Any) -> Any:
    """Remove obey entries from lists of hook entries, dropping containers that become empty."""
    if isinstance(value, list):
        kept = [_strip(v) for v in value if not is_obey_entry(v) or _has_foreign_hooks(v)]
        return [v for v in kept if v not in ({}, [])]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(v, list | dict):
                stripped = _strip(v)
                if stripped in ({}, []) and v not in ({}, []):
                    continue
                out[k] = stripped
            else:
                out[k] = v
        return out
    return value


def _has_foreign_hooks(entry: Any) -> bool:
    # A matcher group shared with the user's own hooks keeps the user's hooks.
    if isinstance(entry, dict) and isinstance(entry.get("hooks"), list):
        return any(not is_obey_entry(h) for h in entry["hooks"])
    return False


def remove_obey(data: dict[str, Any]) -> dict[str, Any]:
    if isinstance(data, dict) and isinstance(data.get("hooks"), dict | list):
        hooks = _strip(data["hooks"])
        if isinstance(data["hooks"], list) and isinstance(hooks, list):
            hooks = [h for h in hooks if not is_obey_entry(h)]
        out: dict[str, Any] = dict(data)
        if hooks in ({}, []):
            out.pop("hooks")
        else:
            out["hooks"] = hooks
        return out
    return data


def add_hooks(data: dict[str, Any], hooks: Mapping[str, list[Any]]) -> dict[str, Any]:
    """Append obey's entries under data["hooks"][event] after removing any previous obey entries."""
    clean = remove_obey(data)
    out = dict(clean)
    current = out.get("hooks")
    merged: dict[str, Any] = dict(current) if isinstance(current, dict) else {}
    for event, entries in hooks.items():
        merged[event] = [*merged.get(event, []), *entries]
    out["hooks"] = merged
    return out


def _indent_of(text: str) -> int:
    for line in text.splitlines()[1:]:
        stripped = line.lstrip(" ")
        if stripped and len(stripped) != len(line):
            return len(line) - len(stripped)
    return 2


def dumps_like(data: Any, original: str | None) -> str:
    indent = _indent_of(original) if original else 2
    return json.dumps(data, indent=indent, ensure_ascii=False) + "\n"


class Plan:
    """Files to write, with the original content for diffs, backups and removal."""

    def __init__(self, root: Path):
        self.root = root
        self.changes: dict[str, tuple[str | None, str | None]] = {}  # path -> (before, after); after None = delete

    def put(self, rel: str, content: str | None) -> None:
        path = self.root / rel
        before = path.read_text(encoding="utf-8") if path.exists() else None
        if before != content:
            self.changes[rel] = (before, content)

    def merge_json(self, rel: str, edit: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        path = self.root / rel
        before = path.read_text(encoding="utf-8") if path.exists() else None
        data = json.loads(before) if before and before.strip() else {}
        if not isinstance(data, dict):
            raise ValueError(f"{rel} is not a JSON object; refusing to change it")
        after_data = edit(data)
        if before is not None and after_data == data:
            return
        backup = self.root / BACKUP_DIR / (rel + ".orig")
        if not after_data:
            # Only obey's entries were in a file obey created: delete it, or restore the backup when one exists.
            if backup.exists():
                self.changes[rel] = (before, backup.read_text(encoding="utf-8"))
            else:
                self.changes[rel] = (before, None)
            return
        if backup.exists():
            original = backup.read_text(encoding="utf-8")
            if json.loads(original or "{}") == after_data:
                self.changes[rel] = (before, original)
                return
        self.changes[rel] = (before, dumps_like(after_data, before))

    def diff(self) -> str:
        import difflib

        out: list[str] = []
        for rel, (before, after) in sorted(self.changes.items()):
            out += difflib.unified_diff(
                (before or "").splitlines(keepends=True),
                (after or "").splitlines(keepends=True),
                fromfile=f"a/{rel}" if before is not None else "/dev/null",
                tofile=f"b/{rel}" if after is not None else "/dev/null",
            )
        return "".join(out)

    def apply(self) -> list[str]:
        root = self.root.resolve()
        written = []
        for rel, (before, after) in sorted(self.changes.items()):
            path = (self.root / rel).resolve()
            if not path.is_relative_to(root):  # obey never writes outside the repository
                raise ValueError(f"refusing to write outside the repository: {rel}")
            if before is not None and after is not None and rel.endswith(".json") and not rel.startswith(".obey/"):
                backup = self.root / BACKUP_DIR / (rel + ".orig")
                if not backup.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    backup.write_text(before, encoding="utf-8")
            if after is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(after, encoding="utf-8")
                if rel.endswith((".py", "pre-commit")) and rel.startswith(".obey/"):
                    path.chmod(0o755)
            written.append(rel)
        return written
