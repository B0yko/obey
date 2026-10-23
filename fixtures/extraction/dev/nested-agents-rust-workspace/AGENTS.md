# Quarry

Cargo workspace for a columnar storage engine. Crates: `crates/core` (the engine),
`crates/server` and `crates/cli`. The core crate has its own `AGENTS.md`.

## Working agreement

- Use Cargo for everything; do not call `rustc` directly.
- `Cargo.lock` is maintained by Cargo. Do not edit it by hand.
- Commit only when asked.
- Run `cargo test --workspace` before finishing.
- Keep the public API of `crates/core` stable.
- Benchmarks, when you add them, must be reproducible.
