# docs/

The site navigation is defined in `mkdocs.yml`, and images go in `docs/assets/`.

- Page file names are kebab-case, for example `docs/guides/release-process.md`.
- Never edit `docs/reference/` by hand; `tools/gen_reference.py` regenerates it.
- Don't leave `TODO` markers in pages.
- Start every new page with a single H1 heading.
- Write in the second person.

## Preview

```bash
uv run mkdocs serve
```
