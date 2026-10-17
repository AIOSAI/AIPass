# The gold standard for tests

[← README](../README.md)

What a good test is in this branch, when not to write one, and the weak oracles by name. Every specimen is a real path in this branch. The shapes a checker enforces are listed under *What is a rule*; the rest of this page is guidance.

## The one question

**What bug reddens this test?**

Name it, or do not write the test. A test that no plausible edit can fail is not a weak test, it is a zero — it costs suite time, review attention and the reader's trust, and returns nothing.

## When NOT to write a test

No pytest coverage for what a seedgo standard already covers. Four cases:

1. **A seedgo standard already enforces it on every write.** `ruff` parses every file, so a test asserting a module parses is already paid for. `encapsulation` forbids cross-branch handler imports, so `assert "spawn.apps.handlers" not in source` (`tests/test_citizen_class_resolution.py`) is the standard restated as a test.
2. **The subject is a constant.** `assert "stderr" in get_stderr_routing_standards().lower()` (`tests/test_content_functions.py`) tests a hardcoded string list about stderr.
3. **The subject is the standard library, or your own test helper.** A test asserting what `ntpath.splitdrive` returns tests CPython; a test asserting a function defined in the same test file never executes seedgo code.
4. **The rule under test fires nowhere and scores nothing.** Pinning a rule that never fires, or is wrong every time it does, pins nothing.

## What a good test looks like here

A KEEP test names a defect that actually shipped, and pins the mechanism rather than the symptom.

- `tests/test_coverage_audit_branch.py` (`_real_module_checker`) — `log_structure_check` shipped `check_branch_post(branch_path)` while the pipeline called it with `bypass_rules=`, a bare `except` ate the `TypeError`, and the audit printed `log_structure: 100` from the file lane alone. The contract tests drive **real function objects**, because a MagicMock accepts any signature and can never catch it.
- `tests/test_incremental_audit.py` (`test_bypass_edit_busts_full_rescan`) — a cache that does not notice a semantics change inside `handlers/bypass/` serves results computed under the old matching rules while CI stays green.
- `tests/test_checklist.py` (`test_each_finding_carries_a_greppable_marker`) — asserts `rendered.count("[FAIL]")` against bytes read out of a **real Rich console**, because a mock records a perfect `"[FAIL]"` that the terminal never receives.

The pattern in all three: **the oracle reads the effect, through the real seam, and a negative control keeps it from passing vacuously.**

## The four weak oracles, by name

| shape | why it is weak | specimen |
|---|---|---|
| sole `is True` on a command router — **a rule, [`router_assert`](../apps/handlers/aipass_standards/router_assert.md)** | every router returns `True`; the test passes if the command did nothing | — |
| `console.print.called` | a function printing one blank line passes | — |
| existence / `isinstance` / key-presence | restates the return type | — |
| substring of a prose constant | the word was typed into the constant by the author | `tests/test_aipass_standards.py:364` — `assert "quarantine" not in text`, vacuously green forever |

## Declaring a justified pass

A test file says "no test needed here, because X" in its declared-pass block (test template v1): a `# The declared pass` comment line followed by marker lines, read by checkers, never by a human convention:

```python
# seedgo: no-test-needed(<category>) — <one line naming what covers it instead>
```

The category names either a seedgo standard that enforces the thing (`ruff`, `documentation`) or a kind such as `constant` or `stdlib`. A line in the block that is not a well-formed marker is a `file_top` finding, so the declaration cannot become a mute button. `declared_pass_symbol_resolves` checks that every name a line cites resolves, and `declared_pass_contradiction` convicts a file that asserts what it declared untested — rows in [aipass_standards_tests_1.md](aipass_standards_tests_1.md). This mirrors `.seedgo/bypass.json`: **make the declared deviation cheap and the silent one impossible.**

## What is a rule

Two shapes from this page are aipass_standards rows. Both apply to test files only, are scored per test file in the audit, and also convict in the checklist lane on the write. The full set of test-file rows is in [aipass_standards_tests_1.md](aipass_standards_tests_1.md) and [aipass_standards_tests_2.md](aipass_standards_tests_2.md).

| rule | convicts |
|---|---|
| [`router_assert`](../apps/handlers/aipass_standards/router_assert.md) | a test whose every assertion is a router returning `is True` |
| [`oversize_test_file`](../apps/handlers/aipass_standards/oversize_test_file.md) | a test file over 1,500 code lines, payload excluded |

## Rules are prohibitions, never requirements

A rule that REWARDS a shape gets the shape written. The archived v4 `test_quality_check.py` scored literal strings under `tests/` — `"return_bool": ["is True", "is False"]`, `"output_capture": ["capsys", "capfd", "StringIO"]` — and agents supplied the strings, which is how sole-return-flag tests get manufactured.

So every rule reads "do not do this", and none reads "must contain this". For the same reason `architecture_check.py` demands no scaffold test files: a scored rule requiring `tests/test_scaffold.py` is pressure to write tests for the sake of it.
