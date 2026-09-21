# The gold standard for tests

[← README](../README.md)

Draft, phase 1 of the gold-seal ruling (owner, 2026-09-20 16:35). Every example is a real path:line in this branch, good and bad. Nothing here is enforced yet.

## The one question

**What bug reddens this test?**

Name it, or do not write the test. A test that no plausible edit can fail is not a weak test, it is a zero — it costs suite time, review attention and the reader's trust, and returns nothing. Of 3,387 tests classified in this branch, **739 (21.8%) cannot name one**.

## When NOT to write a test

The owner's principle: *"we dont need pytest coverage on what seedgo covers."* Four cases, each measured here.

1. **A seedgo standard already enforces it on every write.** `ruff` parses every file, so a test asserting a module parses is already paid for. `encapsulation` forbids cross-branch handler imports, so `assert "spawn.apps.handlers" not in source` (`tests/test_citizen_class_resolution.py:190`) is the standard restated as a test.
2. **The subject is a constant.** `tests/test_content_functions.py` is 38 tests, all of the shape `assert "stderr" in get_stderr_routing_standards().lower()` (`:725`). The subject is a hardcoded string list about stderr. **38 of 38 RETIRE.**
3. **The subject is the standard library, or your own test helper.** `assert ntpath.splitdrive("/tmp") == ("", "/tmp")` (`tests/test_posix_literal_nominator.py:46`) tests CPython. `tests/test_import_dead_cwd.py:1414` asserts a function defined at line 914 of the same file — **44 of its 64 tests** never execute seedgo code.
4. **The rule under test fires nowhere and scores nothing.** `tests/test_pytest_quality_pack.py` spends **258 of 387 tests (67%)** pinning rules that either never fired fleet-wide or were wrong every time they did.

## What a good test looks like here

A KEEP test names a defect that actually shipped, and pins the mechanism rather than the symptom.

- `tests/test_coverage_audit.py:2257` — `log_structure_check` shipped `check_branch_post(branch_path)` while the pipeline called it with `bypass_rules=`. Every branch raised `TypeError`, a bare `except` ate it, and every audit printed `log_structure: 100` from the file lane alone. The test drives a **real function object**, because a MagicMock accepts any signature and could never have caught it.
- `tests/test_incremental_audit.py:864` — a cache that does not notice a semantics change inside `handlers/bypass/`. That happened: 17 branches served results computed under the old matching rules while CI showed 99%.
- `tests/test_checklist.py:401` — asserts `rendered.count("[FAIL]") == 2` against bytes read out of a **real Rich console**, because the mock records a perfect `"[FAIL]"` that the terminal never receives.

The pattern in all three: **the oracle reads the effect, through the real seam, and a negative control keeps it from passing vacuously.**

## The four weak oracles, by name

| shape | why it is weak | specimen |
|---|---|---|
| sole `is True` on a command router — **now a rule, [`router_assert`](../apps/handlers/aipass_standards/router_assert.md)** | every router returns `True`; the test passes if the command did nothing | `tests/test_readme_update.py:130` — named "unknown subcommand … error displayed to user", asserted only `result is True` while 8 unasserted `console.print` lines fired. Rewritten 2026-09-20 |
| `console.print.called` | a function printing one blank line passes | `tests/test_coverage_audit.py:740` |
| existence / `isinstance` / key-presence | restates the return type | `tests/test_aipass_standards.py:56` — seven asserts, zero behaviour |
| substring of a prose constant | the word was typed into the constant by the author | `tests/test_aipass_standards.py:376` — `assert "quarantine" not in text`, vacuously green forever |

## Declaring a justified pass

Today there is **no in-code way to say "no test needed here, because X"** — the only channel is mail to @devpulse. Proposed marker, read by a checker and never by a human convention:

```python
# seedgo: no-test-needed(<standard-or-reason>) — <one line naming what covers it instead>
```

The parenthesised token must name either a seedgo standard that enforces the thing, or one of `constant`, `stdlib`, `generated`. A bare marker with no token is refused, so the declaration cannot become a mute button. This mirrors `.seedgo/bypass.json`: **make the declared deviation cheap and the silent one impossible.**

## Rules are prohibitions, never requirements

A rule that REWARDS a shape gets the shape written. The archived v4 `test_quality_check.py` scored literal strings under `tests/` — `"return_bool": ["is True", "is False"]`, `"output_capture": ["capsys", "capfd", "StringIO"]` — and agents supplied the strings at CI 100. **We caused the 224 sole-return-flag tests in this branch.**

So every rule from here reads "do not do this", and none reads "must contain this". The same argument retires `architecture_check.py:650`'s demand for scaffold test files: a scored rule requiring `tests/test_scaffold.py` is pressure to write tests for the sake of it.
