# Host Portability
**Status:** Draft v1.8 (arms A, C and I removed with the Linux-only fleet; arm H, an empty `.git` read as a repo; arm G, a stdlib import above the floor; arm F, an emptied git identity; arm E, a symlinked prefix — PR #774; arm D, the host's Python — PR #774; lib/ corpus — FPLAN-0554 round three)
**Date:** 2026-11-14

---

## What It Is

A standard that catches assumptions about **the author's own host** that another
Linux host does not share: a binary that is not installed everywhere, the
host's Python, a symlinked prefix, git's identity, the stdlib floor, and an
empty `.git` a sandbox mounts.

---

## Why It Matters

Each arm below comes from a CI run or a sandbox that went red on code that was
green on the seat that wrote it. Nothing else in the pack had a name for them.

---

## What the Checker Scans For

AST-parses every `.py` file under `apps/`, `tests/` **and** `lib/`. Every arm
(B, D to H) scores. The letters are kept from earlier versions so fleet notes
still match.

### Arm B — assumed non-portable binary

A `subprocess.run` / `Popen` / `check_output` / `call` / `check_call` whose
`argv[0]` is a **bare literal** in this curated list:

`tmux`, `systemctl`, `loginctl`, `sysctl`, `gnome-terminal`, `xfce4-terminal`,
`konsole`, `xterm`

Each one is absent on at least one Linux host: a container, a CI runner, a
desktop without that terminal, a WSL2 seat without systemd.

`check=False` is **not** a guard. A missing binary raises `FileNotFoundError`
out of `exec`, before there is any exit code to ignore.

**Portable names are allowlisted:** `git`, `bash`, `sh`, `drone`, `python3`,
`sleep`, `gh`, `ps`, `lsof`, `pgrep`, `npm`, `ruff`. Scoring those adds 134 rows
and no bugs.

**Dynamic `argv[0]` is never read.** 190 of 374 subprocess sites spell it with a
variable, and that spelling is usually the *cure*. A rule that guessed would
convict the fix.

### Arm D — a direct `pathlib.Path` subclass (the host's Python)

A class whose base is `Path` or `PurePath` itself. Below Python 3.12
`Path.__new__` needs `_flavour` on the subclass, so it raises
`AttributeError: ... has no attribute '_flavour'` on 3.10 and 3.11 and runs on
every 3.12 seat (PR #774, Linux 3.10/3.11): backup `_ResolveDeniedPath`, trigger
`tests/test_error_registry.py:1477 _RefusingPath`.

**Acquitted:** a concrete flavour (`PosixPath`, `PurePosixPath`), or a class
body that sets `_flavour`.
**Cure:** wrap a real `Path` instead of subclassing, or patch the one method on
the instance's class with `monkeypatch`.

### Arm E — a resolved path compared with one taken as given (file-local)

A host can spell one directory two ways when a prefix is a symlink (a home
directory or a temp root reached through a link). `Path.home()`, `Path.cwd()`,
`os.getcwd()`, `tempfile.gettempdir()` / `mkdtemp()` / `TemporaryDirectory()`
keep the spelling the host hands out; `.resolve()` and `os.path.realpath` do
not. Comparing one with the other is false whenever a prefix is a symlink.
Specimen: hooks `loader.locate_config()` before 2.1.0 (60d2af72) compared
`aipass_home()` — resolved through `_absolute()` — with walk bounds from
`_search_bounds()` (`Path.cwd(), Path.home()`): eight CI rows, the install read
as an external project.

**What it reads, inside one function:** an `==` / `!=`, an `x in y.parents`, or a
`.relative_to()` / `.is_relative_to()` / `.startswith()` whose one side passed
through `.resolve()` / `os.path.realpath` and whose other side is a host spelling.
A side is followed through a name assigned earlier in the same function (last
assignment wins), through `/`, `.parent`, `.parents[i]`, `str()`, `Path()`,
`os.fspath`, `os.path.join`, `.as_posix()`, `.joinpath()`, a tuple unpack, a
generator, and through a same-file module-level function whose every known return
carries one spelling (followed to a fixed point: `aipass_home -> _absolute ->
resolve` is seen).

**Not read:** a path from a parameter, an attribute or another module carries no
spelling and is never judged — that is the call graph this arm does not have.
`tmp_path` is not a host spelling here.

**Fleet, 2026-10-10 (2,084 files):** 4 rows, all hooks, all the specimen's walk
with `home = Path.home()` as the stop beside a resolved `search`:
`apps/modules/admin_seat.py:99`, `apps/modules/grounding_content.py:225` and
`:406`, `apps/modules/release_notice.py:78`. **Cure:** resolve both sides
(`Path.home().resolve()`), as loader 2.1.0 does.

### Arm F — git's config emptied with no commit email (file-local)

A test that sets `GIT_CONFIG_GLOBAL` to an empty file, or `GIT_CONFIG_NOSYSTEM`,
reads no `user.email` from the host. A developer machine still commits: git
derives an email from the OS user and the hostname. A GitHub runner cannot, and
`git commit` exits 128 (`unable to auto-detect email address`). Specimen: drone's
`aipass_github` fixture in `tests/conftest.py` 1.3.0 emptied the config and set
no identity; `dev_tree` in `test_git_access_gh_door.py` committed on top of it,
13 setup errors on every Python. 1.3.1 sets the four `GIT_AUTHOR_*` /
`GIT_COMMITTER_*` variables.

**What it reads:** a file holding the string `GIT_CONFIG_GLOBAL` or
`GIT_CONFIG_NOSYSTEM` must also hold `GIT_AUTHOR_EMAIL` **and**
`GIT_COMMITTER_EMAIL` (git resolves the two separately), or a string containing
`user.email` (`git config user.email`, `-c user.email=`). One row per file, at
the first emptying line.

**Why file-local:** the fixture that empties the config cannot know which
consumer commits, and the consumer is often another file. The file that takes
the host's identity away gives one back.

**Not read:** the name. A runner's user has one; the email is what fails.

**Fleet, 2026-10-22:** 5 test files empty git's config, all drone; 0 rows. The
specimen at 1.3.0 is convicted at the `GIT_CONFIG_GLOBAL` line.

### Arm G — a stdlib import newer than the declared floor

An `import X` / `from X import ...` where X joined the stdlib after the
`requires-python = ">=3.N"` of the nearest `pyproject.toml` above the branch.
The except branch of such an import is the answer only the floor's CI lane
runs; a seat on a newer Python, and every test written there, pins the other
one. Specimen: aipass `provider_wire.py` before 1.9.1 did `import tomllib` in a
`try` whose `except` returned "needs Python 3.11+"; fourteen tests were red on
PR #811's 3.10 lane and green on 3.11 to 3.13.

**Table:** `tomllib` 3.11 (backport `tomli`), `zoneinfo` 3.9
(`backports.zoneinfo`), `graphlib` 3.9 (`graphlib_backport`).
**Acquitted:** the nearest enclosing `try` or `if` imports the backport anywhere
inside it — `try: import tomllib / except: import tomli as tomllib`, nested or
at module level (aipass `structure_scanner.py`, `aipass.py`). A function or
class boundary ends the search: a `try` around a `def` guards nothing inside it.
**Not read:** a `sys.version_info` gate on its own — it moves the degraded
answer, it does not run it. No `pyproject.toml`, or none declaring a `>=`
floor: the arm is off.
**Cure:** the backport fallback, and a test that hides both modules through
`sys.modules` and pins the last answer (aipass `tests/test_structure_scan.py`).

**Fleet, 2026-10-27:** 5 version-bound imports, floor 3.10; 1 row, sentry's own
`test_inventory/collection.py` (a version gate, no tomli), cured to the
fallback in collection 1.0.3.

### Arm H — an existence test on `.git` that an empty directory passes (product code)

`(x / ".git").exists()` / `.is_dir()`, or `os.path.exists` / `os.path.isdir`
of `os.path.join(..., ".git")`, as the test for "this is a repository". A
sandbox (Codex's) mounts an EMPTY `.git` directory in each writable root, its
cwd and the temp root, so a walk up the tree stops at a directory git itself
never reads as a repo. Specimen: sentry `home_paths.py` 1.0.0 stopped at
`/tmp/.git` and scanned nothing.

**Acquitted:** `.is_file()` (a worktree's pointer file; a sandbox mounts
directories only), and a probe whose enclosing function also opens the marker:
`.git / "HEAD"`, `os.path.join(..., ".git", "HEAD")`, or a listing
(`iterdir` / `listdir` / `scandir`) of `.git` itself. A listing of any other
directory acquits nothing.
**Not read:** files in a test tree — a fixture plants its own `.git`. A
fixture that plants an EMPTY one now needs a `HEAD` file for the code it feeds.
**Cure:** `marker.is_file() or (marker.is_dir() and any(marker.iterdir()))`;
sentry's `ignore_handler.is_git_marker` and `find_repo_root` are that test.

**Fleet, 2026-11-01:** 22 rows across sentry (5, cured), hooks (8), aipass (4),
prax (3), flow (1), api (1).

### Valid guards for Arm B (recognized by checker)
- `try: ... except OSError / FileNotFoundError / Exception:`
- `with pytest.raises(FileNotFoundError / OSError / ...):` (2026-10-03, sentry fleet green
  leg 10): a host without the binary raises exactly what the test expects, so it
  passes everywhere. A `pytest.raises` of any other error is no guard.
- `shutil.which("<name>")` in the same function

---

## Code Examples

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
  enters `tests/`, most failures this exists to prevent were tests, and
  skills keeps all seven built-in skills in `lib/` (widened for this standard
  only; the per-file corpus stays `apps/` until tier-2 skill handlers have a
  SKILL.md-keyed architecture exemption)
- **Score:** `clean files / total files x 100` — the same number the `all_files`
  lane produces by averaging a 100-or-0 per file
- **Score 100:** no unguarded host assumptions anywhere in the branch
- **Failure message:** "N host assumption(s) in M/T files: …"
- **Context line:** a second `passed: True` check counts the binary calls that
  already carry a guard. Context, never scored.
- **Overall pass threshold:** 75%

---

## Measured Baseline (2026-09-12, 18 branches, 1,642 files)

| Arm | Nominated | Convicted |
|---|---|---|
| B — non-portable binary | 27 | 4 |

Convictions:

| Branch | Site | Arm |
|---|---|---|
| HOOKS | `apps/handlers/lifecycle/session_boot.py:248`, `:313`, `:1078` | B |
| trigger | `apps/handlers/service_control.py:82` | B |

Every other branch scores 100.

### Round three (2026-09-12, after every FPLAN-0554 owner cure landed)

After adding `lib/` to the corpus: **every branch 100 except skills, 97** — 12
rows in 3 files, all arm B, all in the telegram skill (off since 2026-08-18):

| File | Rows |
|---|---|
| `lib/telegram/apps/handlers/base_bot.py` | tmux :1743 :1749 :1792 :1913 :1918 :1957, systemctl :2358 |
| `lib/telegram/apps/handlers/bot_factory.py` | tmux :370 :380 :397 |
| `lib/telegram/apps/handlers/tmux_manager.py` | tmux :58 :80 |

**Skills cured all 12 the same day, no bypass** (host_portability 97 → 100 from its seat and from mine):
`tmux_manager.session_exists` was called above the try in three callers, so a missing tmux raised
out of all three — one row was a live escape, not a technicality. Shape: the exec failure caught where
the call sits, `FileNotFoundError` named, a verdict returned; no `which` beside a call every unit mocks.

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
| a read on a pid after the call that ends it (`getpgid` after `hangup()`) | api 950495c9 | kernel semantics |
| a test compares a tempfile dir it did not resolve with a product value the product resolved (the hooks loader stamps realpaths; `temp_test_dir` was `mkdtemp()` as given) | hooks 4d9b18d0 | arm E's cross-file case. A probe that follows the test's value to an `==` / `in` against a product value from a module that calls `resolve()` / `realpath` finds 477 rows in 725 test files; every `tmp_path` row is false by construction (pytest resolves its base temp), and the 4 rows from `tempfile` were all green (0 of 4 real). It catches 1 of the specimen's 2 red asserts. At the fixture: 3 fleet fixtures hand out an unresolved tempfile dir, 1 has bitten. **Cure:** use `tmp_path`, or yield `mkdtemp()` resolved |

**Shapes recommended when curing a row here:**
- at a subprocess seam that every unit mocks, the honest probe is the **exec
  failure** caught, named and returned as a verdict (hooks) — a `shutil.which`
  there reads the real PATH inside mocked units and re-couples the suite to the host
- when a fixture must force `shutil.which`, answer a stand-in for the **one**
  name under test and delegate every other name to the real `which` (api) — a
  blanket stand-in hides the next dependency

---

## Bypass

File-level bypass (the file really needs the binary by design):
```json
{"file": "apps/handlers/systemd/unit.py", "standard": "host_portability",
 "reason": "systemd integration — the branch needs systemctl"}
```

Line-level bypass:
```json
{"file": "apps/handlers/session/tmux_boot.py", "standard": "host_portability",
 "lines": [135], "reason": "tmux is a declared dependency of this branch"}
```

---

## Reference
- **Checker:** host_portability_check.py
- **Scope:** branch_level
- **Entry point:** check_branch()
- **Standard label:** HOST_PORTABILITY
