from __future__ import annotations

from obey_cli.parse_md import parse, plain

DOC = """---
description: TypeScript rules
globs: src/**/*.ts
alwaysApply: false
---
# Project

This is a small web app. It renders invoices.

## Do

- Use `pnpm` for all package operations.
- Keep components small
  and focused.

## Don't

1. Edit files in `migrations/`.
2. **Never** add `console.log` calls.

```bash
npm install  # example only, never a rule
```

You must run `pnpm test` before finishing. The build is fast.

| Rule | Why |
|------|-----|
| No `any` | type safety |

<!-- Always ignore this comment. -->
See @docs/style.md for more, but not `@docs/ignored.md`.
"""


def test_frontmatter_and_candidates() -> None:
    parsed = parse(DOC)
    assert parsed.frontmatter["globs"] == "src/**/*.ts"
    texts = [c.text for c in parsed.candidates]
    assert "Use pnpm for all package operations." in texts
    assert "Keep components small and focused." in texts
    assert "Edit files in migrations/." in texts
    assert "Never add console.log calls." in texts
    assert "You must run pnpm test before finishing." in texts
    assert "No any — type safety" in texts
    assert not any("npm install" in t for t in texts)
    assert not any("ignore this comment" in t for t in texts)
    assert not any("small web app" in t for t in texts)


def test_line_numbers_and_headings() -> None:
    parsed = parse(DOC)
    by_text = {c.text: c for c in parsed.candidates}
    pnpm = by_text["Use pnpm for all package operations."]
    assert (pnpm.line_start, pnpm.line_end) == (12, 12)
    assert pnpm.headings == ["Project", "Do"]
    small = by_text["Keep components small and focused."]
    assert (small.line_start, small.line_end) == (13, 14)
    mig = by_text["Edit files in migrations/."]
    assert mig.headings == ["Project", "Don't"]
    assert mig.code_spans == ["migrations/"]
    assert by_text["You must run pnpm test before finishing."].line_start == 25


def test_imports_skip_code_spans() -> None:
    parsed = parse(DOC)
    assert [i[0] for i in parsed.imports] == ["docs/style.md"]


def test_plain_strips_markup() -> None:
    assert plain("**Never** use [npm](https://example.com) or `yarn`") == "Never use npm or yarn"


def test_email_is_not_an_import() -> None:
    assert parse("Contact team@example.com for access.\n").imports == []
