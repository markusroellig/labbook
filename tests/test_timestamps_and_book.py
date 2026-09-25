"""Entry timestamps (opened/closed) and the month/week/day structure of the generated book."""
import re

from conftest import write_hypothesis


def frontmatter_value(path, key):
    m = re.search(rf'^{key}:[ \t]*("[^"\n]*"|[^#\n]*)', path.read_text(), re.M)
    return m.group(1).strip().strip('"') if m else None


def test_new_entry_is_stamped_opened(project):
    entry = project.root / project.lb("new", "a", "--title", "A").stdout.strip()
    assert re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$", frontmatter_value(entry, "opened"))
    assert frontmatter_value(entry, "closed") == ""


def test_close_sets_status_verdict_and_timestamp(project):
    entry = project.root / project.lb("new", "a", "--title", "A").stdout.strip()
    write_hypothesis(entry)
    r = project.lb("close", entry.parent.name, "--verdict", "refuted", check=False)
    assert r.returncode == 1 and "empty" in r.stderr          # sections still empty: not closed
    assert frontmatter_value(entry, "status") == "open"
    t = entry.read_text()
    for sec in ("Why", "Method", "Result", "Verification", "Interpretation", "Consequences and next steps",
                "Failed attempts", "Deviations from plan"):
        t = t.replace(f"## {sec}\n", f"## {sec}\n\nnone\n", 1)
    entry.write_text(t)
    project.lb("close", entry.parent.name, "--verdict", "refuted")
    assert frontmatter_value(entry, "status") == "closed"
    assert frontmatter_value(entry, "verdict") == "refuted"
    assert frontmatter_value(entry, "closed") >= frontmatter_value(entry, "opened")
    assert project.lb("check", "--no-render", check=False).returncode == 0


def test_closed_entry_without_closed_timestamp_fails_the_check(project):
    entry = project.root / project.lb("new", "a", "--title", "A").stdout.strip()
    entry.write_text(entry.read_text().replace("status: open", "status: closed"))
    out = project.lb("check", "--no-render", check=False).stdout
    assert "needs a `closed` timestamp" in out


def test_template_without_timestamps_gets_them(project):
    tmpl = project.nb / "_templates" / "entry.qmd"
    tmpl.write_text(re.sub(r'^(opened|closed):.*\n', "", tmpl.read_text(), flags=re.M))
    entry = project.root / project.lb("new", "a", "--title", "A").stdout.strip()
    assert frontmatter_value(entry, "opened") and frontmatter_value(entry, "closed") == ""


def test_book_is_structured_by_month_week_day(project):
    specs = [("2026-08-31T10:00:00+02:00", "aug"),   # Monday of ISO week 36, in August
             ("2026-09-01T09:00:00+02:00", "sep1"),  # same ISO week, but September
             ("2026-09-01T15:00:00+02:00", "sep1b"),
             ("2026-09-09T11:00:00+02:00", "sep9")]  # week 37
    for opened, slug in specs:
        entry = project.root / project.lb("new", slug, "--title", f"Entry {slug}").stdout.strip()
        t = entry.read_text()
        t = re.sub(r'^opened:.*$', f'opened: "{opened}"', t, flags=re.M)
        t = re.sub(r'^date:.*$', f'date: {opened[:10]}', t, flags=re.M)
        t = t.replace("## Result\n", "## Result\n\n![plot](fig/p)\n\n![line [S I] (a)](fig/q){#fig-q}\n\n"
                      "```\n# not a heading\n```\n", 1)
        entry.write_text(t)
    project.lb("book", "--no-render")
    yml = (project.nb / "_quarto-book.yml").read_text()
    assert yml.index('part: "August 2026"') < yml.index('part: "September 2026"')
    gen = project.nb / "_generated" / "book"
    assert sorted(p.name for p in gen.glob("*.qmd")) == ["2026-08_W36.qmd", "2026-09_W36.qmd", "2026-09_W37.qmd"]
    w = (gen / "2026-09_W36.qmd").read_text()
    assert 'title: "Week 36 · 1 Sep 2026"' in w
    assert w.count("## Tuesday, 1 September 2026") == 1
    assert w.index("### Entry sep1\n") < w.index("### Entry sep1b\n")
    assert "opened 2026-09-01 09:00" in w
    assert "#### Result" in w                    # entry sections demoted below the entry heading
    assert "```\n# not a heading\n```" in w       # code blocks untouched
    assert re.search(r"!\[plot\]\(\.\./\.\./entries/[^)]*sep1/fig/p\)", w)   # figure path rewritten
    assert re.search(r"\[S I\] \(a\)\]\(\.\./\.\./entries/[^)]*sep1/fig/q\)", w)   # also with brackets in the caption
