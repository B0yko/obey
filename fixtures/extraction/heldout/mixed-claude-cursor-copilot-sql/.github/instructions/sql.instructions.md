---
applyTo: "**/*.sql"
---

Models are materialised by the scheduler as views or tables, depending on the layer. Ad-hoc
queries live in `analyses/`.

Naming and header rules for model files are in `.cursor/rules/models.mdc`.

- Do not use `DROP TABLE` or `TRUNCATE` in model files.
- Avoid vendor-specific functions unless a comment explains why.
