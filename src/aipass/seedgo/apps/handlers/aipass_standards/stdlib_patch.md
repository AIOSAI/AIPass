# Stdlib Patch Standards
**Status:** v1
**Date:** 2026-09-22

---

## What It Is

Crack class **Q** from the 2026-09-22 eyes-on review of @backup's tests. A `patch` whose
target is a **stdlib function the product calls to do its own work**. Replacing it is
process-wide, and the oracle becomes spelling-specific: the test passes only while the
product keeps reaching that exact name.

```python
with patch.object(ceiling.os.path, "getsize", side_effect=AssertionError):   # :103
```

`ceiling.os` **is** the real `os`. That line replaces `posixpath.getsize` for every module in
the process. Rewrite `check_ceiling` to use `Path.stat()` — the same measurement, a different
spelling — and the guard silently stops being tested.

---

## The judgement: which non-aipass targets are sanctioned

The line is **not** "stdlib versus product". It is:

### Sanctioned — an edge the test must seal

A process, the network, the environment, the interpreter's own I/O and module table. Sealing
an edge is what a test is supposed to do, and there is no product-local seam that would be
better.

| | |
|---|---|
| modules | `subprocess` `socket` `urllib` `http` `smtplib` `ssl` `ftplib` `asyncio` `select` |
| attributes | `sys.argv` `sys.stdout` `sys.stderr` `sys.stdin` `sys.path` `sys.modules` `os.environ` |

**819 hits acquitted, 662 of them `subprocess`.** Running a real subprocess in a unit test is
the defect; patching it is the cure.

### Scored — the product's own work, done through the stdlib

The filesystem, the clock, serialisation, imports, `open`. The product could have been given
a seam and was not, so the test reaches around it into a shared namespace.

| module | hits |
|---|---|
| `importlib` | 218 |
| `sys` (not the six above) | 211 |
| `os` | 126 |
| `builtins` | 97 |
| `pathlib` | 94 |
| `shutil` | 93 |
| `time` | 54 |
| `tempfile` · `inspect` · `signal` · `logging` · `datetime` | 21 |

---

## Four cuts, 6,926 → 916

| cut | files | hits |
|---|---|---|
| raw dotted root | 363 | 6,926 |
| the root resolved through the file's imports | 208 | 1,993 |
| **aipass name-collisions checked on disk** | 175 | 1,584 |
| edges sanctioned | **155** | **916** |

The third row is the one worth remembering.
`aipass/ai_mail/apps/handlers/contacts/email.py` is a product module whose name collides with
stdlib `email`, and **291 hits were that one collision**. A segment is only stdlib when the
aipass path up to it does *not* exist as a file on disk. Guessing from the name alone
convicts a third of @ai_mail.

**The review's first cut said 53 files and 362 hits.** This is 155 and 916, and the sanctioned
list above is drawn on the edge/own-work line, not tuned toward the smaller number.

---

## The fifth cut: a stdlib class reached through a product binding

@backup measured this checker against its own source on 2026-09-23 and found a hole. These two
lines replace the same function for the same whole process:

```python
patch("pathlib.Path.resolve", ...)                       # scored
monkeypatch.setattr(upload.Path, "resolve", ...)         # acquitted
```

The second one acquitted because the resolution asked only whether the offending segment was in
`sys.stdlib_module_names`. A stdlib *module* announces itself that way; a stdlib *class* does
not. **A branch could turn the row green one character at a time without changing anything.**

The target is now judged by what it IS. When the segment that leaves the product is not itself a
module name, it is looked up in the **product module's own imports**: `upload.py` says
`from pathlib import Path`, so `upload.Path` is `pathlib.Path`. A class the module *defines* has
no import and stays acquitted — `agent.py` both imports `Path` and defines `TranscriptScanner`,
and the same rule gives opposite verdicts on the two names in that one file.

A **relative** import is part of the same answer. `from ..json import json_handler` has
`node.module == "json"`, which read as stdlib `json` and convicted 4 lines in @backup on the
first run of the fix. Relative imports keep their leading dots now, so their root is empty —
neither aipass nor stdlib — and a sibling package can never be mistaken for the library it
shares a name with.

| | files | hits |
|---|---|---|
| before, module names only | 152 | 905 |
| **after, the class resolved through imports** | **159** | **1,002** |

**97 acquittals were this shape**, every one of them `pathlib.Path`, spread over 19 files, 7 of
which scored 100 the day before.

---

## What it refuses to judge

Targets bound to a local name by assignment rather than an import:

```python
mod = importlib.import_module("aipass.x.y")
patch.object(mod.os, "stat", ...)            # what is `mod`? the AST cannot say
```

The rule says nothing and counts them in the passing message. **That set is larger than
everything it convicts** — the honest edge of a resolution-based rule.

---

## Fleet standing on arrival

Measured 2026-09-22 over 565 test files. **155 files, 916 hits, 5.5s.**
Re-measured 2026-09-23 over 572, after the fifth cut: **159 files, 1,002 hits, 9.2s.**

`test_ceiling_guard.py:103` convicts as `ceiling.os.path` → `os`, which is the evidence line.

---

## Why it cannot be satisfied by accident

A patched stdlib name is replaced for the whole process, so the test pins the product's
*spelling* rather than its behaviour. Change the spelling without changing the behaviour and
the test stops testing anything, silently. **There is no threshold and nothing to tune.**

---

## Known limits

**Locally-bound targets are unjudged**, as above, and they are the majority.

**Third-party packages are not convicted.** Only `sys.stdlib_module_names` is consulted; a
`requests` or `pathspec` target reads as unresolvable rather than scored.

**`patch.dict` and `patch.multiple`** are not read — only `patch`, `patch.object` and
`monkeypatch.setattr` carry one readable target.

---

## Provenance

Crack class Q of the owner's 2026-09-22 ruling, built on @devpulse's dispatch f66ac9d0
(DPLAN-0354). The brief is `dropbox/test_review_cracks_brief_2026-09-22.md`.
