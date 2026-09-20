[<- Back to the README](../README.md)

# Testing

How to run this branch's suite, what runs it in continuous integration, and the
one seam that decides whether it passes at all.

## Running it

```bash
pytest src/aipass/canary/tests -v                                  # from the repo root
pytest src/aipass/canary/tests -c pyproject.toml --rootdir=. -v    # the repo-root config form
```

Both are green. Neither count is written down here on purpose: a test count on a
page rots the next time a test is added, and the command above prints the true
one in about four seconds.

## The seam

`tests/conftest.py` sets `AIPASS_TEST_LOG_DIR` at module import, not inside a
fixture. The repo-root `conftest.py` guard reads that variable while it is
importing, so a fixture sets it too late and the whole suite collapses into
import errors under the repo-root config form.

This branch learned that the expensive way: it was the odd one out, setting the
variable in a fixture while its siblings set it at import, and its suite passed
anyway in the composed fleet run because a sibling's conftest had already set
the variable in the same process. A green suite can ride on another branch's
import side effect. Alone, under the repo-root config, it was all errors.

## What continuous integration actually runs

No workflow names this branch. The fleet is tested in one process from the repo
root, across a matrix of Python versions:

```bash
pytest -v --tb=short --rootdir=. --ignore=tests/e2e -n auto --dist loadscope
```

That run covers this branch without giving it a job of its own. Whether this
branch stays green *inside* that composed invocation has not been reproduced
locally — in that shape a sibling sets the environment variable first, so a
missing import-time set would be masked rather than cured.

## Where tests live, and where they went

`tests/` holds the entry-point tests, the note store tests, and the dead-cwd
import pins. Archived suites sit in `tests/.archive/` with the date they were
retired in the filename.

The json handler tests were archived rather than deleted: every property they
pinned about this branch's shim is now carried once, parametrised across every
branch in the fleet, by the standards branch's own contract test. Nothing about
the shim went unmeasured — the measurement moved to where the shim is one file.

New test files need permission by policy; a hook gate refuses them. Editing an
existing test is fine. The route for a new one is a mail to the orchestration
branch naming the defect or the contract it would pin.

[<- Back to the branch README](../README.md)
