"""Installation variants and compatibility with notebooks of the first (German-named) version."""
import json
import shutil
import subprocess
import sys

import lb_common as C
from conftest import REPO, Project, make_project, sh


def test_normalize_config_maps_german_names():
    cfg = C.normalize_config({
        "pfade": {"laborbuch": "lb", "archiv": ".a"},
        "schutz": {"geschuetzt": ["x"], "nur_anhaengen": ["y"]},
        "pruefung": {"render": "aus", "stop_pruefung": "nur-session", "max_stop_blockaden": 3},
        "lauf": {"dirty_erlaubt": False},
        "trace": {"max_zeichen": 10},
    })
    assert cfg["paths"] == {"notebook": "lb", "archive": ".a"}
    assert cfg["protection"] == {"protected": ["x"], "append_only": ["y"]}
    assert cfg["check"] == {"render": "off", "stop_check": "session-only", "max_stop_blocks": 3}
    assert cfg["run"] == {"allow_dirty": False}
    assert cfg["trace"] == {"max_chars": 10}


def test_english_name_wins_over_german():
    cfg = C.normalize_config({"pruefung": {"render": "aus"}, "check": {"render": "html"}})
    assert cfg["check"]["render"] == "html"


def test_custom_notebook_directory(tmp_path):
    p = make_project(tmp_path, notebook="notes")
    cfg = (p.root / ".claude" / "labbook.toml").read_text()
    assert 'notebook = "notes"' in cfg and '"notes/results.tsv"' in cfg
    assert "`notes/`" in (p.root / "CLAUDE.labbook.md").read_text()
    entry = p.lb("new", "a", "--title", "A").stdout.strip()
    assert entry.startswith("notes/entries/")


def test_settings_json_is_merged_not_replaced(tmp_path):
    root = tmp_path / "proj"
    (root / ".claude").mkdir(parents=True)
    sh(["git", "init", "-q"], root)
    (root / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}}))
    sh(["bash", str(REPO / "install.sh"), str(root)], root)
    s = json.loads((root / ".claude" / "settings.json").read_text())
    assert s["permissions"] == {"allow": ["Bash(ls)"]}
    assert "labhook.py" in json.dumps(s["hooks"]["PreToolUse"])
    assert (root / ".claude" / "settings.json.bak").exists()
    sh(["bash", str(REPO / "install.sh"), str(root)], root)          # idempotent
    s2 = json.loads((root / ".claude" / "settings.json").read_text())
    assert len(s2["hooks"]["PreToolUse"]) == 1


def test_legacy_notebook_layout(tmp_path):
    """A notebook of the first version: German config keys, laborbuch.toml, _vorlagen/, eintraege/."""
    p = make_project(tmp_path)
    root = p.root
    claude = root / ".claude"
    (claude / "labbook.toml").unlink()
    (claude / "labbook.sha256").unlink()
    (claude / "laborbuch.toml").write_text(
        '[pfade]\nlaborbuch = "laborbuch"\n[schutz]\ngeschuetzt = ["laborbuch/konventionen.qmd"]\n'
        '[pruefung]\nrender = "aus"\n')
    old = root / "laborbuch"
    shutil.move(str(p.nb), old)
    (old / "_templates").rename(old / "_vorlagen")
    (old / "_vorlagen" / "entry.qmd").rename(old / "_vorlagen" / "eintrag.qmd")
    (old / "conventions.qmd").rename(old / "konventionen.qmd")
    lp = Project(root, "laborbuch")
    lp.commit("legacy layout")
    lp.lb("schuetze")
    assert (claude / "laborbuch.sha256").exists()
    entry = lp.lb("neu", "alt", "--titel", "Alt").stdout.strip()
    assert entry.startswith("laborbuch/eintraege/")
    assert lp.lb("pruefe", "--ohne-render").returncode == 0
    r = lp.hook("pre", {"tool_name": "Edit", "tool_input": {"file_path": str(old / "konventionen.qmd")}})
    assert r.returncode == 2
    assert "protection violation" in lp.lb("ereignisse", "--offen").stdout


def test_upgrade_replaces_code_only(tmp_path):
    p = make_project(tmp_path)
    (p.root / "tools" / "lb.py").write_text("# old\n")
    cfg = (p.root / ".claude" / "labbook.toml").read_text()
    sh(["bash", str(REPO / "install.sh"), "--upgrade", str(p.root)], p.root)
    assert (p.root / "tools" / "lb.py").read_text() == (REPO / "tools" / "lb.py").read_text()
    assert (p.root / ".claude" / "labbook.toml").read_text() == cfg


def test_demo_script_runs(tmp_path):
    r = subprocess.run(["bash", str(REPO / "examples" / "demo" / "run_demo.sh"), str(tmp_path / "demo")],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
                                                            "LB_DEMO_NO_BOOK": "1", "PYTHON": sys.executable})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Lab-notebook check passed." in r.stdout
