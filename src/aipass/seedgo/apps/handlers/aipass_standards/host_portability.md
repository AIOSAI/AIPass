# Host Portability
**Status:** Draft v1.1 (arm C, lib/ corpus — FPLAN-0554 round three)
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

AST-parses every `.py` file under `apps/`, `tests/` **and** `lib/`. All three
arms score.

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

**Through a bound name, too.** `meminfo_path = "/proc/meminfo"` then
`open(meminfo_path)` is nominated at the `open` — skills
`lib/system_status/handler.py` spelled all three of its reads that way. A name
bound to anything else anywhere in the file is not followed. A `Path(...)` bound
to a name is judged where it is **read**, not where it is built: building a
Path touches nothing (telegram `base_bot.py:2721` was a false row on its
constructor line, beside a read already inside `except OSError`).

### Arm C — a skip that names the wrong host (tests lane)

A test unit whose platform `skipif` names **only Windows**
(`sys.platform == "win32"`, `os.name == "nt"`) while the unit **declares a Linux
recipe**: its name says `_linux` (not `non_`/`off_`/`not_linux`), or its reason
says "Linux-only", or names Linux beside `/proc`, `/sys/`, `systemd` or
`systemctl`. macOS lacks the recipe too, and runs the unit.

Eight macOS reds in a row (runs 34707762639 → 34708132945) were this shape and
none spelled `/proc` in a filesystem call — the product did — so arms A and B
could not see them:

| Site (pre-cure) | Gate | Declared by |
|---|---|---|
| prax `test_instance_lock.py:172` | `sys.platform == "win32"` | name `_on_linux`, reason "/proc is Linux-only" |
| skills `test_runner.py` ×4 | `sys.platform == "win32"` | reason "reads Linux /proc/meminfo" |

**Acquitted:** a unit that manufactures its lane — it patches `sys.platform` /
`os.name`, or the filesystem primitive (`builtins.open`, `os.listdir`, the
module's `Path`, `read_text`). Its gate is not what makes it portable.

**Measured and rejected:**
- a Linux-named unit with **no gate at all** — 5 fleet hits, 5 false
  (`test_filter_linux_only_all_rows` hands the string `"linux"` to a pure function)
- any `/proc` word in a reason — devpulse `test_watchdog_wire.py:832` names
  "/proc nor lsof" and keeps macOS in on purpose, because macOS has the lsof lane

**Write the reason as the recipe unavailable, not the state** (drone's
`WINDOWS_CWD_REASON`, now prax's):
`reason="reads /proc/sys/kernel/random/boot_id - no procfs on this host"`.

### Valid guards (recognized by checker)
- a platform test anywhere in the enclosing function: `sys.platform`, `os.name`,
  `platform.system()`
- `try: ... except OSError / FileNotFoundError / Exception:`
- an existence early-out: `if not path.exists(): return` — kept after measuring:
  skills' pre-cure handler refused by name with `success: False` on a host with
  no `/proc`; its red was in the tests. 1 live fleet site acquits only this way.
- `@pytest.mark.skipif` on the unit, **its class** or the module's
  `pytestmark`, including a module-level alias (`_linux_only = ...` then
  `@_linux_only`, 17+ fleet-wide) — **when the predicate names the host that
  HAS the recipe**: `sys.platform != "linux"`, `"darwin"`, a `/proc` probe, or
  `shutil.which`. `os.name == "nt"` names Windows and no longer acquits a read.
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
- **Corpus:** `apps/`, `tests/` **and** `lib/` — the per-file audit lane never
  enters `tests/`, every macOS failure this exists to prevent was a test, and
  skills keeps all seven built-in skills in `lib/` (widened for this standard
  only; the per-file corpus stays `apps/` until tier-2 skill handlers have a
  SKILL.md-keyed architecture exemption)
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

### Round three (2026-09-12, after every FPLAN-0554 owner cure landed)

Before: every branch 100. After arm C, bound-name reads, the recipe-host skip
rule and `lib/`: **every branch 100 except skills, 97** — 12 rows in 3 files, all
arm B, all in the telegram skill (off since 2026-08-18):

| File | Rows |
|---|---|
| `lib/telegram/apps/handlers/base_bot.py` | tmux :1743 :1749 :1792 :1913 :1918 :1957, systemctl :2358 |
| `lib/telegram/apps/handlers/bot_factory.py` | tmux :370 :380 :397 |
| `lib/telegram/apps/handlers/tmux_manager.py` | tmux :58 :80 |

**Skills cured all 12 the same day, no bypass** (host_portability 97 → 100 from its seat and from mine):
`tmux_manager.session_exists` was called above the try in three callers, so a missing tmux raised
out of all three — one row was a live escape, not a technicality. Shape: the exec failure caught where
the call sits, `FileNotFoundError` named, a verdict returned; no `which` beside a call every unit mocks.

Arm C and the bound-name reads convict **0** live sites: every instance of the
shape that went red was cured by its owner before the rule landed. The pins
reproduce each pre-cure shape instead.

---

## Candidates weighed, not built (FPLAN-0554 round three)

Each came out of an owner's cure. Recorded with its evidence so a later pass
starts from the measurement instead of re-deriving it.

| Shape | From | Why not a rule yet |
|---|---|---|
| one argv builder for N verbs of different arity: `_systemctl(action)` appended the unit to every call, so `daemon-reload` exited 1 "Too many arguments" under a bare except and had not run since 2026-08-31 | trigger d496923d | needs each call site's verb read against the builder's constant tail; one instance fleet-wide, no second to measure acquittals on |
| a test that stubs the spawned argv but leaves the product's `shutil.which` preflight live, so Linux green measured the runner's package list | api 3ef3d571 | host-coupled with no host API in the test file; needs fixtures read against product preflights |
| an exception-class assertion where the same class is raised at more than one site on the path | api 3ef3d571 | needs the call graph; pytest_quality candidate |
| a mock wider than the unit's claim (`Popen` explodes on ANY spawn; the claim is "no process left running") | devpulse dab115fb | the claim is prose; pytest_quality candidate |
| a security-gate test asserting "allowed" for an input that spells the guarded binary (`/usr/bin/git push`) | hooks 474895f5 | pytest_quality / security candidate |
| a debounce unit correlating calls by wall clock and never setting the product's correlation key | hooks 474895f5 | needs the product constant paired with the test's key |
| `os.kill(pid, 0)` reached under a forced platform on a Windows host | devpulse 7262e9ec | kernel semantics; taught in platform_oracle.md |
| a read on a pid after the call that ends it (`getpgid` after `hangup()`) | api 950495c9 | kernel semantics; taught in platform_oracle.md |

**Shapes recommended when curing a row here:**
- at a subprocess seam that every unit mocks, the honest probe is the **exec
  failure** caught, named and returned as a verdict (hooks) — a `shutil.which`
  there reads the real PATH inside mocked units and re-couples the suite to the host
- when a fixture must force `shutil.which`, answer a stand-in for the **one**
  name under test and delegate every other name to the real `which` (api) — a
  blanket stand-in hides the next dependency

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
