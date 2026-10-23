# Skylark Platform

The key words "MUST", "MUST NOT", "SHOULD" and "SHOULD NOT" in this document are to be
interpreted as described in RFC 2119.

## Tooling

- Contributors MUST use bun. `npm`, `yarn` and `pnpm` MUST NOT be used.
- `bun.lock` MUST NOT be edited by hand.
- New runtime dependencies SHOULD be agreed in an issue before they are added.

## Process

- Changes MUST be small enough to review in one sitting.
- A commit MUST NOT be created unless the user asks for one.
- Agents MUST NOT push to any remote.
- The final message SHOULD end with a line starting `Done:` followed by a one-line summary.
