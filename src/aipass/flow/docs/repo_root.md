[← Back to Flow](../README.md)

# Location Discovery — handlers/repo_root.py

The one location answer for the branch, and the test worlds that keep it honest.

---

**Nothing in flow reads the process working directory to find itself.** One
module answers both location questions, and every caller routes through it.

| Function | Answers | Guard it carries |
|----------|---------|------------------|
| `module_file(__file__)` | where is *this module* | `.resolve()` attempted, falls back to the absolute spelling |
| `find_repo_root(start=None)` | which repo root is this | falls back to `SOURCE_ROOT`, **never** `Path.cwd()` |
| `exists_exactly(path)` | is this filename spelled exactly so | lists the parent; `exists()` alone folds case |

A `Path.cwd()` fallback for the repo root is wrong twice: it crashes when the
cwd is gone, and when it does not crash it is a *guess*. Writers that build
`.ai_central/PLANS.central.json` and the `.backup/processed_plans` path would
resolve against whatever directory the caller's shell happened to be in.

**Two `Path.cwd()` reads remain, and both are correct.**
`project_scope.caller_cwd()` and `resolve_location._get_caller_cwd()` ask
*where did the caller stand* — a location, observed — and fall back to the
process directory only when `AIPASS_CALLER_CWD` is absent. They are named in
`tests/test_import_dead_cwd.py` so the ban can never delete a right answer, and
the exemption is keyed on **(file, function)**, not on the name alone.

Enforced by `tests/test_import_dead_cwd.py`: an injected world with its own
liveness control, an AST ban, **and** a behavioural sibling that reaches the
caller-is-None branch by calling the guard directly from a `python -c` child
under a realpath denial. Each catches what the other cannot — the ban names the
offending line anywhere in the tree with no subprocess, the behavioural pin
proves the cure in the world it was built for.

### The bare-checkout world is a tested world

`AIPASS_REGISTRY.json` is **gitignored and machine-local**, so a dev box and a CI
runner disagree about whether `find_repo_root` takes its fallback. That is a
whole second world flow's tests must pass in.

The fallback logs `repo_root_fallback` through `json_handler.log_operation`, and
six modules take the walk while **loading**. On a bare checkout that import-time
diagnostic would land inside whichever test window triggers the first import.

`handlers/json/json_handler.py` is the fleet **shim**: it binds
`aipass.prax.json_handler`'s callables and adds nothing (byte-identical in every
branch, sentry accepts it by hash). `repo_root._record_fallback` resolves
`json_handler.log_operation` as a module attribute at **call** time, so the
autouse `mock_json_handler` spy intercepts it. Containment is the autouse
`mock_infrastructure`, which sets `AIPASS_TEST_LOG_DIR`: the service recomputes
its directory on every call, so a fixture that patches names cannot keep writes
out of `flow_json/`.

`tests/conftest.py` **pre-imports all six module-level callers**, settling the
walk before any test window exists on every machine. The list is guarded by
`TestThePreImportListIsComplete`, which measures the callers off the tree by
parse and compares them against what conftest actually imports — neither side
hand-copied, because a hand-written list is where an undercount hides.

### An injected world has to ARM, and the arming is version-shaped

The dead-cwd pins install their world by patching `os.path.realpath` in a
subprocess. On **Python 3.10 that patch reaches nothing**: `pathlib` still has
`_NormalAccessor`, whose `realpath = staticmethod(os.path.realpath)` takes its
copy when `pathlib` is first imported, and `Path.resolve` reads it as
`self._accessor.realpath(self, strict=strict)`. Patching the module attribute
afterwards rebinds a name nothing reads again. 3.11 removed the accessor and
calls `os.path.realpath` at use.

The world therefore ends in `_ACCESSOR_CURE`, which patches the accessor as a
`staticmethod` behind a `hasattr` — order-independent on 3.10, inert on 3.11+.
A plain function would arrive **bound** and eat the path into `self`.

---
