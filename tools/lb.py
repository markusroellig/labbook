#!/usr/bin/env python3
"""Lab-notebook tool (labbook).

  lb.py new <slug> --title "..."             Create an entry (with its `opened` timestamp)
  lb.py close <id> [--verdict V]             Close an entry (status, verdict, `closed` timestamp)
  lb.py session start <slug> --title "..."   Begin an autonomous session (creates the plan)
  lb.py session end                          End the session (summary + trace statistics)
  lb.py run --entry <id> [--param k=v] [--input FILE] [--output GLOB] [--description "..."] -- COMMAND ...
  lb.py result R-0001 --metric NAME --value X [--unit U] [--reference Y] --status keep|discard|info --description "..."
  lb.py check [--all] [--no-render]          All checks (the same ones the Stop hook runs)
  lb.py events [--open]                      Event list
  lb.py trace-stats [--session DIR]          Statistics from the mechanical trace
  lb.py book [--format pdf|html] [--no-render]  Render the book: part = month, chapter = week, section = day
  lb.py protect                              Write the protection manifest (MAINTAINER ONLY)
  lb.py preflight                            Check readiness for unattended runs

German names of earlier versions remain valid: neu, session ende, ergebnis, pruefe, ereignisse,
trace-statistik, buch, schuetze; --titel, --eintrag, --metrik, --wert, --einheit, --referenz,
--beschreibung, --alle, --ohne-render, --offen, --eingabe, --ausgabe.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import getpass
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT_HINT = Path(__file__).resolve().parent.parent
# Installed layout: <project>/.claude/hooks/lb_common.py; framework repository: <repo>/hooks/lb_common.py.
sys.path[:0] = [str(ROOT_HINT / ".claude" / "hooks"), str(ROOT_HINT / "hooks")]
import lb_common as C  # noqa: E402

# Column names of results.tsv. The ledger format keeps the German names of the first version
# (append-only files); docs/REFERENCE.md gives the English meaning of every column.
RESULTS_HEADER = ["zeit", "lauf", "eintrag", "commit", "dirty", "art", "metrik", "wert",
                  "einheit", "referenz", "status", "beschreibung"]

# German subcommand names of earlier versions -> English (canonical) name.
COMMAND_ALIASES = {"neu": "new", "ergebnis": "result", "pruefe": "check", "ereignisse": "events",
                   "trace-statistik": "trace-stats", "buch": "book", "schuetze": "protect"}

# Plan sections that preflight requires: (display name, accepted heading prefixes: English, German).
PLAN_SECTIONS = [
    ("Goal", ("Goal", "Ziel")),
    ("Hypotheses", ("Hypotheses", "Hypothesen")),
    ("Stop criteria", ("Stop criteria", "Abbruchkriterien")),
    ("Scope of action", ("Scope of action", "Handlungsspielraum")),
]

# Generated trace-statistics block in the session summary (English markers; the German markers
# of legacy summary templates are recognised as well).
TRACE_BLOCK_RE = re.compile(r"<!-- (?:TRACE-STATS:BEGIN|TRACE-STATISTIK:BEGINN).*?(?:TRACE-STATS:END|TRACE-STATISTIK:ENDE) -->",
                            re.S)
TRACE_BLOCK_BEGIN = "<!-- TRACE-STATS:BEGIN (generated) -->"
TRACE_BLOCK_END = "<!-- TRACE-STATS:END -->"


def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def slugify(s: str) -> str:
    s = s.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:50]


def fill(template: str, **kw) -> str:
    for k, v in kw.items():
        template = template.replace("{{" + k + "}}", v)
    return template


def first_section(secs: dict[str, str], *prefixes: str) -> str | None:
    """Content of the first section whose heading starts with one of the prefixes (English or German)."""
    for pref in prefixes:
        content = C.section_content(secs, pref)
        if content is not None:
            return content
    return None


def tsv_append(lb: C.LB, row: dict) -> None:
    with C.locked(lb.results):
        new = not lb.results.exists() or lb.results.stat().st_size == 0
        with open(lb.results, "a") as f:
            if new:
                f.write("\t".join(RESULTS_HEADER) + "\n")
            f.write("\t".join(str(row.get(k, "")).replace("\t", " ").replace("\n", " ")
                              for k in RESULTS_HEADER) + "\n")


# --------------------------------------------------------------------------- new

def cmd_new(lb: C.LB, a) -> None:
    eid = f"{C.today()}_{slugify(a.slug)}"
    d = lb.entries_dir / eid
    if d.exists():
        die(f"{d} already exists")
    (d / "fig").mkdir(parents=True)
    st = C.load_state(lb)
    sess = (st.get("aktive_session") or {}).get("id", "")
    opened = C.now_iso()
    text = fill(C.template(lb, "entry.qmd").read_text(), TITLE=a.title, ID=eid, DATE=C.today(),
                SESSION=sess, SLUG=slugify(a.slug), OPENED=opened)
    if not re.search(r"^opened:", text, re.M):   # template of an earlier version without timestamps
        text = re.sub(r"^(date:.*)$", lambda m: f'{m.group(1)}\nopened: "{opened}"\nclosed: ""', text, count=1, flags=re.M)
    (d / C.ENTRY_FILE).write_text(text)
    shutil.copy(C.template(lb, "analysis.py"), d / "analysis.py")
    print(lb.rel(d / C.ENTRY_FILE))


# --------------------------------------------------------------------------- close

def set_frontmatter(text: str, key: str, value: str, after: tuple[str, ...] = ()) -> str:
    """Set `key: value` in the frontmatter; a missing key is inserted after the first existing key of `after`."""
    end = text.find("\n---", 3)
    head, rest = text[:end], text[end:]
    line = f"{key}: {value}"
    if re.search(rf"^{key}:", head, re.M):
        return re.sub(rf"^{key}:.*$", lambda _: line, head, count=1, flags=re.M) + rest
    for k in after:
        if re.search(rf"^{k}:", head, re.M):
            return re.sub(rf"^({k}:.*)$", lambda m: m.group(1) + "\n" + line, head, count=1, flags=re.M) + rest
    return head + "\n" + line + rest


def cmd_close(lb: C.LB, a) -> None:
    path = lb.entries_dir / a.entry / C.ENTRY_FILE
    if not path.exists():
        die(f"Entry {a.entry} does not exist.")
    old = path.read_text()
    fm, _, ok = C.parse_frontmatter(old)
    if not ok:
        die(f"{lb.rel(path)}: frontmatter missing.")
    if C.normalize_status(fm.get("status")) == "closed":
        die(f"{lb.rel(path)} is already closed.")
    verdict = a.verdict or C.normalize_verdict(fm.get("verdict", ""))
    if not verdict:
        die("a closed entry needs a verdict: --verdict confirmed|refuted|undecided|not-applicable")
    new = set_frontmatter(old, "status", "closed")
    new = set_frontmatter(new, "verdict", verdict, after=("status",))
    new = set_frontmatter(new, "closed", f'"{C.now_iso()}"', after=("opened", "date"))
    path.write_text(new)
    probs = C.check_document(lb, path, {})
    if probs:
        path.write_text(old)
        die("entry not closed:\n" + "\n".join(f"- {p}" for p in probs))
    print(f"{lb.rel(path)} closed ({verdict}). Commit it; it is immutable from now on.")


# --------------------------------------------------------------------------- session

def cmd_session(lb: C.LB, a) -> None:
    if a.action == "start":
        st = C.load_state(lb)
        if st.get("aktive_session"):
            die(f"Session {st['aktive_session']['id']} is still active (run `session end` first).")
        sid = f"{C.today()}_{slugify(a.slug)}"
        d = lb.sessions_dir / sid
        d.mkdir(parents=True, exist_ok=False)
        (d / "plan.qmd").write_text(fill(C.template(lb, "plan.qmd").read_text(), TITLE=a.title or a.slug,
                                         ID=sid, DATE=C.today(), START=C.now_iso()))
        # state.json keys are internal and keep the names of the first version
        with C.state_tx(lb) as st:
            st["aktive_session"] = {"id": sid, "titel": a.title or a.slug, "verzeichnis": lb.rel(d),
                                    "start": C.now_iso(), "claude_sessions": [], "plan_committed": False}
        print(lb.rel(d / "plan.qmd"))
        print("Fill in and commit the plan before starting any runs.")
    else:  # end
        st = C.load_state(lb)
        s = st.get("aktive_session")
        if not s:
            die("no active session")
        d = lb.root / s["verzeichnis"]
        stats = trace_statistics(lb, s)
        z = d / lb.summary_name
        if not z.exists():
            z.write_text(fill(C.template(lb, "summary.qmd").read_text(), TITLE=s.get("titel", s["id"]), ID=s["id"],
                              DATE=C.today(), START=s["start"], END=C.now_iso(), ENDE=C.now_iso()))
        txt = z.read_text()
        block = TRACE_BLOCK_BEGIN + "\n" + stats + "\n" + TRACE_BLOCK_END
        txt = TRACE_BLOCK_RE.sub(lambda _: block, txt)
        z.write_text(txt)
        with C.state_tx(lb) as st:
            st["letzte_session"] = st.pop("aktive_session")
        print(lb.rel(z))


# --------------------------------------------------------------------------- run

def git_info(lb: C.LB) -> dict:
    commit = C.git(lb, "rev-parse", "HEAD").stdout.strip()
    status = C.git(lb, "status", "--porcelain", "--untracked-files=no").stdout
    ignore = lb.rel(lb.dir) + "/"
    dirty_files = [l[3:] for l in status.splitlines() if not l[3:].startswith(ignore)]
    return {"commit": commit, "dirty": bool(dirty_files), "geaenderte_dateien": dirty_files,
            "branch": C.git(lb, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()}


def next_run_id(lb: C.LB, run_cfg: dict) -> str:
    """Next run ID. Several machines sharing one notebook repository avoid collisions with a
    per-machine range: env LB_ID_RANGE="1000-1999" overrides [run] id_range; without either, max+1."""
    names = [p.name for p in lb.runs_dir.glob("R-*")]
    rng = os.environ.get("LB_ID_RANGE") or run_cfg.get("id_range") or ""
    if not rng:
        return C.next_id(names, "R")
    try:
        lo, hi = (int(x) for x in rng.split("-"))
    except ValueError:
        die(f"Run-ID range {rng!r} is not of the form LOW-HIGH.")
    nums = [int(n.split("-")[1]) for n in names if n.split("-")[1].isdigit()]
    nums = [n for n in nums if lo <= n <= hi]
    nxt = (max(nums) + 1) if nums else lo
    if nxt > hi:
        die(f"Run-ID range {rng} exhausted (next would be R-{nxt:04d}).")
    return f"R-{nxt:04d}"


def cmd_run(lb: C.LB, a) -> None:
    if not a.command:
        die("command after `--` is missing")
    entry = lb.entries_dir / a.entry / C.ENTRY_FILE
    if not entry.exists():
        die(f"Entry {a.entry} does not exist (run `lb.py new` first).")
    fm, body, _ = C.parse_frontmatter(entry.read_text())
    hyp = first_section(C.sections(body), "Hypothesis", "Hypothese")
    if C.is_empty_section(hyp):
        die("Section `## Hypothesis / Expectation` is empty. Formulate the hypothesis before the run.")
    run_cfg = lb.cfg.get("run", {})
    if run_cfg.get("require_committed_hypothesis", True) and not C.git_is_tracked_clean(lb, lb.rel(entry)):
        die(f"{lb.rel(entry)} is not committed or has uncommitted changes. "
            f"Commit the hypothesis first (preregistration).")
    st = C.load_state(lb)
    s = st.get("aktive_session")
    if s and not s.get("plan_committed"):
        plan = f"{s['verzeichnis']}/plan.qmd"
        if not C.git_is_tracked_clean(lb, plan):
            die(f"Plan {plan} of the active session is not committed.")
        with C.state_tx(lb) as st2:
            st2["aktive_session"]["plan_committed"] = True
    gi = git_info(lb)
    if gi["dirty"] and not run_cfg.get("allow_dirty", True):
        die("Working tree has uncommitted code changes; run not allowed (run.allow_dirty = false).")

    with C.locked(lb.runs_dir / "zaehler"):
        rid = next_run_id(lb, run_cfg)
        rdir = lb.runs_dir / rid
        rdir.mkdir()
    if gi["dirty"]:
        (rdir / "dirty.patch").write_text(C.git(lb, "diff", "HEAD", "--", *gi["geaenderte_dateien"]).stdout)
    params = dict(kv.split("=", 1) for kv in a.param)
    inputs = {f: C.sha256_file(lb.root / f) for f in a.input}
    compiler = ""
    if run_cfg.get("compiler_command"):
        r = subprocess.run(run_cfg["compiler_command"], shell=True, capture_output=True, text=True)
        compiler = (r.stdout.splitlines()[0] if (r.returncode == 0 and r.stdout)
                    else f"not determinable ({run_cfg['compiler_command']})")
    env_keys = run_cfg.get("env_vars", ["OMP_NUM_THREADS"])
    t0 = time.time()
    start = C.now_iso()
    with open(rdir / "log.txt", "w") as log:
        proc = subprocess.run(a.command, cwd=lb.root, stdout=log, stderr=subprocess.STDOUT)
    duration = time.time() - t0
    outputs = {}
    for pat in a.output:
        for f in sorted(glob.glob(str(lb.root / pat), recursive=True)):
            if Path(f).is_file():
                outputs[lb.rel(f)] = C.sha256_file(Path(f))
    # Provenance keys are part of the ledger format (German names of the first version, see docs/REFERENCE.md).
    prov = {
        "lauf": rid, "eintrag": a.entry, "session": (s or {}).get("id", ""),
        "beschreibung": a.description, "befehl": a.command, "parameter": params,
        "start": start, "dauer_s": round(duration, 3), "exit": proc.returncode,
        "git": gi, "compiler": compiler, "host": platform.node(), "benutzer": getpass.getuser(),
        "python": platform.python_version(), "plattform": platform.platform(),
        "umgebung": {k: os.environ.get(k, "") for k in env_keys},
        "eingaben_sha256": inputs, "ausgaben_sha256": outputs,
    }
    (rdir / "provenance.json").write_text(json.dumps(prov, indent=2, ensure_ascii=False))
    tsv_append(lb, {"zeit": start, "lauf": rid, "eintrag": a.entry, "commit": gi["commit"][:12],
                    "dirty": int(gi["dirty"]), "art": "lauf", "status": f"exit={proc.returncode}",
                    "beschreibung": a.description})
    tail = (rdir / "log.txt").read_text(errors="replace").splitlines()[-15:]
    print("\n".join(tail))
    # The `RUN <id> exit=<n>` marker is parsed by the PostToolUse hook to register the run event.
    print(f"RUN {rid} exit={proc.returncode} duration={duration:.1f}s log={lb.rel(rdir / 'log.txt')}")
    sys.exit(proc.returncode)


# --------------------------------------------------------------------------- result

def cmd_result(lb: C.LB, a) -> None:
    prov_p = lb.runs_dir / a.run / "provenance.json"
    if not prov_p.exists():
        die(f"Run {a.run} unknown")
    prov = json.loads(prov_p.read_text())
    try:
        float(a.value)
    except ValueError:
        die("--value must be a number")
    tsv_append(lb, {"zeit": C.now_iso(), "lauf": a.run, "eintrag": prov["eintrag"],
                    "commit": prov["git"]["commit"][:12], "dirty": int(prov["git"]["dirty"]),
                    "art": "ergebnis", "metrik": a.metric, "wert": a.value, "einheit": a.unit,
                    "referenz": a.reference, "status": a.status, "beschreibung": a.description})
    print(f"RESULT {a.run} {a.metric}={a.value} {a.unit} ({a.status})")


# --------------------------------------------------------------------------- check, events

def cmd_check(lb: C.LB, a) -> None:
    probs = C.full_check(lb, only_changed=not a.all, render=not a.no_render)
    if probs:
        print("\n".join(f"- {p}" for p in probs))
        sys.exit(1)
    print("Lab-notebook check passed.")


def cmd_events(lb: C.LB, a) -> None:
    refs = C.referenced_ids(lb)
    for e in C.read_events(lb):
        doc = C.is_documented(e, refs)
        if a.open and doc:
            continue
        print(f"{e['id']}  {'doc ' if doc else 'OPEN'}  {e['zeit'][:16]}  {C.event_label(e['art']):<40} {e['detail']}")


# --------------------------------------------------------------------------- trace-stats

def trace_statistics(lb: C.LB, session: dict | None) -> str:
    sids = set((session or {}).get("claude_sessions", []))
    since = (session or {}).get("start", "")
    recs = []
    for f in sorted(lb.trace_dir.glob("*.jsonl")):
        for line in f.read_text(errors="replace").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (sids and r.get("session_id") in sids) or (not sids and r.get("ts", "") >= since):
                recs.append(r)
    tools = collections.Counter()
    fails = collections.Counter()
    files = collections.Counter()
    cmds = []
    blocked = []
    for r in recs:
        ev, tool = r.get("hook_event_name"), r.get("tool_name", "")
        if r.get("laborbuch_blockiert"):
            blocked.append(r["laborbuch_blockiert"])
        if ev == "PostToolUse":
            tools[tool] += 1
        elif ev == "PostToolUseFailure":
            tools[tool] += 1
            fails[tool] += 1
        if ev in ("PostToolUse", "PostToolUseFailure"):
            ti = r.get("tool_input") or {}
            if isinstance(ti, dict):
                if tool in ("Edit", "Write", "MultiEdit") and ti.get("file_path"):
                    files[lb.rel(ti["file_path"])] += 1
                if tool == "Bash":
                    cmds.append((ev == "PostToolUseFailure", ti.get("command", "")))
    evs = [e for e in C.read_events(lb) if (e.get("session") in sids) or (not sids and e["zeit"] >= since)]
    refs = C.referenced_ids(lb)
    ts = [r["ts"] for r in recs if "ts" in r]
    out = ["### Trace statistics (generated mechanically)", ""]
    out.append(f"Period: {ts[0] if ts else '–'} to {ts[-1] if ts else '–'}; "
               f"Claude sessions: {len(sids) or 'unknown'}; trace records: {len(recs)}")
    out += ["", "| Tool | Calls | of which failed |", "|---|--:|--:|"]
    out += [f"| {t} | {n} | {fails[t]} |" for t, n in tools.most_common()]
    out += ["", "| Modified file | Changes |", "|---|--:|"]
    out += [f"| `{f}` | {n} |" for f, n in files.most_common(30)]
    nfail = sum(1 for fl, _ in cmds if fl)
    out += ["", f"Shell commands: {len(cmds)}, of which failed: {nfail}."]
    out += ["", "| Event | Kind | Detail | Documented |", "|---|---|---|---|"]
    out += [f"| {e['id']} | {C.event_label(e['art'])} | {e['detail'].replace('|', '/')} | "
            f"{'yes' if C.is_documented(e, refs) else '**no**'} |" for e in evs]
    if blocked:
        out += ["", f"**Blocked write attempts on protected paths: {len(blocked)}**", ""]
        out += [f"- {b}" for b in blocked]
    return "\n".join(out)


def cmd_trace(lb: C.LB, a) -> None:
    sess = None
    if a.session:
        st = C.load_state(lb)
        for cand in (st.get("aktive_session"), st.get("letzte_session")):
            if cand and a.session in (cand["id"], cand["verzeichnis"]):
                sess = cand
    print(trace_statistics(lb, sess))


# --------------------------------------------------------------------------- book

def write_overview(lb: C.LB) -> None:
    lb.generated_dir.mkdir(exist_ok=True)
    lines = ["## Entries", "", "| Entry | Opened | Closed | Status | Verdict | Runs | Review |",
             "|---|---|---|---|---|---|---|"]
    for e in sorted(lb.entries_dir.glob(f"*/{C.ENTRY_FILE}"), reverse=True):
        fm, _, _ = C.parse_frontmatter(e.read_text(errors="replace"))
        opened, closed, _ = C.entry_times(lb, e, fm)
        lines.append(f"| {fm.get('title', e.parent.name)} | {fmt_time(opened)} | {fmt_time(closed) if closed else '–'} | "
                     f"{fm.get('status', '')} | {fm.get('verdict', '')} | {', '.join(fm.get('runs') or [])} | "
                     f"{fm.get('reviewed_by') or '–'} |")
    opened = C.open_events(lb)
    lines += ["", f"## Open events ({len(opened)})", ""]
    lines += [f"- {e['id']} ({C.event_label(e['art'])}): {e['detail']}" for e in opened] or ["None."]
    lines += ["", "## Latest results", ""]
    if lb.results.exists():
        rows = [r.split("\t") for r in lb.results.read_text().splitlines()]
        hdr, data = rows[0], [r for r in rows[1:] if len(r) == len(rows[0])]
        res = [dict(zip(hdr, r)) for r in data if r[hdr.index("art")] == "ergebnis"][-15:]
        if res:
            lines += ["| Run | Metric | Value | Reference | Status |", "|---|---|--:|--:|---|"]
            lines += [f"| {r['lauf']} | {r['metrik']} | {r['wert']} {r['einheit']} | {r['referenz']} | {r['status']} |"
                      for r in reversed(res)]
    lb.overview_file.write_text("\n".join(lines) + "\n")


def yq(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


HEADING_RE = re.compile(r"^(#{1,4})(?=\s)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
# target of an image or link: `](path)`; captions may contain brackets, so the opening `[` is not matched
REL_LINK_RE = re.compile(r"(\]\()(?![a-z]+:|/|#|@)([^)\s]+)")
REL_INCLUDE_RE = re.compile(r"(\{\{<\s*include\s+)(?![a-z]+:|/)(\S+)")
SESSION_DOC_RANK = {"plan.qmd": 0, "summary.qmd": 2, "zusammenfassung.qmd": 2, "audit.qmd": 3}


def book_documents(lb: C.LB) -> list[dict]:
    """All entries and session documents with the day they belong to (their `date`, which for a new
    entry is the day it was opened and for a retrospective entry the day of the work it records),
    ordered by day and then by time."""
    docs = []
    for p in lb.entries_dir.glob(f"*/{C.ENTRY_FILE}"):
        fm, body, _ = C.parse_frontmatter(p.read_text(errors="replace"))
        opened, closed, from_git = C.entry_times(lb, p, fm)
        day = next((c[:10] for c in (str(fm.get("date") or ""), p.parent.name, opened)
                    if re.match(r"\d{4}-\d\d-\d\d", c[:10])), C.today())
        docs.append({"path": p, "fm": fm, "body": body, "day": day, "sort": (day, 1, opened or p.parent.name),
                     "opened": opened, "closed": closed, "from_git": from_git, "kind": "entry"})
    for sd in lb.sessions_dir.glob("*"):
        for name, rank in SESSION_DOC_RANK.items():
            p = sd / name
            if not p.exists():
                continue
            fm, body, _ = C.parse_frontmatter(p.read_text(errors="replace"))
            day = str(fm.get("date") or sd.name[:10])[:10]
            docs.append({"path": p, "fm": fm, "body": body, "day": day, "sort": (day, rank, sd.name),
                         "opened": str(fm.get("start") or ""), "closed": str(fm.get("end") or fm.get("ende") or ""),
                         "from_git": False, "kind": "session"})
    return sorted(docs, key=lambda d: d["sort"])


def fmt_time(iso: str) -> str:
    t = C.parse_iso(iso)
    return t.strftime("%Y-%m-%d %H:%M") if t else "–"


def demote(body: str, levels: int, rel_prefix: str) -> str:
    """Body of a document for inclusion below a heading: headings shifted down by `levels` (outside
    code fences, at most level 6) and relative figure/include paths made relative to the book file."""
    out, fence = [], None
    for line in body.splitlines():
        m = FENCE_RE.match(line)
        if m:
            fence = None if fence == m.group(1) else (fence or m.group(1))
        if fence is None:
            line = HEADING_RE.sub(lambda h: "#" * min(len(h.group(1)) + levels, 6), line)
            line = REL_LINK_RE.sub(lambda l: l.group(1) + rel_prefix + l.group(2), line)
            line = REL_INCLUDE_RE.sub(lambda l: l.group(1) + rel_prefix + l.group(2), line)
        out.append(line)
    return "\n".join(out)


def doc_block(lb: C.LB, d: dict, gen_dir: Path) -> str:
    fm, p = d["fm"], d["path"]
    title = fm.get("title") or p.parent.name
    if d["kind"] == "entry":
        meta = [f"`{p.parent.name}`", f"opened {fmt_time(d['opened'])}"]
        if d["closed"]:
            meta.append(f"closed {fmt_time(d['closed'])}")
        if d["from_git"]:
            meta.append("times from git history")
        if fm.get("retrospective"):
            meta.append("retrospective")
        meta.append(f"status {fm.get('status', '')}")
        if fm.get("verdict"):
            meta.append(f"verdict **{fm['verdict']}**")
        if fm.get("runs"):
            meta.append("runs " + ", ".join(fm["runs"]))
        if fm.get("reviewed_by"):
            meta.append(f"reviewed by {fm['reviewed_by']}")
    else:
        meta = [f"`{p.parent.name}/{p.name}`"]
        if d["opened"]:
            meta.append(f"start {fmt_time(d['opened'])}")
        if d["closed"]:
            meta.append(f"end {fmt_time(d['closed'])}")
    rel_prefix = os.path.relpath(p.parent, gen_dir).replace(os.sep, "/") + "/"
    return (f"### {title}\n\n*" + " · ".join(meta) + "*\n\n" + demote(d["body"], 2, rel_prefix).strip() + "\n")


def generate_book_sources(lb: C.LB) -> list[tuple[str, list[str]]]:
    """Write one chapter file per (month, ISO week) into the generated directory: part = month,
    chapter = week, section = day, subsection = entry or session document. Returns [(part title,
    [chapter files])], chapter paths relative to the notebook directory."""
    gen_dir = lb.generated_dir / "book"
    if gen_dir.exists():
        shutil.rmtree(gen_dir)
    gen_dir.mkdir(parents=True)
    weeks: collections.OrderedDict = collections.OrderedDict()
    for d in book_documents(lb):
        day = dt.date.fromisoformat(d["day"])
        iso = day.isocalendar()
        weeks.setdefault((day.strftime("%Y-%m"), iso[0], iso[1]), collections.OrderedDict()).setdefault(day, []).append(d)
    parts: collections.OrderedDict = collections.OrderedDict()
    for (month, year, week), days in weeks.items():
        first, last = min(days), max(days)
        span = first.strftime("%-d %b") if first == last else f"{first.strftime('%-d')}–{last.strftime('%-d %b')}"
        lines = ["---", f'title: "Week {week} · {span} {last.year}"', "---", ""]
        for day, docs in days.items():
            lines += [f"## {day.strftime('%A, %-d %B %Y')}", ""]
            for d in docs:
                lines += [doc_block(lb, d, gen_dir), ""]
        f = gen_dir / f"{month}_W{week:02d}.qmd"
        f.write_text("\n".join(lines))
        part = dt.date.fromisoformat(month + "-01").strftime("%B %Y")
        parts.setdefault(part, []).append(f.relative_to(lb.dir).as_posix())
    return list(parts.items())


def cmd_book(lb: C.LB, a) -> None:
    write_overview(lb)
    chapters = ["    - index.qmd", f"    - {lb.conventions.name}"]
    for part, files in generate_book_sources(lb):
        chapters += [f'    - part: "{part}"', "      chapters:"] + [f"        - {f}" for f in files]
    book = lb.cfg.get("book", {})
    yml = [f"# GENERATED by tools/lb.py book – do not edit", "project:", "  type: book",
           f"  output-dir: {lb.book_dir}/{a.format}", "book:", f"  output-file: {lb.dir.name}",
           f"  title: {yq(book.get('title', 'Lab notebook'))}",
           f"  author: {yq(book.get('author', ''))}", f'  date: "{C.today()}"', "  chapters:", *chapters,
           "format:", "  pdf:", "    documentclass: scrreprt", "    toc: true", "    toc-depth: 3", "    number-depth: 3",
           "  html:", "    toc: true", "    toc-depth: 3", "    number-depth: 3",
           "    embed-resources: false"]           # single-file HTML is for the per-entry check, not a website
    (lb.dir / f"_quarto-{lb.book_profile}.yml").write_text("\n".join(yml) + "\n")
    if a.no_render:
        print(f"Book sources written: {lb.rel(lb.generated_dir / 'book')}, {lb.rel(lb.dir / f'_quarto-{lb.book_profile}.yml')}")
        return
    commit = C.git(lb, "rev-parse", "--short", "HEAD").stdout.strip()
    r = subprocess.run(["quarto", "render", "--profile", lb.book_profile, "--to", a.format,
                        "-M", f"subtitle:As of commit {commit or 'unknown'}"], cwd=lb.dir)
    sys.exit(r.returncode)


# --------------------------------------------------------------------------- protect, preflight

def cmd_protect(lb: C.LB, a) -> None:
    # Maintainer only: the PreToolUse hook blocks this command for Claude sessions.
    n = C.write_manifest(lb)
    print(f"Protection manifest with {n} files written: {lb.rel(C.manifest_path(lb))}. Please commit it.")


def cmd_preflight(lb: C.LB, a) -> None:
    res = []

    def chk(name, ok, hint=""):
        res.append((ok, name, hint))

    chk(f"Python >= 3.11 or tomli (running {platform.python_version()})", sys.version_info >= (3, 11) or
        C.tomllib.__name__ == "tomli", "install Python 3.11+ or `pip install tomli`")
    chk("git repository", C.git(lb, "rev-parse", "HEAD").returncode == 0, "`git init` and a first commit")
    eng = lb.cfg.get("check", {}).get("render", "pdf")
    chk("quarto installed", eng == "off" or shutil.which("quarto") is not None,
        "https://quarto.org, or set [check] render = \"off\"")
    chk("TeX engine (xelatex)", eng != "pdf" or shutil.which("xelatex") is not None,
        "TeX Live or `quarto install tinytex`, or set [check] render = \"html\"")
    s = lb.root / ".claude" / "settings.json"
    chk("Hooks registered in .claude/settings.json", s.exists() and "labhook.py" in s.read_text(),
        "merge settings.hooks.json into .claude/settings.json")
    user_s = Path.home() / ".claude" / "settings.json"
    days = None
    if user_s.exists():
        try:
            days = json.loads(user_s.read_text()).get("cleanupPeriodDays")
        except json.JSONDecodeError:
            pass
    chk("cleanupPeriodDays >= 365 (~/.claude/settings.json)", isinstance(days, int) and days >= 365,
        "otherwise Claude Code deletes transcripts after 30 days; set e.g. 3650 (not 0)")
    mp = C.verify_manifest(lb)
    chk("Protection manifest present and intact", not mp, "; ".join(mp))
    free = shutil.disk_usage(lb.root).free / 1e9
    min_gb = float(lb.cfg.get("run", {}).get("min_free_gb", 10))
    chk(f"Free disk space >= {min_gb:g} GB (currently {free:.1f} GB)", free >= min_gb)
    st = C.load_state(lb)
    sess = st.get("aktive_session")
    if sess:
        plan = f"{sess['verzeichnis']}/plan.qmd"
        chk(f"Plan {plan} committed", C.git_is_tracked_clean(lb, plan))
        fm, body, _ = C.parse_frontmatter((lb.root / plan).read_text())
        secs = C.sections(body)
        for name, prefixes in PLAN_SECTIONS:
            chk(f"Plan section `{name}` filled in", not C.is_empty_section(first_section(secs, *prefixes)))
    else:
        chk("Active session", False, "`lb.py session start <slug>` for unattended runs")
    chk("No open events", not C.open_events(lb), "`lb.py events --open`")
    width = max(len(n) for _, n, _ in res)
    bad = 0
    for ok, name, hint in res:
        bad += not ok
        print(f"{'OK    ' if ok else 'CHECK '}  {name:<{width}}  {'' if ok else hint}")
    sys.exit(1 if bad else 0)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="lb.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new", aliases=["neu"], help="create an entry")
    p.add_argument("slug"); p.add_argument("--title", "--titel", dest="title", required=True, help="entry title")
    p = sub.add_parser("session", help="begin (start) or end (end) an autonomous session")
    p.add_argument("action", choices=["start", "end", "ende"])
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("--title", "--titel", dest="title", default="", help="session title")
    p = sub.add_parser("run", help="run a command with provenance; the command follows `--`")
    p.add_argument("--entry", "--eintrag", dest="entry", required=True, help="entry id the run belongs to")
    p.add_argument("--param", action="append", default=[], help="parameter k=v (repeatable)")
    p.add_argument("--input", "--eingabe", dest="input", action="append", default=[],
                   help="input file to fingerprint (repeatable)")
    p.add_argument("--output", "--ausgabe", dest="output", action="append", default=[],
                   help="output glob to fingerprint (repeatable)")
    p.add_argument("--description", "--beschreibung", dest="description", default="", help="short description of the run")
    p.add_argument("command", nargs=argparse.REMAINDER, metavar="COMMAND")
    p = sub.add_parser("result", aliases=["ergebnis"], help="record a result metric for a run")
    p.add_argument("run", metavar="RUN_ID")
    p.add_argument("--metric", "--metrik", dest="metric", required=True, help="metric name")
    p.add_argument("--value", "--wert", dest="value", required=True, help="numeric value")
    p.add_argument("--unit", "--einheit", dest="unit", default="", help="unit")
    p.add_argument("--reference", "--referenz", dest="reference", default="", help="reference value")
    p.add_argument("--status", required=True, choices=["keep", "discard", "info"])
    p.add_argument("--description", "--beschreibung", dest="description", required=True, help="what the number means")
    p = sub.add_parser("check", aliases=["pruefe"], help="run all checks (as the Stop hook does)")
    p.add_argument("--all", "--alle", dest="all", action="store_true", help="check all documents, not only changed ones")
    p.add_argument("--no-render", "--ohne-render", dest="no_render", action="store_true",
                   help="skip the Quarto render check")
    p = sub.add_parser("events", aliases=["ereignisse"], help="list events")
    p.add_argument("--open", "--offen", dest="open", action="store_true", help="only undocumented events")
    p = sub.add_parser("trace-stats", aliases=["trace-statistik"], help="statistics from the mechanical trace")
    p.add_argument("--session", default="", help="session id or directory (default: since the active session started)")
    p = sub.add_parser("close", help="close an entry: status, verdict and `closed` timestamp")
    p.add_argument("entry", metavar="ENTRY_ID")
    p.add_argument("--verdict", choices=["confirmed", "refuted", "undecided", "not-applicable"], default="")
    p = sub.add_parser("book", aliases=["buch"], help="render the lab notebook as a Quarto book")
    p.add_argument("--format", default="pdf", choices=["pdf", "html"])
    p.add_argument("--no-render", dest="no_render", action="store_true", help="only write the book sources")
    sub.add_parser("protect", aliases=["schuetze"], help="write the protection manifest (MAINTAINER ONLY)")
    sub.add_parser("preflight", help="check readiness for unattended runs")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    cmd = COMMAND_ALIASES.get(a.cmd, a.cmd)
    if cmd == "run" and a.command and a.command[0] == "--":
        a.command = a.command[1:]
    if cmd == "session":
        a.action = "end" if a.action == "ende" else a.action
        if a.action == "start" and not a.slug:
            die("slug is missing")
    try:  # the project the tool is installed in, else the project around the working directory
        root = C.repo_root(ROOT_HINT)
    except SystemExit:
        root = C.repo_root(Path.cwd())
    lb = C.LB(root)
    {"new": cmd_new, "close": cmd_close, "session": cmd_session, "run": cmd_run, "result": cmd_result, "check": cmd_check,
     "events": cmd_events, "trace-stats": cmd_trace, "book": cmd_book,
     "protect": cmd_protect, "preflight": cmd_preflight}[cmd](lb, a)


if __name__ == "__main__":
    main()
