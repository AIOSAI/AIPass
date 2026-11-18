# Caller File Depth Standard
**Status:** v1
**Date:** 2026-11-17

---

## What This Standard Is

A depth function finds a caller's branch by climbing a fixed number of folders from the file the caller hands
it: `for_module(__file__)` returning `Path(file).parents[3]` is right for a file at
`<branch>/apps/handlers/<x>/file.py`. A call handing it `__file__` from anywhere else is wrong, or right only by
coincidence of depth, and nothing pins the coincidence.

---

## Why It Matters

The hook engine runs its handlers from a snapshot: `drone @hooks promote` copies `hooks/apps/` to
`hooks/.live-<stamp>/`. A snapshot file at `hooks/.live-<stamp>/handlers/json/json_handler.py` has the same depth
as its source, so `parents[3]` still lands on `hooks/`. A depth function that starts reading the layout (an
`apps/` folder in the path) then raises inside every hook, and every tool call of every seat is refused,
including the one that would undo the change.

---

## What the Checker Reads

- **Depth functions**: every function under `src/aipass` (tests, `docs.local`, dot folders skipped) that climbs
  two or more levels from a parameter: `.parents[n]`, `.parent` chains, `os.path.dirname`, through `Path`,
  `resolve`, `abspath`, `realpath`. One level (`Path(file).parent`) finds a folder, not a branch.
- **Calls**: a call by that name whose first argument is the file's own `__file__`, bare or wrapped.
- **Run locations**: the file itself, and each copy of it in a folder beside its branch's `apps/` holding the
  same path below it (a promoted snapshot). `.archive/` is never read.

A call is convicted when, from any run location, the file is not at `<branch>/apps/...` with exactly the depth
the function climbs:

| From | Finding |
|---|---|
| the source, at another depth | the climb lands on another folder, not the branch |
| a copy beside `apps/` | the climb lands on the branch only by coincidence of depth |

### What Passes

- A caller at `<branch>/apps/...` at the function's depth with no copy beside `apps/`.
- A call handing any other path (`SOME_PATH`, `module.__file__`).
- A whole-branch copy elsewhere (`docs.local/snap/apps/...`): its `apps/` layout is intact, and it is not run.

### What It Cannot See

A copy that is not on disk when the audit runs: a clean checkout has no snapshot, and a wheel install or a
temp copy lives elsewhere. Depth functions are matched by name across the fleet, so a call to an unrelated
function sharing a depth function's name is read as one.

---

## Code Examples

### Violation

```python
# hooks/apps/handlers/json/json_handler.py, also run from hooks/.live-<stamp>/handlers/json/
_HANDLE = json_service.for_module(__file__)
```

### Fix

```python
_HANDLE = json_service.for_branch(BRANCH_ROOT)    # the root passed explicitly
```

or the function finds the root by a marker (a folder holding `.trinity/passport.json`), never by depth.

---

## Scoring

- One finding per call, each with its line and enclosing function.
- **Score:** 100 with no unwaived call, else 0. A file Python cannot parse: 0, unjudged.
- **Bypass:** a `lines` or `functions` rule waives those calls; a rule with neither waives the file.

---

## Reference

- Checker: `caller_file_depth_check.py`
- Content: `caller_file_depth_content.py`
- Sibling: `fixed_depth_path` judges a climb off the file's own `__file__`; this standard judges a climb a
  function makes from a path its caller hands it.
