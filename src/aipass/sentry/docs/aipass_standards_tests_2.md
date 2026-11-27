[<- Back to the README](../README.md)

# aipass_standards — the test-file rows, mock_console to weak_oracle

The second half of the pack's `tests` rows. They live on their own page because
[aipass_standards.md](aipass_standards.md) and these rows together exceed the docs-page size cap.
The columns read as the main page's
[How to read the table](aipass_standards.md#how-to-read-the-table) says; the first half is
[aipass_standards_tests_1.md](aipass_standards_tests_1.md).

---

## The rows

These rows are the `tests` group of the audit grid (`groups.py`).

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| mock_console *(tests only)* | all_files | tests | A console stand-in (a Mock, a `Console(file=buf)`, a fake with `print`) installed over the product or handed to it (template item 14). `capsys`, a product-built console and a restore are never convicted |
| named_encoding *(tests only)* | all_files | tests | A text read or write with no encoding named — `open()` in a text mode, `read_text()`, `write_text()` — test template v1 item 21. Binary modes, a positional encoding, and a deliberate non-utf-8 encoding are never convicted. Also convicts in the checklist lane on the write |
| no_product_call *(tests only)* | all_files | tests | A `def test_*` that reaches no aipass code through its body, decorators, same-file helpers or fixtures: a library test. Calls into the file's own apparatus and methods of a reaching class are acquitted |
| oversize_test_file *(tests only)* | all_files | tests | A test file over 1,500 CODE lines — multi-line string payload, docstrings included, is subtracted first. Scored per test file; also convicts in the checklist lane on the write |
| rendered_path_oracle *(tests only; ADVISORY)* | all_files | tests | A whole tmp path, spelled in an f-string, asserted against console-rendered output: Rich wraps it at the console width and `%r` escapes it. `{path.name}` is the cure. Advisory: kept out of the gating average |
| retired_token_docstring *(tests only)* | all_files | tests | Cargo from the retired v4 keyword auditor (`test_quality`) in a test docstring: a run of its terms followed by `token(s)`, or a run of 2+ code-shaped terms; backticked code is not judged |
| router_assert *(tests only)* | all_files | tests | A test whose every assertion is a command router returning `is True` — `is False` is never convicted. Scored per test file; also convicts in the checklist lane on the write |
| self_set_assert *(tests only)* | all_files | tests | A test that writes a value and asserts it back with `==` against the same literal, nothing run in between (constructor kwargs included): it passes with the product deleted. A call in between is counted, not charged |
| sleep_in_test *(tests only)* | all_files | tests | `sleep` inside a test (template item 23), matched by the call's tail name: `os.utime` sets an mtime exactly, and a deadline poll on the real condition replaces a wait |
| stale_header_date *(tests only)* | all_files | tests | A `# Modified:` date older than the file's last commit (an uncommitted file is judged as of today). The first checker to READ GIT, read-only; it DECLINES (not applicable, out of the average) with no git, no work tree or a shallow clone — CI's audit job keeps `fetch-depth: 0` |
| state_leak *(tests only)* | all_files | tests | A test-time write to shared state with nothing to put it back (template item 18): `os.environ`, `sys.path`, `sys.modules`, a product module attribute, an unstopped patcher, `os.chdir`, a product write its own `reset*` undoes |
| stdlib_patch *(tests only)* | all_files | tests | A `patch`, `patch.object` or `monkeypatch.setattr` whose target, resolved through the file's own imports, is a stdlib module rather than aipass: it pins the product's spelling. Process edges and interpreter tables are acquitted |
| subprocess_text_true *(tests only)* | all_files | tests | A `subprocess` call with literal `text=True` or `universal_newlines=True` and no `encoding=` — the locale codec decodes the output: `named_encoding`'s hazard one pipe over. `encoding=None` still convicts; `errors=` alone does not cure |
| through_the_command *(tests only)* | all_files | tests | A test importing an underscore name from a product module, or reaching one on a base it imported — test template v1 item 10. Dunders, the test's own helpers, reads on returned values, and WRITES (item 15's shape) are never convicted. Also convicts in the checklist lane on the write |
| uncalled_public_function *(tests only)* | branch_level | tests | A public function of a test file's declared subject module that no test calls: **O1** named only as a patch target, **O2** named nowhere. A function the product reaches from tested code is acquitted |
| unconsumed_side_effect *(tests only)* | all_files | tests | `mock.side_effect = [more than one answer]` in a test that never claims the call count: an unconsumed answer's branch is deletable with the suite green. The cure is `assert mock.call_count == N` |
| unused_conftest_fixture *(tests only)* | branch_level | tests | A non-autouse fixture in a branch's `conftest.py` that nothing in its `tests/` tree requests, as a parameter on a test or fixture or as any string literal |
| weak_oracle *(tests only)* | all_files | tests | A test whose whole oracle cannot fail: `assert <constant>`, a bare name's truthiness, `is not None` or `isinstance` alone, an argument-free `assert_called`, `assert f() is None` on a `-> None` function |

---

## Related

- [aipass_standards.md](aipass_standards.md) — the pack, its production rows, and how a rule is added
- [aipass_standards_tests_1.md](aipass_standards_tests_1.md) — the test-file rows, calendar_bound to literal_path
