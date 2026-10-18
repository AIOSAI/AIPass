[<- Back to BACKUP](../README.md)

# Path resolution — no resolve() at import

Why every module-level path goes through one stdlib-only helper, and what that protects against.

`ntpath.realpath` reads `os.getcwd()` **unconditionally** (posixpath only does so
for relative paths), and `Path.resolve()` routes through it. So on Windows every
`resolve()` *reached at import time* is an import-time crash for a process whose
cwd has been deleted: the module cannot be imported at all. The discriminator is
**reached-at-import**, not written-at-module-scope — a `resolve()` inside a
function that the module calls while importing is just as fatal.

Every module-level path in this branch therefore goes through one helper,
`handlers/path/module_paths.py`:

- `module_file(__file__)` — `resolve()` first, so symlinks still collapse
  normally; on `OSError` it degrades to `os.path.abspath`, which is the identity
  for an already-absolute path and needs no cwd.
- `branch_root(__file__, n)` — the same, then climbs `n` levels.

The helper is **stdlib-only on purpose**. Importing `@prax` here would put the
logger's own cwd-reading construction onto the path this module exists to
protect, so its diagnostics go to `sys.stderr` — reported once per path, because
in a dead-cwd world *every* resolve fails and one line per call would bury the
real traceback.

The handlers package guard walks `sys._getframe` rather than `inspect.stack()`.
`inspect.stack()` calls `getmodule` → `getabsfile` → `os.path.realpath` on every
frame with no guard (inspect.py:1009), so it dies before the guard's own
skip-the-pseudo-frame logic is ever consulted. Reading `f_code.co_filename` off
the frame touches no filesystem at all; where the fence resolves a real frame's
path it catches `OSError` and keeps the raw spelling, and a pseudo filename
(`<string>`, `<frozen ...>`) is never resolved.

The pin is `tests/test_dead_cwd_imports.py`. Note what it does and does not
do: it runs a child interpreter under two injections (two denial worlds) against
**9 representative modules** (`PROBE_MODULES`), not the whole tree; nothing in
CI re-walks every module. The file also carries an AST ban on
`inspect.stack()` — a behavioural test cannot catch its return, because the
branch that used it is unreachable from any import-shaped pin.

**Backup destinations are unaffected by all of this.** Every path under
`.backup/` is derived from the caller-supplied `project_root` (see
`handlers/path/builder.py`), never from a module-level resolve and never from
the cwd — so no backup or archive is written to a location derived from where
the caller's shell happens to be standing.

---

[<- Back to BACKUP](../README.md)
