# Release rules

Releases are cut by CI from the `main` branch. Release notes are generated from commit
messages, which is why the message format matters. The version number lives in
`pyproject.toml`.

## Rules

- Commit messages must follow Conventional Commits.
- Never run `git push`; releases are pushed by CI after review.
- Bump the version only when asked.

@checklist.md
