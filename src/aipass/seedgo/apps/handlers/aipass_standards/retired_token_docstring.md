# Retired Token Docstring Standards
**Status:** v1
**Date:** 2026-09-25

---

## What It Is

The v4 keyword auditor (`test_quality`, removed in commit `c1e0eeed`) scored a test file by
grepping it for keyword patterns. Agents learned the grep and wrote the keywords into test
docstrings as bait. The gate is gone; the cargo stays, and it tells a reader nothing about
what the test proves.

```python
"""Test output capture -- capsys, capfd, StringIO tokens."""            # backup test_cli_routing.py
"""Second call doesn't fail -- no_overwrite, already_exists."""         # backup test_handlers_filesystem.py
```

Tests only, docstrings only: module, class and function docstrings. Comments and other string
literals are not judged.

---

## The vocabulary

The retired file's own `STANDARD_CATEGORIES` as of `c1e0eeed^`
(`docs.local/v4_test_quality_check.py.txt`), embedded verbatim: 7 category names, 28 item
names, and each item's patterns. Nothing is added. `patterns, whitelist` reads like bait and is
not v4's, so it is not convicted.

A term is **code-shaped** when it is a category or item name with an underscore; a pattern
holding one of `_ ( ) . -`; CamelCase (`StringIO`, `FileNotFoundError`, `JSONDecodeError`);
or one of `capsys capfd tmp_path rmtree makedirs mkdir`. Plain English patterns (`yield`,
`corrupt`, `malformed`, `nonexistent`, `overwrite`, `teardown`, `autouse`, `unrecognized`,
`is True`, `== False`, `autouse=True`) are how people write about tests and never count.
`cleanup` is the one item name without an underscore; it is English, so it never makes a T2.

## Two shapes

One finding per docstring, naming its line, its shape and the terms.

| shape | what | example |
|---|---|---|
| **T1** token label | a run of v4 terms (any name, or a code-shaped pattern) the docstring labels `token`/`tokens` | `creates_files, .exists() tokens` |
| **T2** bait list | two or more code-shaped terms joined only by `,` `/` `and` `or` and whitespace | `unknown_command / invalid_command` |

`print_help` and `print_introspection` are v4 items AND the fleet's own CLI contract
functions, defined by every module. Naming them is naming product: they lengthen a bait list,
never make one.

---

## Check first

Measured 2026-09-25 over the fleet's 596 test files (`.archive` and seedgo's fixtures out).

The first cut read T1 as "says token anywhere and names a v4 term". It convicted 20 files and
27 docstrings, and 11 of its 15 T1 hits were "token" in its own sense: an argv token beside
`--help` (daemon, drone, trigger, seedgo, hooks, ai_mail), a shell token beside `mkdir`, a
wrapped `tmp_path` "mid-token" (canary, spawn), api's auth tokens. So the label must follow
the run. Three T2 hits were `print_introspection and print_help` naming real functions (api
twice, seedgo `test_checkers_batch7.py`), which is why those two cannot make a list alone.

| branch | files scanned | convicted | docstrings | T1 | T2 |
|---|---|---|---|---|---|
| backup | 15 | 2 | 8 | 4 | 7 |
| api | 49 | 3 | 3 | 0 | 3 |
| commons | 23 | 1 | 1 | 0 | 1 |
| drone | 33 | 1 | 1 | 0 | 1 |
| 14 others | 476 | 0 | 0 | 0 | 0 |
| **total** | **596** | **7** | **13** | **4** | **12** |

Every one of the 13 was read, and every one is cargo: backup's keyword tails, and module
docstrings in api, commons and drone that list v4 item names as coverage ("Covers 9 items:
help_flag, short_help, ..."). The template's model file, `tests/test_readme_update.py`,
passes.

## Scoring

Scored, per file: 0 with any finding, else 100. Every hit on ONE check.

## The cure

Drop the retired v4 keywords; say what the test proves.

---

[← Back to README](../../../README.md)
