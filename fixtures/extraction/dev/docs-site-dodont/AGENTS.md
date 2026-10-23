# Ironwood Docs

Documentation site for the Ironwood CLI, built with Docusaurus and Yarn 4. Pages live in
`docs/`; the sidebar is defined in `sidebars.js`. The pages in `docs/api/` are generated
from source comments by `yarn gen:api`.

## Commands

```bash
yarn install
yarn start    # local dev server on port 3000
yarn build
```

## Do

- Use Yarn for every command.
- Put new guides in `docs/guides/` and name the file in kebab-case, for example
  `docs/guides/getting-started.md`.
- Begin every new page with front matter that includes a `title:` field.
- Run `yarn build` before you finish a docs change, so broken links are caught.
- Start commit messages with `docs:`, `build:` or `chore:`.
- Use sentence case for headings.
- Link to other pages with relative paths.

## Don't

- Don't use npm or pnpm. The lockfile is `yarn.lock`.
- Don't edit anything in `docs/api/`; it is regenerated on every build.
- Don't leave `TODO` or `FIXME` markers in published pages.
- Don't write "simply" or "just" in instructions.
- Don't paste screenshots larger than 200 KB.
