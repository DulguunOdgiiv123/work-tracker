#!/bin/sh
# One-time setup of `wt` on another PC (WSL or Linux).
# Run after cloning:  sh ~/work-tracker/tools/setup-pc.sh
set -e
DIR="$HOME/work-tracker"
gh auth status >/dev/null 2>&1 || { echo "First run: gh auth login"; exit 1; }
python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q -r "$DIR/tools/requirements.txt"
mkdir -p "$HOME/bin"
printf '#!/bin/sh\nexec "$HOME/work-tracker/.venv/bin/python" "$HOME/work-tracker/tools/wt.py" "$@"\n' > "$HOME/bin/wt"
chmod +x "$HOME/bin/wt"
case ":$PATH:" in *":$HOME/bin:"*) ;; *) echo 'Add ~/bin to PATH in ~/.zshrc:  export PATH="$HOME/bin:$PATH"' ;; esac
RULES="$HOME/.claude/CLAUDE.md"
if [ -f "$RULES" ] && ! grep -q '^## Work tracker (every session)' "$RULES"; then
  cat "$DIR/tools/claude-rule.md" >> "$RULES"
  echo "Added the tracker rule to $RULES"
fi
echo "Next: wt init   (type the tracker password), then: wt list"
