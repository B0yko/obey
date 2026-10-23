# rust/

The compression core, built as a static library and linked into the collector.

- 🚫 No `.unwrap()` in `src/`; propagate errors with `?`.
- 🚫 Don't add crates to `Cargo.toml` without approval.
- ✅ Document every public function.

## Layout

- `src/` library code
- `benches/` benchmarks
- `tests/` integration tests
