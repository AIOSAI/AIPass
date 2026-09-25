[<- Back to the README](../README.md)

# aipass_standards — the checker pack

**Branch** seedgo · **Pack** `apps/handlers/aipass_standards/` · **Verb** `drone @seedgo audit aipass [@branch]`
**Live roster** `drone @seedgo standards_query aipass_standards` — generated from the directory, never from this page.

---

## How to read the table

`Scope` is the checker's own `AUDIT_SCOPE` — where a result is REPORTED (`all_files`,
`entry_point`, `branch_level`). `Applies to` is its `APPLIES_TO` — which files are
ELIGIBLE, default `everywhere`. Two different axes; `applicability.py` is where they meet.

Both columns are read from the checker sources, not maintained by hand. The row count is
verified against `discover_checkers()` on every regeneration rather than carried forward:
the 2026-08-25 pass wrote a row count that matched by accident while the table silently
omitted `trinity`. If this table and the directory disagree, the directory is right.

**The corpus is `apps/` plus `tests/`** as of 2026-09-21 (owner ruling 21:20) — `test_*.py`
and `conftest.py`, under the same exclusions `apps/` gets. Until then it was `apps/` only,
36 of these checkers declared no `APPLIES_TO` at all, and the four written for test files
had no files to score. Every checker declares one now, and the four are real rows.
`everywhere` is still the default for a checker that forgets, because forgetting should
cost noise and never a missed bug.

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| accepted_and_never_used_parameter *(production only)* | all_files | production | A product function accepts a parameter and no path in its body reads it — crack class M from the 2026-09-22 review of @backup's tests. `cleanup_deleted_files(..., should_ignore, ...)` documents the callable and never calls it, while `copy/snapshot.py:93` builds a lambda to pass in; ONE defect, two lines, and the verdict lands on the ACCEPTING side where the cure lives. HOW A PROTOCOL IS TOLD APART, four shapes that all say somebody else owns this signature: the branch never calls the function (`pytest_runtest_logfinish` is pytest's hookspec — whether it should exist at all is `unused_function`'s verdict, not this one's); the name is handed off as a VALUE, a bare mention that is not a call, not its own `def` line and NOT an import (counting an import as a hand-off acquitted the specimen itself); the def sits inside an `except ImportError` handler, so it is a shim that must match the real module; the name is defined more than once in the branch. Ordinary exemptions: `self`/`cls`, `*args`/`**kwargs`, dunders, decorated, a stub body, and any `_`-prefixed parameter. The corpus is stripped of strings and comments with the tokenizer — this checker's own docstring names `pytest_runtest_logfinish` and that one sentence convicted both of its parameters until it was. Fleet: 38 files, 49 hits over 1,203 product files, 2,841 parameters acquitted by shape |
| architecture | all_files | production | Module/handler separation, entry point structure |
| calendar_bound | branch_level | tests | A test that asserts a date literal against code that computes with the clock, and does not own the clock — true only while the calendar agrees (corpus: tests/ and lib/*/tests/) |
| cli | all_files | production | Rich console usage, no bare print() |
| cli_flags | entry_point | production | --help, --version flag handling |
| cli_ux | entry_point | production | CLI navigation + output quality (Nav/Output scoring) |
| commented_logger | all_files | everywhere | No commented-out logger/logging calls |
| conftest_fixtures *(tests only)* | all_files | tests | A branch's `tests/conftest.py` carries item 20's two fixtures, both reported on ONE check — **C1** a session-scope autouse fixture pinning `.width` on the consoles the PRODUCT exports (`display.CONSOLE`, `display.err_console`), and **C2** an autouse fixture calling `display.reset_command_state()` AFTER the yield. Only `conftest.py` is ever judged; every other file in `tests/` passes silently, because item 16 puts these fixtures in exactly one place. A `Console(width=200)` the fixture builds itself pins nothing — the pin has to land on the product's consoles. The checker never convicts a branch for a conftest that is not there |
| constant_predicate *(tests only)* | all_files | tests | A lambda handed to the product as a call argument whose body is a CONSTANT — crack class C from the 2026-09-22 review of @backup's tests. Scored only when the constant is a bool: `should_ignore=lambda p: False` answers the same for every path, so it cannot discriminate, and the product may never call it at all (`test_ignore_pathspec.py:491` hands one to `mirror.py`, which never consults it). A lambda bound to a name and never handed over is not yet consulted by anything and is acquitted. Reported with a count and charged to nobody: `lambda *a: None` (an inert `on_progress` or logger — 236 of the fleet's 309, and a legitimate stub for a callback that is not under test) and any lambda returning a value, which does answer the product's question. `isinstance(True, int)` is True in Python, so the bool test runs FIRST or every `lambda: 0` reads as a predicate. Fleet: 38 files, 163 scored, 309 counted |
| dead_code | branch_level | production | Unreachable functions and dead imports |
| debug_print | all_files | everywhere | No debug print/pprint statements |
| declared_pass_contradiction *(tests only)* | all_files | tests | A declared pass — the `# seedgo: no-test-needed(X)` block of template item 4 — that the same file breaks. Crack class H from the 2026-09-22 review of @backup's tests. Two scored forms: **H1** a `(constant)` line naming a constant whose product LITERAL the file then asserts (`TRACKER_FILENAME` declared untested while three asserts pin `'drive_tracker.json'`), and **H2** a declared symbol that appears nowhere in the branch's `apps/` (`DEFAULT_MAX_SIZE_GB`; the constant is `DEFAULT_MAX_TOTAL_GB`). THE JUDGEMENT: using a declared constant BY NAME is consistent with declaring it untested — `assert CURE in message` survives any change to CURE's text; asserting its VALUE pins exactly what was declared untested. Absence is searched in the apps/ SOURCE TEXT, not the AST's names: an env-var string, an annotated dataclass field and a directory segment are all real uses, and the name set missed all three and convicted 86 live symbols. Reported with a count and charged to nobody: 106 — 39 lines naming no symbol (prose is a legitimate declaration) and 67 dotted stdlib names, where incidental use is indistinguishable from testing. A declared LIBRARY whose call feeds an assert is also only counted: `no_product_call` already convicts `test_ignore_pathspec.py:46`, the one case where the library really is the subject. Fleet: 37 files declare a pass at all, 7 files / 8 hits scored |
| declared_pass_symbol_resolves *(tests only)* | all_files | tests | The WRONG-SYMBOL shape of a declared pass (template item 7), beside H1/H2: every name in a `no-test-needed` line resolves — in `apps/` source text, or on a `(stdlib)` line to a real stdlib chain the product uses (`os.scandir`: @backup never calls it; `pathspec` is a library). A line naming nothing is a finding unless its category is a pack standard (`ruff`, `documentation`). Fleet 2026-09-25: 40 files declare, 10 convicted / 12 hits |
| deep_nesting | all_files | everywhere | Max nesting depth 4 (AST-measured) |
| discarded_patch *(tests only)* | all_files | tests | A mock of the branch's OWN code that nothing ever observes — crack class R from the 2026-09-22 review of @backup's tests, where deleting `_log_breach` left all 21 tests green. Convicts a `with patch(...)`/`patch.object(...)` with no `as` binding (or one never referenced anywhere in the test, INCLUDING after the block closes), a `@patch` whose injected parameter the body never mentions, and a `monkeypatch.setattr` whose replacement is anonymous — `Mock()` with no arguments, or `lambda *a, **k: None`. Four acquittals: another branch or a gateway (sealing an edge is the job); a replacement HANDED OVER, by keyword or by the second positional slot (`patch(target, tmp_path)`); a named or recording replacement; and any patch outside a `def test_*` body, because the conftest seam is sanctioned. The branch comes from the file's own path |
| docs_page | entry_point | production | Every docs/*.md in one shape: a README back-link and one H1, a purpose paragraph, depth ≤3, links resolve, size under the context pack's cap, and no retired defect register by name — plus advisory story and defect-prose lines |
| documentation | all_files | production | Docstrings on public functions |
| duplicate_test *(tests only)* | all_files | tests | A test another test in the SAME FILE already covers — crack class B from the 2026-09-22 review of @backup's tests. Two shapes on one check: **B1 clone**, two tests whose bodies are the same statements with the docstring dropped; **B2 subsumed**, every statement of X also appears in Y AND Y's extras beyond X are only asserts or bindings that call nothing. That restriction is the rule: a `write_text` Y adds is a different PRECONDITION, not a superset. Constants are kept (`*.log` and `*.txt` are different claims). The FIRST by line is the original, every later copy is the finding, and a clone is never also charged as subsumed. One file, not the branch — cross-file duplication is measured (21 files, 22 clones) and left for a branch-level lane |
| encapsulation | all_files | production | No cross-branch imports, proper isolation |
| error_handling | all_files | production | Try/except patterns, error propagation |
| flag_never_passed *(tests only)* | branch_level | tests | A `--flag` a branch's parser reads that no test ever passes it — crack class P from the 2026-09-22 review of @backup's tests, where `public = False` survived all 21 share tests. The declared set starts at `handle_command` and follows the same-file functions it calls; a flag parsed only in `__main__` is a different surface and is never convicted. A test PASSES the flag when the literal reaches an ARGUMENT of some call — the parser directly, a sub-handler (`handle_create([t, '--dry-run'])`, how @spawn tests its flags), a `sys.argv` set before `main()`, a name bound to an argv list, or a `parametrize` argvalue. A tuple that is only ITERATED is not an argument, which is what stops @backup's help sweep acquitting the flags it names. An argv carrying `--help`/`-h` exercises nothing else in that row, because the product returns from `print_help()` first; those flags are counted in the passing message |
| gateway_boundary | all_files | production | A branch writes its OWN private storage; another branch's goes through that branch's door |
| handler_import | branch_level | production | apps/__init__.py contains `from . import handlers` |
| handlers | all_files | production | Handler directory structure + handler independence |
| hardcoded_key | all_files | everywhere | No hardcoded API keys or secrets |
| hardcoded_path | all_files | everywhere | No hardcoded absolute paths |
| help_flag_safety | all_files | production | A help flag ANYWHERE means explain, never execute |
| help_text | all_files | production | --help content quality |
| host_portability | branch_level | everywhere | Linux-only host assumptions — `/proc` reads (direct or through a bound name), non-portable binaries, and a test skip that names Windows on a Linux recipe (corpus: apps/, tests/ **and** lib/) |
| import_site *(tests only)* | all_files | tests | A product import inside a function, or a `sys.modules` stub naming an aipass module — test template v1 item 8. Module-level imports and third-party imports inside a function are never convicted. Scored per test file since 2026-09-21, when `tests/` joined the audit corpus; also convicts in the checklist lane on the write |
| imports | all_files | everywhere | Import ordering and grouping |
| introspection | all_files | production | No-args introspection gate |
| json_handler | branch_level | production | The canonical json shim by sha256 + bidirectional config/data/log triplet completeness |
| json_structure | all_files | production | json_handler import + log_operation calls |
| log_handler | all_files | production | Prax logger usage (not stdlib logging) |
| log_level | all_files | production | Correct log level usage |
| file_top *(tests only)* | all_files | tests | The top of a test file, top to bottom — test template v1 items 5, 6 and 7 as three sub-rules: the META header block first (banner word `META`, meta_check's five fields), then a ONE-line docstring naming the subject as a path, then the declared pass (`# seedgo: no-test-needed(...)`). Each sub-rule reports its own message. `conftest.py` is judged on item 5 only: it has no subject and holds no tests. `meta` and `documentation` are production-only, so none of this was checked before |
| literal_path *(tests only)* | all_files | tests | An absolute path literal HANDED TO A CALL in a test — `Path("/nonexistent/path")`, `classify("/fake/repo/x.py")`, or a name bound only to one — test template v1 item 22. A literal that merely sits somewhere is data: mock return values, URL routes, dict keys and oracles are never convicted, nor are system roots, pure path classes or home-rooted paths (`hardcoded_path` owns those). Drive-rooted literals are counted in the passing message, never charged |
| log_structure | all_files | production | Structured log message format |
| log_visibility | all_files | production | Log output in key operations |
| meta | all_files | production | File header metadata block |
| modules | all_files | production | Module structure and naming |
| module_scope_side_effect *(tests only)* | all_files | tests | A side effect that runs when a `test_*.py` is IMPORTED — top-level statements, class bodies, decorators, default arguments (not function bodies, not under `__main__`): `sys.addaudithook`, a host read (`Path.home()`, `expanduser`, `getcwd`), a write to `os.environ` / `sys.modules` / `sys.path`, a setattr on an import, `os.chdir`, a global recorder. `conftest.py` is exempt — the declared session harness (template C0). Fleet 2026-09-25: 557 judged, 15 convicted / 32 hits |
| mock_console *(tests only)* | all_files | tests | A console stand-in INSTALLED OVER the product, or handed to it — test template v1 item 14. Four install sites (`patch("...console")`, `patch.object`, `setattr`, `mod.console = X`) and one hand-off (`f(console=X)`); three stand-ins (a Mock — including the default MagicMock a bare `patch` supplies — a `Console(file=buf)`, a test-local fake with a `print` method). `capsys`, a console the PRODUCT builds, a restore, and a Mock for anything not console-named are never convicted. A `Console(file=...)` the test prints to ITSELF and never installs is counted in the passing message, never charged |
| named_encoding *(tests only)* | all_files | tests | A text read or write with no encoding named — `open()` in a text mode, `read_text()`, `write_text()` — test template v1 item 21. Binary modes, a positional encoding, and a deliberate non-utf-8 encoding (counted in the passing message) are never convicted. Scored per test file; also convicts in the checklist lane on the write |
| naming | all_files | everywhere | snake_case, column-0 constants |
| no_product_call *(tests only)* | all_files | tests | A `def test_*` that reaches NO aipass code — crack class A from the 2026-09-22 review of @backup's tests, where the reviewers called them LIBRARY tests. A REACHABILITY rule, not a call-site rule: the body, the decorators, every same-file helper called and every fixture requested. Naming the product means an `aipass.*` import binding, a module-level constant that reaches one (to a fixed point, which is how a parametrized test reaches `mod.handle_command`), a dotted `"aipass...."` string, a multi-line literal mentioning aipass (a probe source), or a path from `__file__`. Two acquittals: a call into the file's OWN apparatus (a same-file helper or a conftest fixture — a control for an in-file detector is a meta-test), and a method of a class whose body reaches (a `TestCase` reaches through `self.conn`, which `setUp` built) |
| oversize_test_file *(tests only)* | all_files | tests | A test file over 1,500 CODE lines — multi-line string payload, docstrings included, is subtracted first. Scored per test file since 2026-09-21, when `tests/` joined the audit corpus; also convicts in the checklist lane on the write |
| output_routing | all_files | production | Status output via @cli helpers, not raw console.print |
| permission_flags | all_files | everywhere | No dangerous permission overrides |
| readme | entry_point | production | README.md exists and is current — plus the advisory lane: docs index, named paths, rot bait, and the eight `##` sections in order |
| readme_quality | entry_point | production | README content depth and section quality |
| retired_token_docstring *(tests only)* | all_files | tests | Cargo from the retired v4 keyword auditor (`test_quality`, cut in c1e0eeed) in a test docstring: a run of its terms followed by `token(s)`, or a run of 2+ code-shaped terms (`capsys, capfd, StringIO`). The vocabulary is v4's own `STANDARD_CATEGORIES`, verbatim. Fleet 2026-09-25: 596 scanned, 7 convicted / 13 hits |
| rich_markup | all_files | production | Literal `[placeholders]` Rich silently eats at render time |
| router_assert *(tests only)* | all_files | tests | A test whose every assertion is a command router returning `is True` — `is False` is never convicted. Scored per test file since 2026-09-21, when `tests/` joined the audit corpus; also convicts in the checklist lane on the write |
| ruff | branch_level | everywhere | Ruff lint + format compliance — a violation fails the row and counts in the score |
| self_set_assert *(tests only)* | all_files | tests | A test that writes a value and then asserts the value is there — crack class E from the 2026-09-22 review of @backup's tests. `r.files_deleted = 5` then `assert r.files_deleted == 5` is a statement about Python's `setattr`, and it passes with the product deleted. Three shapes, and the CONSTRUCTOR KWARG (`obj = C(attr=X)` then `assert obj.attr == X`) is 14 of the fleet's 15 — the one nobody sees while writing it. THE JUDGEMENT: score only when NOTHING RAN in between. A call between the write and the read makes the assert a durability oracle — "the product did not clobber this" — which is a real claim, and those ride in the passing message as a count. The comparison must also be `==` against the SAME literal: `client._drive_service = service` then `assert client.drive_service is service` sets the backing field and asserts the PROPERTY, so the getter is under test and the rule declines it. `weak_oracle` reads a self-set assert as STRONG because it is a real value comparison; this rule is the other half of that verdict. Fleet: 5 files / 15 hits scored, 8 counted |
| shebang | all_files | everywhere | No shebang lines in library code |
| silent_catch | all_files | everywhere | No bare except/pass patterns |
| sleep_in_test *(tests only)* | all_files | tests | `sleep` inside a test — crack class N from the 2026-09-22 review of @backup's tests, and test template v1 item 23. Every hit is scored: both shapes have a strictly better cure. A sleep to move an mtime is a 0.01s nudge that does not move it at all on a one-second-granularity filesystem, where `os.utime(path, (when, when))` sets it exactly and instantly; a sleep to wait for something is a bet the machine is fast enough today, where a deadline poll on the REAL condition is faster and honest. Matched by the call's TAIL name, because the fleet spells the module four ways (`time`, `_time`, `time_module`, `time_mod`) and matching `time.sleep` alone missed eight calls. Fleet: 17 files, 43 hits |
| stale_header_date *(tests only)* | all_files | tests | A `# Modified:` date older than the file's last commit (an uncommitted file is judged as of today). The first checker to READ GIT, read-only; it DECLINES (not applicable, out of the average) with no git, no work tree or a shallow clone — CI's audit job keeps `fetch-depth: 0`. Fleet 2026-09-25: 433 judged, 326 stale |
| state_leak *(tests only)* | all_files | tests | A write to shared state at TEST TIME with nothing to put it back — test template v1 item 18. Three shapes: a direct write (`os.environ[k] = v`, `sys.path.insert`, `sys.modules[k] = v`, `mod.attr = x` / `setattr(mod, ...)` on an imported product module), a patcher `.start()`ed and never stopped, and `os.chdir` with no restore. Every `monkeypatch` verb credits its own family only; `with patch(...)`, `@patch`, a `try`/`finally`, and a restoring fixture the test REQUESTS are never convicted, nor is a `sys.modules` key naming an aipass module (`import_site` owns it). Depth ONE only — `mod.helper.return_value = x` configures an object, not the module. A write at import time is counted in the passing message, never charged |
| stdlib_patch *(tests only)* | all_files | tests | A `patch`, `patch.object` or `monkeypatch.setattr` whose target resolves to a stdlib module rather than aipass — crack class Q from the 2026-09-22 review of @backup's tests. Replacing `os.path.getsize` or `shutil.copy2` is process-wide, so the test pins the product's SPELLING, not its behaviour. The target is resolved through the FILE'S OWN IMPORTS, not read off the local alias: `patch.object(ceiling.os.path, ...)` resolves to `aipass.backup...ceiling.os.path`, and the boundary is the first segment that is no longer a product module ON DISK. That disk check is the defence against a name collision — @ai_mail's own `modules/email.py` is not stdlib `email`, and guessing from the name convicted it 291 times. A stdlib CLASS reached through a product binding is judged by what it IS, not by which name reached it: `monkeypatch.setattr(upload.Path, "resolve", ...)` is looked up in `upload.py`'s own imports and lands on `pathlib`, the same verdict `patch("pathlib.Path.resolve")` gets, while a class the module DEFINES (`agent.TranscriptScanner`) stays acquitted — @backup found that hole on 2026-09-23 and closing it recovered 97 acquittals, every one of them `pathlib.Path`. A relative import keeps its leading dots, so `from ..json import json_handler` is a sibling package and never stdlib `json`. ACQUITTED as seams a test is right to seal: the process edges (`subprocess`, `socket`, `urllib`, `http`, `smtplib`, `ssl`, `ftplib`, `asyncio`, `select`) and the interpreter's own tables (`sys.argv`, `sys.stdout`, `sys.stderr`, `sys.stdin`, `sys.path`, `sys.modules`, `os.environ`). Reported with a count and charged to nobody: a target bound to a LOCAL name by assignment, which the AST cannot resolve — 4,614 of them, larger than everything the rule convicts. Fleet: 159 files, 1,002 hits |
| stderr_routing | all_files | production | Proper stderr vs stdout usage |
| subcommand_help | branch_level | production | Subcommand --help interception before dispatch |
| template *(advisory)* | branch_level | everywhere | No unresolved spawn template markers |
| through_the_command *(tests only)* | all_files | tests | A test importing an underscore name from a product module, or reaching one on a base it imported — test template v1 item 10. Dunders, the test's own helpers, reads on returned values, and WRITES (item 15's shape) are never convicted. Scored per test file since 2026-09-21, when `tests/` joined the audit corpus; also convicts in the checklist lane on the write |
| todo | all_files | everywhere | No unresolved TODO/FIXME/HACK comments |
| trigger | all_files | production | Trigger integration patterns |
| trinity | branch_level | production | `.trinity/` document set — schema, caps, ordering, freshness |
| uncalled_public_function *(tests only)* | branch_level | tests | A public function of a test file's DECLARED SUBJECT module — the path in its one-line docstring, template item 6 — that no test in the branch calls. Crack class O from the 2026-09-22 review of @backup's tests. Named in a `Call`, or an attribute access that is then called, IS called; named ONLY as a `patch`/`monkeypatch.setattr` target is **O1 replaced, never run**; named nowhere and unreachable is **O2**. The false conviction to avoid is a function the product still reaches: a name-level call graph over the branch's `apps/`, seeded with every function the tests do call and closed to a fixed point, acquits it — 18 of 20 candidates, and the count rides in the passing message. Reads the docstring with `findall`, because a subject line can name two modules. Only 69 of the fleet's 561 test files declare a subject at all, which caps the rule; `file_top`'s item 6 convicts the rest |
| unconsumed_side_effect *(tests only)* | all_files | tests | `mock.side_effect = [more than one answer]` in a test that never claims how many times the mock was called — crack class F from the 2026-09-22 review of @backup's tests. A list of three says the product will call the mock three times; nothing in the test says so, and if it calls twice the third answer is never consumed, the test still passes, and the branch that answer was written to feed is deletable with the suite green. ACQUITTED by any claim on the calls: `call_count`, `assert_called*`, `assert_has_calls`, `mock_calls`, `call_args`, `assert_not_called`, the `await_` forms — 9 of the fleet's 26. SCORED when the mock reaches no assertion at all — 17. COUNTED when the mock is asserted some other way (its return value reaches an assert), which is 0 today; the bucket exists because the shape is legitimate. A list of ONE is never judged — a single queued answer is a return value spelled differently, with no tail to lose. The cure is one line: `assert mock.call_count == 3`. Fleet: 5 files / 17 hits |
| unused_conftest_fixture *(tests only)* | branch_level | tests | A fixture defined in a branch's `conftest.py`, not `autouse`, that nothing in its `tests/` tree ever requests — crack class G from the 2026-09-22 review of @backup's tests (`conftest.py` 80 `temp_dir`, 92 `sample_data`, 176 `mock_logger`). Branch-level and not folded into `conftest_fixtures`, because "is this requested" is a fact about the whole tree and an `all_files` rule reading its siblings would be a file-level rule in disguise. A request counts in every spelling: a parameter on a test OR on another fixture (so a chain's root is never convicted), and any string literal in the tree, which covers `usefixtures` and `getfixturevalue` without reading only those two call shapes. `autouse=True` means nothing needs to ask, and is never convicted. Fleet: 13 files, 22 hits |
| unused_function | branch_level | production | No unreferenced public functions |
| weak_oracle *(tests only)* | all_files | tests | A test whose WHOLE oracle cannot fail — crack class D from the 2026-09-22 review of @backup's tests, and their largest verdict class (51 of 285). Scored on the six forms that cannot be right when they are the only assertions: `assert <constant>`; a bare NAME's truthiness (never a call's — `assert is_ignored(p, spec)` is the claim); `is not None` alone; `isinstance` alone; `assert_called`/`assert_called_once` with no argument check; and `assert f(...) is None` where `f` is annotated `-> None`, resolved through a module alias as well as a direct import. Reported with a count and charged to nobody: plain `is None`, `len`/`count` compares, bounds, `in`/`not in`, `== {}`. A `pytest.raises` acquits outright; a SOFT companion does not, only a strong one does. `router_assert`'s `is True` reads as strong, so the two never meet |
| windows_compat | all_files | everywhere | Cross-platform compatibility (no Unix-only APIs) |

The audit consults one entry more than this table has rows: `diagnostics` (pyright) has no
`_check.py` of its own. `.github/scripts/seedgo_audit.py` pins that consulted total in
`EXPECTED_STANDARDS` and fails CI when the live number differs — a standard that leaves the
gate silently, or one added without moving the pin, both trip it.

---

## How a rule is added

A standard is a **triplet** in `apps/handlers/aipass_standards/`, and the `triplet` proof
(`apps/handlers/aipass_proof/triplet.py`) is what measures whether it is complete:

| File | Contract |
|---|---|
| `<name>_check.py` | `AUDIT_SCOPE` + optional `APPLIES_TO`; a `check_module(module_path, bypass_rules=None)` or `check_branch(branch_path)` returning `{passed, checks[], score, standard}`. `discover_checkers()` picks up any `*_check.py` exporting one of those two — nothing registers a name by hand. |
| `<name>_content.py` | `get_<name>_standards() -> str`, the Rich-markup text `drone @seedgo standard <name>` prints. |
| `<name>.md` | The prose: what it is, why it matters, the failure case, the bypass position. |

Then, in the same change:

1. Move `EXPECTED_STANDARDS` in `.github/scripts/seedgo_audit.py`, or every branch trips the
   tripwire on the next CI run.
2. Prove it both ways before it lands — break a real file, see the violation, then fix it.
   A checker that has never fired is a checker nobody has measured.
3. Decide the bypass position in the `.md`. Shape rules (`trinity`) carry none by design.
4. A standard that scores but must not gate sets `ADVISORY = True`: `branch_audit` keeps it
   out of the branch's gating average. That flag is per MODULE — switching it on a standard
   that already scores moves every branch's average, which is why the docs-index lane is a
   `check_branch_info()` info line instead (see `apps/handlers/aipass_standards/readme.md`).

**Landing a checker in one commit reds the fleet.** On 2026-09-13 a renderer change put 17 of
18 branches below the CI threshold. The ruling since is *advisory, then ratchet*: measure for
a week, then gate.

---

## The `ruff` / `ruff_check` naming split

The checker file is `ruff_check.py`, so stripping the `_check.py` suffix yields the standard
name **`ruff`** — that is what the audit and the checklist display. Its content and doc files
are `ruff_check_content.py` / `ruff_check.md`, so the query surface lists and accepts
**`ruff_check`**: `drone @seedgo standard ruff` answers "Unknown standard". The name the audit
shows you is not the name the query takes, and the `triplet` proof reports the pair as two
half-standards. Tracked in APLAN-0005.

`drone @seedgo standard` is pack-agnostic and lists the union of all four packs;
`drone @seedgo standards_query aipass_standards` lists this one. Both read names from
`*_content.py`, which is why `ruff_check` appears there and `ruff` does not.

---

## One json handler, fleet-wide

Since DPLAN-0325 (2026-09-04) every citizen ships a byte-identical
`apps/handlers/json/json_handler.py` — a shim that binds the prax-owned service and resolves
nothing of its own. The `json_handler` standard accepts a handler **only** if its sha256
matches that pinned shim; no substring and no marker path is left in the checker.

The shim *binds*, never wraps: the service reads its caller at `sys._getframe(2)`, so one
extra wrapper frame would misroute every log line in the branch. The behaviour is pinned by
execution over every shim in `tests/test_json_handler_contract.py`.

---

## `test_quality` (v4) left this pack on 2026-09-07

It was the pack's only `APPLIES_TO = tests` checker: a per-branch TEXT scan that awarded an
item for finding a substring anywhere under `tests/`. The owner sealed DPLAN-0323 that night —
the scan manufactured tests instead of measuring them, and one json sweep had to add four
`test_cli_routing.py` files purely to keep its items covered. Checker, content module and
`.md` are in `apps/handlers/aipass_standards/.archive/`, and no checker declares
`APPLIES_TO = tests` any more.

What replaced it is not another gate: [pytest_quality.md](pytest_quality.md) — AST rules that
score and gate nothing.

---

## Related

- [audit_engine.md](audit_engine.md) — how a pack is discovered, scored, cached and rendered
- [checklist_and_hooks.md](checklist_and_hooks.md) — the per-file lane the PostToolUse hook runs
- [proof_and_coverage.md](proof_and_coverage.md) — the proof pack that audits this pack
- [context_standards.md](context_standards.md) — the startup-budget pack and the layer contract
