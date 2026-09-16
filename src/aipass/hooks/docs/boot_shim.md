# The boot shim — it edits your shell startup files

**Branch** hooks · **Code** `tools/install_boot_shim.sh`, `apps/handlers/lifecycle/session_boot.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

---

## The Boot Shim — it edits your shell startup files

`tools/install_boot_shim.sh` is the one thing in this branch that writes outside the repo, so it is
documented rather than left to be discovered. Verified by reading the script, 2026-09-05:

- It **appends** a `claude()` shell function to `~/.bashrc` **and** `~/.zshrc`, between the markers
  `# >>> AIPass boot shim >>>` / `# <<< AIPass boot shim <<<`. A missing rc file is skipped, and a rc
  file already carrying the marker is left alone, so re-running is safe.
- The function intercepts **only** bare `claude` and `claude --permission-mode …`, and **only** when
  the current directory contains a `.trinity/` directory. Everything else — `claude agents`,
  `--resume`, `-c`, `auth`, `--help` — falls through to `command claude` untouched.
- An intercepted call runs `python -m aipass.hooks.apps.handlers.lifecycle.session_boot`, with the
  interpreter resolved from the repo's own `.venv` at install time (POSIX and Windows layouts both
  probed, falling back to `python3`). No user path is hardcoded.

There is no uninstall script: remove the marked block from each rc file by hand.

---

## Related

- [project_config.md](project_config.md) — what `aipass init` stamps into a project
