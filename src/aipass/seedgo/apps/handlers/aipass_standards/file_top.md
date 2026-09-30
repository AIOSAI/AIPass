# Test File Top Standards
**Status:** v1
**Date:** 2026-09-22 (banner ruling 2026-09-27)

---

## What It Is

Test template v1, **items 5, 6 and 7** — the top of a test file, in order:

```python
# =================== AIPass ====================
# Name: test_readme_update.py
# Description: Template v1 model — readme_update module, readme_generator and readme_ops
# Version: 2.2.0
# Created: 2026-09-20
# Modified: 2026-09-21
# =============================================

"""Tests for apps/modules/readme_update.py and the handlers it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in handlers/readme/ parses and imports
# seedgo: no-test-needed(constant) — SECTION_NAMES' display strings and MARKER_PREFIX's text
```

They are one shape, not three, so they are one checker with three sub-rules — the way `imports` carries six. The **order** is half the rule: the template's own heading is "File shape, top to bottom", so a docstring above the header is convicted even though the header is present.

---

## Check first: nothing is charged twice

| standard | scope | why it does not reach this |
|---|---|---|
| `meta` | `APPLIES_TO = "production"` | validates exactly this block, and never sees `tests/` |
| `documentation` | `APPLIES_TO = "production"` | docstrings, same blind spot |
| `template` | `branch_level`, **advisory** | reads the branch prompt, README and passport for un-configured stub markers — nothing to do with a file's top |

Items 5 to 7 had no checker at all.

---

## The three messages

Each sub-rule says its own thing, so an author knows which of the three is missing. All three live in **one** check message, because `checklist._format_failure` prints the first failed check and appends "(+N more)" — three checks would show one and hide two.

```
test_thing.py: item 5 META header: the file opens with code — the header block comes first
test_thing.py: item 6 subject docstring: missing — one line naming the module this file tests
test_thing.py: item 7 declared pass: missing — what is NOT tested here, and what covers it
see templates/test_template_v1.md items 5 to 7, and tests/test_readme_update.py
```

| sub-rule | what it says |
|---|---|
| item 5 | `the file opens with code` / `with a docstring` / `with a shebang` — the header block comes first |
| item 5 | ``the banner line is `# ===================AIPASS====================`, not `# =================== AIPass ====================` `` |
| item 5 | `missing Description, Created, Modified` |
| item 6 | `missing` — one line naming the module this file tests |
| item 6 | `3 lines, not 1` |
| item 6 | `names no path` — say which module it tests, as a path |
| item 7 | `missing` — what is NOT tested here, and what covers it |
| item 7 | `line N is not a seedgo: no-test-needed(...) marker` |
| item 7 | `the block is above the docstring` |

---

## The banner is meta_check's rule, imported, not copied

The template once said *"for a test file the banner word is `META`"*, while `meta_check` called `META` the **legacy** spelling and `AIPass` the canonical one. Measured over 579 fleet test files on 2026-09-22:

| first line | files |
|---|---|
| `# =================== AIPass ====================` | 345 |
| `# ===================AIPASS====================` | 72 |
| `# =================== META ====================` | 22 |
| a shebang, a docstring, or code | 140 |

**The owner's ruling, 2026-09-27: `AIPass` is the banner word for product and test files alike.** So a test file's banner passes exactly when `meta_check` would pass it on a product file: its `META_HEADER` (`AIPass`) or its `META_HEADER_LEGACY` (`META`), the whole line, stripped. The checker imports those two constants; there is one banner rule in the pack, and if `meta_check` ever retires the legacy line this rule follows it. The 22 `META` files pass as legacy, the same as a product file would; no banner is rewritten fleet-wide for this. The 72 squashed `AIPASS` lines are refused by `meta_check`'s exact line, so they are refused here, and the message prints the line wanted.

The **fields** are `meta_check`'s five — Name, Description, Version, Created, Modified — because item 5 says "the same block product files carry", and that is the block they carry.

---

## conftest.py is judged on item 5 only

Decided from the template's text, not by taste. The numbered items live under the heading "File shape, top to bottom"; the template's conftest section (C1 to C4) is about which **fixtures** belong there and never speaks about a header, a docstring or a declared pass.

- **Item 6** asks for "one line naming the **subject** as a path". A conftest has no subject: it is shared setup, not a test of anything.
- **Item 7** asks what is NOT tested **here**. A file that contains no tests has nothing to answer.
- **Item 5** has no such problem. A conftest is a Python file, and every Python file in the fleet carries the block.

21 conftests are in the corpus; 7 already open with a header.

---

## Fleet standing on arrival

Measured 2026-09-22 over 579 test files, before the rule landed:

| | files | share |
|---|---|---|
| META block first | 367 | 63% |
| …of which the banner word is `META` | 22 | 4% |
| a module docstring at all | 562 | 97% |
| exactly one line | 223 | 39% |
| a declared-pass block | 7 | 1% |

**573 of 580 files are convicted.** The seven that are clean are all seedgo's: `test_readme_update.py` (the model), `test_tests_lane.py`, and the five gold-seal checker test files — `test_import_site_check.py`, `test_through_the_command_check.py`, `test_named_encoding_check.py`, `test_literal_path_check.py` and `test_file_top_check.py`. Four of those five were one `Modified:` line short when the rule first ran and were cured the same day.

Which sub-rules fire together:

| combination | files |
|---|---|
| items 5 + 6 + 7 | 494 |
| items 5 + 7 | 42 |
| item 5 alone | 25 |
| items 6 + 7 | 15 |
| item 6 alone | 1 |

The declared pass is the item with no fleet habit at all — and the template says why it matters: *"In the trial this slot is where six tests got dropped: writing it does the deciding."*

Two branches were audited for real on the day it landed:

| branch | overall before | overall after | `file_top` |
|---|---|---|---|
| memory | 96% | 94% | 0% |
| aipass | 95% | 94% | 0% |

---

## Known limits

**A file Python cannot parse yields no findings.** `ruff` already convicts the syntax error, and naming a missing docstring in a file that does not parse sends its author to the wrong place.

**The declared-pass block may hold no markers.** A file with nothing to declare still says so: the block must exist, not be full. A comment inside it that is not a marker is named by line — the block is a roster, not a scratchpad.

**A shebang above the header is still convicted.** 16 fleet files open with `#!/usr/bin/env python3`; this rule reads the first non-blank line, so they fail item 5. The message names the shebang rather than calling it code, because an author told "the file opens with code" would go looking for an import. Whether a shebang may precede the header is the template's to say, and it does not say.

**A docstring above the header needs no order rule.** `_header_span` reads the first non-blank line, so a header pushed below anything is not a header that is first — item 5 already convicts it. A mutant that disabled a separate order check for exactly this survived the suite, which is how the dead branch was found and removed.

---

## Provenance

`templates/test_template_v1.md` items 5, 6 and 7, built 2026-09-22 on @devpulse's dispatch d3685bc1 (DPLAN-0354). Seventh checker in the per-item series, after `router_assert`, `oversize_test_file`, `import_site`, `through_the_command`, `named_encoding` and `literal_path`. The model file defines the shape; the checker follows it.
