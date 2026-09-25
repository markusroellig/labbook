# Changelog

## 0.2.0 – 2026-09-25

First release prepared for use outside the project it came from.

### Changed
- English names are canonical everywhere a user touches the framework: CLI subcommands and options,
  configuration sections and keys (`[paths] notebook`, `[protection] protected`, `[check] render = "off"`,
  ...), shortcodes (`result`, `run-param`), notebook layout (`entries/`, `_templates/`, `summary.qmd`,
  `conventions.qmd`, `_book/`), the skill (`labbook`), the audit agent (`labbook-auditor`),
  `CLAUDE.labbook.md`, `Makefile.labbook`, `.claude/labbook.toml`. The run marker printed by
  `lb.py run` is `RUN R-NNNN exit=N`.
- The German names of 0.1 keep working: configuration keys are mapped on load, `.claude/laborbuch.toml`
  is found, a notebook with `_vorlagen/` keeps its German layout, the German CLI names and shortcodes
  are aliases. Ledger formats (results.tsv, provenance.json, events.jsonl) are unchanged.
- Templates, conventions, skill and auditor are project-neutral; the KOSMA-tau configuration and
  conventions moved to `examples/kosma-tau/`.
- `install.sh`: `--notebook DIR`, `--upgrade`; merges the hooks into an existing
  `.claude/settings.json` (backup kept) instead of asking for a manual merge; adds the transcript
  archive to `.gitignore`; portable path rewriting (perl instead of GNU sed).
- The notebook `.gitignore` keeps rendered books, generated overviews, state and locks out of git.

### Fixed
- Protection bypass: a shell line that started with an `lb.py` call was exempt as a whole, so
  `python3 tools/lb.py check; rm labbook/results.tsv` passed. Every segment of a command line is now
  checked; the command run by `lb.py run -- ...` and redirections of `lb.py` output are checked too.
- `preflight` reported the Python version check as passed unconditionally.
- `tools/lb.py` could not import its library when run from the framework repository.

### Added
- Entry timestamps: `opened` (set by `lb.py new`, also when an older template lacks the field) and
  `closed` (set by the new `lb.py close <id> --verdict …`, which refuses and leaves the file unchanged
  if the entry would not pass the check). The checker requires a valid `closed` for closed entries
  that carry `opened`; older entries get both times from git history in the book.
- Book structure month › ISO week › day › entry: `lb.py book` generates one chapter per week
  (headings of the included documents shifted, relative paths rewritten); `--no-render` writes only
  the sources. The overview table shows opened/closed.
- Per-machine run-ID ranges (`[run] id_range`, env `LB_ID_RANGE`) for notebooks shared by several machines.
- Bytecode (`__pycache__`) excluded from the protection manifest (differs between Python versions).
- Test suite (`tests/`, pytest) and GitHub Actions workflow; end-to-end demo `examples/demo/run_demo.sh`.
- `docs/REFERENCE.md`: CLI, configuration, file formats, compatibility names.

## 0.1.0 – 2026-09-22

Extracted from the KOSMA-tau PDR project (German names, single project).
