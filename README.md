# labbook — a Quarto lab notebook with Claude Code hooks for computational experiments

A lightweight framework that turns a code repository into a preregistered lab notebook for numerical
experiments run with (or by) Claude Code. It was built for the KOSMA-τ PDR code and is
project-agnostic.

What it enforces:

- **Preregistration.** No model run without an entry whose hypothesis is committed first
  (`lb.py run` refuses otherwise). Runs get IDs (`R-0001`), provenance (command, inputs and outputs with
  SHA-256, git commit, compiler, dirty patch if the tree was dirty) and a per-run directory.
- **Results in a ledger, not in prose.** Metrics go to `results.tsv` via `lb.py result` and are cited in
  the entries through a Quarto shortcode; figures come only from a per-entry `analysis.py`.
- **Events.** Hooks record what happened during a Claude Code session (protection violations, test-scope
  changes, run starts) as events `E-0001` that every entry must list or discard with a reason.
- **Protection.** A `PreToolUse` hook stops the assistant from editing protected paths (the ledger, the
  run records, the tool itself, reference data) by edit or by shell; a SHA-256 manifest written by the
  human is verified by the `Stop` hook.
- **Immutability.** Closed entries cannot be changed; corrections are new entries.
- **A book.** `lb.py book` renders all entries and session summaries as a Quarto book (PDF or HTML).

## Layout of this repository

| path | purpose |
|---|---|
| `tools/lb.py` | the command-line tool: `new`, `run`, `result`, `check`, `events`, `book`, `protect`, `preflight` |
| `hooks/labhook.py`, `hooks/lb_common.py` | Claude Code hooks (`SessionStart`, `PreToolUse`, `PostToolUse`, `Stop`) and the shared library |
| `settings.hooks.json` | the hook registration for `.claude/settings.json` |
| `laborbuch.toml.example` | configuration: notebook path, protected paths, run settings, book title |
| `skills/laborbuch/SKILL.md` | the working method as a Claude Code skill |
| `agents/protokoll-auditor.md` | an independent audit agent for finished sessions |
| `laborbuch/` | the notebook skeleton: Quarto config, shortcode extension, entry/plan/summary templates, conventions |
| `CLAUDE.laborbuch.md` | the binding rules, to be included from the project's `CLAUDE.md` |
| `Makefile.laborbuch` | convenience targets |

## Installation into a project

```
./install.sh /path/to/project            # copies tool, hooks, skill, agent, config; creates laborbuch/
cd /path/to/project
$EDITOR .claude/laborbuch.toml           # protected paths, book title, run settings
python3 tools/lb.py preflight            # quarto, TeX, git, hooks
python3 tools/lb.py protect              # human only: write the protection manifest
```

Add `@CLAUDE.laborbuch.md` to the project's `CLAUDE.md` so that the rules are loaded in every session.

The notebook directory may be a git repository of its own (a nested clone ignored by the project), so that
one notebook serves every code branch and every machine; the tool detects this and checks entry commits in
the notebook repository while taking code provenance from the project repository.

## Requirements

Python 3.11 (or `tomli` on 3.10), git, Quarto with a TeX engine for the PDF book, Claude Code for the hooks.

## Origin and licence

Developed 2026 in the KOSMA-τ project (Markus Röllig, Physikalischer Verein / University of Cologne).
MIT licence, see `LICENSE`.
