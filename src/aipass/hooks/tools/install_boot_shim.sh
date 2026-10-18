#!/usr/bin/env bash
# install_boot_shim.sh — append the claude() shell function to ~/.bashrc and ~/.zshrc
# Idempotent: skips an rc file that already carries the marker.

set -euo pipefail

MARKER="# >>> AIPass boot shim >>>"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    VENV_PY="$REPO_ROOT/.venv/bin/python"
elif [ -x "$REPO_ROOT/.venv/Scripts/python.exe" ]; then
    VENV_PY="$REPO_ROOT/.venv/Scripts/python.exe"
else
    VENV_PY="python3"
fi

SHIM='
# >>> AIPass boot shim >>>
# Intercepts bare claude (or claude --permission-mode ...) in AIPass branch dirs.
# All other invocations (agents, auth, --resume, -c, --help, ...) pass through.
# Installed by: tools/install_boot_shim.sh
claude() {
    if [ -d ".trinity" ]; then
        case "${1-}" in
            ""|--permission-mode)
                __VENV_PY__ \
                    -m aipass.hooks.apps.handlers.lifecycle.session_boot "$@"
                return
                ;;
        esac
    fi
    command claude "$@"
}
# <<< AIPass boot shim <<<
'

# Bake the resolved interpreter into the shim (single-quoted above kept "$@" literal).
SHIM="${SHIM//__VENV_PY__/$VENV_PY}"

for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    if [ ! -f "$rc" ]; then
        echo "⏭  $rc does not exist, skipping"
        continue
    fi
    if grep -qF "$MARKER" "$rc"; then
        echo "✓  $rc already has the shim"
    else
        printf '%s\n' "$SHIM" >> "$rc"
        echo "✓  Appended shim to $rc"
    fi
done

echo ""
echo "Done. Source your shell rc or open a new terminal to activate:"
echo "  source ~/.bashrc   # or ~/.zshrc"
