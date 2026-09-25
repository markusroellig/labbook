# Contributing

Issues and pull requests are welcome. A few ground rules keep the framework small and trustworthy:

- **Standard library only** for the tool and the hooks (Python ≥ 3.11). They run inside every Claude
  Code tool call of a project; a dependency there is a liability.
- **Ledger formats are append-only.** `results.tsv`, `runs/*/provenance.json`, `_state/events.jsonl`
  and the trace keep their field names across versions, so that notebooks stay valid for years. New
  fields may be added; existing ones are never renamed or removed.
- **Compatibility.** Configuration keys, CLI names and shortcodes of earlier versions keep working
  (see the compatibility tables in `docs/REFERENCE.md`).
- **Hooks never block because of their own errors.** Internal failures go to the hook error log.
- **Tests.** `python -m pytest -q tests` must pass; a change to the protection or the checker comes
  with a test. `examples/demo/run_demo.sh` is part of the suite.
- Keep the protection honest: it is a guard-rail against careless or pressured changes, not a
  sandbox. Do not advertise it as more.
