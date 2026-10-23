# 6. Merging into agent settings files

Date: 2026-10-23 · Status: accepted

## Context

`.claude/settings.json`, `.gemini/settings.json` and the hook files of other agents often already hold the
user's own entries. Overwriting them would be destructive; appending blindly would duplicate entries on every run.

## Decision

- JSON files are parsed and rewritten with every user key and entry preserved, in their original order.
- obey's entries are recognised by their command, which always runs `.obey/hooks/obey_hook.py`; no extra marker
  key is added, because some agents validate their settings schema.
- Re-running `obey enforce` replaces obey's entries and leaves everything else alone, so it is idempotent.
- Before the first change a file is backed up under `.obey/backup/`. `--dry-run` prints the diff and writes nothing.
- `obey enforce --remove` deletes only obey's entries. If the result equals the backed-up original, the original
  bytes are restored exactly; a file obey created is deleted.
- obey never writes outside the repository (`~/.claude`, `~/.codex`, `~/.cursor` and the like are never touched).
  Tests assert this for every target.
- Files that obey owns completely (the OpenCode plugin, `.obey/`) are written whole.

## Consequences

Users can run `obey enforce` in CI or by hand repeatedly, and undo it cleanly.
