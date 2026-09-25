# labbook reference

## Command line (`python3 tools/lb.py …`)

| Command | Purpose |
|---|---|
| `new <slug> --title T` | create `entries/<date>_<slug>/entry.qmd` from the template (stamped `opened`), plus `analysis.py` and `fig/` |
| `close <id> [--verdict V]` | set `status: closed`, the verdict and the `closed` timestamp; refused (and nothing changed) if the entry would not pass the check |
| `session start <slug> [--title T]` | begin an autonomous session: `sessions/<date>_<slug>/plan.qmd` |
| `session end` | write `summary.qmd` with the generated trace statistics; close the session |
| `run --entry ID [--param k=v]… [--input FILE]… [--output GLOB]… [--description D] -- CMD …` | run `CMD` from the repository root with provenance; refuses without a committed hypothesis |
| `result RUN --metric M --value X [--unit U] [--reference Y] --status keep\|discard\|info --description D` | append a metric to `results.tsv` |
| `check [--all] [--no-render]` | the checks of the Stop hook (only documents changed since the last pass, unless `--all`) |
| `events [--open]` | event list; `--open` = not yet documented |
| `trace-stats [--session ID]` | statistics from the mechanical trace |
| `book [--format pdf\|html] [--no-render]` | render all entries and sessions as a Quarto book into `_book/<format>/` (see *Book structure*) |
| `protect` | write the SHA-256 manifest of the protected files – **human only**, the hook blocks it for Claude |
| `preflight` | readiness for an unattended session (tools, hooks, manifest, plan, open events, disk) |

Exit code of `run` = exit code of `CMD`. The line `RUN R-NNNN exit=N …` is parsed by the PostToolUse hook.

Environment: `LB_ID_RANGE=LOW-HIGH` overrides `[run] id_range`.

## Configuration (`.claude/labbook.toml`)

| Key | Default | Meaning |
|---|---|---|
| `[paths] notebook` | `"labbook"` | notebook directory (may be a nested git repository, see below) |
| `[paths] archive` | `".labbook-archive"` | gzip copies of Claude Code transcripts at session end |
| `[book] title`, `author` | | title page of the book |
| `[protection] protected` | | glob patterns the assistant may not modify |
| `[protection] append_only` | | protected files that grow through the tool; HEAD must be a prefix of the working copy |
| `[relevance] code` | `[]` | changes create a `code` event (comment/whitespace-only changes do not) |
| `[relevance] comment_prefixes` | `["#"]` | line-comment markers for that comparison |
| `[relevance] deviation` | `[]` | changes create a `deviation` event (parameter space, tests, tolerances) |
| `[relevance] test_commands` | `[]` | regexes on shell commands; a PASS↔FAIL change creates an event |
| `[relevance] test_failure_pattern` | `FAILED\|… failed\|FAIL` | regex on test output that means failure |
| `[relevance] build_commands` | `[]` | regexes; a new failure signature creates a `build error` event |
| `[relevance] run_commands` | `['lb\.py\s+run\b']` | regexes; commands that register run events |
| `[run] require_committed_hypothesis` | `true` | preregistration |
| `[run] allow_dirty` | `true` | runs with uncommitted code allowed; the diff is saved as `dirty.patch` |
| `[run] compiler_command` | `""` | first output line goes into the provenance |
| `[run] env_vars` | `["OMP_NUM_THREADS"]` | environment variables recorded in the provenance |
| `[run] min_free_gb` | `10` | preflight threshold |
| `[run] id_range` | unset | `"LOW-HIGH"`: run IDs of this machine |
| `[check] render` | `"pdf"` | `pdf`, `html` or `off`: render test of changed documents |
| `[check] stop_check` | `"always"` | `always` or `session-only` (Stop hook checks only during a session) |
| `[check] max_stop_blocks` | `5` | after this many refused stops the session may end; problems go to `_state/UNRESOLVED.md` |
| `[trace] max_chars` | `4000` | truncation of tool input/output in the trace (a SHA-256 of the full text is kept) |
| `[trace] omit_response` | `["Read","Grep","Glob"]` | tools whose responses are recorded only as length and checksum |
| `[trace] archive_transcripts` | `true` | copy the transcript into `[paths] archive` at session end |

