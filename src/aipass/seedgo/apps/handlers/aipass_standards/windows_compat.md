# Windows Compatibility
**Status:** Draft v1.1
**Date:** 2026-10-16

---

## What It Is

A standard that ensures Python code runs on both Linux and Windows by detecting
POSIX-only APIs used without platform guards.  No CI runner exercises Windows:
this standard is the only guard, and nothing proves the Windows paths at runtime.

---

## Why It Matters

AIPass is pip-installable and must work cross-platform.  POSIX-only patterns
like bare `import fcntl` or `os.waitpid(-1, os.WNOHANG)` crash immediately on
Windows with `ImportError` or `WinError 87`.  This standard prevents regressions.

---

## What the Checker Scans For

AST-parses every `.py` file and flags POSIX-only usage outside platform guards.

### Rule 1 — POSIX-only imports
`import fcntl`, `import pwd`, `import grp`, `import termios`, `import resource`
without `if sys.platform` or `try/except ImportError`.

### Rule 2 — POSIX-only constants
`os.WNOHANG`, `signal.SIGPIPE` without platform guard or `hasattr()` check.

### Rule 3 — POSIX-only calls
`os.fork()`, `os.setpgid()`, `os.killpg()`, `os.getpgid()`, `os.waitpid()`
without platform guard.

### Rule 4 — os.kill without exception handling
`os.kill(pid, signal)` without `try/except OSError`.  Windows raises
`OSError: [WinError 87] The parameter is incorrect` for invalid PIDs.

