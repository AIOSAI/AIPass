# Triplet Proof — Standard File Completeness
**Version:** 1.0.1
**Created:** 2026-03-22
**Modified:** 2026-10-24
**Status:** Placeholder

---

## Purpose

The triplet proof verifies that every standard in a pack exists as a complete set of 3 files. A standard is only fully realized when all three components are present — the runtime checker, the queryable content, and the human-readable documentation.

---

## The 3-File Convention

Every standard `{name}` in a pack must have:

| File | Role | Consumer |
|------|------|----------|
| `{name}_check.py` | Runtime checker — validates branches against the standard | Audit engine |
| `{name}_content.py` | Queryable content — returns formatted text for the query system | standards_query module |
| `{name}.md` | Full documentation — complete specification for humans | Developers, branch managers |

---

## What the Scan Checks

1. **Glob all `*_check.py` files** in the pack directory to establish the standard names
2. **For each standard name**, verify that `{name}_content.py` and `{name}.md` also exist
3. **Detect orphans** — content or md files that exist without a matching checker, and any other
   `.py` file. A `.py` that a sibling file imports (`check_support.py`, `prose_lines.py`) is a shared
   helper, not an orphan
4. **Report completeness** — count of complete triplets vs incomplete standards

---

## Examples

### Complete Triplet (passing)

```
architecture_check.py      -- checker
architecture_content.py    -- queryable content
architecture.md            -- documentation
```

All three files present. The standard is fully realized.

### Incomplete Standard (failing)

```
naming_check.py            -- checker exists
                           -- naming_content.py MISSING
                           -- naming.md MISSING
```

The checker runs, but branches cannot query the standard and humans have no documentation.

### Orphaned Content (failing)

```
                           -- bypass_check.py MISSING
bypass_content.py          -- content exists with no checker
```

Content exists but there is no checker to enforce it.

---

## How to Fix Failures

1. **Missing content file**: Create `{name}_content.py` with a `get_{name}_standards()` function that returns formatted Rich text
2. **Missing md file**: Create `{name}.md` with full documentation (purpose, rules, examples, how to fix violations)
3. **Orphaned content/md**: Either create the missing checker or remove the orphan if the standard was intentionally dropped

Use existing complete triplets as templates. The `architecture` standard is a reliable reference.

---

## Scan Interface

```python
scan(pack_dir: Path) -> dict
# Returns: {"passed": bool, "issues": list, "summary": str, ...}
```

<!-- TODO: Document return dict shape in detail once scanner is implemented -->

---

## Related

- **DPLAN-0044**: Self-audit tooling design
- **tools/triplet_scanner.py**: Original prototype that this proof is based on
- **Checker**: `triplet.py` in this directory
