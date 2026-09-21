# Router Assert Standards
**Status:** v1
**Date:** 2026-09-20

---

## What It Is

A prohibition on one shape: a test whose *only* oracle is a command router returning `is True`.

```python
def test_handle_command_unknown_subcommand():
    """Unknown subcommand returns True (error displayed to user)."""
    result = handle_command("readme", ["bogus_subcommand"])
    assert result is True
```

The docstring names an error displayed to a user. Eight `console.print` lines fire on that path and the test reads none of them.

---

## Why It Matters

Every command router in this fleet answers `True` for "I handled it" — and "I handled it by printing an error" is one of those paths. `handle_command` in `aipass/apps/modules/doctor.py` has seven `return True` statements and a single `return False`, and the `False` is the command-name guard on line 1454. So `assert handle_command("doctor", ["--check"]) is True` cannot distinguish a clean run from fifty errors, which is precisely what the test named `test_doctor_no_errors_returns_true` claims to do.

223 units across 15 branches are in this shape.

The shape was manufactured, not stumbled into. The archived v4 `test_quality_check.py` **scored the literal string** `"is True"` as a positive signal under `tests/`, and agents writing to a CI number duly supplied it. That is why every rule from here reads *do not do this* and none reads *must contain this*.

---

## What the Checker Scans For

A test function is convicted when it has at least one `assert` and **every** one of them is `assert <router result> is True`.

| Element | Accepted |
|---|---|
| Router callees | `handle_command`, `route_command`, `main`, `handle` |
| Call form | bare (`handle_command(...)`) or attribute (`mod.handle_command(...)`) |
| Assertion form | direct (`assert handle_command(...) is True`) or via a local bound to the call |
| Operator | `is` only — `== True` is a different, weaker claim and a separate rule's job |

### What acquits a unit

- **Any other assertion.** One honest `assert` anywhere in the function and the unit is clean.
- **`is False`.** Never convicted — see below.
- **An `assert_*` or `_assert_*` helper call.** `mock`'s `assert_called_once_with` raises on its own, and so does a module-local oracle helper like aipass's `_assert_nothing_happened`. Both *are* the effect assertion this standard asks for.
- **`pytest.raises` / `pytest.warns` / `pytest.deprecated_call`.**

---

## `is False` is never convicted

```python
def test_handle_command_wrong_command_returns_false():
    assert handle_command("not_audit", []) is False
```

A decline is a whole contract. The router recognising that a command is not its own *is* the behaviour under test, and there is no effect to assert beyond the return value. 117 units fleet-wide are of this shape and all of them are legitimate. The standard will not be widened to reach them.

---

## How to fix a violation

The test's own name and docstring already say what it is for. Assert that.

| The name says | Assert |
|---|---|
| shows / displays / lists | what reached the console |
| passes X to Y | Y's call args |
| does not Z | that Z's mock was **not** called |
| writes / updates | the file read back |

```python
def test_handle_command_unknown_subcommand():
    """Unknown subcommand is named back to the user."""
    with patch.object(readme_update, "console") as con:
        assert handle_command("readme", ["bogus_subcommand"]) is True
    out = " ".join(str(c) for c in con.print.call_args_list)
    assert "bogus_subcommand" in out
```

---

## Scope, and why no score moved

`APPLIES_TO = "tests"`. The audit's corpus is `apps/` (`branch_audit._collect_py_files`), so no test file enters the scoring lane and **this standard contributes nothing to any branch's audit number**.

It convicts in the per-file `checklist` lane, which the PostToolUse hook runs on the write — so it meets an agent at the moment the shape is created, and the existing 223 are not charged to whoever runs the audit next. The standing backlog is reported once per branch through the audit's unscored info channel:

```
router_assert backlog: 51 test(s) in 10 file(s) assert only a router's True
(unscored - convicted on the next write of the file)
```

---

## Known false positive

The implicit oracle. `hooks/tests/test_wire_verify.py:366` is named `test_clean_run_does_not_exit`, and its real claim is that `handle_command` *returned* instead of calling `sys.exit` — proved by the assert being reached at all, not by what it says. There is no effect to assert, so the answer is a bypass entry with that reason written in it:

```json
{"standard": "router_assert", "file": "tests/test_wire_verify.py", "lines": [366]}
```

Hand-checked precision on a random 15-hit fleet sample: **14/15**.

---

## Provenance

Owner ruling, 2026-09-20 16:35 (the gold-seal brief) and 18:15 ("go with ur recommendations"). Built check-first per the 16:59 amendment — *"if u find a bad item u build the check first before the fix"* — so the rule landed and was measured before a single test was touched. Plan of record: DPLAN-0354.

See also: [`docs/test_gold_standard.md`](../../../docs/test_gold_standard.md) — the four weak oracles, of which this is the first to become a rule.
