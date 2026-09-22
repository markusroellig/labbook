#!/bin/bash
# Install the lab-notebook framework into a project (copies; nothing in the target is overwritten silently).
# Usage: ./install.sh /path/to/project [notebook-dir-name]   (default notebook dir: laborbuch)
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
P=${1:?project path}; B=${2:-laborbuch}
[ -d "$P/.git" ] || { echo "not a git repository: $P"; exit 1; }
mkdir -p "$P/tools" "$P/.claude/hooks" "$P/.claude/skills" "$P/.claude/agents" "$P/$B"
put() {  # source, target: copy unless the target exists
  if [ -e "$2" ]; then echo "keep     $2"; else cp -r "$1" "$2"; echo "install  $2"; fi
}
put "$HERE/tools/lb.py"                 "$P/tools/lb.py"
put "$HERE/hooks/labhook.py"            "$P/.claude/hooks/labhook.py"
put "$HERE/hooks/lb_common.py"          "$P/.claude/hooks/lb_common.py"
put "$HERE/skills/laborbuch"            "$P/.claude/skills/laborbuch"
put "$HERE/agents/protokoll-auditor.md" "$P/.claude/agents/protokoll-auditor.md"
put "$HERE/laborbuch.toml.example"      "$P/.claude/laborbuch.toml"
put "$HERE/CLAUDE.laborbuch.md"         "$P/CLAUDE.laborbuch.md"
put "$HERE/Makefile.laborbuch"          "$P/Makefile.laborbuch"
for f in _quarto.yml index.qmd konventionen.qmd .gitignore _vorlagen _extensions; do
  put "$HERE/laborbuch/$f" "$P/$B/$f"
done
if [ -e "$P/.claude/settings.json" ]; then
  echo "note     $P/.claude/settings.json exists: merge the hooks from $HERE/settings.hooks.json by hand"
else
  cp "$HERE/settings.hooks.json" "$P/.claude/settings.json"; echo "install  $P/.claude/settings.json"
fi
[ "$B" = laborbuch ] || echo "note     set [pfade] laborbuch = \"$B\" in $P/.claude/laborbuch.toml"
grep -q "CLAUDE.laborbuch.md" "$P/CLAUDE.md" 2>/dev/null || echo "note     add the line '@CLAUDE.laborbuch.md' to $P/CLAUDE.md"
echo "next     cd $P && python3 tools/lb.py preflight && python3 tools/lb.py protect   (protect: human only)"
