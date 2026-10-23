# Demo data for `obey demo`

`obey demo` replays agent runs recorded in the obey study on the study's TypeScript repository
(`study/repos/ts-web`, shipped in the package as the demo repository) and re-scores them with the current checkers.
It needs no API key and no Docker.

- `obey.yaml`: the ten rules of the study's TypeScript repository, in their imperative phrasing.
- `runs/before.jsonl.gz`: normalised run records from the main experiment (imperative and no-rule conditions).
- `runs/after.jsonl.gz`: the same probes re-run with hooks from `obey enforce`.
- `runs/meta.json`: agent, version, model, dates and cost of those runs.

The files are built by `eval/build_demo.py` from the study's raw records.
