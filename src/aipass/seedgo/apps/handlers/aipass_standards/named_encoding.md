# Named Encoding Standards
**Status:** v1
**Date:** 2026-09-21

---

## What It Is

Test template v1, **item 21**: every file read or write in a test names its encoding.

```python
(tmp_path / "README.md").write_text(body)                 # convicted
assert "—" in (tmp_path / "README.md").read_text()        # convicted
```

Neither call says what encoding it means, so both take whatever the host's locale prefers.

---

## Why It Matters

`open()`, `Path.read_text()` and `Path.write_text()` fall back to `locale.getpreferredencoding(False)`. On this fleet's Linux and macOS hosts that is UTF-8 and the omission is invisible. On Windows, through Python 3.12, it is **cp1252**.

The product's output is not ASCII. The audit prints box-drawing characters, plan templates carry em dashes, @commons posts carry whatever a citizen typed. A test that writes such a fixture without naming utf-8 passes on the machine it was written on and raises `UnicodeDecodeError` in the Windows CI lane — which is a failure of the **test**, not of the product it was meant to measure. PR#774's Windows leg is where this rule comes from.

Measured 2026-09-21 across 553 fleet test files (`test_*.py` and `conftest.py` under each branch's `tests/`):

| | files | hits |
|---|---|---|
| any hit | 82 of 553 | 918 |
| `write_text()` | — | 703 |
| `read_text()` | — | 215 |
| bare `open()` | 0 | 0 |

The fleet already learned half the lesson: not one `open()` call in a test file is missing an encoding. It is pathlib's two convenience methods, whose signatures hide the argument, that carry all 918.

---

## What the Checker Scans For

| Shape | Convicted |
|---|---|
| `open(p)` / `open(p, "w")` — any text mode, no encoding | yes |
| `p.read_text()` — no encoding | yes |
| `p.write_text(body)` — no encoding | yes |
| `open(p, "rb")`, `open(p, mode="wb")`, `read_bytes()`, `write_bytes()` | **no** — bytes have no encoding |
| `open(p, "w", -1, "utf-8")`, `p.write_text(body, "utf-8")` | **no** — named positionally is still named |
| `p.read_text(encoding="latin-1")` | **no** — counted, see below |
| `p.read_text(encoding=CHARSET)` | **no** — named; which one is the test's business |

---

## A non-utf-8 encoding is counted, never convicted

```python
assert p.read_text(encoding="latin-1") == "café"
```

A test of latin-1 handling has to name latin-1, and a rule that convicted it would be demanding the test lie about its own subject. Such calls are counted and the count is carried in the file's **passing** message:

```
Every text read and write names an encoding (1 names latin-1, which the rule allows)
```

Visible in the numbers, never a verdict. Zero fleet test files name one today.

---

## How to fix a violation

Add the keyword. There is no threshold, no tuning, and no judgement call — the argument is one keyword and it is always the same one.

```python
(tmp_path / "README.md").write_text(body, encoding="utf-8")
assert "—" in (tmp_path / "README.md").read_text(encoding="utf-8")
```

---

## Scope, and how it scores

`APPLIES_TO = "tests"`, `AUDIT_SCOPE = "all_files"`. The audit's corpus has included `tests/` since **2026-09-21** (owner ruling 21:20), so every `test_*.py` and `conftest.py` is measured: a file with any hit scores 0 and the branch number moves. It also convicts in the per-file checklist lane, on the write that creates the shape.

Fleet standing on arrival, 2026-09-21 — standard average **86%**:

| branch | score | branch | score | branch | score |
|---|---|---|---|---|---|
| canary | 100% | cli | 100% | commons | 100% |
| memory | 100% | devpulse | 96% | flow | 96% |
| ai_mail | 92% | api | 92% | trigger | 90% |
| backup | 86% | seedgo | 82% | daemon | 80% |
| aipass | 79% | prax | 76% | skills | 73% |
| hooks | 73% | spawn | 72% | drone | 69% |

---

## Known limits

**A mode that is not a literal is skipped.** `p.open(mode)` cannot be read as text or binary from the statement alone. Two sites fleet-wide (`api/tests/test_settings_conformance.py`, `skills/tests/test_machine_vitals.py`).

**Only the builtin `open` is convicted**, not every attribute named `open`. `ZipFile.open` is binary-only and `gzip.open` takes a different mode vocabulary, so convicting `x.open(...)` on an arbitrary receiver would charge two APIs with a rule that does not apply to them. Zero fleet test files have a bare `open()` or `path.open()` missing an encoding, so the limit costs nothing measured — the day it does, the checker's docstring says where it goes.

**A `*args` or `**kwargs` splat acquits the call.** Either can carry the encoding, so nothing about the call can be read with confidence.

---

## Provenance

`templates/test_template_v1.md` item 21, built 2026-09-21 on @devpulse's dispatch (DPLAN-0354). Fifth checker in the per-item series, after `router_assert`, `oversize_test_file`, `import_site` and `through_the_command`, and built to the same two-lane shape. The Windows evidence is PR#774.
