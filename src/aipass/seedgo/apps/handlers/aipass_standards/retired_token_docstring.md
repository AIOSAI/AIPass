# Retired Token Docstring Standards
**Status:** v1.1
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

The retired file's own `STANDARD_CATEGORIES`
(`apps/handlers/aipass_standards/test_quality_check.py`) from two commits, embedded verbatim
as their union: 10 category names, 48 item names, and each item's patterns.

| source | what it carries | in the checker |
|---|---|---|
| `c1e0eeed^` — the commit that removed the file (`docs.local/v4_test_quality_check.py.txt`) | 7 categories, 28 items | `V4_CATEGORIES` |
| `7cd59aa4^` — the parent of DPLAN-0325 part B, 2026-09-03, which retired 20 items (`docs.local/v4_test_quality_check_7cd59aa4parent.py.txt`) | the 20 items only it carries: whole categories `json_handler` (8), `exception_contracts` (3), `data_structure_contracts` (3); plus `mock_json_handler`, `ensure_returns_bool`, `load_correct_type`, `returns_dict`, `sys_modules_mock`, `reimport_after_mock` | `V4_RETIRED_EARLIER` |

Every other item at `7cd59aa4^` has the same patterns or a subset (`empty_file` gained
`test_empty`, `command_returns_bool` gained `, bool)` later), so the union is the two merged.
Nothing is added. `patterns, whitelist` reads like bait and is not v4's, so it is not convicted.

A term is **code-shaped** when it is a category or item name with an underscore; a pattern
holding one of `_ ( ) . -`; CamelCase (`StringIO`, `FileNotFoundError`, `ValueError`);
or one of `capsys capfd tmp_path rmtree makedirs mkdir`. Plain English patterns (`yield`,
`corrupt`, `malformed`, `nonexistent`, `overwrite`, `teardown`, `autouse`, `unrecognized`,
`operation`, `is True`, `== False`, `autouse=True`) are how people write about tests and never
count. Four item names have no underscore — `cleanup`, `load`, `save`, `validate` — and are
English: they never make a T2, and a T1 run needs a code-shaped term besides them ("validate
tokens" is about auth, not v4).

Code quoted in backticks is emptied before judging: `` ``save_json(module_name, json_type, data)`` ``
is a real signature, not a keyword list, and no run crosses a quoted span.

## Two shapes

One finding per docstring, naming its line, its shape and the terms.

| shape | what | example |
|---|---|---|
| **T1** token label | a run of v4 terms (any name, or a code-shaped pattern; one code-shaped) the docstring labels `token`/`tokens` | `returns_dict, isinstance(result, dict), json_type tokens` |
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

## Check again: the 7cd59aa4^ items

Measured 2026-09-25 over 598 test files, after backup had cured its 8 docstrings live (its
`returns_dict, isinstance(result, dict), json_type tokens` class docstring, line 183 at
`7cbe39e5`, is gone from disk).

| branch | files scanned | before (c1e0eeed^): files / docstrings | after (union): files / docstrings |
|---|---|---|---|
| api | 49 | 3 / 3 | 3 / 3 (`test_init_provisioning.py:9` now also names `returns_dict`) |
| commons | 23 | 1 / 1 | 1 / 1 |
| drone | 33 | 1 / 1 | 1 / 1 |
| memory | 45 | 0 / 0 | 1 / 2 |
| aipass | 30 | 0 / 0 | 1 / 1 |
| 13 others | 418 | 0 / 0 | 0 / 0 |
| **total** | **598** | **5 / 5** | **7 / 8** |

The new hits, read one by one:

- `memory/tests/test_contracts.py:10` — the module docstring lists `_create_default / ValueError`
  and `invalid_mode / invalid_type` as the "Exception contracts (3 items)". Cargo.
- `memory/tests/test_contracts.py:75` — "reject data with an invalid_type or invalid_mode"; the
  test raises its own `ValueError` inside `pytest.raises`. Cargo.
- `aipass/tests/conftest.py:107` — "suppress log_operation and ensure_module_jsons side
  effects", naming the two functions its `mock_json_handler` fixture patches. A false
  positive, left standing: quoting the names in backticks cures it.

Two more in `seedgo/tests/test_json_handler_contract.py` (lines 358 and 1802) were the
calling convention `` ``(module_name, json_type)`` `` in backticks, a real signature: the quoted
code rule clears them and changes none of the other hits.

## Scoring

Scored, per file: 0 with any finding, else 100. Every hit on ONE check.

## The cure

Drop the retired v4 keywords; say what the test proves.

---

[← Back to README](../../../README.md)
