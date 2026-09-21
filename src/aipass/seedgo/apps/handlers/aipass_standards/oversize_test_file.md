# Oversize Test File Standards
**Status:** v1
**Date:** 2026-09-20

---

## What It Is

A cap of **1,500 code lines** on a single test file. Fixture payload is subtracted before the cap applies.

```
tests/test_pytest_quality_pack.py — 4,595 code lines of 10,524
```

---

## Why It Matters

A test file is read by someone looking for one subject. Past a few thousand lines nobody reads it — they grep it, find a test that looks close, and copy it. That is the mechanism by which a weak shape spreads inside a branch, and this branch has the evidence: 258 of the 387 tests in its largest file pin rules that never fire, all of them variations on each other.

The cap is the same figure the product side already uses, so tests and modules are held to one number.

---

## Fixture payload does not count

Every line inside a multi-line string literal is subtracted — sample JSON, a captured log, a rendered README, **and docstrings**.

| file | total | payload | code | verdict |
|---|---|---|---|---|
| `seedgo/tests/test_import_dead_cwd.py` | 2,718 | 1,533 | 1,185 | passes |
| `seedgo/tests/test_checkers_batch8.py` | 1,533 | 152 | 1,381 | passes |
| `seedgo/tests/test_pytest_quality_pack.py` | 10,524 | 5,929 | 4,595 | **fails** |

Two deliberate consequences:

- Charging for payload would push authors to hide fixtures in another file rather than split anything.
- Charging for docstrings would make a size rule a reason to delete the sentence naming the bug a test pins — which the gold standard asks for by name.

The payload count uses a **set of line numbers**, not a sum of spans. An f-string holds its own nested constants, and adding each span independently double-counts shared lines; measured 2026-09-20 that gap was 26 lines on this branch's largest file. Small, but it makes the number irreproducible, and a threshold nobody can re-derive is worse than a wrong one.

---

## Why 1,500

Measured across the fleet on 2026-09-20 — 538 test files, retired paths excluded:

| statistic | code lines |
|---|---|
| median | 378 |
| 90th percentile | 1,161 |
| cap | **1,500** |
| files over cap | 34 |

The cap sits above nine files in ten. It convicts the tail, not the body, and it was not moved to make a number land.

---

## How to fix — and the gate you will meet

Split along **the unit under test**, one file per subject. Never by line count, never into `_part2`.

**The cure needs new test files, and the hooks test-write gate refuses those by policy** (`.aipass/test_write_policy.json`). This is not an oversight in the rule; it is the reason the rule's message ends where it does.

Do not route around the gate. Mail @devpulse with the file, its code-line count, and the subjects you would split it into. A split that adds no test function is moving tests, not writing them — that is the case to make.

If the file is large because it pins rules that are themselves being retired, the retire comes first and the split may not be needed at all.

---

## Scope, and why no score moved

`APPLIES_TO = "tests"`. The audit's corpus is `apps/` (`branch_audit._collect_py_files`), so no test file enters the scoring lane and **this standard contributes nothing to any branch's audit number**.

It convicts in the per-file `checklist` lane on the write that grows the file. The standing backlog is one unscored info line, which names the largest offender rather than only counting them — "3 files over the cap" gives an owner nothing to start on:

```
oversize_test_file backlog: 8 test file(s) over 1500 code lines,
largest test_pytest_quality_pack.py at 4595 (unscored - convicted on the next write of the file)
```

---

## Fleet, on arrival

34 of 538 files over the cap, across 11 branches:

`seedgo 8 · hooks 5 · ai_mail 4 · memory 3 · api 3 · prax 3 · trigger 2 · drone 2 · aipass 2 · spawn 1 · flow 1`

The five biggest by code lines:

| code | file |
|---|---|
| 4,595 | `seedgo/tests/test_pytest_quality_pack.py` |
| 3,576 | `ai_mail/tests/test_dispatch_monitor.py` |
| 3,024 | `memory/tests/test_rollover_pipeline.py` |
| 2,996 | `hooks/tests/test_edit_gate_trinity.py` |
| 2,678 | `seedgo/tests/test_trinity_check.py` |

The worst file in the fleet is this branch's own, and it is not split yet: 258 of its tests leave with their rules in phase 3, so the retire comes before the split.

---

## Bypass

```json
{"standard": "oversize_test_file", "file": "tests/test_big.py"}
```

A generated test file is the honest bypass case — nobody reads it and nobody splits it. Write the generator's name in the reason.

---

## Provenance

Owner ruling, 2026-09-20 18:15 ("go with ur recommendations"); brief `dropbox/gold_seal_rule2_size_brief_2026-09-20.md`. Built check-first: the rule was landed and measured against three real files before anything was split. Plan of record: DPLAN-0354.

See also: [`docs/test_gold_standard.md`](../../../docs/test_gold_standard.md) and [`router_assert.md`](router_assert.md), phase 2's first rule.
