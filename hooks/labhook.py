#!/usr/bin/env python3
"""Claude Code hooks for the lab notebook.

Usage:  labhook.py start|pre|post|fail|stop|end   (JSON input on stdin)

Principles
- The trace is written for EVERY event, independent of the model.
- `pre` blocks writes to protected files (exit 2).
- `post`/`fail` create events that must be documented and report them as context.
- `stop` prevents the session from ending while entries are faulty or events are
  undocumented (bounded by pruefung.max_stop_blockaden).
- Internal errors never block; they go to _state/hook-fehler.log.

Event kinds written to the ledger keep their German tokens (`schutzverletzung`, `lauf`,
`code`, ...); when shown to a human they carry an English label, e.g. `lauf (run)`.
"""
from __future__ import annotations

import json
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lb_common as C  # noqa: E402

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
BASH_WRITE_RE = re.compile(
    r"((?<![\d&=-])>>?(?![&=])|\btee\b|\bsed\s+-i|\bperl\s+-[a-z]*i|\bmv\b|\bcp\b|\brm\b|\btruncate\b|\bchmod\b|\bln\b|"
    r"\bdd\b|open\([^)]*['\"][wa]|write_text|\bgit\s+(checkout|restore|reset|rm|mv)\b|\bpatch\b)"
)
# Marker printed by `lb.py run` (literal token, parsed here -- do not rename).
RUN_MARKER_RE = re.compile(r"LAUF (R-\d+) exit=(-?\d+)")
# Accepted "nothing to report" placeholders in the failed-attempts section.
NONE_WORDS = ("keine", "keine.", "none", "none.")


def emit_context(event_name: str, text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": text}},
                     ensure_ascii=False))


def tool_path(payload: dict) -> str | None:
    ti = payload.get("tool_input") or {}
    return ti.get("file_path") or ti.get("notebook_path") or ti.get("path")


