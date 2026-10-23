# Changes to the extraction sets

The held-out split is frozen (`heldout/MANIFEST.sha256`). Any label or fixture correction is listed here with its
reason; nothing else changes after the freeze.

## dev

- `dev/claude-import-chain`: the imports inside `docs/agent/*.md` were written relative to the repository root
  (`@docs/agent/testing.md`). Claude Code resolves a relative import relative to the file that contains it
  ("Relative paths resolve relative to the file containing the import, not the working directory",
  https://code.claude.com/docs/en/memory#import-additional-files), so those files would never load. The imports now
  use paths relative to the importing file (`@testing.md`, `@release.md`, `@checklist.md`); labels are unchanged.
