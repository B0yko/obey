# Plover CLI

Plover is a command-line tool that renames photo batches. Rust 2021, clap for arguments.

Shared contributor notes: @docs/contributing.md
Naming reference: @docs/naming.md

The syntax for an import in your own notes looks like this (documentation only):

```text
@docs/sample-notes.md
```

## Rules

- No `.unwrap()` in `src/`; propagate errors with `?`.
- Do not leave `todo!()` or `unimplemented!()` in committed code.
- Run `cargo clippy -- -D warnings` after editing Rust files.
- Name Rust source files in snake_case.
- Do not commit; the maintainer commits.
- Prefer borrowing over cloning.
