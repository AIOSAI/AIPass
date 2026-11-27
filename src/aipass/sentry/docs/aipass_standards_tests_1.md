[<- Back to the README](../README.md)

# aipass_standards — the test-file rows, calendar_bound to literal_path

The first half of the pack's `tests` rows. They live on their own page because
[aipass_standards.md](aipass_standards.md) and these rows together exceed the docs-page size cap.
The columns read as the main page's
[How to read the table](aipass_standards.md#how-to-read-the-table) says; the second half is
[aipass_standards_tests_2.md](aipass_standards_tests_2.md).

---

## The rows

These rows are the `tests` group of the audit grid (`groups.py`).

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| calendar_bound | branch_level | tests | A test that asserts a date literal against code that computes with the clock, and does not own the clock — true only while the calendar agrees (corpus: tests/ and lib/*/tests/) |
| conftest_fixtures *(tests only)* | all_files | tests | A branch's `tests/conftest.py` carries both fixtures: **C1** a session-scope autouse fixture pinning `.width` on the product's consoles, **C2** an autouse fixture calling `display.reset_command_state()` after the yield. Only `conftest.py` is judged |
| constant_predicate *(tests only)* | all_files | tests | A lambda handed to the product as a call argument whose body is a constant bool (`should_ignore=lambda p: False`): it cannot discriminate. `lambda *a: None` and value-returning lambdas are counted, not charged |
| declared_pass_contradiction *(tests only)* | all_files | tests | A declared pass (`# sentry: no-test-needed(X)`) the same file breaks: **H1** a declared-untested constant whose literal value the file asserts; **H2** a declared symbol found nowhere in the branch's `apps/` source text |
| declared_pass_symbol_resolves *(tests only)* | all_files | tests | Every name in a `no-test-needed` line resolves, in `apps/` source text or, on a `(stdlib)` line, to a stdlib chain the product uses. A line naming nothing is a finding unless its category is a pack standard |
| discarded_patch *(tests only)* | all_files | tests | A mock of the branch's own code that nothing observes: an unbound or unreferenced `patch`, an unused `@patch` parameter, an anonymous `monkeypatch.setattr` replacement. Cross-branch seals and conftest patches are acquitted |
| duplicate_test *(tests only)* | all_files | tests | A test another test in the same file already covers: **B1 clone** (the same statements, docstring dropped) or **B2 subsumed** (Y adds only asserts or call-free bindings). The first by line is the original |
| flag_never_passed *(tests only)* | branch_level | tests | A `--flag` the branch's parser reads (from `handle_command` and the same-file functions it calls) that no test passes as a call argument; an argv carrying `--help` exercises nothing else |
| host_coupled_oracle | branch_level | tests | A test hands `os.getpid()`/`os.getppid()` to a callee named for the command line; pytest-xdist retitles every worker, so the oracle holds only on the writing host (corpus: tests/ and lib/*/tests/) |
| import_site *(tests only)* | all_files | tests | A product import inside a function, or a `sys.modules` stub naming an aipass module — test template v1 item 8. Module-level imports and third-party imports inside a function are never convicted. Scored per test file; also convicts in the checklist lane on the write |
| file_top *(tests only)* | all_files | tests | The top of a test file in order (template items 5, 6, 7): the META header block, a one-line docstring naming the subject as a path, then the declared pass. `conftest.py` is judged on item 5 only |
| literal_path *(tests only)* | all_files | tests | An absolute path literal handed to a call in a test (template item 22). Data (mock returns, routes, dict keys, oracles), system roots, pure path classes and home-rooted paths are never convicted |

---

## Related

- [aipass_standards.md](aipass_standards.md) — the pack, its production rows, and how a rule is added
- [aipass_standards_tests_2.md](aipass_standards_tests_2.md) — the test-file rows, mock_console to weak_oracle
