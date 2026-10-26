# Host Coupled Oracle
**Status:** Draft v1.0 (the PR #807 CI red, hooks cc_sessions)
**Date:** 2026-10-26

---

## What It Is

A standard that catches a test whose expected value is a fact about **the host it
ran on**, not about the code: it reads its own process title, or it counts
subprocess calls down a path that forks on the platform.

---

## Why It Matters

PR #807 went red in CI (Linux run 40283331105, macOS run 40283331148) on hooks
tests that were green on the seat:

- `test_this_process_args_name_its_interpreter` read `process_args(os.getpid())`
  and expected the interpreter. CI runs `pytest -n auto`; pytest-xdist retitles
  every worker through setproctitle, so the test read `[pytest-xdist running] …`.
- `test_a_failed_ps_ends_the_walk_with_none_not_a_raise` asserted
  `ps.call_count == 1` on a patched `subprocess.run`. `process_args` reads
  `/proc/<pid>/cmdline` on Linux and runs `ps` elsewhere, so macOS counted 2.

**Why no existing rule saw it.** `host_portability` reads one file: the platform
branch lived in the product module, the count in the test. No rule read a test's
own pid as a host fact.

---

## What the Checker Scans For

AST-parses every `.py` file under the branch's `tests/` and each
`lib/<skill>/tests/`, and reads production through the tests' own imports under
the package root (the resolver `calendar_bound` uses).

### Arm 1 — the test reads its own process's command line
A call whose argument is `os.getpid()` or `os.getppid()` and whose callee name
holds args, argv, cmdline, command, title or proctitle as a whole
underscore-separated word. `is_pid_alive(os.getpid())` reads no title and is clean.

### Arm 2 — an exact command count across a platform fork
All of:

1. `<mock>.call_count == N`, N an integer literal above zero;
2. `<mock>` bound by `with patch("...subprocess.<runner>") as <mock>` or
   `with patch.object(<x>.subprocess, "<runner>") as <mock>`, runner one of
   run, Popen, check_output, call, check_call;
3. the test reaches, by name, breadth-first, up to 6 hops, a production function
   that both branches on the platform (`sys.platform`, `os.name`,
   `platform.system()` and friends, or a module-level name bound to one, such as
   `_PLATFORM = sys.platform`) and calls a runner on `subprocess` or a local
   alias of it (`import subprocess as _sp`).

### Acquitted
- a skip mark that reads the platform, on the test, its class or `pytestmark`;
- a platform read inside the test: the expectation already follows the host;
- a platform gate that runs nothing (`is_supported()` returning False off Linux)
  in another function than the runner: a fixture pins the gate, the count holds.

### Deliberately not claimed
- a count compared with `>=`, `<` or a name; a count of zero;
- a mock bound by assignment or a decorator, not a `with`;
- a platform fork in a test helper (the test owns that branch);
- a transitive read of the git-ignored registry (the PR #807 third red): the
  clean-checkout probe (`-p clean_checkout_probe`) catches it at run time.

---

## Code Examples

### Violation — the test's own title
```python
args = cc_sessions.process_args(os.getpid())
assert "python" in args[0]
```

### Fix — start a child and read its pid
```python
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
assert "python" in cc_sessions.process_args(child.pid)[0]
```

### Violation — a count that differs per platform
```python
with patch("subprocess.run", side_effect=OSError("no ps")) as ps:
    assert cc_sessions.resolve_session_pid() is None
assert ps.call_count == 1
```

### Fix — count the call the test is about, or follow the platform
```python
assert ps.call_count == (1 if sys.platform.startswith("linux") else 2)
```

---

## Scoring

`clean test files / total test files x 100`. Up to 3 offending `file:line`
rows in the message, every row in `violations`. Pass threshold 75%.

---

## Bypass

Via `.seedgo/bypass.json`, key `host_coupled_oracle`: standard, file-level and
line-level rules.

---

## Reference

- Checker: `host_coupled_oracle_check.py`
- Content: `host_coupled_oracle_content.py`
- Sibling: `host_portability` (one file's host reads), `calendar_bound` (the date)
