# Dead Code Standard
**Status:** v1.5
**Date:** 2026-10-10

---

## What This Standard Is

Every `.py` file in `apps/modules/` and `apps/handlers/` must be referenced somewhere in the branch. Unreferenced files are dead code -- they confuse navigation, burn AI context, and rot over time. If a file is not imported, not glob-discovered, and not referenced by name, it should not exist.

---

## Why It Matters

- **Navigation clarity:** Dead files mislead developers and AI into reading code that has no effect.
- **Context efficiency:** AI processes every file it encounters. Dead files waste context tokens on code that does nothing.
- **Maintenance burden:** Dead code rots silently. When surrounding code changes, dead files become increasingly wrong without anyone noticing.
- **Clean architecture:** The 3-layer pattern (entry -> modules -> handlers) requires clear dependency chains. Orphaned files break that chain.

---

## What the Checker Scans For

This is a **branch-level** checker. It receives the branch root path and scans the entire `apps/` tree.

### Collection Phase

1. Collects all `.py` files from `apps/modules/` and `apps/handlers/` (recursively)
2. Skips `__init__.py` and files inside excluded directories

### Reference Detection

For each collected file, the checker builds a search corpus from ALL `.py` content under `apps/` and checks whether the file is referenced by any of these methods:

| Method | Example |
|--------|---------|
| Full dotted import | `from aipass.branch.apps.handlers.foo import bar` |
| Relative dotted path | `handlers.foo` in the source |
| Import statement with stem | `from ... import foo_handler`, or inside a parenthesised block `from ... import (\n    foo_handler,\n)` (read since 2026-09-14; comments in the block do not count) |
| importlib.import_module | `import_module("...foo_handler")` |
| Glob-based discovery | `glob("*_check.py")`, `glob("*.py")` |
| Filename string literal | `"foo_handler.py"` in source |
| Project config, dotted path only | `"aipass.branch.apps.handlers.foo.handle"` in the project's `.aipass/*.json`, the project root being the nearest directory at or above the branch holding a `*_REGISTRY.json` (since 2026-10-08: hooks names 28 handlers only there), or the AIPass install, known as hooks' loader knows it: `.aipass/hooks.json` beside `src/aipass/` (since 2026-10-10: `AIPASS_REGISTRY.json` is git-ignored, so a clean checkout read hooks 88 where the seat read 100). A stem or filename in a json acquits nothing |

### Always Considered Used

- `__init__.py` (package structure)
- Entry point files (`apps/{branch}.py`)
- Doors (`apps/modules/door_*.py`) that pass the modules standard's Door shape row (DPLAN-0404, since 2026-10-08): a door is called from other branches, so its own branch never names it. A `door_` file that fails Door shape is read like any other module
- Glob-discovered patterns (`*_check.py`, `*_content.py`) when a matching glob call exists
- Direct children of `modules/` when `glob("*.py")` exists in the source

### Skip Directories

The following directories are excluded from both collection and corpus building:

`__pycache__`, `.archive`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`, `json_templates`, `logs`, `tools`, `.venv`, `venv`, `node_modules`, `.git`, `site-packages`, `.trinity`, `.aipass`, `.ai_mail.local`, `.spawn`, `backups`, `reports`, `docs`, `tests`, `.sorting_unprocessed`

The set is `SOURCE_SKIP_DIRS` plus `tests` and `json_templates`, read below the branch root only. A `SOURCE_SKIP_DIRS` name that is an importable package (an identifier directory holding `__init__.py`) is source and is read: commons keeps live code in `apps/handlers/artifacts/` (since 2026-10-08).

---

## Code Examples

### Violation

```
apps/
  handlers/
    legacy/
      old_processor.py    <-- 0 references anywhere in apps/
    json/
      json_handler.py     <-- imported normally, no issue
  modules/
    unused_module.py      <-- 0 references anywhere in apps/
```

Result: `2/15 files unreferenced: handlers/legacy/old_processor.py, modules/unused_module.py`

### Fix -- Delete or Archive

```bash
# If obsolete, remove it
rm apps/handlers/legacy/old_processor.py

# Or move to archive
mv apps/handlers/legacy/old_processor.py .archive/
```

### Fix -- Add a Proper Reference

```python
# If still needed, import it somewhere
from aipass.branch.apps.handlers.legacy import old_processor
```

---

## Scoring

- **Score formula:** `referenced_files / total_files * 100`
- **Threshold:** Score >= 75 to pass overall
- A branch with 20/25 files referenced scores 80 (passes)
- A branch with 15/25 files referenced scores 60 (fails)
- The violation message lists up to 10 unreferenced files, each relative to `apps/` with forward slashes on every host (`handlers/x/y.py`, never `handlers\x\y.py`; since 2026-10-10, Windows CI)

---

## Bypass

Add an entry to `.seedgo/bypass.json`:

```json
{
    "standard": "dead_code",
    "file": "apps/handlers/path/to/file.py"
}
```

`file` is matched as a substring of the path from the branch root, so `apps/handlers/x.py`
and `handlers/x.py` both match (checker 1.4.0, 2026-10-08). Until then dead_code alone was
handed the `apps/`-relative path: @hooks' rows written `apps/handlers/lifecycle/session_boot.py`
silenced nothing, and `bypass prune`'s dead-rule report could not see it because every other
lane matched them. A rule naming no `file` is inert (owner, 2026-09-25), not branch-wide.

---

## Audit Scope

`AUDIT_SCOPE = "branch_level"` -- this checker runs once per branch, not per file. It receives the branch root path and scans the entire `apps/` tree.

---

## Reference

- Checker: `dead_code_check.py`
- Standards pack: seedgo standards (dead_code)
