"""PreToolUse protection: edits and (heuristically) shell writes to protected paths are blocked."""
import pytest

from conftest import write_hypothesis


def edit(project, rel):
    return project.hook("pre", {"tool_name": "Edit", "tool_input": {"file_path": str(project.root / rel),
                                                                     "old_string": "a", "new_string": "b"}})


def bash(project, cmd):
    return project.hook("pre", {"tool_name": "Bash", "tool_input": {"command": cmd}})


def test_edit_of_protected_file_is_blocked(project):
    r = edit(project, "labbook/conventions.qmd")
    assert r.returncode == 2
    assert "protected" in r.stderr


def test_edit_of_ordinary_file_is_allowed(project):
    assert edit(project, "src/model.py").returncode == 0


@pytest.mark.parametrize("cmd", [
    "rm labbook/results.tsv",
    "echo x > labbook/conventions.qmd",
    "sed -i s/a/b/ tools/lb.py",
    # chained after a harmless lb.py call (bypass of versions <= 0.1)
    "python3 tools/lb.py check; rm labbook/results.tsv",
    "python3 tools/lb.py events && echo x >> labbook/_state/events.jsonl",
    # the command executed by `lb.py run` is checked like any other
    "python3 tools/lb.py run --entry x -- rm -rf labbook/runs",
    # redirecting the output of lb.py into a protected file
    "python3 tools/lb.py events > labbook/results.tsv",
])
def test_shell_writes_to_protected_paths_are_blocked(project, cmd):
    assert bash(project, cmd).returncode == 2, cmd


@pytest.mark.parametrize("cmd", [
    "cat labbook/results.tsv",
    "rm -f build/tmp.o",
    'python3 tools/lb.py result R-0001 --metric m --value 1 --status info --description "rm labbook/results.tsv > x"',
    "python3 tools/lb.py run --entry x --output 'labbook/runs/*' -- python3 src/model.py",
    "git status && python3 tools/lb.py events --open",
])
def test_harmless_shell_commands_pass(project, cmd):
    assert bash(project, cmd).returncode == 0, cmd


def test_protect_is_reserved_for_the_human(project):
    assert bash(project, "python3 tools/lb.py protect").returncode == 2
    assert bash(project, "python3 tools/lb.py schuetze").returncode == 2


def test_blocked_attempt_becomes_an_event(project):
    bash(project, "rm labbook/results.tsv")
    out = project.lb("events", "--open").stdout
    assert "protection violation" in out


def test_closed_entry_is_immutable(project):
    entry = project.root / project.lb("new", "x", "--title", "X").stdout.strip()
    write_hypothesis(entry)
    entry.write_text(entry.read_text().replace("status: open", "status: closed"))
    project.commit("close")
    r = edit(project, entry.relative_to(project.root))
    assert r.returncode == 2 and "closed" in r.stderr


def test_manifest_detects_a_modified_protected_file(project):
    conv = project.nb / "conventions.qmd"
    conv.write_text(conv.read_text() + "\nsneaky change\n")
    r = project.lb("check", "--no-render", check=False)
    assert r.returncode == 1
    assert "Protected file modified: labbook/conventions.qmd" in r.stdout
