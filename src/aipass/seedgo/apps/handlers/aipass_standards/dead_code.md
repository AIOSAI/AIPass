# Dead Code Standard
**Status:** Draft v1
**Date:** 2026-03-22

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

### Always Considered Used

- `__init__.py` (package structure)
- Entry point files (`apps/{branch}.py`)
- Glob-discovered patterns (`*_check.py`, `*_content.py`) when a matching glob call exists
- Direct children of `modules/` when `glob("*.py")` exists in the source

### Skip Directories

The following directories are excluded from both collection and corpus building:

`__pycache__`, `.archive`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`, `json_templates`, `logs`, `tools`, `.venv`, `venv`, `node_modules`, `.git`, `site-packages`, `.trinity`, `.aipass`, `.ai_mail.local`, `.spawn`, `backups`, `reports`, `docs`, `tests`, `.sorting_unprocessed`

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
- The violation message lists up to 10 unreferenced files

---

## Bypass

Add an entry to `.seedgo/bypass.json`:

```json
{
    "standard": "dead_code",
    "file": "path/to/file.py"
}
```

The entire standard can also be bypassed at branch level:

```json
{
    "standard": "dead_code"
}
```

---

## Audit Scope

`AUDIT_SCOPE = "branch_level"` -- this checker runs once per branch, not per file. It receives the branch root path and scans the entire `apps/` tree.

---

## Reference

- Checker: `dead_code_check.py`
- Standards pack: seedgo standards (dead_code)
