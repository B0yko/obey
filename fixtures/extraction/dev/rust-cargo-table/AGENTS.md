# Mossbridge

Mossbridge is a Rust library that parses and validates build manifests. The workspace has
two crates: `mossbridge` (the library) and `mossbridge-cli`.

## Commands

| Task | Command |
|---|---|
| Build | `cargo build` |
| Test | `cargo test --all` |
| Lint | `cargo clippy --all-targets` |
| Format | `cargo fmt` |

## Conventions

| Area | Rule |
|---|---|
| Errors | Never call `.unwrap()` in `src/`. Return `Result` and use `?`. |
| Unsafe | Do not write `unsafe` blocks. |
| Dependencies | Only `serde`, `thiserror` and `anyhow` may be added to `Cargo.toml` without approval. |
| Headers | New `.rs` files start with `// SPDX-License-Identifier: MIT` on the first line. |
| Lint | Run `cargo clippy --all-targets -- -D warnings` after editing Rust code. |
| Size | Keep modules under about 400 lines. |
| Naming | Prefer descriptive names over abbreviations. |
| Docs | Public items should have doc comments. |
| Reply | End your final message with a line starting `Summary:` followed by one sentence. |
