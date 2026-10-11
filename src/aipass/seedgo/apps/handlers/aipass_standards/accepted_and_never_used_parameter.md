# Accepted And Never Used Parameter Standards
**Status:** v1
**Date:** 2026-09-23

---

## What It Is

A product function accepts a parameter and no path in its body ever reads it. The caller
computes a value, hands it over, and it goes nowhere.

`APPLIES_TO: production` · `AUDIT_SCOPE: all_files` · scored per file, 0 or 100.

---

## The specimen

`backup/apps/handlers/cleanup/mirror.py:92`:

```python
def cleanup_deleted_files(backup_path, source_dir, should_ignore, result, dry_run=False):
    """...
    should_ignore: Callable(Path) -> bool for ignore check.
    """
```

`should_ignore` is documented, accepted, and never called. At the other end,
`copy/snapshot.py:93` builds `lambda p: _should_ignore_for_cleanup(p, project_root, spec)`
to pass in.

**Those are not two defects, they are one.** The caller builds a predicate, the callee drops
it, and the mirror cleanup ignores nothing. The verdict lands on the **accepting** side,
because that is where the cure lives. The call site scores 100.

---

## What it is not

Not tidiness. A dropped parameter is a promise in the signature that the body does not keep,
so every caller reasons about behaviour that never happens. The docstring above is the proof
— it describes a contract the function never honours.

---

## How you tell a protocol

A signature is only the product's to change if the product is the one calling it. Four shapes
are acquitted, and all four say *somebody else owns this shape*.

| shape | example | why |
|---|---|---|
| **The branch never calls it** | `pytest_runtest_logfinish(nodeid, location)` | pytest's hookspec fixed it; `handle_stop(hook_data)` is dispatched by the bridge under its name |
| **The name is handed off as a value** | `signal.signal(SIGINT, signal_handler)` | the consumer fixed the arity |
| **It is a fallback for a failed import** | `except ImportError:` → `def should_dispatch(fingerprint): return True` | the shim must match the real module |
| **The name is defined more than once** | two `def render(...)` in one branch | a shared shape with two implementations |

The first one draws the boundary with `unused_function`: whether a function nobody calls
should exist **at all** is that rule's verdict, not this one's. This rule only ever judges a
signature the branch itself is calling.

### An import is not a hand-off

A bare mention — the name appearing without `(` after it — is how the rule spots a function
passed to something else. An `import` line is a bare mention too, and counting it as one
**acquitted the mirror.py specimen this rule exists for**. Imports are subtracted: importing
a name only makes it callable.

---

## Ordinary exemptions

`self` and `cls` · `*args` and `**kwargs` (not named parameters — a body that ignores them
forwards a shape rather than dropping a value) · dunders · a decorated function (the decorator
may read the signature) · a stub body (`pass`, `...`, `raise NotImplementedError`) · any
parameter whose name starts with `_`, which is Python's own way of writing "accepted and
deliberately ignored".

---

## The corpus is code, not prose

Strings and comments are blanked with the tokenizer before the branch is counted, the same
way `unused_function` prepares its corpus, and for the same reason.

This is not housekeeping. **This checker's own docstring** names
`pytest_runtest_logfinish(nodeid, location)`, and that one sentence made the branch look like
it called pytest's hook — which convicted both of its parameters. A name written in prose is
not the branch calling it.

---

## Reading, precisely

`ast.Name` is the whole test. A first cut also collected `ast.keyword.arg`, on the theory that
forwarding by keyword counts as reading — but `inner.arg` is the **callee's** parameter name,
not this function's, so `helper(should_ignore=other)` would have cleared a `should_ignore`
this body never touched. Forwarding the real value is already an `ast.Name` on the right-hand
side, so nothing was lost. A mutant that deleted the keyword branch survived the whole file,
which is how it was found.

---

## Fleet standing on arrival

Measured 2026-09-23 over **1,203 product files in 18 branches**.

**38 files, 49 hits, 10.4s.** 2,841 parameters acquitted by a shape above.

| branch | hits |
|---|---|
| commons | 10 |
| seedgo | 10 |
| ai_mail · hooks | 6 each |
| aipass | 5 |
| prax | 4 |
| daemon · trigger | 2 each |
| api · backup · drone · memory | 1 each |

The review's first cut said 83 files and 157 hits. This is 38 and 49, and the gap is the
protocol shapes above, not tuning — every acquittal names the mechanism that owns the
signature instead.

---

## Why it cannot be satisfied by accident

Reading the parameter once anywhere in the body clears it, and that reading is the whole
point. There is no threshold and nothing to tune.

---

## Scoring

Scored, per file. 100 when every parameter is read, 0 on any hit. Every hit names the line,
the function and the parameter, on **one** check — `checklist._format_failure` prints the
first failed check and appends `(+N more)`, so one check per parameter would show the first
and hide the rest behind a count.

---

## The cure

**read the parameter, forward it, or drop it from the signature**

---

## Provenance

Crack class M of the owner's 2026-09-22 ruling on the eyes-on review of @backup's tests,
built on @devpulse's dispatch a752532e (DPLAN-0354). Specimens held untouched by @backup:
`cleanup/mirror.py:95` and its call site `copy/snapshot.py:93`.
