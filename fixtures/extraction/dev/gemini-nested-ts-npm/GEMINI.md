# Sagebrush Calendar

A shared team calendar. `web/` is the Vue client and `server/` is the Node API, both in
one npm workspace. Sub-directories have their own `GEMINI.md` with extra rules.

## Rules

* Use npm. Do not use yarn, pnpm or bun.
* `dist/` and `build/` hold build output. Never edit them by hand.
* Run "npm test" when you are done with a change.
* Do not commit; the maintainer reviews the working tree first.
* Keep explanations short.
* Follow the existing folder structure when adding files.
