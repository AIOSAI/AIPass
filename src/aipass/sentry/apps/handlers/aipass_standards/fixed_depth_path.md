# Fixed Depth Path Standard
**Status:** v1
**Date:** 2026-11-17

---

## What This Standard Is

No production file finds a home, repo root, project root, log or JSON directory by climbing a
fixed number of folders up from its own file. AIPass ships as a wheel: installed, a module
sits in `site-packages/aipass/...`, not in a checkout, and a depth that is right in the repo
is wrong there.

---

## Why It Matters

- **Above the package is site-packages.** `Path(__file__).parents[5]` from
  `src/aipass/<branch>/apps/handlers/x/y.py` is the repo root in a checkout and the
  interpreter's `lib/` directory on a wheel.
- **State is not shipped.** The wheel is built from `src/aipass` and skips what git ignores:
  `logs/`, `system_logs/`, `*_json/`. A climb to a branch root joined to one of them writes
  logs and JSON state into the installed package. A branch's own dot folders are not that state.

---

## What the Checker Reads

A climb is `.parents[n]` (n + 1 levels), `.parent` (1) or `os.path.dirname` (1), through
`Path`, `PurePath`, `resolve`, `absolute`, `abspath`, `realpath`, `normpath`, starting from:

| Base | Levels to `src/aipass` |
|---|---|
| `__file__` | the file's depth below `src/aipass` (`demo/apps/x.py` is 3) |
| `aipass.<x>.__file__` | the module's origin: a package's `__init__.py`, else `<x>.py` |
| `find_spec("aipass.<x>").origin`, also through a name bound to the spec | the same |
| a name bound to a climb (`HERE = Path(__file__).parent`) | the climb's, followed in source order |

A name is also followed into the files of the SAME branch that import it: `TRIGGER_ROOT` bound to a climb in
`apps/config.py` and imported by `apps/handlers/error_registry.py` is a climb there too, also when an alias or
a second file re-exports it. The finding sits at the join line and names where the root was counted
(`TRIGGER_ROOT counted at apps/config.py:22`). A name the importing file rebinds is not followed.

A site is convicted when:

1. **The climb leaves `src/aipass`**: it climbs more levels than remain.
2. **The climb is joined to something the wheel does not ship**: `p / "logs"`, `os.path.join(p, ".trinity")`,
   `p.joinpath("x_json")`, where the first segment is a dot name, `logs`, `system_logs`, ends `_json`, or is
   named by the repo `.gitignore` at the place the climb lands (`trigger/trigger_data.json`, `artifacts/`).
   A climb that already left the package is reported once, as (1).

A dot folder at the branch's own root (`.trinity`, `.sentry`, `.ai_mail.local`, `.daemon`) passes. It is part of
the branch folder and stays there on an install: the gitignored ones are the citizen's own stored files, the
tracked ones ship with the code, and neither is runtime output. A dot folder reached above the branch
(`parents[4] / ".ai_central"`) or below its root is still convicted.

### What It Cannot See

- A root imported from another branch, or read as a module attribute (`config.TRIGGER_ROOT`).
- A root passed as a parameter, or built through `".."` joins.
- A `.gitignore` negation (`!`) is not read, and for a root imported from a deeper file the `.gitignore`
  place is read along the importing file's path.

### What Passes

- A climb that stays inside `src/aipass` and names shipped files: `Path(__file__).parent /
  "data.json"`, `BRANCH_ROOT / "templates"` — package data the wheel carries.
- A climb from a parameter (`Path(file).parents[3]`) or through a `".."` join: the depth is
  not in the file, so it is not read.
- A file outside `src/aipass`: it is not in the wheel.
- Test files: `APPLIES_TO = production`.

---

## Code Examples

### Violation

```python
REPO_ROOT = Path(__file__).resolve().parents[5]           # leaves src/aipass
LOG_DIR = Path(__file__).resolve().parents[3] / "logs"     # unshipped folder
```

### Fix

```python
HOME = Path(os.environ["AIPASS_HOME"])                      # a resolver: env, registry walk
LOG_DIR = HOME / "logs"
TEMPLATES = Path(__file__).parent / "templates"            # shipped package data
```

---

## Scoring

- One finding per site, each with its line and enclosing function.
- **Score:** 100 with no unwaived site, else 0.
- **A file Python cannot parse:** 0, unjudged.

---

## Bypass

A `lines` or `functions` rule in the owning branch's `.sentry/bypass.json` waives those sites;
a rule with neither waives the whole file.

```json
{
    "standard": "fixed_depth_path",
    "file": "apps/handlers/x/y.py",
    "lines": [20],
    "reason": "why this climb is right on a wheel"
}
```

---

## Reference

- Checker: `fixed_depth_path_check.py`
- Content: `fixed_depth_path_content.py`
