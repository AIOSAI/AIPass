[<- Back to the README](../README.md)

# Internals — import safety and the conformance corpus

**Branch** api · **Code** `apps/handlers/__init__.py`, `apps/handlers/module_root.py`, `apps/handlers/host/settings.py`

---

## No module needs a working directory to be imported (2026-08-31)

`ntpath.realpath` reads `os.getcwd()` **unconditionally** — not only for relative paths, the way
`posixpath` does — and `Path.resolve()` routes through it. So on Windows every
`Path(__file__).resolve()` *reached at import* is an import-time cwd dependency: a process whose
working directory has been deleted cannot import the module at all. On POSIX the equivalent raise
happens earlier, inside a `try` that `inspect` already owns, which is why this was invisible on
Linux for as long as it existed.

The discriminator is **reached at import**, not written at module scope, so it is measured by
*running* the imports in a child interpreter, never by grepping for spellings.

Measured here on 2026-08-31, two denial worlds (A: realpath reads cwd, then cwd is denied — convicts
a raw `resolve()`; B: realpath denied directly, abspath left working — convicts `inspect.stack`):

| stage | modules red (of 61) |
|---|---|
| before | 61 — the handlers guard masked everything |
| after the guard cure | 49 — one line left: `json_handler.py`'s `API_ROOT` |
| after routing three sites through `module_file()` | 0 |

*The table is the 08-31 measurement and is left as measured. Its middle row names
a line that no longer exists: `json_handler.py` became the fleet's shim on 09-04
(DPLAN-0325) and `API_ROOT` was retired with the old handler — do not grep for it.
Two module-level constants route through `module_file()` today, not three.*

Two cures:

- `apps/handlers/__init__.py` walks frames with `sys._getframe` instead of `inspect.stack()`,
  skips pseudo-files and importlib frames *before* any resolve, guards the resolve with a
  raw-spelling fallback, and reads the import line with `linecache`. The second `inspect.stack()`
  walk in the caller-is-None branch is gone — it was a second copy of the same cwd dependency in
  service of a branch that returned either way.
- `apps/handlers/module_root.py` holds `module_file()`, the one guarded spelling. **Two**
  module-level constants route through it today (`usage/aggregation.py`, `usage/tracking.py`)
  — it was three until 09-04, when `json/json_handler.py` became the fleet shim and stopped
  resolving anything of its own. Its diagnostics live inside their own protection: the world that reaches
  the fallback is the world where prax's logger may be down too, so `sys.stderr` is the last
  resort rather than a crash.

Pinned in `tests/test_dead_cwd_imports.py`. The behavioural pins cannot see the deleted
`inspect.stack()` walk — `apps/__init__` always supplies a real-file frame, so restoring the defect
leaves them green — so an **AST ban** convicts any `inspect.stack` call in the guard file. It is an
AST ban and not a string ban because the guard's own docstring names `inspect.stack` while
explaining the defect, and a spelling ban would convict the explanation.
## The settings conformance corpus (FPLAN-0438)

The settings lane is a faithful mirror of @baud's `settings.rs`, and a mirror
drifts. @baud measured six real divergences in one night — by *running* both
implementations, not by reading each other's source — and every one was a place
where the two faces would have written the operator's own config differently
while each believed it was correct.

Prose cannot hold a mirror straight; shared **data** can. `tests/conformance/settings/`
holds 39 cases in plain JSON — starting file state, the operation, the expected
outcome — that each runtime proves it satisfies in its own suite. The python
runner is `tests/test_settings_conformance.py`; a rust `#[test]` walks the same
files with `serde` and no translation, which is the whole design constraint.

Cases carry a per-runtime verdict, so a divergence one side has not closed yet
is **skipped and reported**, never quietly passed. Two differences are recorded
rather than forced: the desktop still accepts a zero compaction window and still
drops unknown patch keys (both freeze-gated on their side), and file mode
genuinely differs — python stages through `mkstemp` and lands `0600` whatever
the umask is, rust inherits it.

**A runtime difference and a platform difference are two axes, and 08-18 proved
it.** Six cases went red the first time the corpus ran on Windows — python on
Windows and rust on Windows hit the identical wall, so a per-runtime verdict
cannot describe it. Cases now carry an optional `platform` block, and every
capability in it is **measured on the machine**, never read off `sys.platform`:

- `unreadable_files` — write a file, `chmod 000`, try to read it. Absent for
  root and on Windows, where the mode only sets a read-only attribute. A case
  that needs it is **skipped with the capability named**, because its starting
  state could not be built and running it would measure the harness.
- `posix_mode_bits` — create with `0600`, read the mode back. Absent on Windows,
  so the mode expectation drops there and the rest of the case still counts.
- `parent_is_a_file_is_distinguishable` — put a **file** where a directory
  belongs and look at what opening through it raises. Where an OS reports it as
  `FileNotFoundError`, the missing-file-reads-blank rule genuinely cannot tell a
  broken tree from a fresh branch, and the read answers blank. That is a **real
  per-platform semantic divergence**, recorded as the expectation for that
  world rather than papered over — verified by feeding the door a
  `FileNotFoundError` and watching it answer blank.

**Digests normalize line endings before hashing, and the manifest says so in a
`digest` field.** git rewrites text files to CRLF on a Windows checkout under
`core.autocrlf`, so a raw byte digest measures which OS ran the checkout rather
than whether a case changed — it went red on the Windows lane with nothing
wrong. A scoped `.gitattributes` pins `eol=lf` as well, but the normalization is
the contract, because a vendored copy in another repository carries its own
checkout rules.

The corpus guards itself, because the failure that matters reports as success: a
manifest pins every case by digest and by count, so an empty corpus and a stale
one are both loud. Two further guards were added when the platform axis landed —
a capability probe that stops finding things would turn cases into *skips*,
which read as green, so a POSIX machine that fails to measure all three is an
error; and the skip path itself is exercised by taking the capabilities away by
hand, because on a box that has them the whole block is unreachable and a
mutation deleting it survived. See its own README for the format.

## The module that must import where it cannot run

`host/attach.py` hosts a PTY running a tmux client. A PTY is a Unix object and
tmux does not run on Windows, so **nothing in that module can work there** —
which is fine, guarded by `PTY_AVAILABLE`, and tested. Failing to **import** is
a different failure, and on 08-18 it cost 22 collection errors on the Windows
lane from one line: `_setsid: Any = os.setsid` in a function signature.

A default argument is evaluated when the module is imported. The three other
POSIX-only names in that same signature were already fetched with `getattr`;
this one was reached for directly, so the platform guard forty lines above it
never got the chance to run — and `server` imports `attach`, `host_api` imports
`server`, so eleven host test files went down across two workers.

Fixed at the line, then pinned two ways rather than one. An AST test asserts no
default in that signature is a bare attribute access, so the *next* one is
caught instead of shipped. And `tests/test_windows_import.py` imports **every**
module under `apps/` in a disposable child interpreter with POSIX hidden — a
`meta_path` finder refuses `fcntl`/`pty`/`termios`/`grp`/`pwd`/`resource`/`tty`
and the POSIX-only `os` attributes are deleted. Verified to bite: restoring the
old line reproduces the exact cascade, three failures from one character of
syntax. The finder matters — patching `builtins.__import__` puts the test file
into the import stack, where the fleet's cross-branch import gate reads it and
blocks the sweep instead of measuring anything.

---

[← api README](../README.md)