Patterns are relative to the repository root; `*` matches within one path segment, `**` across segments.

## Notebook layout

```
labbook/
  _quarto.yml  index.qmd  conventions.qmd      # skeleton (installed)
  _templates/  _extensions/labbook/            # templates, shortcodes (protected)
  entries/<YYYY-MM-DD_slug>/entry.qmd          # one experiment: text, analysis.py, fig/
  sessions/<YYYY-MM-DD_slug>/plan.qmd, summary.qmd, audit.qmd
  runs/R-NNNN/provenance.json, log.txt [, dirty.patch]
  results.tsv                                  # ledger of runs and metrics
  _state/events.jsonl                          # event ledger
  _trace/<date>_<session>.jsonl                # every hook call
  _state/state.json, _generated/, _book/       # local, ignored by git
```

### Entry schema

Frontmatter: `title`, `id` (= directory name), `date`, `opened` / `closed` (ISO timestamps with
offset, set by `new` and `close`; a closed entry that has `opened` must have a valid `closed` not
earlier than `opened`), `status` (`open|closed|discarded`),
`author`, `session`, `runs: [R-…]`, `events: [E-…]`, `discarded: {E-…: "reason"}`, `corrected: <id>`,
`verdict` (`confirmed|refuted|undecided|not-applicable`, required when closed), `reviewed_by` (human).

Required `##` sections, in order: Why · Hypothesis / Expectation · Method · Result · Verification ·
Interpretation · Consequences and next steps · Failed attempts · Deviations from plan (all non-empty
once the entry is closed; write "none" where applicable).

An event counts as documented when its ID is listed under `events:` or `runs:` or discarded with a
non-empty reason in any entry or session file. A run event is also documented when its run ID is listed.

### Book structure

`lb.py book` writes one chapter file per week into `_generated/book/` and a book profile
`_quarto-book.yml`:

- **part** = month (`September 2026`)
- **chapter** = ISO week (`Week 39 · 21–25 Sep 2026`); a week that spans two months is split
  between the two parts
- **section** = day (`Wednesday, 23 September 2026`)
- **subsection** = entry or session document (plan, summary, audit), each under its title with a
  metadata line: ID, opened/closed, status, verdict, runs. The document's own headings are shifted down
  two levels (code blocks untouched), and relative figure, link and include paths are rewritten.

A document belongs to the day of its `date` field. For a new entry that is the day it was opened;
for a retrospective entry it is the day of the work it records. Entries written before the
timestamps existed show the time of their first commit as *opened* and the time of the commit that
closed them as *closed*, marked "times from git history". The standalone per-entry render (the
check) is unchanged.

### Shortcodes

| Shortcode | Output |
|---|---|
| `{{< prov R-0007 >}}` | *Run R-0007, commit abc1234, 2026-09-16* (with a note if the tree was dirty) |
| `{{< run-param R-0007 key >}}` | the value of `--param key=…` of that run |
| `{{< result R-0007 metric >}}` | the latest value of the metric for that run from `results.tsv`, with unit |

Missing data render as a bold `[… missing …]` marker, never as an empty string.

## Ledger formats

The ledgers are append-only and keep the (German) field names of the first version, so that old
notebooks stay valid. English meaning:

**results.tsv** (tab-separated, header line):
`zeit` time · `lauf` run ID · `eintrag` entry ID · `commit` · `dirty` 0/1 · `art` kind (`lauf` = run
record, `ergebnis` = metric) · `metrik` metric · `wert` value · `einheit` unit · `referenz` reference
value · `status` (`keep|discard|info`, or `exit=N` for run records) · `beschreibung` description.

**runs/R-NNNN/provenance.json**:
`lauf` run ID · `eintrag` entry · `session` · `beschreibung` description · `befehl` command (list) ·
`parameter` {key: value} · `start` · `dauer_s` duration in s · `exit` · `git` {`commit`, `dirty`,
`geaenderte_dateien` changed files, `branch`} · `compiler` · `host` · `benutzer` user · `python` ·
`plattform` platform · `umgebung` recorded environment variables · `eingaben_sha256` inputs ·
`ausgaben_sha256` outputs.

