"""Lint rule: figure references must not carry an explicit image extension."""
import lb_common as C

MSG = "figure reference carries an explicit extension"


def probs(body):
    return C.lint_entry_text("e/entry.qmd", body)


def test_explicit_extensions_are_errors():
    for ext in ("pdf", "png", "svg", "jpg"):
        p = probs(f"![cap](fig/a.{ext}){{#fig-a}}\n")
        assert len(p) == 1 and MSG in p[0] and f"fig/a.{ext}" in p[0]


def test_extensionless_and_foreign_paths_pass():
    assert probs("![cap](fig/a){#fig-a}\n![x](other/a.pdf)\n![u](https://x.org/fig/a.png)\n") == []


def test_opt_out_on_same_line_only():
    assert probs("![cap](fig/a.pdf) <!-- lint: allow-extension -->\n") == []
    assert len(probs("<!-- lint: allow-extension -->\n![cap](fig/a.pdf)\n")) == 1


def test_code_is_excluded():
    assert probs("```\n![cap](fig/a.pdf)\n```\nand `![c](fig/b.png)` inline\n") == []


def test_checker_reports_it_and_since_grandfathers(project):
    entry = project.root / project.lb("new", "figext", "--title", "t").stdout.strip()
    entry.write_text(entry.read_text() + "\n![c](fig/a.pdf)\n")
    (entry.parent / "fig").mkdir(exist_ok=True)
    (entry.parent / "fig" / "a.pdf").write_text("x")
    r = project.lb("check", "--all", "--no-render", check=False)
    assert r.returncode == 1 and MSG in r.stdout
    r = project.lb("check", "--all", "--no-render", "--since", "2999-01-01", check=False)
    assert MSG not in r.stdout