### Rule 5 — platform-only import deferred into a function (checker 1.4.0)
`fcntl`, `pwd`, `grp`, `termios`, `resource`, `msvcrt` or `winreg` imported
inside a function body, outside a `try` whose handler catches `ImportError`
(or `ModuleNotFoundError`, `Exception`, a bare `except`). A `sys.platform` /
`os.name` guard does **not** clear this rule: a deferred import is decided at
call time, after a test may have pretended another platform. Specimen: devpulse
a831fe55 (PR #774, CI 38068553235) — registry's `_FileLock` imported `fcntl`
under `sys.platform != "win32"`; the off-Linux liveness tests pretend darwin,
so the Windows runner imported a module it lacks. Acquitted shape: one
module-level `try: import fcntl / except ImportError: fcntl = None` (logged),
and the function reads the binding (`if fcntl is not None:`). Module-level
imports — gated by platform or by try/except — are decided once at import,
before any test runs, and are not read by this rule. A line Rule 1 already
reports is not reported twice.

### Rule 6 — a stream answer pinned at import (checker 1.5.0)
Product files only (not `tests/`, `test_*.py`, `conftest.py`). Flags, in code a
module runs when imported, a rich `Console(...)` — the name, an alias from
`from rich.console import Console as X`, `rich.console.Console`, or a same-file
subclass — and any `.isatty()` / `get_terminal_size()` call. Rich runs
`_detect_color_system()` in `Console.__init__` and keeps the answer (rich
15.0.0, console.py:710, read per print at console.py:2136), so leaving
`force_terminal` unset does not make colour live. Specimen: cli b6655280 (PR
#774, CI 38068553235) — display.py read `sys.stdout.isatty()` into `_IS_TTY`
and built `CONSOLE = Console(force_terminal=_IS_TTY)`; a conftest imported it
while pytest's capture was suspended, a Windows xdist worker's stdout is NUL
and NUL answers `isatty()` True, so every later capture carried escape codes
(380 of 518 Windows rows, fleet-wide). Linux and macOS pipes answer False.

Read: the module body, class bodies, and the bodies and heads of module-level
`if` / `try` / `with` / `for` / `while`. Not read: function bodies, lambdas,
`if __name__ == "__main__":`, and `except` handlers — the fleet's 27 module-level
consoles in handlers are all `except ImportError` fallbacks for
`from aipass.cli.apps.modules import console`, which never runs where the
package is installed (measured 2026-10-10). Acquitted: `file=` anything other
than `sys.stdout` / `sys.stderr` (a buffer decides against itself),
`force_terminal=True` / `False` (a constant, not a stream answer),
`color_system=None`, a `**kwargs` call (the decision is not in the file), and a
subclass that defines `_color_system` — cli's `_LiveConsole`, which re-detects
colour per print against the live stream (the cure). One row per line.

Known misses: a console built at import in another module's function the
module calls at import; `Console` reached through a factory or a re-export.
Measured at introduction (2026-10-10, 1638 product files): 1 row, seedgo's own
`diagnostics_check.py` (cured the same day: the console is built in its
`__main__` block); cli's cured display.py acquitted.

### Rule 7 — a tmp_path name holding a backslash, written (checker 1.6.0)
Test files only, in `test_*` functions with no platform skipif (the test-file
arm that also reads `os.chmod` / `os.symlink` / `stat.S_I*`). Flags a write —
`.write_text` / `.write_bytes` / `.touch` / `.mkdir`, `.open(...)` or
`open(...)` with a `w` / `a` / `x` / `+` mode — to a path rooted at the
`tmp_path` / `tmpdir` fixture (`/` chains and `.joinpath(...)`) where a string
literal segment holds a backslash, either in place or through a name bound
once in the function to such a path. On POSIX that is one file whose name
carries backslashes; on Windows it is a tree whose parents do not exist, so
the write raises before the code under test runs. Specimen: seedgo's own
`tests/test_checkers_batch7.py` (PR #774, CI 38087470872, rows 1 and 2) wrote
`tmp_path / "aipass\\memory\\apps\\modules\\door_entry_limits.py"`. Acquitted:
the cure (a real tree written with `joinpath(...)` and `mkdir(parents=True)`,
its Windows spelling handed over as a string via `PureWindowsPath`), a
backslashed name only read or handed on (the same missing file on both
hosts), a test under a platform skipif or `sys.platform` guard (it means the
POSIX name), and a name bound more than once (which binding reaches the write
needs flow). Known misses: a backslashed name built in a variable or helper
(`name = "a\\b"; tmp_path / name`), and writes in fixtures or helper methods.
Measured at introduction (2026-10-10): 2 rows in seedgo's batch7 test as it
stood at HEAD (L596, L607, both true, cured the same day), 0 in 786 test files
fleet-wide after the cure. The scored audit walks product files; this arm
convicts through the checklist lane on test files.

### Valid Guards (recognized by checker)
- `if sys.platform != "win32":` / `if sys.platform == "linux":`
- `if os.name != "nt":` / `if os.name == "posix":`
- `try: ... except ImportError:`
- `try: ... except OSError:`
- `if hasattr(signal, "SIGPIPE"):`

### Skips
- `__init__.py` files
- Non-`.py` files

### What a Linux seat cannot observe — pin it by shape
Two Windows reds in one week (CI 35192484222, CI 35416653326) had the same
cause: the code or test was wrong on Windows and **right by accident on POSIX**,
because the POSIX value is a degenerate case of the thing being handled.

- **States Windows has and POSIX lacks.** Delete-pending, sharing violations,
  a file held open by another process: POSIX unlinks a name at once, so a
  `PermissionError` handler for them is dead code on Linux and never runs.
- **Spellings Windows produces and POSIX does not.** Backslash separators and
  drive letters: `repr()` doubles a backslash, `as_posix()` turns it, a regex
  treats it as an escape. On a POSIX path each of those is the identity — there
  is nothing to double, turn or escape — so the test passes by having no input
  for the bug.
- **Bytes Windows writes and POSIX does not.** Text mode writes each `\n` as
  `\r\n` on Windows and unchanged on POSIX, so a fixture written with
  `write_text` and checked as bytes holds on Linux by having no `\r` to add.

A green Linux run proves nothing about either. When a behaviour only differs on
Windows, the rule that guards it reads the SHAPE statically; it cannot wait for
a run to go red. The three advisories below are that rule.

One half of the spelling class CAN be made observable on Linux: a literal
backslash in pytest's base temp (`pytest --basetemp='<tmp>/x\probe'`) puts one
in every `tmp_path`, so a path compared against a repr goes red on the Linux
seat too (flow reproduced CI 35416653326 that way, 2026-09-18; its suite is
1011 passed under it once cured). It does not reach `as_posix()` — a POSIX
backslash is a character, not a separator, so `as_posix()` still equals
`str()` — nor drive letters, nor any state class. Run it as a cheap extra lane,
not as a replacement for the static read.

### Path length: the tmp prefix is the host's, not the test's
Not checked; advisory text. On macOS CI a `tmp_path` starts about 125 characters
deep (`/private/var/folders/<2>/<30>/T/pytest-of-runner/pytest-0/popen-gwN/<test>0/`,
the test name cut at 30), about 150 once a test adds its project directory; Linux's
`/tmp/pytest-of-runner/...` is about 50 shorter. A test whose fixture name plus the
product's store layout nears a length guard the product names (Windows' 260
`MAX_PATH`) goes red on macOS only, and green on every Linux seat. macOS run
38999228656: backup's `test_prune.py` wrote a 64-character name that the versioned
store nests under a hashed folder, about 280 characters on macOS against about 230
on Linux, so the 260 guard skipped it and four prune tests counted one stored path
fewer. Keep fixture names short, or spell the length math in an assertion
(`assert len(str(longest)) < 260, longest`) so the next long prefix reds the test,
not CI. No checker reads this: the prefix is a property of the CI host, and the
guard and its limit live in the product, so a static "longest fixture path against
a product constant" would be a guess.

### Advisory — exclusive creates that lose the delete-pending race
Not scored. Reported on the audit's info channel (`check_branch_info`) as
`windows_compat lock race (advisory): <file>:<line> ...`, one line per site.

On Windows, `os.open(path, O_CREAT | O_EXCL)` (or `open(path, "x")`) against a
file another thread or process is still deleting ("delete pending") raises
`PermissionError` (errno 13), not `FileExistsError`. POSIX removes the name at
once, so no Linux or macOS run can show it. CI 35192484222: api's token store
lock caught `FileExistsError` only, the revoke thread died, and a revoked
credential stayed live.

Read from the `try` that owns the `FileExistsError` handler:
- **Escape:** no handler on it, or on any `try` around it in the same function,
  takes a PermissionError (`PermissionError`, `OSError`, `Exception`, bare).
- **Gives up:** the `try` is in a loop, `FileExistsError` retries, and the
  handler that takes PermissionError always returns, raises or breaks.

Not flagged: a single-shot `except OSError` that fails the same way "exists"
does; a path rebuilt from a name the loop rebinds (a fresh file each attempt);
a create inside a `sys.platform` / `os.name` guard.

Known misses: flags held in a variable, a create behind a wrapper function, a
PermissionError caught by a `try` outside the retry loop. Known false positive:
a single-shot create of a file nothing ever deletes, with a
`FileExistsError`-only handler — none in the fleet on 2026-09-17; bypass it.

Fix: treat PermissionError on the create as "held, try again" inside the wait,
and surface it once the wait is spent:
```python
except FileExistsError:
    time.sleep(POLL)
except PermissionError as e:  # Windows delete-pending
    if time.monotonic() >= deadline:
        raise OSError(f"lock at {path} still denied after {wait}s: {e}") from e
    time.sleep(POLL)
```

Corpus is the scored lane's (`apps/**/*.py`), so the ratchet to a scored rule
moves no file. Measured at introduction: 18 exclusive creates fleet-wide, 8
advisory lines (flow 5, ai_mail 2, drone 1).
Re-measured 2026-09-18 after flow (bdd60273) and ai_mail (d4e4018f) cured: 1
line left, drone's git lock.

### Advisory — a path asserted against the repr of a mock call
Not scored. Info channel, as
`windows_compat mock repr path (advisory): tests/<file>:<line> ...`.

`str(call(...))`, `str(m.call_args)`, `repr(m.call_args_list)` and
`str(c.args)` are reprs, and repr doubles each backslash. A Windows path
`C:\Users\x\a.lock` is spelled `C:\\Users\\x\\a.lock` in that text, so
`str(lock) in logged` fails there and passes on POSIX. CI 35416653326: three of
flow's lock tests joined `str(c) for c in mock_logger.error.call_args_list` and
asserted the lock path in it.

Flagged, per function with a name-flow pass: `in` / `not in` / `==` / `!=`, or
`.count/.find/.index/.startswith/.endswith`, with REPR TEXT on one side (the
str / repr / f-string of a call record, a call list, or an args container,
carried through joins, slices, case changes and names) and PATH TEXT on the
other (str / `os.fspath` / an f-string of `tmp_path`, `tmpdir`, `Path(...)`,
`tempfile` and `os.path` results, or anything built from them with `/`,
`.with_suffix()`, `.parent`, ...). `in` is red on Windows; `not in` is vacuous
there — it passes without checking anything.

Not flagged: the real message one level inside the args (`c.args[0]`,
`m.call_args[0][0]`, `str(arg) for arg in c.args`) — that is the cure; a path
side repr cannot change (`.name`, `.stem`, `.suffix`, `.as_posix()`,
`Path("one_part")`); a side the test already escaped (`repr(str(p))`,
`.replace(...)`); a test under a platform skipif or `sys.platform` guard.

Helpers in the same module are read by what they return, a tuple return
element by element (`home, foreign = self._fenced_world(tmp_path, ...)`); a
helper whose returns disagree in kind stays opaque. `self.` / `cls.` /
`ClassName.` receivers and bare names reach them, nothing else.

Known misses: a path reached only through a fixture (module or conftest), an
attribute (`self.lock`), a helper from another module, or a helper whose path
arrives through a parameter not named `tmp_path` / `tmpdir`; `%` / `.format()`
of a path; `p.as_posix() in logged` (also red on Windows when the product
logged `str(p)` — which spelling the product used is not in the test).

Second mechanism, same shape (CI 38843541023, 2026-10-15, checker
`mock_repr_path` 1.2.0): api's `test_host_lifetime` asserted
`str(home) in str(log.info.call_args_list[0])` where the product logged `home`
as a Path ARGUMENT. The call's repr spells it `WindowsPath('C:/Users/.../home')`
— forward slashes — while `str(home)` is `C:\Users\...\home`. Already flagged
by this arm (it convicts the pre-cure line 720); it never tripped the gate
because the arm is advisory. The message now names both mechanisms and the
cure: compare the argument itself, `log.info.call_args_list[0].args[1] == home`,
or the message text in `args[0]`.

Same mechanism, not detected: `str()` of an `OSError` built with a filename
(`PermissionError(13, msg, path)`) renders that filename with repr, so
`str(path) in str(exc)` is red on Windows the same way. Measured 2026-09-19: 20
such constructions in tests, 11 in apps, none red on Windows CI 35426157867 —
named here, not built.

Fix — compare against the logged arguments, never the call's repr:
```python
logged = " ".join(str(arg) for c in mock_logger.error.call_args_list for arg in c.args)
assert str(lock) in logged
```

Corpus is `tests/**/*.py` — a test-side shape, in a lane the scored audit never
walks. Measured at introduction (2026-09-18): the three incident lines at
bdd60273, 0 after flow's cure (c0fedb17), 0 elsewhere in 570 test files. A
name-guessing arm (`*_path`, `*_dir`, `*lock` params, `self.*`) added 0; an
any-operand arm added 14 lines, all literal text with no backslash (verbs,
signatures, `"cp /branch/..."` steps) — 0 of 14 real, so neither shipped.

Widened 2026-09-19 after CI 35426157867 (memory's marker-7 test, the paths
returned by a helper): of 19 sinks with a repr haystack and an opaque needle,
2 needles (one line) were paths — both memory's — and 17 were words or counts.
Same-module helper returns convert exactly those 2; the fleet stays at 0 lines
across 570 test files with 238 helpers now read. A name-guessing arm would have
caught `home` but not `foreign`, and fixture reading converts none of the 19.
Path needles into haystacks the pass cannot read: 105, of which 9 sit in a
function that touches `call_args`; all 9 read the real args (the cure).

### Advisory — a text-mode fixture with a newline meets a bytes oracle
Not scored. Info channel, as
`windows_compat text fixture bytes oracle (advisory): tests/<file>:<line> ...`.
Detector: `text_fixture_bytes_oracle.py` 1.0.0 (2026-10-15).

CI 38843541023: hooks' settings-backup fixture wrote
`(claude / "settings.json").write_text('{"model": "before"}\n', encoding="utf-8")`
and the test asserted the backup's `read_bytes() == b'{"model": "before"}\n'`.
The product copied the file byte for byte; on Windows the file held `\r\n`.

Flagged, per test function: a FIXTURE — `P.write_text(<str literal / f-string
with \n>)` with `P` a path, or `open(x, "w"/"a"/"x"/"+")` / `P.open(...)` given
`.write` / `.writelines` of such a literal (names bound to the literal carry it)
— in the test, in a same-module `@pytest.fixture` it names as a parameter, or in
a same-module function it calls by name, transitively; and an ORACLE in the test:
`==` / `!=` of `X.read_bytes()` against a bytes literal (or a literal's
`.encode()`), of `hashlib.<algo>(...read_bytes()).hexdigest()` / `.digest()`
against a str / bytes literal or a digest of a bytes literal, or of
`len(...read_bytes())` against an int literal or `len(b"...")`. The oracle may
read any path (the incident read the backup copy). The line is the oracle's.

Not flagged: `write_bytes(...)` or `newline=""` / `newline="\n"` (the cures); a
`read_text` oracle; a bytes oracle with no text-mode newline fixture reachable;
a literal with no `\n`; bytes compared with bytes the test did not spell
(`== src.read_bytes()`, a digest the product recorded); a platform-guarded test.

Known misses: opaque content (`json.dumps`, `textwrap.dedent`, a parameter —
canary's `_store(tmp_path, "a\t1\n")` helper would be one if it lacked its
`newline=""`), `print(..., file=f)`, a receiver the flow pass cannot read as a
path, a conftest / other-module / `name=`-renamed fixture, an oracle inside a
helper, `open(p, "rb").read()`, `in` / `.startswith` on bytes, a literal held
in a module constant.

Fix — write the bytes the oracle names:
```python
(claude / "settings.json").write_bytes(b'{"model": "before"}\n')
```

Measured at introduction (2026-10-15): 931 test files, 8 bytes-vs-literal
oracles fleet-wide, 0 with a text-mode newline fixture (hooks is cured; its
pre-cure mutant is convicted at the oracle line); a relaxed receiver (any
`write_text`) also gives 0.

---

## Code Examples

### Violation — bare POSIX import
```python
import fcntl
fcntl.flock(fd, fcntl.LOCK_EX)
```

### Fix 1 — platform guard with Windows fallback
```python
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

def lock_file(fd):
    if sys.platform == "win32":
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX)
```

### Fix 2 — try/except import
```python
try:
    import fcntl
except ImportError:
    fcntl = None
```

### Violation — unguarded os.WNOHANG
```python
pid, _ = os.waitpid(-1, os.WNOHANG)
```

### Fix — platform guard
```python
if sys.platform != "win32":
    pid, _ = os.waitpid(-1, os.WNOHANG)
```

### Violation — os.kill without exception handling
```python
os.kill(pid, 0)  # Crashes on Windows with WinError 87
```

### Fix — wrap in try/except
```python
try:
    os.kill(pid, 0)
except OSError:
    return False
```

---

## Scoring
- **Scope:** AUDIT_SCOPE = "all_files"
- **Checks per file:** 1 (Windows compat)
- **Score 100:** No unguarded POSIX-only patterns found
- **Score 0:** One or more unguarded patterns found
- **Failure message:** "N unguarded POSIX pattern(s): L42: import fcntl; ..."
- **Overall pass threshold:** 75%

---

## Bypass

File-level bypass (entire file is Linux-only):
```json
{"file": "apps/handlers/dispatch/daemon.py", "standard": "windows_compat",
 "reason": "Daemon process management is Linux-only by design"}
```

Line-level bypass (specific line has a valid reason):
```json
{"file": "apps/config.py", "standard": "windows_compat", "lines": [89],
 "reason": "fcntl used only in POSIX lock path, Windows path above"}
```

---

## Reference
- **Checker:** windows_compat_check.py
- **Scope:** all_files
- **Entry point:** check_module()
- **Standard label:** WINDOWS_COMPAT
- **Windows CI:** none; `windows-test.yml(windows_disabled)` is the retired lane, unread by Actions
- **Issue:** #326 (Input-X Windows platform report)