**_state/events.jsonl**: `id` · `zeit` time · `session` (Claude session ID) · `art` kind · `detail` ·
`schluessel` de-duplication key. Kinds: `schutzverletzung` protection violation · `lauf` run ·
`code` code change · `abweichung` deviation · `plan-aenderung` plan change after the session start ·
`test-wechsel` test status change · `build-fehler` build error · `stop-limit` session ended with
unresolved problems.

**_trace/*.jsonl**: the hook payload per call plus `ts`; long values are replaced by
`{"gekuerzt": prefix, "laenge": length, "sha256": …}`, omitted responses by
`{"weggelassen": true, …}`; blocked calls carry `laborbuch_blockiert` (reason).

## Hooks

| Event | Mode | Action |
|---|---|---|
| SessionStart | `start` | trace; inject context: active session, open events, recent dead ends |
| PreToolUse (Edit/Write/MultiEdit/NotebookEdit/Bash) | `pre` | block writes to protected paths and closed entries (exit 2) |
| PostToolUse, PostToolUseFailure, SubagentStop | `post`/`fail` | trace; classify the change; create events |
| Stop | `stop` | full check of changed documents; refuse to stop while problems remain (bounded) |
| SessionEnd | `end` | trace; archive the transcript |

## Nested notebook repository and several machines

The notebook directory may be a git repository of its own (a clone ignored by the project), so that
one notebook serves all branches and machines. The tool detects this: entry commits and closed-entry
checks use the notebook repository, code provenance uses the project repository. Commit notebook
changes inside the notebook directory. When several machines write runs, give each an `id_range`
(or `LB_ID_RANGE`) so that run IDs cannot collide.

## Compatibility names (0.1)

| 0.1 (German) | 0.2 |
|---|---|
| `.claude/laborbuch.toml`, `.sha256` | `.claude/labbook.toml`, `.sha256` (either is found) |
| `[pfade] laborbuch`, `archiv` | `[paths] notebook`, `archive` |
| `[buch] titel`, `autor` | `[book] title`, `author` |
| `[schutz] geschuetzt`, `nur_anhaengen` | `[protection] protected`, `append_only` |
| `[relevanz] physik`, `kommentar_praefix`, `abweichung`, `test_befehle`, `test_fehler_muster`, `build_befehle`, `lauf_befehle` | `[relevance] code`, `comment_prefixes`, `deviation`, `test_commands`, `test_failure_pattern`, `build_commands`, `run_commands` |
| `[lauf] hypothese_commit_pflicht`, `dirty_erlaubt`, `compiler_befehl`, `umgebungsvariablen`, `min_frei_gb` | `[run] require_committed_hypothesis`, `allow_dirty`, `compiler_command`, `env_vars`, `min_free_gb` |
| `[pruefung] render = "aus"`, `stop_pruefung = "immer"\|"nur-session"`, `max_stop_blockaden` | `[check] render = "off"`, `stop_check = "always"\|"session-only"`, `max_stop_blocks` |
| `[trace] max_zeichen`, `ohne_antwort`, `transkripte_archivieren` | `[trace] max_chars`, `omit_response`, `archive_transcripts` |
| `neu`, `ergebnis`, `pruefe`, `ereignisse`, `trace-statistik`, `buch`, `schuetze`, `session ende` | `new`, `result`, `check`, `events`, `trace-stats`, `book`, `protect`, `session end` |
| `--titel`, `--eintrag`, `--eingabe`, `--ausgabe`, `--beschreibung`, `--metrik`, `--wert`, `--einheit`, `--referenz`, `--alle`, `--ohne-render`, `--offen` | `--title`, `--entry`, `--input`, `--output`, `--description`, `--metric`, `--value`, `--unit`, `--reference`, `--all`, `--no-render`, `--open` |
| shortcodes `ergebnis`, `lauf-param` | `result`, `run-param` |
| layout `eintraege/`, `_vorlagen/eintrag.qmd`, `zusammenfassung.qmd`, `konventionen.qmd`, `_generiert/`, `_buch/` | `entries/`, `_templates/entry.qmd`, `summary.qmd`, `conventions.qmd`, `_generated/`, `_book/` |

A notebook is treated as legacy (German layout) when it contains `_vorlagen/`.
Frontmatter keys and values of 0.1 (`datum`, `verworfen`, `urteil: bestaetigt`, `status: abgeschlossen`, …)
and German section headings are read as their English equivalents.
