# Host Portability
**Status:** Draft v1
**Date:** 2026-09-12

---

## What It Is

A standard that catches **Linux** assumptions — as opposed to POSIX ones. It has
two arms: reading `/proc` as a filesystem, and shelling out to a binary that is
not installed on every supported host.

---

## Why It Matters

A macOS CI run went red with **32 failures**, and the seedgo audit read **100**
on every branch that carried one. `windows_compat` could not have caught them:
it asks "does this run on Windows", and both species are perfectly good Windows
code. `/proc` is absent on macOS; `tmux` and `systemctl` are absent on a stock
Mac and on Windows. Nothing in the pack had a name for either.

---

## What the Checker Scans For

AST-parses every `.py` file under `apps/` **and** `tests/`. Both arms score.

### Arm A — `/proc` as a filesystem argument

A string literal (plain or f-string) beginning `/proc`, passed **directly** as
an argument to `open()`, `Path()`, `os.readlink`, `os.listdir`, `os.stat`,
`.read_text()`, `.read_bytes()` or `.exists()`.

**The argument restriction is the rule, not a detail.** 36 `/proc` literals
live in the fleet's corpus and only 22 touch a disk. The three shapes it throws
out are the three that would have made the rule a nuisance:

| Shape | Example | Why it is not a bug |
|---|---|---|
| mock-table dict key | `_fake_open_factory(f, {"/proc/42/status": f})` | a dict key opens nothing |
| skipif `reason=` prose | `skipif(..., reason="/proc is Linux-only")` | it is the guard's own text |
| argv element | `["bwrap", "--proc", "/proc", "true"]` | not a path this caller opens |

A docstring cannot reach this rule at all: a docstring's parent node is an
`ast.Expr`, and an `ast.Expr` is never a call argument.

### Arm B — assumed non-portable binary

A `subprocess.run` / `Popen` / `check_output` / `call` / `check_call` whose
`argv[0]` is a **bare literal** in this curated list:

`tmux`, `systemctl`, `loginctl`, `sysctl`, `gnome-terminal`, `xfce4-terminal`,
`konsole`, `xterm`, `wt`, `tasklist`

`check=False` is **not** a guard. A missing binary raises `FileNotFoundError`
out of `exec`, before there is any exit code to ignore.

**Portable names are allowlisted:** `git`, `bash`, `sh`, `drone`, `python3`,
`sleep`, `gh`, `ps`, `lsof`, `pgrep`, `npm`, `ruff`. Scoring those adds 134 rows
and no bugs.

**Dynamic `argv[0]` is never read.** 190 of 374 subprocess sites spell it with a
variable, and that spelling is usually the *cure* — hooks `sound.py` picks
`afplay` on darwin and `aplay` otherwise inside a platform `if`, then runs
`_PLAY_CMD`. A rule that guessed would convict the fix.

### Valid guards (recognized by checker)
- a platform test anywhere in the enclosing function: `sys.platform`, `os.name`,
  `platform.system()`
- `try: ... except OSError / FileNotFoundError / Exception:`
- an existence early-out: `if not path.exists(): return`
- `@pytest.mark.skipif` on the unit **or its class**, including a module-level
  alias — `_posix_only = pytest.mark.skipif(os.name == "nt", ...)` then
  `@_posix_only`. There are 17+ such aliases fleet-wide; a reader that only
  understands the inline form convicts every one of them.
- **one hop:** a function whose *every* call site in the module sits under a
  platform test, including a named predicate (`if _openat2_available():` where
  that function returns `sys.platform == "linux" and ...`)
- `shutil.which("<name>")` in the same function (Arm B only)

### Deliberately NOT a guard
A skipif whose predicate is a **capability probe**:
`pty_required = pytest.mark.skipif(not host_attach.is_available(), ...)` is a
PTY probe, and macOS has a PTY. The predicate must actually name a platform.

---

## Code Examples

### Violation — the non-Linux fallback reads `/proc`
```python
def _resolve_beneath(base, relpath):
    if _openat2_available():                 # sys.platform == "linux" and ...
        return _resolve_via_openat2(base, cleaned)
    return _resolve_via_walk(base, parts)    # reached when NOT Linux

def _resolve_via_walk(base, parts):
    ...
    return Path(os.readlink(f"/proc/self/fd/{current_fd}"))   # ← convicted
```
The twin at `_resolve_via_openat2` reads the same path and is **acquitted** by
the one-hop caller rule. Without that rule the checker convicts both, and the
one real bug becomes a row of noise.

### Fix — answer honestly off Linux
```python
def _resolve_via_walk(base, parts):
    ...
    if sys.platform != "linux":
        return Path(os.path.realpath(joined))
    return Path(os.readlink(f"/proc/self/fd/{current_fd}"))
```

### Violation — a binary that is not everywhere
```python
subprocess.run(["tmux", "kill-session", "-t", session], check=False)
```

### Fix 1 — probe first
```python
if not shutil.which("tmux"):
    return False
subprocess.run(["tmux", "kill-session", "-t", session], check=False)
```

### Fix 2 — catch the exec failure
```python
try:
    subprocess.run(["systemctl", "--user", "enable", SERVICE_NAME], timeout=10)
except (OSError, subprocess.SubprocessError) as exc:
    logger.info("[MEDIC] systemctl unavailable: %s", exc)
```

---

## Scoring
- **Scope:** AUDIT_SCOPE = "branch_level", entry point `check_branch()`
- **Corpus:** `apps/` **and** `tests/` — the per-file audit lane never enters
  `tests/`, and every macOS failure this exists to prevent was a test
- **Score:** `clean files / total files x 100` — the same number the `all_files`
  lane produces by averaging a 100-or-0 per file
- **Score 100:** no unguarded host assumptions anywhere in the branch
- **Failure message:** "N Linux-only host assumption(s) in M/T files: …"
- **Context line:** a second `passed: True` check counts the binary calls that
  already carry a guard. Context, never scored.
- **Overall pass threshold:** 75%

---

## Measured Baseline (2026-09-12, 18 branches, 1,642 files)

| Arm | Nominated | Convicted |
|---|---|---|
| A — `/proc` filesystem argument | 22 (19 apps / 3 tests) | 3 |
| B — non-portable binary | 27 | 4 |

Convictions:

| Branch | Site | Arm |
|---|---|---|
| drone | `apps/handlers/broker/path_resolver.py:135` | A |
| api | `tests/test_host_attach.py:912`, `:919` | A |
| HOOKS | `apps/handlers/lifecycle/session_boot.py:248`, `:313`, `:1078` | B |
| trigger | `apps/handlers/service_control.py:82` | B |

Every other branch scores 100.

---

## Bypass

File-level bypass (the file really is Linux-only by design):
```json
{"file": "apps/handlers/systemd/unit.py", "standard": "host_portability",
 "reason": "systemd integration — the branch does not ship off Linux"}
```

Line-level bypass:
```json
{"file": "apps/handlers/broker/path_resolver.py", "standard": "host_portability",
 "lines": [135], "reason": "openat2-only build, walk path is unreachable here"}
```

---

## Reference
- **Checker:** host_portability_check.py
- **Scope:** branch_level
- **Entry point:** check_branch()
- **Standard label:** HOST_PORTABILITY
- **Sibling:** windows_compat (same helpers, different host)
