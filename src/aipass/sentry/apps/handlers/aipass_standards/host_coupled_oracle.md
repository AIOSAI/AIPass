# Host Coupled Oracle
**Status:** Draft v1.1 (the PR #807 CI red, hooks cc_sessions)
**Date:** 2026-11-14

---

## What It Is

A standard that catches a test whose expected value is a fact about **the host it
ran on**, not about the code: it reads its own process title.

---

## Why It Matters

PR #807 went red in CI (Linux run 40283331105) on a hooks test that was green on
the seat:

- `test_this_process_args_name_its_interpreter` read `process_args(os.getpid())`
  and expected the interpreter. CI runs `pytest -n auto`; pytest-xdist retitles
  every worker through setproctitle, so the test read `[pytest-xdist running] …`.

**Why no existing rule saw it.** No rule read a test's own pid as a host fact.

---

## What the Checker Scans For

AST-parses every `.py` file under the branch's `tests/` and each
`lib/<skill>/tests/`.

### The test reads its own process's command line
A call whose argument is `os.getpid()` or `os.getppid()` and whose callee name
holds args, argv, cmdline, command, title or proctitle as a whole
underscore-separated word. `is_pid_alive(os.getpid())` reads no title and is clean.

### Deliberately not claimed
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

---

## Scoring

`clean test files / total test files x 100`. Up to 3 offending `file:line`
rows in the message, every row in `violations`. Pass threshold 75%.

---

## Bypass

Via `.sentry/bypass.json`, key `host_coupled_oracle`: standard, file-level and
line-level rules.

---

## Reference

- Checker: `host_coupled_oracle_check.py`
- Content: `host_coupled_oracle_content.py`
- Sibling: `host_portability` (one file's host reads), `calendar_bound` (the date)
