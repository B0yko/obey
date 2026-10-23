---
applyTo: "tests/**/*.py"
---

# Test rules

Tests run against an in-memory SQLite database that `tests/conftest.py` creates.

- Test files are named `test_<module>.py`.
- When you change code in `app/`, add or update a test in `tests/`.
- Use fixtures instead of module-level state.
