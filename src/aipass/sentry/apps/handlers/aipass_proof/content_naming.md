# Content Naming Proof — Function Name Convention
**Version:** 1.0.0
**Created:** 2026-03-22
**Modified:** 2026-03-22
**Status:** Placeholder

---

## Purpose

The content naming proof verifies that every `*_content.py` file exports a function whose name matches the convention the `standards_query` module expects. The query system derives the function name from the filename — if the name doesn't match, the query fails silently.

---

## The Naming Convention

The convention is deterministic: the standard name is extracted from the filename, then used to construct the function name.

```
Filename:     {name}_content.py
Function:     get_{name}_standards()
```

### Correct Examples

| File | Expected Function |
|------|-------------------|
| `architecture_content.py` | `get_architecture_standards()` |
| `imports_content.py` | `get_imports_standards()` |
| `log_handler_content.py` | `get_log_handler_standards()` |
| `error_handling_content.py` | `get_error_handling_standards()` |
| `json_structure_content.py` | `get_json_structure_standards()` |

### Incorrect Examples

| File | Wrong Function | Why |
|------|----------------|-----|
| `architecture_content.py` | `get_architecture_content()` | Suffix must be `_standards`, not `_content` |
| `architecture_content.py` | `get_arch_standards()` | Name must match full prefix, no abbreviations |
| `imports_content.py` | `get_import_standards()` | Must be `imports` (plural), exactly as in filename |

---

## How standards_query Resolves Function Names

1. Discover all `*_content.py` files via glob
2. For each file, extract the name: strip `_content.py` suffix to get `{name}`
3. Construct expected function name: `get_{name}_standards`
4. Import the module and call `getattr(module, function_name)`
5. If the attribute doesn't exist, the standard silently has no queryable content

<!-- TODO: Document the exact standards_query resolution code path
     and error handling behavior -->

---

## What the Scan Checks

1. **Glob** all `*_content.py` files in the pack
2. **Extract** the standard name from each filename
3. **Import** the module (or parse with AST)
4. **Verify** the expected `get_{name}_standards` function exists
5. **Report** any mismatches

---

## Common Failures

- **Wrong suffix**: `get_{name}_content()` instead of `get_{name}_standards()`
- **Abbreviated name**: `get_arch_standards()` instead of `get_architecture_standards()`
- **Missing function**: File exists but contains no matching function at all
- **Typo in name**: `get_arcitecture_standards()` — close but not exact

---

## How to Fix

1. Open the content file
2. Extract the standard name from the filename (everything before `_content.py`)
3. Ensure the file contains exactly: `def get_{name}_standards() -> str:`
4. Verify the function returns a string of formatted content

---

## Related

- **DPLAN-0044**: Self-audit tooling design
- **tools/content_naming_scanner.py**: Original prototype
- **Checker**: `content_naming.py` in this directory
