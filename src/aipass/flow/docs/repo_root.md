[← Back to Flow](../README.md)

# Location Discovery — handlers/repo_root.py

The one location answer for the branch, and the test worlds that keep it honest.

---

**Nothing in flow reads the process working directory to find itself.** One
module answers the repo-root question, and every caller routes through it.

| Function | Answers | Guard it carries |
|----------|---------|------------------|
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

Enforced by `tests/test_import_dead_cwd.py`: an AST ban names any other cwd read
anywhere in the tree, with no subprocess.

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

---
