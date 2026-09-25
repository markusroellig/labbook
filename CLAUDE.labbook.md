# Lab-notebook obligation

Numerical experiments, tests of model behaviour, debugging attempts with model runs and
autonomous sessions are documented in the Quarto lab notebook under `labbook/`.
Working method and rules: skill `labbook` (`.claude/skills/labbook/SKILL.md`) – read before the first
experiment of a session.

Binding:
- No model run without an entry with a committed hypothesis; runs only through `python3 tools/lb.py run`.
- Every reported event `E-NNNN` is listed in the frontmatter of an entry under `events:` or
  `discarded:` (with a concrete justification).
- Figures only from `analysis.py`; numbers via shortcode from `results.tsv`/provenance.
- Do not change tests, tolerances, time limits, parameter grids and reference data to obtain
  results. Do not bypass protected files; report problems to the human.
- Closed entries are immutable; corrections as a new entry.
- Commit messages for experiments begin with the entry ID.
