# Duplicate Test Standards
**Status:** v1
**Date:** 2026-09-22

---

## What It Is

Crack class **B** from the 2026-09-22 eyes-on review of @backup's tests. A test that adds
nothing, because another test in the same file already asserts everything it asserts. It
doubles the maintenance and the runtime and it widens no net.

The reviewers found **24** across nine files — the second-largest verdict class after WEAK.

---

## The headline, first, because it reorders the brief

**Of @backup's 24 DUPLICATE rows this checker convicts two.**

The other 22 are **semantic** duplication — the same claim in a different spelling — and no
shape rule reaches them. The brief's own headline pair:

```python
# test_drive_pipeline.py:783
assert drive_sync.handle_command("drive_sync", []) is True
printed = capsys.readouterr().out
assert "drive_sync Module" in printed

# test_drive_mocked.py:49
assert drive_sync.handle_command(drive_sync.PRIMARY_COMMAND, []) is True
out, err = capsys.readouterr()
assert "drive_sync Module" in out
assert err == ""
```

A reader sees one test twice. An AST sees two different programs: a literal against a
constant, a property access against a tuple unpack, and one extra assert.

**That is the tuning answer for the owner.** B is not the second-richest class by evidence
yield. It is a cheap, zero-false-positive rule that catches the literal copies, and the
reviewers' 24 need a judgement layer this cannot be. The brief's order put B second; the
numbers put it lower than A and lower than D.

The two it **does** convict are both confirmed rows, and it invents none:

| row | reviewer's reason | shape |
|---|---|---|
| `test_cli_routing.py:250` | "identical claim to line 163" | **B2 subsumed** |
| `test_dead_cwd_imports.py:828` | "line-for-line the same assertion as 469" | **B1 clone** |

---

## Two shapes, both mechanical

**B1 CLONE** — two tests whose bodies are the same statements, docstring dropped. The name
differs and nothing else does.

**B2 SUBSUMED** — every statement of X also appears in Y, **and** the statements Y adds
beyond X are only asserts or bindings that call nothing.

```python
# 163, the original
assert hasattr(mod, "print_introspection")
assert callable(mod.print_introspection)

# 250, subsumed — Y's one extra statement is an assert
assert callable(mod.print_introspection)
```

### The restriction on Y's extras is the whole rule

Without it, this pair reads as a duplicate and both reviewers called both rows SOUND:

```python
def test_floor_applies_with_no_backupignore(self, tmp_path):
    spec = load_spec(str(tmp_path))
    assert [p for p in _TEMP_SHAPES if not is_ignored(p, spec)] == []
    assert [p for p in _KEPT_NEIGHBOURS if is_ignored(p, spec)] == []

def test_floor_applies_when_the_file_never_names_tmp(self, tmp_path):
    (tmp_path / ".backupignore").write_text("node_modules/\n*.log\n", encoding="utf-8")
    spec = load_spec(str(tmp_path))
    assert [p for p in _TEMP_SHAPES if not is_ignored(p, spec)] == []
    assert [p for p in _KEPT_NEIGHBOURS if is_ignored(p, spec)] == []
    assert is_ignored("app.log", spec) is True
```

The second adds a `write_text`. **A statement that changes the world makes it a different
precondition, not a superset** — one tests "no `.backupignore` at all", the other "a
`.backupignore` that omits tmp". A binding like `ignore = project / ".backupignore"`
changes nothing and does not break the reading. That is the line: a call, a `with`, a loop
— no. An assert or a call-free binding — yes.

| B2 form | files | hits | correct in @backup |
|---|---|---|---|
| Y's extras must be asserts or pure bindings (**ships**) | 27 | 36 | 1 of 1 |
| Y's extras unrestricted | 130 | 204 | 2 of 3 — convicts the SOUND pair |

The wide form buys 168 more hits with a false conviction rate this measurement cannot
bound. The narrow form ships and the wide number is reported.

---

## Constants are kept

`*.log` and `*.txt` are two different claims about the product. A normalisation that
blanked constants convicted **345 files with 2,415 hits** fleet-wide — it read every
two-line parametrized assertion as a copy of every other.

`ast.dump` omits `lineno` and `col_offset` unless asked, so the dump alone already ignores
line breaks, indentation and comments while every identifier and every constant survives.
An earlier cut round-tripped each statement through `unparse` and `parse` first: identical
findings, and **7.8s** of the fleet runtime.

---

## One file, not the branch

Cross-file duplication is real and measured — **21 files, 22 exact clones** fleet-wide, and
@backup's six `drive_pipeline` / `drive_mocked` pairs are the kind of thing it would name.

It is left out because the verdict would have to be reported against one of two files, and
this lane hands the checker one path at a time. It wants a branch-level lane; the number is
here so the owner can ask for one.

---

## Fleet standing on arrival

Measured 2026-09-22 over 559 test files.

| | value |
|---|---|
| convicted | **59 (11%)** |
| hits | **92** — 57 clones, 35 subsumed |
| runtime | **6.8s** |

| branch | files |
|---|---|
| api | 8 |
| seedgo | 8 |
| trigger | 6 |

Worst single file: @devpulse's `test_git_gate.py` at 6.

---

## Why it cannot be satisfied by accident

If every statement of your test already appears, verbatim, in another test in the same
file, and that other test's only additions are asserts, your test excludes no failure the
other does not already exclude. **There is no threshold and nothing to tune.**

---

## Known limits

**Semantic duplication is invisible**, and it is 22 of @backup's 24. See the headline.

**Cross-file is out**, by the one-file boundary above.

**A parametrized test is one test.** Two `@pytest.mark.parametrize` decorators with
different argvalues are different statements, so the bodies never match — correct, and it
means a genuinely duplicated parametrized pair is missed.

**A file Python cannot parse yields no findings.** `ruff` already convicts the syntax error.

---

## Provenance

Crack class B of the owner's 2026-09-22 ruling on the eyes-on review of @backup's tests,
built on @devpulse's dispatch a3ad380b (DPLAN-0354). The brief is
`dropbox/test_review_cracks_brief_2026-09-22.md`; the nine reviewer reports are in
`dropbox/test_review_reports_2026-09-22/`. The model file `tests/test_readme_update.py`
passes clean.
