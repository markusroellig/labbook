"""Fixes ported from the originating project on 2026-11-05: `lb.py commit` (private index), trace rotation,
the content-keyed render cache and negative exponent values for `result`."""
import json
import sys

import lb_common as C
from conftest import write_hypothesis


def new_entry(project, slug):
    return project.root / project.lb("new", slug, "--title", slug).stdout.strip()


def committed_run(project, slug="fixes"):
    entry = new_entry(project, slug)
    write_hypothesis(entry)
    project.commit(f"{entry.parent.name}: hypothesis")
    r = project.lb("run", "--entry", entry.parent.name, "--", "true")
    return entry, r.stdout.split()[1]            # "RUN R-0001 exit=0"


def test_result_accepts_negative_exponent_values(project):
    _, rid = committed_run(project)
    project.lb("result", rid, "--metric", "bias", "--value", "-7e-05", "--status", "keep",
               "--description", "negative exponent notation is a value, not an option")
    project.lb("result", rid, "--metric", "bias2", "--value=-7.5", "--status", "info", "--description", "x")
    rows = (project.nb / "results.tsv").read_text().splitlines()
    assert any("\tbias\t-7e-05\t" in r for r in rows) and any("\tbias2\t-7.5\t" in r for r in rows)


def test_commit_takes_only_the_named_paths(project):
    a = new_entry(project, "mine")
    b = new_entry(project, "theirs")
    project.git("add", "--", str(b))             # another agent has staged its entry in the shared index
    msg = project.root / "msg.txt"
    msg.write_text(f"{a.parent.name}: hypothesis committed by lb.py commit\n")

    r = project.lb("commit", a.parent.name, "-F", str(msg), "--dry-run")
    assert "would commit 2 file(s)" in r.stdout        # entry.qmd + analysis.py
    r = project.lb("commit", a.parent.name, "-F", str(msg), "--no-push")
    assert "(2 file(s))" in r.stdout
    head_files = project.git("show", "--stat", "--format=%s", "HEAD").stdout
    assert a.parent.name in head_files and b.parent.name not in head_files
    assert head_files.startswith(a.parent.name)
    # the other agent's staged file is untouched; mine is clean in the shared index
    status = project.git("status", "--short").stdout
    assert f"A  labbook/entries/{b.parent.name}/entry.qmd" in status
    assert a.parent.name not in status

    r = project.lb("commit", "no-such-entry", "-F", str(msg), "--no-push", check=False)
    assert r.returncode == 1 and "unknown entry or path" in r.stderr
    r = project.lb("commit", a.parent.name, "-F", str(msg), "--no-push")
    assert "nothing to commit" in r.stdout


def test_commit_ledger_adds_results_and_state(project):
    _, rid = committed_run(project)
    msg = project.root / "msg.txt"
    msg.write_text("ledger rows\n")
    r = project.lb("commit", "--ledger", "-F", str(msg), "--no-push")
    files = project.git("show", "--name-only", "--format=", "HEAD").stdout.split()
    assert "labbook/results.tsv" in files and f"labbook/runs/{rid}/provenance.json" not in files
    assert project.lb("check", "--no-render", check=False).returncode in (0, 1)


def test_trace_rotates_into_part_files(project):
    cfg = project.root / ".claude" / "labbook.toml"
    cfg.write_text(cfg.read_text().replace("[trace]\n", "[trace]\nrotate_mb = 0.0002\n", 1))   # 200 bytes
    for i in range(4):
        project.hook("post", {"tool_name": "Bash", "tool_input": {"command": f"echo {i}"},
                              "tool_response": {"stdout": "x" * 300}})
    names = sorted(p.name for p in (project.nb / "_trace").glob("*.jsonl"))
    assert any(n.endswith("_p2.jsonl") for n in names), names
    assert any(n.endswith("_p3.jsonl") for n in names), names
    records = [json.loads(l) for p in (project.nb / "_trace").glob("*.jsonl") for l in p.read_text().splitlines()]
    assert sum(1 for r in records if r.get("hook_event_name") == "PostToolUse" or "tool_name" in r) >= 4
    st = json.loads((project.nb / "_state" / "state.json").read_text())
    assert st["trace_dateien"]["test-session"].endswith("_p4.jsonl")   # every call exceeded the limit


def test_render_key_follows_content_not_mtime(project):
    entry = new_entry(project, "cache")
    lb = C.LB(project.root)
    k0 = C.render_key(lb, entry, "pdf")
    entry.touch()                                                  # mtime changes, content does not
    assert C.render_key(lb, entry, "pdf") == k0
    assert C.render_key(lb, entry, "html") != k0
    fig = entry.parent / "fig" / "f.png"
    fig.write_bytes(b"PNG1")
    t = entry.read_text()
    entry.write_text(t + "\n![a figure](fig/f.png)\n")
    k1 = C.render_key(lb, entry, "pdf")
    assert k1 != k0
    fig.write_bytes(b"PNG2")                                       # a changed figure changes the key
    assert C.render_key(lb, entry, "pdf") != k1
