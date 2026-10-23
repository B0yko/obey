# Naming

Plover renames files in batches, so naming conventions matter in two places: the Rust code
base itself and the file names the tool produces.

## Code

- CLI flags use kebab-case, for example `--dry-run`.
- Do not abbreviate public type names.

## Produced file names

Renamed photos follow the pattern `YYYY-MM-DD_HHMMSS_<camera>.jpg`.
