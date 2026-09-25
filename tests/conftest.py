"""Fixtures: a throw-away git project with labbook installed by install.sh."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "hooks"))

GIT_ENV = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@example.org"}


def sh(cmd: list[str], cwd: Path, check: bool = True, **kw) -> subprocess.CompletedProcess:
    base = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "LB_ID_RANGE")}
    env = {**base, **GIT_ENV, **kw.pop("env", {})}
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env, **kw)
    if check and r.returncode != 0:
        raise AssertionError(f"{cmd} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


class Project:
    def __init__(self, root: Path, notebook: str = "labbook"):
        self.root = root
        self.nb = root / notebook

    def lb(self, *args: str, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
        return sh([sys.executable, "tools/lb.py", *args], self.root, check=check, env=env or {})

    def hook(self, mode: str, payload: dict) -> subprocess.CompletedProcess:
        payload = {"session_id": "test-session", **payload}
        return sh([sys.executable, ".claude/hooks/labhook.py", mode], self.root, check=False,
                  input=json.dumps(payload), env={"CLAUDE_PROJECT_DIR": str(self.root)})

    def git(self, *args: str) -> subprocess.CompletedProcess:
        return sh(["git", *args], self.root)

    def commit(self, msg: str = "commit") -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg, "--allow-empty")


def make_project(tmp_path: Path, notebook: str = "labbook") -> Project:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "model.py").write_text("# model\nK = 1.0  # rate\n")
    sh(["git", "init", "-q"], root)
    args = ["bash", str(REPO / "install.sh")]
    if notebook != "labbook":
        args += ["--notebook", notebook]
    sh(args + [str(root)], root)
    cfg = root / ".claude" / "labbook.toml"
    cfg.write_text(cfg.read_text().replace('render = "pdf"', 'render = "off"'))
    p = Project(root, notebook)
    p.commit("initial")
    p.lb("protect")
    p.commit("protection manifest")
    return p


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return make_project(tmp_path)


def write_hypothesis(entry: Path, text: str = "The error halves when h halves (ratio 2.0 +- 0.1).") -> None:
    t = entry.read_text()
    marker = "## Hypothesis / Expectation\n"
    entry.write_text(t.replace(marker, marker + "\n" + text + "\n", 1))
