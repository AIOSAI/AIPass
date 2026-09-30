# Declared Pass Contradiction Standards
**Status:** v1
**Date:** 2026-09-23

---

## What It Is

Crack class **H**, and test template v1 item 4. A test file's declared pass — the
`# seedgo: no-test-needed(X) — prose` block — is a promise about what this file does NOT
cover. The promise is worth exactly as much as its accuracy, and two ways of breaking it
are mechanical.

---

## H1 — the declaration is contradicted

The file says a constant's value needs no test, and then asserts that value as a literal.

```python
# seedgo: no-test-needed(constant) — BACKUP_FOLDER_NAME, FOLDER_MIME and TRACKER_FILENAME's strings
...
assert tracker_path.name == "drive_tracker.json"    # pins exactly what was declared untested
```

## H2 — the declaration names nothing

```python
# seedgo: no-test-needed(constant) — DEFAULT_MAX_FILES and DEFAULT_MAX_SIZE_GB constant values
```

The constant is `DEFAULT_MAX_TOTAL_GB`. A promise about a symbol that does not exist covers
nothing at all, and the real constant stays uncovered behind it.

### The cure is not always "repoint it"

@backup cured its H2 convictions on 2026-09-23 and **dropped** two of the lines rather than
correcting the name. `DRIVE_PKG` and `PROBE_MODULES` are constants of the *test file itself* —
fixtures' own scaffolding, with no product counterpart anywhere in `apps/`. There is nothing to
repoint them at, because the declaration was never about the product in the first place. A
declared pass is a promise about what the *product* does not need covered; a line naming the
test's own furniture makes no such promise and belongs deleted.

Repoint when the symbol was a typo for a real one. Drop when the symbol was never the
product's.

---

## The judgement this rule makes

USING a declared constant BY NAME is consistent with declaring it untested. `assert CURE in
message` survives any change to `CURE`'s text — it pins the wiring, not the prose. ASSERTING
ITS VALUE as a literal does not. So the rule reads the constant's value out of the branch's
`apps/` and looks for that literal inside an assert in a test body. A bare mention of the
name is never convicted.

## Search the source text for an absent name, not the AST's names

A declared symbol can be an environment variable (a string, never an identifier), an
annotated dataclass field, or a directory segment inside a path. Collecting
`def`/`class`/`Name`/`Attribute` nodes missed all three and convicted **86** live symbols; a
word-boundary search of `apps/` leaves **3**, and all three are real.

---

## Check first

Measured 2026-09-23 over the fleet's 572 test files.

| | |
|---|---|
| files carrying a declared pass at all | 37 (137 lines) |
| files scored | 7 |
| hits scored | 8 — 5 contradicted constants, 3 absent names |

### Reported with a count, charged to nobody

| shape | count | why it is not scored |
|---|---|---|
| lines that name no symbol | 39 | prose is a legitimate declaration — since 2026-09-25 `declared_pass_symbol_resolves` scores one whose category is not a pack standard |
| dotted stdlib names (`Path.resolve`, `os.scandir`) | 67 | a test's incidental use of the call is indistinguishable from testing it |
| declared libraries whose call feeds an assert | 3 | `no_product_call` already convicts `test_ignore_pathspec.py:46`, the one case where the library really is the subject; the other two files score 100 there, which proves their library call is the test's reading tool |

---

## Why it cannot be satisfied by accident

Both scored forms are contradictions between two statements in the same file. There is no
threshold and nothing to tune.

## Scoring

Scored, per file. Every hit names the declared line, the symbol and what is wrong, on ONE
check — `checklist._format_failure` prints the first failed check and hides the rest.

## The cure

Assert the constant by name, or drop the line that declares it untested. Name the symbol
that exists, or drop the line.

---

[← Back to README](../../../README.md)
