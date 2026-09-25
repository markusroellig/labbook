"""The experiment workflow: entry -> committed hypothesis -> run -> result -> events -> check."""
import json
import sys

from conftest import write_hypothesis


def new_entry(project, slug="euler-order"):
    return project.root / project.lb("new", slug, "--title", "Order of explicit Euler").stdout.strip()


def test_run_requires_a_hypothesis(project):
    entry = new_entry(project)
    r = project.lb("run", "--entry", entry.parent.name, "--", "true", check=False)
    assert r.returncode == 1 and "Hypothesis" in r.stderr


def test_run_requires_the_hypothesis_to_be_committed(project):
    entry = new_entry(project)
    write_hypothesis(entry)
    r = project.lb("run", "--entry", entry.parent.name, "--", "true", check=False)
    assert r.returncode == 1 and "not committed" in r.stderr


def test_full_cycle(project):
    entry = new_entry(project)
    eid = entry.parent.name
    write_hypothesis(entry)
    project.commit(f"{eid}: hypothesis")

    r = project.lb("run", "--entry", eid, "--param", "h=0.01", "--input", "src/model.py",
                   "--description", "fiducial", "--", sys.executable, "src/model.py")
    assert "RUN R-0001 exit=0" in r.stdout
    prov = json.loads((project.nb / "runs" / "R-0001" / "provenance.json").read_text())
    assert prov["parameter"] == {"h": "0.01"}
    assert prov["git"]["dirty"] is False
    assert "src/model.py" in prov["eingaben_sha256"]

    project.lb("result", "R-0001", "--metric", "order", "--value", "1.0", "--status", "keep",
               "--description", "observed order")
    rows = (project.nb / "results.tsv").read_text().splitlines()
    assert rows[0].startswith("zeit\tlauf\teintrag") and len(rows) == 3

    # the PostToolUse hook registers the run as an event that must be documented
    project.hook("post", {"tool_name": "Bash", "tool_input": {"command": "python3 tools/lb.py run --entry x -- y"},
                          "tool_response": {"stdout": r.stdout}})
    r_check = project.lb("check", "--no-render", check=False)
    assert r_check.returncode == 1 and "is not documented" in r_check.stdout

    # listing the run in `runs:` documents the run event
    entry.write_text(entry.read_text().replace("runs: []", "runs: [R-0001]"))
    r_check = project.lb("check", "--no-render", check=False)
    assert r_check.returncode == 0, r_check.stdout


def test_discarded_event_needs_a_reason(project):
    project.hook("post", {"tool_name": "Edit", "tool_input": {"file_path": str(project.root / "src/model.py"),
                                                              "old_string": "K = 1.0", "new_string": "K = 2.0"}})
    ev = project.lb("events", "--open").stdout.split()[0]
    entry = new_entry(project)
    entry.write_text(entry.read_text().replace("discarded: {}", f'discarded:\n  {ev}: ""'))
    assert project.lb("check", "--no-render", check=False).returncode == 1
    entry.write_text(entry.read_text().replace(f'{ev}: ""', f'{ev}: "typo fixed at once, no run affected"'))
    assert project.lb("check", "--no-render", check=False).returncode == 0


def test_comment_only_change_is_not_a_code_event(project):
    src = str(project.root / "src/model.py")
    project.hook("post", {"tool_name": "Edit", "tool_input": {"file_path": src, "old_string": "K = 1.0  # rate",
                                                              "new_string": "K = 1.0  # decay rate in 1/s"}})
    assert project.lb("events", "--open").stdout.strip() == ""
    project.hook("post", {"tool_name": "Edit", "tool_input": {"file_path": src, "old_string": "K = 1.0",
                                                              "new_string": "K = 1.5"}})
    assert "code change" in project.lb("events", "--open").stdout


def test_run_id_range(project):
    entry = new_entry(project)
    write_hypothesis(entry)
    project.commit("h")
    r = project.lb("run", "--entry", entry.parent.name, "--", "true", env={"LB_ID_RANGE": "1000-1999"})
    assert "RUN R-1000 exit=0" in r.stdout
    r = project.lb("run", "--entry", entry.parent.name, "--", "true", env={"LB_ID_RANGE": "1000-1999"})
    assert "RUN R-1001 exit=0" in r.stdout
    r = project.lb("run", "--entry", entry.parent.name, "--", "true")
    assert "RUN R-1002 exit=0" in r.stdout      # without a range: max + 1


def test_german_command_names_still_work(project):
    r = project.lb("neu", "alt", "--titel", "Alter Name")
    assert r.stdout.strip().endswith("entry.qmd")
    assert project.lb("ereignisse", "--offen").returncode == 0
