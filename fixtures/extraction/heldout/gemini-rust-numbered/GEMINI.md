# Sundial

Sundial is a cron-expression parsing crate written in Rust. Its only runtime dependencies
are `chrono` and `thiserror`.

## Contribution rules

1. Code
   1. Do not use `unsafe` anywhere in this crate.
   2. Do not use `panic!`, `todo!` or `unimplemented!`.
   3. Prefer `&str` parameters over `String` where ownership is not needed.
2. Process
   1. Run `cargo test` after every code change.
   2. Never run `git push`.
3. Dependencies
   1. Do not add crates other than `chrono` and `thiserror`.
4. Replies
   1. Finish every reply with a line `Outcome:` followed by `done`, `blocked` or `partial`.
   2. Keep the parser readable and comment tricky edge cases.
