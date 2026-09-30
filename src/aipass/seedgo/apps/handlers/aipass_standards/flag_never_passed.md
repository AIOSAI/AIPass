# Flag Never Passed Standards
**Status:** v1
**Date:** 2026-09-22

---

## What It Is

Crack class **P** from the 2026-09-22 eyes-on review of @backup's tests. The product's
`handle_command` parses a `--flag` out of `args` and no test in the branch ever passes that
flag to it.

The flag's branch is unpinned. Delete the parse, hardcode the default, and the suite stays
green.

---

## The shape, from `share.py:129`

```python
public = "--public" in args
run_share(file_path, public=public)
```

`public = False` survives all 21 share tests. The only places `--public` appears under
`backup/tests/`:

```python
assert "drone @backup share <file_path> [--public]" in printed   # a help substring
for flag in ("--name", "--quiet", "--force", "--project", "--note", "--public"):  # iterated
```

Neither hands it to the parser.

---

## What counts as passing it

The literal must reach an **argument of some call**:

```python
handle_command("share", ["--public"])                    # the direct form
handle_create([target, "--dry-run"])                     # a sub-handler — how @spawn does it
monkeypatch.setattr(sys, "argv", [...]); main()          # the argv form
@pytest.mark.parametrize("args", [["--force"], ...])     # an argvalue handed over
```

A tuple that is only **iterated** is not an argument. That is exactly what keeps @backup's
help sweep from acquitting the very flags it names.

### An argv carrying `--help` or `-h` exercises nothing else in that row

The product itself says so:

```python
if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
    print_help()
    return True
```

So `["drive_clear", root, "--force", "--help"]` pins `--help` and leaves `--force` exactly
as unpinned as before. Without this rule the sweep acquitted three of the five flags the
reviewers named.

---

## Three cuts, and the middle one is the instructive failure

| cut | files | hits |
|---|---|---|
| the flag appears as ANY string under `tests/` | 7 | 9 |
| the literal must reach a `handle_command` call | 38 | 82 |
| **any call argument, minus the `--help` rows** | **27** | **43** |

The middle cut convicted **all 20** of @spawn's flags, because @spawn tests its
sub-handlers (`handle_create`) and never names `handle_command`. A rule that reads one
function name mistakes a different spelling for an absent test.

**Is P near its final size?** No. The review's first cut of 7 files / 8 hits is the
*loosest* reading — it reproduces here at 7 / 9. The dispatch's own stricter wording, that
a test must pass the literal to the parser, is five times larger.

---

## Fleet standing on arrival

Measured 2026-09-22. **27 files, 43 hits, 8.7s**, nine branches.

| branch | flags |
|---|---|
| aipass | 14 |
| spawn | 10 |
| backup | 5 |
| seedgo | 4 |
| devpulse | 3 |
| drone | 3 |

@backup's five are the evidence list exactly: `--force` (`drive_clear.py:96`), `--note` and
`--project` (`drive_sync.py` 248, 250), `--name` (`register.py:94`), `--public`
(`share.py:129`). `--quiet` and `--version` from the cli_routing gap list are **not**
@backup's — nothing under `backup/apps/` parses them.

@seedgo's four (`--json`, `--no-mail`, `--prototype`, `--top`) are mine to cure.

---

## The judgement call

A flag parsed only in a module's `__main__` block, or only in a helper that builds argv for
something else, is **not declared** and is never convicted. The declared set starts at
`handle_command` and follows only the same-file functions it calls.

The router's contract is the one the tests exercise; a `__main__`-only flag is a different
surface and belongs to whatever tests that entry point.

---

## Why it cannot be satisfied by accident

If the literal never reaches the parser in any test, the branch behind it is never taken,
and deleting the parse cannot turn the suite red. **There is no threshold and nothing to
tune.**

---

## Known limits

**Short flags are out.** `-f` collides with every single-letter string in a test file.
`--help`'s partner `-h` is read only to recognise a help row, never convicted.

**A flag built at runtime is invisible.** An f-string or a variable is not a literal.

**One delegation deep.** A parser that hands `args` to another *module* is not followed;
the declared set would need a cross-module call graph and would start guessing.

**Branch-level, not file-level.** The verdict compares a branch's `apps/` against its whole
`tests/` tree, so no single file owns it.

---

## Provenance

Crack class P of the owner's 2026-09-22 ruling on the eyes-on review of @backup's tests,
built on @devpulse's dispatch cb55cc37 (DPLAN-0354). The brief is
`dropbox/test_review_cracks_brief_2026-09-22.md`.
