# Windows Compatibility
**Status:** Draft v1
**Date:** 2026-05-10

---

## What It Is

A standard that ensures Python code runs on both Linux and Windows by detecting
POSIX-only APIs used without platform guards.  Windows CI (GitHub Actions on
Windows Server 2022) validates compliance end-to-end.

---

## Why It Matters

AIPass is pip-installable and must work cross-platform.  POSIX-only patterns
like bare `import fcntl` or `os.waitpid(-1, os.WNOHANG)` crash immediately on
Windows with `ImportError` or `WinError 87`.  The Windows CI caught 71 failures
from these systemic patterns.  This standard prevents regressions.

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

### Valid Guards (recognized by checker)
- `if sys.platform != "win32":` / `if sys.platform == "linux":`
- `if os.name != "nt":` / `if os.name == "posix":`
- `try: ... except ImportError:`
- `try: ... except OSError:`
- `if hasattr(signal, "SIGPIPE"):`

### Skips
- `__init__.py` files
- Non-`.py` files

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
- **Windows CI:** .github/workflows/windows-test.yml
- **Issue:** #326 (Input-X Windows platform report)
