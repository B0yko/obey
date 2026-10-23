# Moorhen

Moorhen is a feed reader. Node 22, npm, Express, SQLite.

Run `npm ci`, never `npm install`, so that `package-lock.json` is not rewritten by accident.

Dependency policy: @docs/policy/dependencies.md

The old `@docs/archive/old-rules.md` file is obsolete and only kept for history.

Keep server start-up fast; it runs in short-lived containers.
