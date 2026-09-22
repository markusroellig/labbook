#!/usr/bin/env python3
"""Lab-notebook tool.

  lb.py new <slug> --title "..."             Create an entry
  lb.py session start <slug> --title "..."   Begin an autonomous session (creates the plan)
  lb.py session end                          End the session (summary + trace statistics)
  lb.py run --entry <id> [--param k=v] [--input FILE] [--output GLOB] -- COMMAND ...
  lb.py result R-0001 --metric NAME --value X [--unit U] [--reference Y] --status keep|discard|info --description "..."
  lb.py check [--all] [--no-render]          All checks (the same ones the Stop hook runs)
  lb.py events [--open]                      Event list
  lb.py trace-stats [--session DIR]          Statistics from the mechanical trace
  lb.py book [--format pdf|html]             Render the lab notebook as a Quarto book
  lb.py protect                              Write the protection manifest (MAINTAINER ONLY)
  lb.py preflight                            Check readiness for unattended runs

The German names remain valid: neu, session start|ende, run, ergebnis, pruefe, ereignisse, trace-statistik,
buch, schuetze, preflight; --titel, --eintrag, --metrik, --wert, --einheit, --referenz, --beschreibung,
--alle, --ohne-render, --offen, --eingabe, --ausgabe.
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
sys.path.insert(0, str(ROOT_HINT / ".claude" / "hooks"))
import lb_common as C  # noqa: E402

# Column names of results.tsv (ledger format, unchanged).
RESULTS_HEADER = ["zeit", "lauf", "eintrag", "commit", "dirty", "art", "metrik", "wert",
                  "einheit", "referenz", "status", "beschreibung"]

# English subcommand alias -> canonical (German) name used by the dispatch table.
COMMAND_ALIASES = {"new": "neu", "result": "ergebnis", "check": "pruefe", "events": "ereignisse",
                   "trace-stats": "trace-statistik", "book": "buch", "protect": "schuetze"}

# Event kinds as written to the ledger (German tokens, unchanged) with their English display labels.
EVENT_KIND_LABELS = {"schutzverletzung": "protection violation", "lauf": "run", "code": "code change",
                     "abweichung": "deviation", "test": "test", "build": "build"}

# Plan sections that preflight requires: (display name, accepted heading prefixes: English, German).
PLAN_SECTIONS = [
    ("Goal", ("Goal", "Ziel")),
    ("Hypotheses", ("Hypotheses", "Hypothesen")),
    ("Stop criteria", ("Stop criteria", "Abbruchkriterien")),
    ("Scope of action", ("Scope of action", "Handlungsspielraum")),
]

# Generated trace-statistics block in the session summary; the marker comments are part of the
# zusammenfassung.qmd template and stay verbatim.
TRACE_BLOCK_RE = re.compile(r"<!-- TRACE-STATISTIK:BEGINN.*?TRACE-STATISTIK:ENDE -->", re.S)
TRACE_BLOCK_BEGIN = "<!-- TRACE-STATISTIK:BEGINN (generiert) -->"
TRACE_BLOCK_END = "<!-- TRACE-STATISTIK:ENDE -->"


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


def kind_label(art: str) -> str:
    """Ledger token followed by its English label for display, e.g. `lauf (run)`."""
    lab = EVENT_KIND_LABELS.get(art)
    return f"{art} ({lab})" if lab else art


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


# --------------------------------------------------------------------------- neu / new

def cmd_neu(lb: C.LB, a) -> None:
    eid = f"{C.today()}_{slugify(a.slug)}"
    d = lb.entries_dir / eid
    if d.exists():
        die(f"{d} already exists")
    (d / "fig").mkdir(parents=True)
    tmpl = lb.dir / "_vorlagen"
    st = C.load_state(lb)
    sess = (st.get("aktive_session") or {}).get("id", "")
    (d / C.ENTRY_FILE).write_text(fill((tmpl / "eintrag.qmd").read_text(), TITLE=a.titel, ID=eid,
                                       DATE=C.today(), SESSION=sess, SLUG=slugify(a.slug)))
    shutil.copy(tmpl / "analysis.py", d / "analysis.py")
    print(lb.rel(d / C.ENTRY_FILE))


# --------------------------------------------------------------------------- session

def cmd_session(lb: C.LB, a) -> None:
    tmpl = lb.dir / "_vorlagen"
    if a.aktion == "start":
        st = C.load_state(lb)
        if st.get("aktive_session"):
            die(f"Session {st['aktive_session']['id']} is still active (run `session end` first).")
        sid = f"{C.today()}_{slugify(a.slug)}"
        d = lb.sessions_dir / sid
        d.mkdir(parents=True, exist_ok=False)
        (d / "plan.qmd").write_text(fill((tmpl / "plan.qmd").read_text(), TITLE=a.titel or a.slug,
                                         ID=sid, DATE=C.today(), START=C.now_iso()))
        with C.state_tx(lb) as st:
            st["aktive_session"] = {"id": sid, "titel": a.titel or a.slug, "verzeichnis": lb.rel(d), "start": C.now_iso(),
                                    "claude_sessions": [], "plan_committed": False}
        print(lb.rel(d / "plan.qmd"))
        print("Fill in and commit the plan before starting any runs.")
    elif a.aktion in ("ende", "end"):
        st = C.load_state(lb)
        s = st.get("aktive_session")
        if not s:
            die("no active session")
        d = lb.root / s["verzeichnis"]
        stats = trace_statistics(lb, s)
        z = d / "zusammenfassung.qmd"
        if not z.exists():
            z.write_text(fill((tmpl / "zusammenfassung.qmd").read_text(), TITLE=s.get("titel", s["id"]), ID=s["id"],
                              DATE=C.today(), START=s["start"], ENDE=C.now_iso()))
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
    ignore = lb.cfg["pfade"]["laborbuch"] + "/"
    dirty_files = [l[3:] for l in status.splitlines() if not l[3:].startswith(ignore)]
    return {"commit": commit, "dirty": bool(dirty_files), "geaenderte_dateien": dirty_files,
            "branch": C.git(lb, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()}


def cmd_run(lb: C.LB, a) -> None:
    if not a.befehl:
        die("command after `--` is missing")
    entry = lb.entries_dir / a.eintrag / C.ENTRY_FILE
    if not entry.exists():
        die(f"Entry {a.eintrag} does not exist (run `lb.py new` first).")
    fm, body, _ = C.parse_frontmatter(entry.read_text())
    hyp = first_section(C.sections(body), "Hypothesis", "Hypothese")
    if C.is_empty_section(hyp):
        die("Section `## Hypothesis / Expectation` is empty. Formulate the hypothesis before the run.")
    run_cfg = lb.cfg.get("lauf", {})
    if run_cfg.get("hypothese_commit_pflicht", True) and not C.git_is_tracked_clean(lb, lb.rel(entry)):
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
    if gi["dirty"] and not run_cfg.get("dirty_erlaubt", True):
        die("Working tree has uncommitted code changes; run not allowed (lauf.dirty_erlaubt=false).")

    with C.locked(lb.runs_dir / "zaehler"):
        rid = C.next_id([p.name for p in lb.runs_dir.glob("R-*")], "R")
        rdir = lb.runs_dir / rid
        rdir.mkdir()
    if gi["dirty"]:
        (rdir / "dirty.patch").write_text(C.git(lb, "diff", "HEAD", "--", *gi["geaenderte_dateien"]).stdout)
    params = dict(kv.split("=", 1) for kv in a.param)
    inputs = {f: C.sha256_file(lb.root / f) for f in a.eingabe}
    compiler = ""
    if run_cfg.get("compiler_befehl"):
        r = subprocess.run(run_cfg["compiler_befehl"], shell=True, capture_output=True, text=True)
        compiler = r.stdout.splitlines()[0] if (r.returncode == 0 and r.stdout) else f"not determinable ({run_cfg['compiler_befehl']})"
    env_keys = run_cfg.get("umgebungsvariablen", ["OMP_NUM_THREADS"])
    t0 = time.time()
    start = C.now_iso()
    with open(rdir / "log.txt", "w") as log:
        proc = subprocess.run(a.befehl, cwd=lb.root, stdout=log, stderr=subprocess.STDOUT)
    dauer = time.time() - t0
    outputs = {}
    for pat in a.ausgabe:
        for f in sorted(glob.glob(str(lb.root / pat), recursive=True)):
            if Path(f).is_file():
                outputs[lb.rel(f)] = C.sha256_file(Path(f))
    # Provenance record keys are part of the ledger format and stay as they are.
    prov = {
        "lauf": rid, "eintrag": a.eintrag, "session": (s or {}).get("id", ""),
        "beschreibung": a.beschreibung, "befehl": a.befehl, "parameter": params,
        "start": start, "dauer_s": round(dauer, 3), "exit": proc.returncode,
        "git": gi, "compiler": compiler, "host": platform.node(), "benutzer": getpass.getuser(),
        "python": platform.python_version(), "plattform": platform.platform(),
        "umgebung": {k: os.environ.get(k, "") for k in env_keys},
        "eingaben_sha256": inputs, "ausgaben_sha256": outputs,
    }
    (rdir / "provenance.json").write_text(json.dumps(prov, indent=2, ensure_ascii=False))
    tsv_append(lb, {"zeit": start, "lauf": rid, "eintrag": a.eintrag, "commit": gi["commit"][:12],
                    "dirty": int(gi["dirty"]), "art": "lauf", "status": f"exit={proc.returncode}",
                    "beschreibung": a.beschreibung})
    tail = (rdir / "log.txt").read_text(errors="replace").splitlines()[-15:]
    print("\n".join(tail))
    # The `LAUF <id> exit=<n>` token is parsed by the PostToolUse hook (labhook.py) to register the run
    # event; keep it verbatim.
    print(f"LAUF {rid} exit={proc.returncode} duration={dauer:.1f}s log={lb.rel(rdir / 'log.txt')}")
    sys.exit(proc.returncode)


# --------------------------------------------------------------------------- ergebnis / result

def cmd_ergebnis(lb: C.LB, a) -> None:
    prov_p = lb.runs_dir / a.lauf / "provenance.json"
    if not prov_p.exists():
        die(f"Run {a.lauf} unknown")
    prov = json.loads(prov_p.read_text())
    try:
        float(a.wert)
    except ValueError:
        die("--value must be a number")
    tsv_append(lb, {"zeit": C.now_iso(), "lauf": a.lauf, "eintrag": prov["eintrag"],
                    "commit": prov["git"]["commit"][:12], "dirty": int(prov["git"]["dirty"]),
                    "art": "ergebnis", "metrik": a.metrik, "wert": a.wert, "einheit": a.einheit,
                    "referenz": a.referenz, "status": a.status, "beschreibung": a.beschreibung})
    print(f"RESULT {a.lauf} {a.metrik}={a.wert} {a.einheit} ({a.status})")


# --------------------------------------------------------------------------- pruefe / check, ereignisse / events

def cmd_pruefe(lb: C.LB, a) -> None:
    probs = C.full_check(lb, only_changed=not a.alle, render=not a.ohne_render)
    if probs:
        print("\n".join(f"- {p}" for p in probs))
        sys.exit(1)
    print("Lab-notebook check passed.")


def cmd_ereignisse(lb: C.LB, a) -> None:
    refs = C.referenced_ids(lb)
    for e in C.read_events(lb):
        doc = C.is_documented(e, refs)
        if a.offen and doc:
            continue
        print(f"{e['id']}  {'doc ' if doc else 'OPEN'}  {e['zeit'][:16]}  {kind_label(e['art']):<40} {e['detail']}")


# --------------------------------------------------------------------------- trace-statistik / trace-stats

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
    out += [f"| {e['id']} | {kind_label(e['art'])} | {e['detail'].replace('|', '/')} | "
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


# --------------------------------------------------------------------------- buch / book

def doc_title(p: Path) -> str:
    fm, _, _ = C.parse_frontmatter(p.read_text(errors="replace"))
    return fm.get("title", p.parent.name)


def write_overview(lb: C.LB) -> None:
    gen = lb.dir / "_generiert"
    gen.mkdir(exist_ok=True)
    lines = ["## Entries", "", "| Entry | Status | Verdict | Runs | Review |", "|---|---|---|---|---|"]
    for e in sorted(lb.entries_dir.glob(f"*/{C.ENTRY_FILE}"), reverse=True):
        fm, _, _ = C.parse_frontmatter(e.read_text(errors="replace"))
        # `verdict` is the canonical key; `urteil` is read as a fallback for a parser without the compat layer.
        verdict = fm.get("verdict", fm.get("urteil", ""))
        lines.append(f"| {fm.get('title', e.parent.name)} | {fm.get('status', '')} | "
                     f"{verdict} | {', '.join(fm.get('runs') or [])} | {fm.get('reviewed_by') or '–'} |")
    opened = C.open_events(lb)
    lines += ["", f"## Open events ({len(opened)})", ""]
    lines += [f"- {e['id']} ({kind_label(e['art'])}): {e['detail']}" for e in opened] or ["None."]
    lines += ["", "## Latest results", ""]
    if lb.results.exists():
        rows = [r.split("\t") for r in lb.results.read_text().splitlines()]
        hdr, data = rows[0], [r for r in rows[1:] if len(r) == len(rows[0])]
        erg = [dict(zip(hdr, r)) for r in data if r[hdr.index("art")] == "ergebnis"][-15:]
        if erg:
            lines += ["| Run | Metric | Value | Reference | Status |", "|---|---|--:|--:|---|"]
            lines += [f"| {r['lauf']} | {r['metrik']} | {r['wert']} {r['einheit']} | {r['referenz']} | {r['status']} |"
                      for r in reversed(erg)]
    (gen / "uebersicht.md").write_text("\n".join(lines) + "\n")


def yq(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def cmd_buch(lb: C.LB, a) -> None:
    write_overview(lb)
    items = []
    for p in lb.sessions_dir.glob("*"):
        for name in ("plan.qmd", "zusammenfassung.qmd", "audit.qmd"):
            if (p / name).exists():
                items.append((p.name[:10], {"plan.qmd": 0, "zusammenfassung.qmd": 2, "audit.qmd": 3}[name], p.name, p / name))
    for p in lb.entries_dir.glob(f"*/{C.ENTRY_FILE}"):
        items.append((p.parent.name[:10], 1, p.parent.name, p))
    items.sort()
    items = [(key, order, p) for key, order, _, p in items]
    parts = collections.OrderedDict()
    for key, _, p in items:
        parts.setdefault(key[:7], []).append(p.relative_to(lb.dir).as_posix())
    chapters = ["    - index.qmd", "    - konventionen.qmd"]
    for month, files in parts.items():
        chapters.append(f'    - part: "{month}"')
        chapters.append("      chapters:")
        chapters += [f"        - {f}" for f in files]
    book = lb.cfg.get("buch", {})
    yml = ["# GENERATED by tools/lb.py book – do not edit", "project:", "  type: book",
           f"  output-dir: _buch/{a.format}", "book:", "  output-file: laborbuch", f"  title: {yq(book.get('titel', 'Lab notebook'))}",
           f"  author: {yq(book.get('autor', ''))}", f'  date: "{C.today()}"', "  chapters:", *chapters,
           "format:", "  pdf:", "    documentclass: scrreprt", "    toc: true", "    toc-depth: 1", "    number-depth: 2",
           "  html:", "    toc: true"]
    (lb.dir / "_quarto-buch.yml").write_text("\n".join(yml) + "\n")
    commit = C.git(lb, "rev-parse", "--short", "HEAD").stdout.strip()
    r = subprocess.run(["quarto", "render", "--profile", "buch", "--to", a.format,
                        "-M", f"subtitle:As of commit {commit or 'unknown'}"], cwd=lb.dir)
    sys.exit(r.returncode)


# --------------------------------------------------------------------------- schuetze / protect, preflight

def cmd_schuetze(lb: C.LB, a) -> None:
    # Maintainer only: the PreToolUse hook blocks this command for Claude sessions.
    n = C.write_manifest(lb)
    print(f"Protection manifest with {n} files written: {lb.rel(C.manifest_path(lb))}. Please commit it.")


def cmd_preflight(lb: C.LB, a) -> None:
    res = []

    def chk(name, ok, hint=""):
        res.append((ok, name, hint))

    chk("Python >= 3.11 or tomli", True)
    chk("quarto installed", shutil.which("quarto") is not None, "https://quarto.org")
    eng = lb.cfg.get("pruefung", {}).get("render", "pdf")
    chk("TeX engine (xelatex)", eng != "pdf" or shutil.which("xelatex") is not None, "TeX Live or `quarto install tinytex`")
    chk("git repository", C.git(lb, "rev-parse", "HEAD").returncode == 0)
    s = (lb.root / ".claude" / "settings.json")
    chk("Hooks in .claude/settings.json", s.exists() and "labhook.py" in s.read_text())
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
    min_gb = float(lb.cfg.get("lauf", {}).get("min_frei_gb", 10))
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


def main() -> None:
    ap = argparse.ArgumentParser(prog="lb.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("neu", aliases=["new"], help="create an entry")
    p.add_argument("slug"); p.add_argument("--titel", "--title", required=True, help="entry title")
    p = sub.add_parser("session", help="begin (start) or end (end|ende) an autonomous session")
    p.add_argument("aktion", choices=["start", "ende", "end"])
    p.add_argument("slug", nargs="?", default=""); p.add_argument("--titel", "--title", default="", help="session title")
    p = sub.add_parser("run", help="run a command with provenance; the command follows `--`")
    p.add_argument("--eintrag", "--entry", required=True, help="entry id the run belongs to")
    p.add_argument("--param", action="append", default=[], help="parameter k=v (repeatable)")
    p.add_argument("--eingabe", "--input", action="append", default=[], help="input file to fingerprint (repeatable)")
    p.add_argument("--ausgabe", "--output", action="append", default=[], help="output glob to fingerprint (repeatable)")
    p.add_argument("--beschreibung", "--description", default="", help="short description of the run")
    p.add_argument("befehl", nargs=argparse.REMAINDER, metavar="COMMAND")
    p = sub.add_parser("ergebnis", aliases=["result"], help="record a result metric for a run")
    p.add_argument("lauf", metavar="RUN_ID"); p.add_argument("--metrik", "--metric", required=True, help="metric name")
    p.add_argument("--wert", "--value", required=True, help="numeric value")
    p.add_argument("--einheit", "--unit", default="", help="unit")
    p.add_argument("--referenz", "--reference", default="", help="reference value")
    p.add_argument("--status", required=True, choices=["keep", "discard", "info"])
    p.add_argument("--beschreibung", "--description", required=True, help="what the number means")
    p = sub.add_parser("pruefe", aliases=["check"], help="run all checks (as the Stop hook does)")
    p.add_argument("--alle", "--all", action="store_true", help="check all documents, not only changed ones")
    p.add_argument("--ohne-render", "--no-render", action="store_true", help="skip the Quarto render check")
    p = sub.add_parser("ereignisse", aliases=["events"], help="list events")
    p.add_argument("--offen", "--open", action="store_true", help="only undocumented events")
    p = sub.add_parser("trace-statistik", aliases=["trace-stats"], help="statistics from the mechanical trace")
    p.add_argument("--session", default="", help="session id or directory (default: since the active session started)")
    p = sub.add_parser("buch", aliases=["book"], help="render the lab notebook as a Quarto book")
    p.add_argument("--format", default="pdf", choices=["pdf", "html"])
    sub.add_parser("schuetze", aliases=["protect"], help="write the protection manifest (MAINTAINER ONLY)")
    sub.add_parser("preflight", help="check readiness for unattended runs")
    a = ap.parse_args()
    cmd = COMMAND_ALIASES.get(a.cmd, a.cmd)
    if cmd == "run" and a.befehl and a.befehl[0] == "--":
        a.befehl = a.befehl[1:]
    if cmd == "session" and a.aktion == "start" and not a.slug:
        die("slug is missing")
    lb = C.LB(C.repo_root(ROOT_HINT))
    {"neu": cmd_neu, "session": cmd_session, "run": cmd_run, "ergebnis": cmd_ergebnis, "pruefe": cmd_pruefe,
     "ereignisse": cmd_ereignisse, "trace-statistik": cmd_trace, "buch": cmd_buch,
     "schuetze": cmd_schuetze, "preflight": cmd_preflight}[cmd](lb, a)


if __name__ == "__main__":
    main()
