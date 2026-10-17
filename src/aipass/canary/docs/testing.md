[<- Back to the README](../README.md)

# Testing

How to run this branch's suite, what runs it in continuous integration, and the
one seam that decides whether it passes at all.

## Running it

```bash
pytest src/aipass/canary/tests -v                                  # from the repo root
pytest src/aipass/canary/tests -c pyproject.toml --rootdir=. -v    # the repo-root config form
```

Neither count is written down here on purpose: a test count on a page rots the
next time a test is added, and the command above prints the true one in about
four seconds. The second form cannot be run from this branch's own seat: the
project write gate reads the `-c pyproject.toml` path as a write target and
refuses it.

## The seam

`tests/conftest.py` sets `AIPASS_TEST_LOG_DIR` at module import, not inside a
fixture. The repo-root `conftest.py` guard reads that variable while it is
importing, so a fixture sets it too late and the whole suite collapses into
import errors under the repo-root config form.

A suite run inside the composed fleet process can pass without that import-time
set, because a sibling's conftest has already set the variable in the same
process. A green suite can ride on another branch's import side effect; alone,
under the repo-root config, the same suite is all errors.

## What continuous integration actually runs

No workflow names this branch. The fleet is tested in one process from the repo
root: `ci.yml` across Python 3.10 to 3.13 on Linux, `macos-test.yml` on macOS
without the e2e ignore.

```bash
pytest -v --tb=short --rootdir=. --ignore=tests/e2e -n auto --dist loadscope --timeout 300 --timeout-method thread --max-worker-restart 0
```

That run covers this branch without giving it a job of its own. Whether this
branch stays green *inside* that composed invocation has not been reproduced
locally — in that shape a sibling sets the environment variable first, so a
missing import-time set would be masked rather than cured.

## Where tests live

`tests/` holds the entry-point tests, one file per module (note, span, top,
align, kv), the dead-cwd import pins, and the handler fence tests with their
support file. Archived suites sit in `tests/.archive/`, untracked, with the
date they were retired in the filename.

The json handler shim has no test file here: every property of it is carried
once, parametrised across every branch in the fleet, by the standards branch's
own contract test, where the shim is one file.

New test files need permission by policy, and a hook gate refuses them across
the fleet. `agent_test_writing` is off and `allow` holds `seedgo` alone; this
branch is not on it, so the gate refuses a new test file here as it does
anywhere else. Read it live with `drone @hooks testwrite`; never route around
it. The route to a new test is a mail to the orchestration branch naming the
defect or the contract it would pin.

[<- Back to the branch README](../README.md)
