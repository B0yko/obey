# crates/core

The storage engine. It is synchronous; there is no async runtime in this crate.
Benchmarks live in `benches/` and are run with `cargo bench -p core`.

- No `unsafe` in this crate.
- No `println!`, `eprintln!` or `dbg!` in this crate; use `tracing`.
- New `.rs` files start with the line `// Copyright (c) Quarry contributors`.
- Do not add dependencies to this crate without approval.
- Prefer iterators over index loops.
