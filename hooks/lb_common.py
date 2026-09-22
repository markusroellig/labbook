"""Shared functions for the lab-notebook system (hooks and tools/lb.py).

Standard library only. Python >= 3.11 (tomllib) or an installed `tomli`.

Schema note: the entry schema is English (keys `date`, `author`, `discarded`, `corrected`,
`verdict`, `retrospective`; values `open|closed|discarded`, `confirmed|refuted|...`). Files
written under the former German schema are still read: `parse_frontmatter` maps the German
keys and values to the English ones, and `section_content` accepts either heading spelling.
Ledger records (events.jsonl, state.json, trace files) keep their original field names and
event-kind tokens because those files are append-only.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import difflib
import fcntl
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

try:  # Python 3.11+
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

ENTRY_FILE = "entry.qmd"
STATUS_VALUES = {"open", "closed", "discarded"}
VERDICT_VALUES = {"", "confirmed", "refuted", "undecided", "not-applicable"}
# Mandatory level-2 headings of an entry: (English prefix, German prefix), in the required order.
# The checker matches by prefix, case-insensitively, and accepts either spelling.
REQUIRED_SECTIONS = [
    ("Why", "Warum"),
    ("Hypothesis", "Hypothese"),
    ("Method", "Methode"),
    ("Result", "Ergebnis"),
    ("Verification", "Verifikation"),
    ("Interpretation", "Interpretation"),
    ("Consequences", "Konsequenzen"),
    ("Failed attempts", "Fehlgeschlagene Versuche"),
    ("Deviations from plan", "Abweichungen vom Plan"),
]
# Full canonical headings (used when a German heading is rewritten to English).
SECTION_HEADINGS = [
    ("Why", "Warum"),
    ("Hypothesis / Expectation", "Hypothese / Erwartung"),
    ("Method", "Methode"),
    ("Result", "Ergebnis"),
    ("Verification", "Verifikation"),
    ("Interpretation", "Interpretation"),
    ("Consequences and next steps", "Konsequenzen und nächste Schritte"),
    ("Failed attempts", "Fehlgeschlagene Versuche"),
    ("Deviations from plan", "Abweichungen vom Plan"),
]
# Frontmatter keys: German -> English (English is canonical; English wins if both are present).
FRONTMATTER_KEY_MAP = {
    "datum": "date",
    "autor": "author",
    "verworfen": "discarded",
    "korrigiert": "corrected",
    "urteil": "verdict",
    "retrospektiv": "retrospective",
}
STATUS_MAP = {"offen": "open", "abgeschlossen": "closed", "verworfen": "discarded"}
AUTHOR_MAP = {"mensch": "human"}
VERDICT_MAP = {"bestaetigt": "confirmed", "widerlegt": "refuted", "unentschieden": "undecided",
               "nicht-anwendbar": "not-applicable"}
# Event kinds (`art` in events.jsonl) keep their German tokens; this gives the English label
# shown to a human next to the token, e.g. "lauf (run)".
EVENT_KIND_LABELS = {
    "schutzverletzung": "protection violation",
    "lauf": "run",
    "code": "code change",
    "abweichung": "deviation",
    "plan-aenderung": "plan change",
    "test": "test",
    "test-wechsel": "test status change",
    "build": "build",
    "build-fehler": "build error",
    "stop-limit": "stop limit",
}
# Aliases for the former constant names (imported by older callers).
STATUS_WERTE = STATUS_VALUES
URTEIL_WERTE = VERDICT_VALUES
PFLICHT_ABSCHNITTE = [en for en, _de in REQUIRED_SECTIONS]
ID_RE = re.compile(r"\b([ER]-\d{4,})\b")


# --------------------------------------------------------------------------- Compatibility helpers

def normalize_status(value) -> str:
    """Map a German status value to the English one; other values pass through unchanged."""
    s = str(value or "").strip()
    return STATUS_MAP.get(s, s)


def normalize_verdict(value) -> str:
    """Map a German verdict value to the English one; other values pass through unchanged."""
    s = str(value or "").strip()
    return VERDICT_MAP.get(s, s)


def normalize_author(value) -> str:
    """Map a German author value (`mensch`) to the English one; others pass through unchanged."""
    s = str(value or "").strip()
    return AUTHOR_MAP.get(s, s)


def normalize_frontmatter(data: dict) -> dict:
    """Return the frontmatter with English keys and English status/author/verdict values.
    German keys are renamed; if both spellings are present the English one wins."""
    out = dict(data)
    for de, en in FRONTMATTER_KEY_MAP.items():
        if de in out:
            if en not in out:
                out[en] = out[de]
            del out[de]
    if "status" in out:
        out["status"] = normalize_status(out["status"])
    if "author" in out:
        out["author"] = normalize_author(out["author"])
    if "verdict" in out:
        out["verdict"] = normalize_verdict(out["verdict"])
    return out


def section_prefixes(prefix: str) -> tuple[str, ...]:
    """All accepted spellings of a required-section prefix (English and German)."""
    p = prefix.lower()
    for en, de in REQUIRED_SECTIONS:
        if p in (en.lower(), de.lower()):
            return (en, de)
    return (prefix,)


def event_label(kind: str) -> str:
    """Event kind as shown to a human: the ledger token plus an English label, e.g. `lauf (run)`."""
    lab = EVENT_KIND_LABELS.get(kind)
    return f"{kind} ({lab})" if lab and lab != kind else kind


# --------------------------------------------------------------------------- Paths, configuration

def repo_root(start: Path | None = None) -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and (Path(env) / ".claude" / "laborbuch.toml").exists():
        return Path(env).resolve()
    p = (start or Path.cwd()).resolve()
    for cand in [p, *p.parents]:
        if (cand / ".claude" / "laborbuch.toml").exists():
            return cand
    raise SystemExit("Lab notebook: .claude/laborbuch.toml not found")


def load_config(root: Path) -> dict:
    with open(root / ".claude" / "laborbuch.toml", "rb") as f:
        return tomllib.load(f)


class LB:
    """Bundles the paths and configuration of one repository."""

    def __init__(self, root: Path | None = None):
        self.root = root or repo_root()
        self.cfg = load_config(self.root)
        self.dir = self.root / self.cfg["pfade"]["laborbuch"]
        self.state_dir = self.dir / "_state"
        self.trace_dir = self.dir / "_trace"
        self.runs_dir = self.dir / "runs"
        self.entries_dir = self.dir / "eintraege"
        self.sessions_dir = self.dir / "sessions"
        self.results = self.dir / "results.tsv"
        self.events_file = self.state_dir / "events.jsonl"
        self.archive_dir = self.root / self.cfg["pfade"].get("archiv", ".laborbuch-archiv")
        for d in (self.state_dir, self.trace_dir, self.runs_dir, self.entries_dir, self.sessions_dir):
            d.mkdir(parents=True, exist_ok=True)

    def rel(self, p: str | Path) -> str:
        pp = Path(p)
        if not pp.is_absolute():
            pp = self.root / pp
        try:
            return pp.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return pp.as_posix()


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def today() -> str:
    return dt.date.today().isoformat()


# --------------------------------------------------------------------------- Glob patterns

def glob_to_regex(pattern: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif c == "*":
            out += "[^/]*"
            i += 1
        elif c == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(c)
            i += 1
    return re.compile("^" + out + "$")


def matches_any(rel: str, patterns: list[str]) -> bool:
    return any(glob_to_regex(p).match(rel) for p in patterns)


def literal_prefix(pattern: str) -> str:
    m = re.search(r"[*?\[]", pattern)
    return pattern[: m.start()] if m else pattern


# --------------------------------------------------------------------------- Locks and state

@contextlib.contextmanager
def locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + ".lock", "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def load_state(lb: LB) -> dict:
    p = lb.state_dir / "state.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def save_state(lb: LB, state: dict) -> None:
    p = lb.state_dir / "state.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    tmp.replace(p)


@contextlib.contextmanager
def state_tx(lb: LB):
    with locked(lb.state_dir / "state.json"):
        st = load_state(lb)
        yield st
        save_state(lb, st)


# --------------------------------------------------------------------------- Events

def read_events(lb: LB) -> list[dict]:
    if not lb.events_file.exists():
        return []
    out = []
    for line in lb.events_file.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def next_id(existing: list[str], prefix: str) -> str:
    nums = [int(x.split("-")[1]) for x in existing if x.startswith(prefix + "-")]
    return f"{prefix}-{(max(nums) + 1) if nums else 1:04d}"


def add_event(lb: LB, art: str, detail: str, session: str = "", schluessel: str = "",
              dedupe_open: bool = True) -> str | None:
    """Create an event. With dedupe_open no new event is created while an open event with
    the same key exists. Returns the new ID or None. (Record fields `id, zeit, session, art,
    detail, schluessel` are the ledger format and stay as they are.)"""
    with locked(lb.events_file):
        events = read_events(lb)
        if dedupe_open and schluessel:
            refs = referenced_ids(lb)
            for e in events:
                if e.get("schluessel") == schluessel and not is_documented(e, refs):
                    return None
        eid = next_id([e["id"] for e in events], "E")
        rec = {"id": eid, "zeit": now_iso(), "session": session, "art": art,
               "detail": detail, "schluessel": schluessel}
        with open(lb.events_file, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return eid


def is_documented(event: dict, refs: set[str]) -> bool:
    if event["id"] in refs:
        return True
    m = ID_RE.search(event.get("detail", ""))
    return bool(event.get("art") == "lauf" and m and m.group(1) in refs)


def open_events(lb: LB) -> list[dict]:
    refs = referenced_ids(lb)
    return [e for e in read_events(lb) if not is_documented(e, refs)]


# --------------------------------------------------------------------------- Frontmatter (YAML subset)

def _scalar(v: str):
    v = v.strip()
    if v in ("", "~", "null"):
        return ""
    if v == "[]":
        return []
    if v == "{}":
        return {}
    if v.startswith("[") and v.endswith("]"):
        return [_scalar(x) for x in _split_flow(v[1:-1]) if x.strip()]
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    return v


def _split_flow(s: str) -> list[str]:
    parts, cur, q = [], "", None
    for ch in s:
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            cur += ch
        elif ch == ",":
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def _strip_comment(line: str) -> str:
    q = None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i].rstrip()
    return line.rstrip()


def parse_frontmatter(text: str) -> tuple[dict, str, bool]:
    """Return (data, body, ok). Supports scalar values, flow lists, block lists and
    one-level block mappings -- enough for the lab-notebook fields. The returned dict uses
    the English schema: German keys and status/author/verdict values are mapped."""
    if not text.startswith("---"):
        return {}, text, False
    lines = text.splitlines()
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}, text, False
    data: dict = {}
    key = None
    for raw in lines[1:end]:
        line = _strip_comment(raw)
        if not line.strip():
            continue
        if not line[0].isspace():
            m = re.match(r"^([A-Za-z0-9_\-]+):\s*(.*)$", line)
            if not m:
                continue
            key, val = m.group(1), m.group(2)
            data[key] = _scalar(val) if val.strip() else None
        elif key is not None:
            s = line.strip()
            if s.startswith("- "):
                if not isinstance(data[key], list):
                    data[key] = []
                data[key].append(_scalar(s[2:]))
            else:
                m = re.match(r"^([^:]+):\s*(.*)$", s)
                if m:
                    if not isinstance(data[key], dict):
                        data[key] = {}
                    data[key][_scalar(m.group(1))] = _scalar(m.group(2))
    for k, v in data.items():
        if v is None:
            data[k] = ""
    return normalize_frontmatter(data), "\n".join(lines[end + 1:]), True


def sections(body: str) -> dict[str, str]:
    out, cur, buf = {}, None, []
    for line in body.splitlines():
        m = re.match(r"^##\s+(.+?)\s*(\{.*\})?\s*$", line)
        if m and not line.startswith("###"):
            if cur is not None:
                out[cur] = "\n".join(buf).strip()
            cur, buf = m.group(1).strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    return out


def section_content(secs: dict[str, str], prefix: str | tuple[str, ...]) -> str | None:
    """Content of the first section whose heading starts with one of the accepted prefixes.
    `prefix` may be a single string (an English or German required-section prefix resolves to
    both spellings) or a tuple of prefixes."""
    prefixes = prefix if isinstance(prefix, tuple) else section_prefixes(prefix)
    for pre in prefixes:
        for k, v in secs.items():
            if k.lower().startswith(pre.lower()):
                return v
    return None


def is_empty_section(text: str | None) -> bool:
    if text is None:
        return True
    t = re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()
    return t == ""


def qmd_documents(lb: LB) -> list[Path]:
    return sorted([*lb.entries_dir.glob("*/*.qmd"), *lb.sessions_dir.glob("*/*.qmd")])


def referenced_ids(lb: LB) -> set[str]:
    refs: set[str] = set()
    for p in qmd_documents(lb):
        fm, _, ok = parse_frontmatter(p.read_text(errors="replace"))
        if not ok:
            continue
        for key in ("events", "runs"):
            v = fm.get(key)
            if isinstance(v, list):
                refs.update(str(x) for x in v)
        v = fm.get("discarded")
        if isinstance(v, dict):
            refs.update(str(k) for k, why in v.items() if str(why).strip())
    return refs


# --------------------------------------------------------------------------- Git

def git(lb: LB, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=lb.root, capture_output=True, text=True, check=check)


def _git_ctx(lb: LB, rel: str) -> tuple[Path, str]:
    """Repository and path for a project-relative file: the notebook directory when it is a repository of
    its own (a nested clone ignored by the project), otherwise the project repository. Lets the notebook
    live in a separate repository shared by all code branches and machines (split of 2026-09-22)."""
    book_rel = lb.dir.relative_to(lb.root).as_posix()
    if (lb.dir / ".git").exists() and (rel == book_rel or rel.startswith(book_rel + "/")):
        return lb.dir, ("." if rel == book_rel else rel[len(book_rel) + 1:])
    return lb.root, rel


def git_head_content(lb: LB, rel: str) -> str | None:
    cwd, path = _git_ctx(lb, rel)
    r = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=cwd, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def git_is_tracked_clean(lb: LB, rel: str) -> bool:
    cwd, path = _git_ctx(lb, rel)
    if subprocess.run(["git", "ls-files", "--error-unmatch", path], cwd=cwd, capture_output=True).returncode != 0:
        return False
    return subprocess.run(["git", "diff", "--quiet", "HEAD", "--", path], cwd=cwd, capture_output=True).returncode == 0


# --------------------------------------------------------------------------- Normalisation for the relevance check

def normalize_code(text: str, comment_prefixes: list[str]) -> list[str]:
    out = []
    for line in text.splitlines():
        s = line
        for pref in comment_prefixes:
            idx = _comment_index(s, pref)
            if idx is not None:
                s = s[:idx]
        s = re.sub(r"\s+", " ", s).strip()
        if s:
            out.append(s)
    return out


def _comment_index(line: str, pref: str) -> int | None:
    q = None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif line.startswith(pref, i):
            return i
    return None


def diff_stat(old: str, new: str) -> tuple[int, int]:
    plus = minus = 0
    for l in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0):
        if l.startswith("+") and not l.startswith("+++"):
            plus += 1
        elif l.startswith("-") and not l.startswith("---"):
            minus += 1
    return plus, minus


# --------------------------------------------------------------------------- Trace

def trace_path(lb: LB, session_id: str) -> Path:
    with state_tx(lb) as st:
        mp = st.setdefault("trace_dateien", {})
        if session_id not in mp:
            mp[session_id] = f"{today()}_{session_id[:8] or 'ohne-id'}.jsonl"
        name = mp[session_id]
    return lb.trace_dir / name


def truncate_value(v, limit: int):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    if len(s) <= limit:
        return v
    return {"gekuerzt": s[:limit], "laenge": len(s), "sha256": hashlib.sha256(s.encode()).hexdigest()}


def append_trace(lb: LB, payload: dict) -> None:
    tcfg = lb.cfg.get("trace", {})
    limit = int(tcfg.get("max_zeichen", 4000))
    no_resp = payload.get("tool_name") in tcfg.get("ohne_antwort", ["Read", "Grep", "Glob"])
    rec = {"ts": now_iso()}
    for k, v in payload.items():
        if k == "tool_response" and no_resp:
            s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            rec[k] = {"weggelassen": True, "laenge": len(s), "sha256": hashlib.sha256(s.encode()).hexdigest()}
        elif k in ("tool_response", "tool_input", "error", "last_assistant_message"):
            rec[k] = truncate_value(v, limit)
        elif k != "transcript_path":
            rec[k] = v
    p = trace_path(lb, payload.get("session_id", ""))
    with locked(p):
        with open(p, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def archive_transcript(lb: LB, payload: dict) -> Path | None:
    src = payload.get("transcript_path")
    if not src or not Path(src).exists():
        return None
    lb.archive_dir.mkdir(parents=True, exist_ok=True)
    dst = lb.archive_dir / f"{today()}_{payload.get('session_id', 'unbekannt')}.jsonl.gz"
    with open(src, "rb") as fi, gzip.open(dst, "wb") as fo:
        shutil.copyfileobj(fi, fo)
    return dst


# --------------------------------------------------------------------------- Protection

def protected_patterns(lb: LB) -> list[str]:
    return list(lb.cfg.get("schutz", {}).get("geschuetzt", []))


def append_only_patterns(lb: LB) -> list[str]:
    return list(lb.cfg.get("schutz", {}).get("nur_anhaengen", []))


def expand_patterns(lb: LB, patterns: list[str]) -> list[str]:
    found = []
    for pat in patterns:
        rx = glob_to_regex(pat)
        base = lb.root / (literal_prefix(pat).rsplit("/", 1)[0] if "/" in literal_prefix(pat) else "")
        if not base.exists():
            continue
        cands = [base] if base.is_file() else base.rglob("*")
        for p in cands:
            if p.is_file() and not p.name.endswith(".lock"):
                rel = p.relative_to(lb.root).as_posix()
                if rx.match(rel):
                    found.append(rel)
    return sorted(set(found))


def manifest_path(lb: LB) -> Path:
    return lb.root / ".claude" / "laborbuch.sha256"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(lb: LB) -> int:
    ao = append_only_patterns(lb)
    files = [f for f in expand_patterns(lb, protected_patterns(lb)) if not matches_any(f, ao)
             and f != manifest_path(lb).relative_to(lb.root).as_posix()]
    manifest_path(lb).write_text("".join(f"{sha256_file(lb.root / f)}  {f}\n" for f in files))
    return len(files)


def verify_manifest(lb: LB) -> list[str]:
    mp = manifest_path(lb)
    if not mp.exists():
        return ["Protection manifest missing (human: `python3 tools/lb.py schuetze`)."]
    probs = []
    listed = set()
    for line in mp.read_text().splitlines():
        if not line.strip():
            continue
        h, rel = line.split("  ", 1)
        listed.add(rel)
        p = lb.root / rel
        if not p.exists():
            probs.append(f"Protected file missing: {rel}")
        elif sha256_file(p) != h:
            probs.append(f"Protected file modified: {rel}")
    return probs


def verify_append_only(lb: LB) -> list[str]:
    probs = []
    for rel in expand_patterns(lb, append_only_patterns(lb)):
        head = git_head_content(lb, rel)
        if head is None:
            continue
        cur = (lb.root / rel).read_text(errors="replace")
        if not cur.startswith(head):
            probs.append(f"Append-only file modified after the fact (not just extended): {rel}")
    return probs


def canonical_document(text: str) -> str:
    """Document text with the schema surface rewritten to English: German frontmatter keys and
    status/author/verdict values, and the German mandatory `## ` headings (a trailing `{#...}`
    label is kept). Everything else is returned byte for byte. Used so that a closed entry that
    was only migrated from the German schema to the English one compares as unchanged."""
    if not text.startswith("---"):
        return text
    lines = text.splitlines(keepends=True)
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return text
    value_maps = {"status": STATUS_MAP, "author": AUTHOR_MAP, "verdict": VERDICT_MAP}
    for i in range(1, end):
        m = re.match(r"^([A-Za-z0-9_\-]+):(\s*)(.*?)(\s*)$", lines[i].rstrip("\r\n"))
        if not m:
            continue
        key = FRONTMATTER_KEY_MAP.get(m.group(1), m.group(1))
        val = value_maps.get(key, {}).get(m.group(3).strip('"\''), m.group(3))
        nl = lines[i][len(lines[i].rstrip("\r\n")):]
        lines[i] = f"{key}:{m.group(2)}{val}{m.group(4)}{nl}"
    for i in range(end + 1, len(lines)):
        m = re.match(r"^(##\s+)(.+?)(\s*\{.*\})?\s*$", lines[i].rstrip("\r\n"))
        if not m or lines[i].startswith("###"):
            continue
        for en, de in SECTION_HEADINGS:
            if m.group(2) == de:
                nl = lines[i][len(lines[i].rstrip("\r\n")):]
                lines[i] = f"{m.group(1)}{en}{m.group(3) or ''}{nl}"
                break
    return "".join(lines)


def verify_closed_entries(lb: LB) -> list[str]:
    """A document whose HEAD version is closed (status `closed`, or `abgeschlossen` under the
    former schema) must not change in the working copy. Both versions are compared after
    `canonical_document`, so a pure schema migration of a closed entry is not a violation."""
    probs = []
    for p in qmd_documents(lb):
        rel = lb.rel(p)
        head = git_head_content(lb, rel)
        if head is None:
            continue
        fm, _, ok = parse_frontmatter(head)
        if not ok or normalize_status(fm.get("status")) != "closed":
            continue
        strip = lambda t: "\n".join(l for l in canonical_document(t).splitlines()
                                    if not l.startswith("reviewed_by:"))
        if strip(head) != strip(p.read_text(errors="replace")):
            probs.append(f"Closed document modified: {rel} (correct it in a new entry with `corrected:`)")
    return probs


# --------------------------------------------------------------------------- Checking entries

def check_document(lb: LB, path: Path, all_labels: dict[str, str]) -> list[str]:
    rel = lb.rel(path)
    text = path.read_text(errors="replace")
    fm, body, ok = parse_frontmatter(text)
    probs: list[str] = []
    if not ok:
        return [f"{rel}: frontmatter missing or not terminated (---)."]
    is_entry = path.name == ENTRY_FILE and path.parent.parent == lb.entries_dir
    if not fm.get("title"):
        probs.append(f"{rel}: field `title` missing.")
    status = normalize_status(fm.get("status", ""))
    if status not in STATUS_VALUES:
        probs.append(f"{rel}: `status` must be open|closed|discarded (is: {status!r}).")
    if is_entry:
        if fm.get("id") != path.parent.name:
            probs.append(f"{rel}: `id` ({fm.get('id')!r}) must equal the directory name.")
        verdict = normalize_verdict(fm.get("verdict", ""))
        if verdict not in VERDICT_VALUES:
            probs.append(f"{rel}: `verdict` invalid ({fm.get('verdict')!r}).")
        secs = sections(body)
        for name, name_de in REQUIRED_SECTIONS:
            content = section_content(secs, (name, name_de))
            if content is None:
                probs.append(f"{rel}: section `## {name}` missing.")
            elif status == "closed" and is_empty_section(content):
                probs.append(f"{rel}: section `## {name}` is empty (mandatory for a closed entry; use 'none' if so).")
        if status == "closed" and not verdict:
            probs.append(f"{rel}: a closed entry needs a `verdict`.")
    for key in ("runs",):
        for rid in fm.get(key) or []:
            if not (lb.runs_dir / str(rid) / "provenance.json").exists():
                probs.append(f"{rel}: run {rid} has no provenance.json.")
    v = fm.get("discarded")
    if isinstance(v, dict):
        for k, why in v.items():
            if not str(why).strip():
                probs.append(f"{rel}: `discarded: {k}` without a reason.")
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    for rid in set(re.findall(r"\{\{<\s*(?:prov|lauf-param|ergebnis)\s+(R-\d+)", body)):
        if not (lb.runs_dir / rid / "provenance.json").exists():
            probs.append(f"{rel}: shortcode refers to unknown run {rid}.")
    for m in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)\)", body):
        target = m.group(1)
        if re.match(r"^[a-z]+://", target):
            continue
        base = path.parent / target
        if not (base.exists() or base.with_suffix(".pdf").exists() or base.with_suffix(".png").exists()):
            probs.append(f"{rel}: figure missing: {target}")
        elif not (base.suffix or (base.with_suffix(".pdf").exists() and base.with_suffix(".png").exists())):
            probs.append(f"{rel}: figure {target} needs .pdf and .png (for PDF and HTML).")
    for lab in re.findall(r"\{#((?:fig|eq|tbl|sec)-[A-Za-z0-9_\-]+)", body):
        if lab in all_labels and all_labels[lab] != rel:
            probs.append(f"{rel}: label `{lab}` duplicated (also in {all_labels[lab]}); prefix it with the entry slug.")
        all_labels.setdefault(lab, rel)
    return probs


def render_check(lb: LB, path: Path, fmt: str) -> str | None:
    if fmt == "aus":
        return None
    out = path.with_suffix("." + ("pdf" if fmt == "pdf" else "html"))
    if out.exists():
        out.unlink()
    r = subprocess.run(["quarto", "render", str(path), "--to", fmt, "--quiet"], cwd=lb.dir,
                       capture_output=True, text=True, timeout=600)
    if r.returncode == 0 and out.exists():
        return None
    msg = ""
    log = path.with_suffix(".log")
    if log.exists():
        errs = [l for l in log.read_text(errors="replace").splitlines() if l.startswith("!")]
        msg = " | ".join(errs[:3])
    if not msg:
        msg = (r.stderr or r.stdout).strip().splitlines()[-3:] if (r.stderr or r.stdout) else ["unknown error"]
        msg = " | ".join(msg)
    return f"{lb.rel(path)}: rendering to {fmt} failed: {msg}"


def full_check(lb: LB, only_changed: bool = True, render: bool = True) -> list[str]:
    """All checks. only_changed: only documents changed since the last successful check are
    checked for content and by rendering."""
    probs: list[str] = []
    st = load_state(lb)
    last_ok = st.get("pruefung_ok", {})
    labels: dict[str, str] = {}
    fmt = lb.cfg.get("pruefung", {}).get("render", "pdf")
    passed = {}
    for p in qmd_documents(lb):
        rel = lb.rel(p)
        mtime = p.stat().st_mtime
        changed = last_ok.get(rel) != mtime
        doc_probs = check_document(lb, p, labels)
        if doc_probs:
            if changed or not only_changed:
                probs.extend(doc_probs)
            continue
        if render and (changed or not only_changed):
            err = render_check(lb, p, fmt)
            if err:
                probs.append(err)
                continue
        passed[rel] = mtime
    for e in open_events(lb):
        probs.append(f"Event {e['id']} ({event_label(e['art'])}: {e['detail']}) is not documented.")
    probs.extend(verify_manifest(lb))
    probs.extend(verify_append_only(lb))
    probs.extend(verify_closed_entries(lb))
    with state_tx(lb) as st2:
        st2.setdefault("pruefung_ok", {}).update(passed)
    return probs