def response_text(payload: dict) -> str:
    parts = []
    for k in ("tool_response", "error"):
        v = payload.get(k)
        if v is None:
            continue
        parts.append(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
    return "\n".join(parts)


def exit_code_from(payload: dict) -> int | None:
    resp = payload.get("tool_response")
    if isinstance(resp, dict):
        for k in ("exit_code", "exitCode", "returncode", "return_code"):
            if isinstance(resp.get(k), int):
                return resp[k]
    m = re.search(r"exit(?:ed with)? code[:\s]+(\d+)", response_text(payload), re.I)
    return int(m.group(1)) if m else None


def active_session(lb: C.LB) -> dict | None:
    return C.load_state(lb).get("aktive_session")


def register_session_id(lb: C.LB, sid: str) -> None:
    if not sid:
        return
    with C.state_tx(lb) as st:
        a = st.get("aktive_session")
        if a is not None and sid not in a.setdefault("claude_sessions", []):
            a["claude_sessions"].append(sid)


def fmt_event(e: dict) -> str:
    return f"{e['id']} ({C.event_label(e['art'])}: {e['detail']})"


# --------------------------------------------------------------------------- start

def on_start(lb: C.LB, p: dict) -> int:
    C.append_trace(lb, p)
    register_session_id(lb, p.get("session_id", ""))
    lines = ["Lab-notebook context (injected automatically):"]
    a = active_session(lb)
    if a:
        lines.append(f"- Active session: {a['verzeichnis']} (plan: {a['verzeichnis']}/plan.qmd).")
    else:
        lines.append("- No active session.")
    opened = C.open_events(lb)
    if opened:
        lines.append(f"- {len(opened)} undocumented events: " + ", ".join(fmt_event(e) for e in opened[:15]))
    fails = []
    for entry in sorted(lb.entries_dir.glob(f"*/{C.ENTRY_FILE}"))[-8:]:
        fm, body, ok = C.parse_frontmatter(entry.read_text(errors="replace"))
        txt = C.section_content(C.sections(body), "Failed attempts")
        if txt and not C.is_empty_section(txt) and txt.strip().lower() not in NONE_WORDS:
            first = " ".join(txt.split())[:300]
            fails.append(f"  - {entry.parent.name}: {first}")
    if fails:
        lines.append("- Documented dead ends of the latest entries (do not repeat without a new reason):")
        lines.extend(fails)
    lines.append("- Conventions: laborbuch/konventionen.qmd. Working method: skill `laborbuch`.")
    print("\n".join(lines))
    return 0


# --------------------------------------------------------------------------- pre (protection)

def blocked(lb: C.LB, p: dict, reason: str) -> int:
    C.add_event(lb, "schutzverletzung", reason, p.get("session_id", ""), dedupe_open=False)
    C.append_trace(lb, {**p, "laborbuch_blockiert": reason})
    print(f"Lab-notebook protection: {reason}", file=sys.stderr)
    return 2


def on_pre(lb: C.LB, p: dict) -> int:
    tool = p.get("tool_name", "")
    prot = C.protected_patterns(lb)
    if tool in WRITE_TOOLS:
        path = tool_path(p)
        if not path:
            return 0
        rel = lb.rel(path)
        if C.matches_any(rel, prot):
            return blocked(lb, p, f"{rel} is protected (reference data, conventions, ledger or infrastructure). "
                                  f"Changes only by the human; ledgers only via tools/lb.py.")
        target = lb.root / rel
        if target.suffix == ".qmd" and target.exists():
            fm, _, ok = C.parse_frontmatter(target.read_text(errors="replace"))
            if ok and C.normalize_status(fm.get("status")) == "closed":
                return blocked(lb, p, f"{rel} is closed and immutable. "
                                      f"Correct it in a new entry with `corrected: {target.parent.name}`.")
        return 0
    if tool == "Bash":
        cmd = (p.get("tool_input") or {}).get("command", "")
        if re.search(r"lb\.py\s+(schuetze|protect)\b", cmd):
            return blocked(lb, p, "`lb.py schuetze` (`protect`) may only be run by the human (maintainer only).")
        if re.search(r"\blb\.py\b", cmd) and not BASH_WRITE_RE.search(re.sub(r"\blb\.py\b.*", "", cmd)):
            return 0
        if BASH_WRITE_RE.search(cmd):
            for pat in prot:
                pref = C.literal_prefix(pat).rstrip("/")
                if pref and pref in cmd:
                    return blocked(lb, p, f"the shell command probably modifies the protected path `{pref}`.")
    return 0


# --------------------------------------------------------------------------- post / fail (relevance)

def classify_write(lb: C.LB, p: dict) -> list[tuple[str, str, str]]:
    path = tool_path(p)
    if not path:
        return []
    rel = lb.rel(path)
    rel_cfg = lb.cfg.get("relevanz", {})
    sid = p.get("session_id", "")
    out = []
    if C.matches_any(rel, rel_cfg.get("physik", [])):
        ti = p.get("tool_input") or {}
        prefixes = rel_cfg.get("kommentar_praefix", ["!"])
        if "old_string" in ti:
            old, new = ti.get("old_string", ""), ti.get("new_string", "")
        elif "edits" in ti:
            old = "\n".join(e.get("old_string", "") for e in ti["edits"])
            new = "\n".join(e.get("new_string", "") for e in ti["edits"])
        else:
            old = C.git_head_content(lb, rel) or ""
            new = ti.get("content", "")
        if C.normalize_code(old, prefixes) != C.normalize_code(new, prefixes):
            plus, minus = C.diff_stat(old, new)
            out.append(("code", f"{rel} (+{plus}/-{minus})", f"code:{sid}:{rel}"))
    if C.matches_any(rel, rel_cfg.get("abweichung", [])):
        out.append(("abweichung", f"{rel} changed (parameter space/test scope)", f"abw:{sid}:{rel}"))
    a = active_session(lb)
    if a and rel == f"{a['verzeichnis']}/plan.qmd" and a.get("plan_committed"):
        out.append(("plan-aenderung", f"plan of the active session changed after its start", f"plan:{sid}:{rel}"))
    return out


def classify_bash(lb: C.LB, p: dict, failed: bool) -> list[tuple[str, str, str]]:
    cmd = (p.get("tool_input") or {}).get("command", "")
    rel_cfg = lb.cfg.get("relevanz", {})
    sid = p.get("session_id", "")
    text = response_text(p)
    code = exit_code_from(p)
    failed = failed or (code is not None and code != 0)
    out = []
    is_test = any(re.search(rx, cmd) for rx in rel_cfg.get("test_befehle", []))
    if is_test:
        fail_rx = rel_cfg.get("test_fehler_muster", r"\b\d+ failed\b|FAILED|Tests? failed|\bFAIL\b")
        status = "FAIL" if (failed or re.search(fail_rx, text)) else "PASS"
        key = re.sub(r"\s+", " ", cmd.strip())
        with C.state_tx(lb) as st:
            prev = st.setdefault("teststatus", {}).get(key)
            st["teststatus"][key] = status
        if (prev is None and status == "FAIL") or (prev is not None and prev != status):
            detail = f"`{key[:80]}`: {status}" + (f" (previously {prev})" if prev else "")
            out.append(("test-wechsel", detail, ""))
    if failed and not is_test and any(re.search(rx, cmd) for rx in rel_cfg.get("build_befehle", [])):
        errs = [l for l in text.splitlines() if re.search(r"error|Error|FEHLER", l)][:3]
        sig = re.sub(r"\d+", "#", " ".join(errs))[:300]
        with C.state_tx(lb) as st:
            seen = st.setdefault("build_signaturen", {}).setdefault(sid, [])
            new = sig not in seen
            if new:
                seen.append(sig)
        if new:
            out.append(("build-fehler", (errs[0].strip()[:120] if errs else f"`{cmd[:60]}` failed"), ""))
    if any(re.search(rx, cmd) for rx in rel_cfg.get("lauf_befehle", [])):
        m = RUN_MARKER_RE.search(text)
        if m:
            out.append(("lauf", f"{m.group(1)} exit={m.group(2)}", f"lauf:{m.group(1)}"))
    return out


def on_post(lb: C.LB, p: dict, failed: bool) -> int:
    C.append_trace(lb, p)
    register_session_id(lb, p.get("session_id", ""))
    tool = p.get("tool_name", "")
    if tool in WRITE_TOOLS and not failed:
        found = classify_write(lb, p)
    elif tool == "Bash":
        found = classify_bash(lb, p, failed)
    else:
        found = []
    new = []
    for art, detail, key in found:
        eid = C.add_event(lb, art, detail, p.get("session_id", ""), key)
        if eid:
            new.append(f"{eid} ({C.event_label(art)}: {detail})")
    if new:
        n_open = len(C.open_events(lb))
        emit_context("PostToolUseFailure" if failed else "PostToolUse",
                     "Lab notebook: new events that must be documented " + "; ".join(new) +
                     f". Open events in total: {n_open}. Document them via `events:` "
                     f"(or `discarded:` with a reason) in the frontmatter of an entry.")
    return 0


# --------------------------------------------------------------------------- stop

def on_stop(lb: C.LB, p: dict) -> int:
    C.append_trace(lb, p)
    mode = lb.cfg.get("pruefung", {}).get("stop_pruefung", "immer")
    if mode == "nur-session" and not active_session(lb):
        return 0
    probs = C.full_check(lb, only_changed=True, render=True)
    max_blocks = int(lb.cfg.get("pruefung", {}).get("max_stop_blockaden", 5))
    with C.state_tx(lb) as st:
        if not probs:
            st["stop_blockaden"] = 0
            return 0
        st["stop_blockaden"] = st.get("stop_blockaden", 0) + 1
        n = st["stop_blockaden"]
    if n > max_blocks:
        C.add_event(lb, "stop-limit", f"Session ended despite {len(probs)} open lab-notebook problems",
                    p.get("session_id", ""), dedupe_open=False)
        (lb.state_dir / "UNERLEDIGT.md").write_text(
            f"# Unresolved lab-notebook problems ({C.now_iso()})\n\n" + "\n".join(f"- {x}" for x in probs) + "\n")
        with C.state_tx(lb) as st:
            st["stop_blockaden"] = 0
        return 0
    print("Lab-notebook check failed (attempt %d/%d). Fix before ending the session:\n" % (n, max_blocks)
          + "\n".join(f"- {x}" for x in probs[:40]), file=sys.stderr)
    return 2


# --------------------------------------------------------------------------- end

def on_end(lb: C.LB, p: dict) -> int:
    C.append_trace(lb, p)
    if lb.cfg.get("trace", {}).get("transkripte_archivieren", True):
        C.archive_transcript(lb, p)
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    try:
        lb = C.LB()
    except SystemExit:
        return 0
    try:
        if mode == "start":
            return on_start(lb, payload)
        if mode == "pre":
            return on_pre(lb, payload)
        if mode == "post":
            return on_post(lb, payload, failed=False)
        if mode == "fail":
            return on_post(lb, payload, failed=True)
        if mode == "stop":
            return on_stop(lb, payload)
        if mode == "end":
            return on_end(lb, payload)
        return 0
    except Exception:  # never block because of an internal error
        with open(lb.state_dir / "hook-fehler.log", "a") as f:
            f.write(f"--- {C.now_iso()} {mode}\n{traceback.format_exc()}\n")
        print("Lab-notebook hook: internal error, see laborbuch/_state/hook-fehler.log", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
