# README Currency Proof — Documentation Accuracy
**Version:** 1.1.0
**Created:** 2026-03-22
**Modified:** 2026-10-24
**Status:** Active

---

## Purpose

The README currency proof verifies that a pack's `README.md` accurately reflects the actual state of the pack. README files are the first thing branches and humans read to understand pack coverage. Stale READMEs erode trust and cause confusion.

---

## What Gets Checked

### 1. Checker Count Accuracy

The README typically states how many standards the pack contains (e.g., "24 active standards"). This proof compares that stated count against the actual number of `*_check.py` files in the pack.

```
README says:  "24 active standards"
Actual count: glob("*_check.py") -> 26 files
Result:       FAIL — count mismatch (off by 2)
```

### 2. Undocumented Standards

Every `*_check.py` in the pack has a row in the standards table on the pack's docs pages, `docs/<pack>*.md`, which the README indexes. A standard with no row is "undocumented."

```
Pack contains:  stderr_routing_check.py
Docs tables:    (no stderr_routing row)
Result:          FAIL — undocumented standard
```

### 3. Stale References

A table row names a standard that no longer exists in the pack. When a standard is archived or removed, its row goes too.

```
Docs tables:     | diagnostics |
Pack contains:   (no such file — moved to .archive/)
Result:          FAIL — stale reference
```

---

## How Detection Works

1. **Count extraction**: Parse the README for numeric patterns near keywords like "standards", "checkers", "active"
2. **Standard enumeration**: Glob `*_check.py` in the pack directory, extract standard names
3. **Table rows**: Read the first cell of every `| name |` table row on `docs/<pack>*.md`
4. **Cross-reference**: Names match exactly after lower-casing; a pack name with no row is undocumented, a row with no pack file is stale

---

## What "Undocumented" Means

A standard is undocumented if:
- Its `*_check.py` file exists in the pack directory
- No table row on `docs/<pack>*.md` starts with that standard's name

A mention in prose does not count: the table is the one listing a reader scans.

---

## Common Failures

| Failure | Cause | Fix |
|---------|-------|-----|
| Count mismatch | Standards added/removed without updating README count | Update the count |
| Undocumented standard | New checker added, docs table not updated | Add its row |
| Stale reference | Standard archived/removed, docs table not updated | Remove the row |

---

## How to Fix

1. **Count**: Run `ls *_check.py | wc -l` in the pack directory, update the README count
2. **Undocumented**: Add a table row for each missing standard
3. **Stale**: Remove or mark as archived any references to non-existent standards

---

## Related

- **DPLAN-0044**: Self-audit tooling design
- **tools/readme_currency_scanner.py**: Original prototype
- **Checker**: `readme_currency.py` in this directory
