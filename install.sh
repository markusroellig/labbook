#!/bin/bash
# Install the labbook framework into a project, or upgrade the code of an existing installation.
#
#   ./install.sh [--notebook DIR] /path/to/project    fresh install (existing files are kept, never overwritten)
#   ./install.sh --upgrade /path/to/project           replace tool, hooks and shortcode extension only
#
# DIR is the notebook directory inside the project (default: labbook).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
NB=labbook; UPGRADE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --notebook) NB=${2:?--notebook needs a directory name}; shift 2 ;;
    --upgrade)  UPGRADE=1; shift ;;
    -h|--help)  sed -n '2,8p' "$0"; exit 0 ;;
    -*)         echo "unknown option $1"; exit 1 ;;
    *)          P=$1; shift ;;
  esac
done
P=${P:?usage: install.sh [--notebook DIR] [--upgrade] /path/to/project}
P=$(cd "$P" && pwd)
git -C "$P" rev-parse --git-dir >/dev/null 2>&1 || { echo "not a git repository: $P"; exit 1; }

if [ "$UPGRADE" = 1 ]; then
  CFG=""
  for c in "$P/.claude/labbook.toml" "$P/.claude/laborbuch.toml"; do [ -z "$CFG" ] && [ -e "$c" ] && CFG=$c; done
  [ -n "$CFG" ] || { echo "no labbook installation in $P (.claude/labbook.toml missing)"; exit 1; }
  NB=$(python3 -c 'import sys,tomllib; c=tomllib.load(open(sys.argv[1],"rb")); print((c.get("paths") or c.get("pfade") or {}).get("notebook") or (c.get("pfade") or {}).get("laborbuch") or "labbook")' "$CFG")
  cp "$HERE/tools/lb.py" "$P/tools/lb.py";                 echo "upgrade  $P/tools/lb.py"
  cp "$HERE/hooks/labhook.py" "$HERE/hooks/lb_common.py" "$P/.claude/hooks/"; echo "upgrade  $P/.claude/hooks/"
  for ext in labbook laborbuch; do                          # legacy notebooks keep their extension name
    d="$P/$NB/_extensions/$ext"
    [ -d "$d" ] && cp "$HERE/notebook/_extensions/labbook/labbook.lua" "$d/$ext.lua" && echo "upgrade  $d/$ext.lua"
  done
  echo "note     config, templates, conventions, skill and agent were left unchanged; compare them with $HERE"
  echo "next     the maintainer re-runs: python3 tools/lb.py protect   and commits the manifest"
  exit 0
fi

mkdir -p "$P/tools" "$P/.claude/hooks" "$P/.claude/skills" "$P/.claude/agents" "$P/$NB"
put() {  # source, target: copy unless the target exists
  if [ -e "$2" ]; then echo "keep     $2"; else cp -r "$1" "$2"; echo "install  $2"; NEW+=("$2"); fi
}
NEW=()
put "$HERE/tools/lb.py"                 "$P/tools/lb.py"
put "$HERE/hooks/labhook.py"            "$P/.claude/hooks/labhook.py"
put "$HERE/hooks/lb_common.py"          "$P/.claude/hooks/lb_common.py"
put "$HERE/skills/labbook"              "$P/.claude/skills/labbook"
put "$HERE/agents/labbook-auditor.md"   "$P/.claude/agents/labbook-auditor.md"
put "$HERE/labbook.toml.example"        "$P/.claude/labbook.toml"
put "$HERE/CLAUDE.labbook.md"           "$P/CLAUDE.labbook.md"
put "$HERE/Makefile.labbook"            "$P/Makefile.labbook"
for f in _quarto.yml index.qmd conventions.qmd .gitignore _templates _extensions; do
  put "$HERE/notebook/$f" "$P/$NB/$f"
done

# A notebook directory other than `labbook`: rewrite the paths in the freshly installed text files.
if [ "$NB" != labbook ]; then
  for f in "${NEW[@]}"; do
    case "$f" in
      *labbook.toml|*CLAUDE.labbook.md|*/skills/labbook|*labbook-auditor.md)
        [ -d "$f" ] && f="$f/SKILL.md"
        NB="$NB" perl -pi -e 's#([ "`(])labbook/#$1$ENV{NB}/#g; s#^notebook = "labbook"#notebook = "$ENV{NB}"#' "$f"
        echo "adapt    $f (notebook directory $NB/)" ;;
    esac
  done
fi

# Register the hooks: merge into an existing .claude/settings.json (backup first).
python3 - "$HERE/settings.hooks.json" "$P/.claude/settings.json" <<'PY'
import json, shutil, sys
from pathlib import Path
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
new = json.loads(src.read_text())
if not dst.exists():
    dst.write_text(json.dumps(new, indent=2) + "\n"); print(f"install  {dst}"); sys.exit()
cur = json.loads(dst.read_text() or "{}")
if "labhook.py" in json.dumps(cur):
    print(f"keep     {dst} (labbook hooks already registered)"); sys.exit()
shutil.copy(dst, dst.with_suffix(".json.bak"))
hooks = cur.setdefault("hooks", {})
for event, groups in new["hooks"].items():
    hooks.setdefault(event, []).extend(groups)
dst.write_text(json.dumps(cur, indent=2) + "\n")
print(f"merge    {dst} (backup: {dst.name}.bak)")
PY

# Transcript archive stays out of git.
grep -qx '/.labbook-archive/' "$P/.gitignore" 2>/dev/null || { echo '/.labbook-archive/' >> "$P/.gitignore"; echo "append   $P/.gitignore: /.labbook-archive/"; }
grep -q "CLAUDE.labbook.md" "$P/CLAUDE.md" 2>/dev/null || echo "note     add the line '@CLAUDE.labbook.md' to $P/CLAUDE.md"
echo "next     edit $P/.claude/labbook.toml (protected paths, code patterns, book title)"
echo "next     cd $P && python3 tools/lb.py preflight && python3 tools/lb.py protect   (protect: human only), then commit"
