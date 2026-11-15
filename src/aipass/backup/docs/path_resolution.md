[<- Back to BACKUP](../README.md)

# Path resolution and a dead cwd

What still reads the cwd, what the tests pin, and where backups land.

Module-level paths are plain `Path(__file__).resolve().parents[n]`. On Linux a
loaded module's `__file__` is absolute, and `resolve()` reads `os.getcwd()`
only for a relative path, so these never touch the cwd.

The handlers package guard walks `sys._getframe` rather than `inspect.stack()`.
`inspect.stack()` calls `getmodule` → `getabsfile` → `os.path.realpath` on every
frame with no guard (inspect.py:1009), so it dies before the guard's own
skip-the-pseudo-frame logic is ever consulted. Reading `f_code.co_filename` off
the frame touches no filesystem at all; where the fence resolves a real frame's
path it catches `OSError` and keeps the raw spelling, and a pseudo filename
(`<string>`, `<frozen ...>`) is never resolved.

The pin is `tests/test_dead_cwd_imports.py`. Note what it does and does not
do: it runs a child interpreter with `os.getcwd()` denied against
**8 representative modules** (`PROBE_MODULES`), not the whole tree; nothing in
CI re-walks every module.

**Backup destinations are unaffected by all of this.** Every path under
`.backup/` is derived from the caller-supplied `project_root` (see
`handlers/path/builder.py`), never from a module-level resolve and never from
the cwd — so no backup or archive is written to a location derived from where
the caller's shell happens to be standing.

---

[<- Back to BACKUP](../README.md)
