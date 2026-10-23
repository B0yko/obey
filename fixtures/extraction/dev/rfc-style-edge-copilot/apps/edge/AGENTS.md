# apps/edge

Edge workers that run on the CDN. Handlers live in `src/`, tests in `test/`.
Deployment settings are in `edge.config.json`.

## Requirements

- Code in this directory MUST NOT use `require()`; use ES module imports.
- Handlers SHOULD be stateless.
- A change in `src/` MUST be accompanied by a change in `test/`.

## Commands

```bash
bun test apps/edge
```
