# Plugin Integrity Proof — Dynamic Discovery Contract
**Version:** 1.0.1
**Created:** 2026-03-22
**Modified:** 2026-10-23
**Status:** Placeholder

---

## Purpose

The plugin integrity proof verifies that core audit modules do not hardcode standard names. The seedgo audit system uses a plugin architecture — standards are discovered dynamically via `glob` + `importlib`. If core modules hardcode standard names, the "drop-in" contract breaks: adding a new standard by dropping a file into the pack no longer works without also editing core code.

---

## Modules Scanned

These are the core audit modules that must stay clean of hardcoded standard names:

| Module | Role |
|--------|------|
| `standards_audit.py` | Discovers and executes checkers via glob + importlib |
| `branch_audit.py` | Orchestrates branch-level audit runs |
| `audit_display.py` | Formats and displays audit results to the terminal |
| `seedgo.py` | Main entry point for the seedgo system |

---

## What Counts as Hardcoded

A standard name is "hardcoded" when it appears as a string literal inside a core module in a context that affects logic or routing. The scanner checks for known standard names (e.g., `"architecture"`, `"encapsulation"`, `"imports"`) appearing in these modules.

### The AMBIGUOUS_NAMES Filter

Some standard names are common English words that appear in non-standard contexts. The scanner maintains an `AMBIGUOUS_NAMES` set to filter false positives:

<!-- TODO: Document the full AMBIGUOUS_NAMES list once scanner is finalized -->

Examples of ambiguous names that may need filtering:
- `"meta"` — appears in Python metadata contexts
- `"naming"` — appears in general discussions of naming
- `"testing"` — appears in general testing references
- `"trigger"` — appears in event/action contexts

---

## Cosmetic vs Structural Hardcoding

Not all hardcoded references have the same severity:

### Structural (must fix)

Standard names used in logic that affects which standards run or how results are processed:

```python
# BAD — hardcoded routing
if standard_name == "architecture":
    result = check_architecture(branch_path)
elif standard_name == "encapsulation":
    result = check_encapsulation(branch_path)
```

```python
# GOOD — dynamic iteration
for checker in discovered_checkers:
    result = checker.check_module(file_path, bypass_rules=bypass_rules)
```

### Cosmetic (upgrade target)

Standard names in display strings, section headers, or help text:

```python
# Cosmetic — doesn't affect logic, but still couples display to specific standards
console.print("[bold]Architecture:[/bold]")
console.print(results["architecture"]["summary"])
```

**`audit_display.py`** has known cosmetic hardcoding. This is tracked as **DPLAN-0047** — the upgrade path is to iterate result dicts dynamically instead of hardcoding section order.

---

## Known Special Cases

### branch_audit.py — 3 Legitimate Cases

`branch_audit.py` has 3 standards that require special handling because they operate at a different scope than file-level checkers:

1. **architecture** — Template baseline check requires branch-level context
2. **meta** — Passport/trinity validation requires branch-level context
3. **testing** — Test discovery requires branch-level context

These are not bugs — they are architectural necessities documented in the checker interfaces. They use `AUDIT_SCOPE = "branch_level"` which requires distinct calling logic.

### audit_display.py — Cosmetic References

Display formatting references specific standard names for section headers and ordering. This is functional but not ideal. The upgrade path (DPLAN-0047) would replace hardcoded sections with dynamic iteration over whatever results the audit returns.

---

## What the Scan Checks

1. **Read** each core module's source code
2. **Extract** all string literals
3. **Compare** against the known standard names list
4. **Filter** through AMBIGUOUS_NAMES to remove false positives
5. **Classify** remaining matches as structural or cosmetic
6. **Report** violations with file, line number, and context

<!-- TODO: Document the exact regex/AST approach and threshold for
     pass/fail once scanner is implemented -->

---

## How to Fix

1. **Structural hardcoding**: Replace with dynamic iteration over discovered checkers or result dicts
2. **If/elif chains**: Convert to loop over `glob('*_check.py')` results
3. **Dict key references**: Use `.items()` iteration instead of hardcoded key access
4. **Display sections**: Iterate result keys dynamically (DPLAN-0047 upgrade)
5. **Document special cases**: If a reference is truly necessary, document why in the code and in this proof

---

## The Drop-In Contract

The fundamental promise of the plugin architecture:

> To add a new standard to a pack, drop `{name}_check.py` into the pack directory. The audit engine discovers it automatically. No other files need to change.

Every hardcoded standard name in a core module is a violation of this contract. It means adding a standard requires editing core code, which defeats the purpose of plugin discovery.

---

## Related

- **DPLAN-0044**: Self-audit tooling design
- **DPLAN-0047**: audit_display.py cosmetic hardcoding upgrade
- **tools/plugin_integrity_scanner.py**: Original prototype
- **Checker**: `plugin_integrity.py` in this directory
