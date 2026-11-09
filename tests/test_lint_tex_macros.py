"""Lint rule: TeX font switches undefined in the notebook LaTeX class (\\rm \\bf \\it \\sl \\sc \\tt) in math."""
import pytest

import lb_common as C


def sw(body):
    return C.lint_tex_switches(body)


@pytest.mark.parametrize("m", ["rm", "bf", "it", "sl", "sc", "tt"])
def test_inline_and_display_math(m):
    assert sw(f"text ${{\\{m} ext}}$ more") == [f"\\{m}"]
    assert sw(f"$$\n x_{{\\{m} a}} = 1\n$$") == [f"\\{m}"]
    assert sw(f"\\[ \\{m}\\ x \\]") == [f"\\{m}"]


def test_raw_latex_block_is_scanned():
    assert sw("```{=latex}\n{\\bf bold} text\n```\n") == ["\\bf"]


def test_proper_commands_and_longer_names_pass():
    body = "$\\mathrm{ext} \\mathbf{x} \\mathit{y} \\text{a} \\item \\scriptstyle \\tilde{x} \\sigma \\itshape$"
    assert sw(body) == []


def test_outside_math_ignored():
    assert sw("prose mentioning \\rm without math, price $5 and $6.") == []


def test_code_excluded():
    assert sw("```python\ns = '$\\rm x$'\n```\ninline `$\\bf x$` here\n") == []
    assert sw("~~~\n$$\\tt x$$\n~~~\n") == []


def test_html_comment_ignored():
    assert sw("<!-- $\\rm x$ -->") == []


def test_message_and_checker_integration(project):
    p = C.lint_entry_text("e/entry.qmd", "$a_{\\rm gas}$")
    assert len(p) == 1 and "undefined in the notebook LaTeX class" in p[0] and "\\mathrm" in p[0]
    entry = project.root / project.lb("new", "texsw", "--title", "t").stdout.strip()
    entry.write_text(entry.read_text() + "\nInline ${\\rm ext}$.\n")
    r = project.lb("check", "--all", "--no-render", check=False)
    assert r.returncode == 1 and "TeX font switch \\rm" in r.stdout
    r = project.lb("check", "--all", "--no-render", "--since", "2999-01-01", check=False)
    assert "TeX font switch" not in r.stdout
