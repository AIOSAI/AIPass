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
| architecture | all_files | production | Module/handler separation, entry point structure |
| calendar_bound | branch_level | tests | A test that asserts a date literal against code that computes with the clock, and does not own the clock — true only while the calendar agrees (corpus: tests/ and lib/*/tests/) |
| cli | all_files | production | Rich console usage, no bare print() |
| cli_flags | entry_point | production | --help, --version flag handling |
| cli_ux | entry_point | production | CLI navigation + output quality (Nav/Output scoring) |
| commented_logger | all_files | everywhere | No commented-out logger/logging calls |
| conftest_fixtures *(tests only)* | all_files | tests | A branch's `tests/conftest.py` carries item 20's two fixtures, both reported on ONE check — **C1** a session-scope autouse fixture pinning `.width` on the consoles the PRODUCT exports (`display.CONSOLE`, `display.err_console`), and **C2** an autouse fixture calling `display.reset_command_state()` AFTER the yield. Only `conftest.py` is ever judged; every other file in `tests/` passes silently, because item 16 puts these fixtures in exactly one place. A `Console(width=200)` the fixture builds itself pins nothing — the pin has to land on the product's consoles. The checker never convicts a branch for a conftest that is not there |
| dead_code | branch_level | production | Unreachable functions and dead imports |
| debug_print | all_files | everywhere | No debug print/pprint statements |
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
| mock_console *(tests only)* | all_files | tests | A console stand-in INSTALLED OVER the product, or handed to it — test template v1 item 14. Four install sites (`patch("...console")`, `patch.object`, `setattr`, `mod.console = X`) and one hand-off (`f(console=X)`); three stand-ins (a Mock — including the default MagicMock a bare `patch` supplies — a `Console(file=buf)`, a test-local fake with a `print` method). `capsys`, a console the PRODUCT builds, a restore, and a Mock for anything not console-named are never convicted. A `Console(file=...)` the test prints to ITSELF and never installs is counted in the passing message, never charged |
| named_encoding *(tests only)* | all_files | tests | A text read or write with no encoding named — `open()` in a text mode, `read_text()`, `write_text()` — test template v1 item 21. Binary modes, a positional encoding, and a deliberate non-utf-8 encoding (counted in the passing message) are never convicted. Scored per test file; also convicts in the checklist lane on the write |
| naming | all_files | everywhere | snake_case, column-0 constants |
| no_product_call *(tests only)* | all_files | tests | A `def test_*` that reaches NO aipass code — crack class A from the 2026-09-22 review of @backup's tests, where the reviewers called them LIBRARY tests. A REACHABILITY rule, not a call-site rule: the body, the decorators, every same-file helper called and every fixture requested. Naming the product means an `aipass.*` import binding, a module-level constant that reaches one (to a fixed point, which is how a parametrized test reaches `mod.handle_command`), a dotted `"aipass...."` string, a multi-line literal mentioning aipass (a probe source), or a path from `__file__`. Two acquittals: a call into the file's OWN apparatus (a same-file helper or a conftest fixture — a control for an in-file detector is a meta-test), and a method of a class whose body reaches (a `TestCase` reaches through `self.conn`, which `setUp` built) |
| oversize_test_file *(tests only)* | all_files | tests | A test file over 1,500 CODE lines — multi-line string payload, docstrings included, is subtracted first. Scored per test file since 2026-09-21, when `tests/` joined the audit corpus; also convicts in the checklist lane on the write |
| output_routing | all_files | production | Status output via @cli helpers, not raw console.print |
| permission_flags | all_files | everywhere | No dangerous permission overrides |
| readme | entry_point | production | README.md exists and is current — plus the advisory lane: docs index, named paths, rot bait, and the eight `##` sections in order |
| readme_quality | entry_point | production | README content depth and section quality |
| rich_markup | all_files | production | Literal `[placeholders]` Rich silently eats at render time |
| router_assert *(tests only)* | all_files | tests | A test whose every assertion is a command router returning `is True` — `is False` is never convicted. Scored per test file since 2026-09-21, when `tests/` joined the audit corpus; also convicts in the checklist lane on the write |
| ruff *(advisory)* | branch_level | everywhere | Ruff linter compliance — surfaces violations, never gates the score |
| shebang | all_files | everywhere | No shebang lines in library code |
| silent_catch | all_files | everywhere | No bare except/pass patterns |
| state_leak *(tests only)* | all_files | tests | A write to shared state at TEST TIME with nothing to put it back — test template v1 item 18. Three shapes: a direct write (`os.environ[k] = v`, `sys.path.insert`, `sys.modules[k] = v`, `mod.attr = x` / `setattr(mod, ...)` on an imported product module), a patcher `.start()`ed and never stopped, and `os.chdir` with no restore. Every `monkeypatch` verb credits its own family only; `with patch(...)`, `@patch`, a `try`/`finally`, and a restoring fixture the test REQUESTS are never convicted, nor is a `sys.modules` key naming an aipass module (`import_site` owns it). Depth ONE only — `mod.helper.return_value = x` configures an object, not the module. A write at import time is counted in the passing message, never charged |
| stderr_routing | all_files | production | Proper stderr vs stdout usage |
| subcommand_help | branch_level | production | Subcommand --help interception before dispatch |
| template *(advisory)* | branch_level | everywhere | No unresolved spawn template markers |
| through_the_command *(tests only)* | all_files | tests | A test importing an underscore name from a product module, or reaching one on a base it imported — test template v1 item 10. Dunders, the test's own helpers, reads on returned values, and WRITES (item 15's shape) are never convicted. Scored per test file since 2026-09-21, when `tests/` joined the audit corpus; also convicts in the checklist lane on the write |
| todo | all_files | everywhere | No unresolved TODO/FIXME/HACK comments |
| trigger | all_files | production | Trigger integration patterns |
| trinity | branch_level | production | `.trinity/` document set — schema, caps, ordering, freshness |
| uncalled_public_function *(tests only)* | branch_level | tests | A public function of a test file's DECLARED SUBJECT module — the path in its one-line docstring, template item 6 — that no test in the branch calls. Crack class O from the 2026-09-22 review of @backup's tests. Named in a `Call`, or an attribute access that is then called, IS called; named ONLY as a `patch`/`monkeypatch.setattr` target is **O1 replaced, never run**; named nowhere and unreachable is **O2**. The false conviction to avoid is a function the product still reaches: a name-level call graph over the branch's `apps/`, seeded with every function the tests do call and closed to a fixed point, acquits it — 18 of 20 candidates, and the count rides in the passing message. Reads the docstring with `findall`, because a subject line can name two modules. Only 69 of the fleet's 561 test files declare a subject at all, which caps the rule; `file_top`'s item 6 convicts the rest |
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
