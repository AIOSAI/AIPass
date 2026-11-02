# Self Set Assert Standards
**Status:** v1
**Date:** 2026-09-23

---

## What It Is

Crack class **E**. A test writes a value and then asserts that the value is there.

```python
r = BackupResult(mode="snapshot")
r.files_deleted = 5
assert r.files_deleted == 5          # Python's setattr decided this, not the product
```

Nothing about the product decided that. It would pass against an empty class. The test reads
as coverage of `BackupResult` and covers only `setattr`.

---

## The three shapes

| shape | fleet |
|---|---|
| `target.attr = X` then `assert target.attr == X` | 1 |
| `d[key] = X` then `assert d[key] == X` | 0 |
| `obj = C(attr=X)` then `assert obj.attr == X` | 14 |

The constructor kwarg is the shape nobody sees while writing it.

---

## The judgement this rule makes

Score only when NOTHING RAN in between. If a call sits between the assignment and the
assertion, the assert is a durability oracle — "the product did not clobber this" — and that
is a real claim about the product.

```python
client.file_tracker = {"existing.txt": {"drive_id": "abc"}}
assert client.get_or_create_backup_folder() == "found_folder"   # the product runs
assert client.file_tracker == {"existing.txt": {"drive_id": "abc"}}   # and did not clear it
```

That is the test's whole point, and convicting it would be wrong. Those ride in the passing
message as a count.

## The other line it holds

The comparison must be `==` against the SAME literal.

```python
client._drive_service = service
assert client.drive_service is service      # the PROPERTY, and `is` not `==`
```

Different name, different operator: the product's getter is under test there, so the rule
declines it.

## The other half of weak_oracle

`weak_oracle` reads a self-set assert as STRONG, because it is a real value comparison. This
rule is the other half of that verdict: the comparison is strong, the value is the test's own.

---

## Check first

Measured 2026-09-23 over the fleet's 572 test files.

| | |
|---|---|
| files scored | 5 |
| hits scored | 15 |
| reported (a call ran in between) | 8, in 5 other files |

The largest single cluster is one `Event` built with eight keyword arguments and all eight
read straight back.

---

## Why it cannot be satisfied by accident

With no call in between there is no product between the write and the read. The assertion is
a statement about Python, and it passes with the product deleted.

## Scoring

Scored, per file. Every hit names the assert line, the path and the shape, on ONE check.

## The cure

Assert what the product computed, not what this test just wrote.

---

[← Back to README](../../../README.md)
