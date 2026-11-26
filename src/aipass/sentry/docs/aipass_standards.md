[<- Back to the README](../README.md)

# aipass_standards — the checker pack

**Branch** sentry · **Pack** `apps/handlers/aipass_standards/` · **Verb** `drone @sentry audit aipass [@branch]`
**Live roster** `drone @sentry standards_query aipass_standards` — generated from the directory, never from this page.

---

## How to read the table

`Scope` is the checker's own `AUDIT_SCOPE`, where a result is REPORTED (`all_files`,
`entry_point`, `branch_level`). `Applies to` is its `APPLIES_TO`, which files are ELIGIBLE,
default `everywhere`; `applicability.py` is where the two axes meet. Both columns are read
from the checker sources. If this page and the directory disagree, the directory is right.

**The corpus is `apps/` plus `tests/`** (`test_*.py` and `conftest.py`, under the same
exclusions `apps/` gets).

Rows are grouped by `apps/handlers/aipass_standards/groups.py`, and each section below is one
of its groups, in its order. The audit prints a clean group as one line and opens a group with
any row under 100; `drone @sentry audit aipass @branch --group NAME` prints one group alone.
A checker file registered in no group fails the `pack_registry` row.

Each row is the rule's one-line meaning; the full detail lives in the standard's own `.md`
beside its checker, `drone @sentry standards_query aipass_standards <name>`.

## architecture

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| architecture | all_files | production | Module/handler separation, entry point structure; `shared/` beside `apps/` is the library layer |
| encapsulation | all_files | production | No cross-branch imports, proper isolation |
| front_door | all_files | everywhere | A cross-branch import goes through the branch's package top file, `from aipass.<branch> import <name>`; one reaching beneath it is one finding per site |
| gateway_boundary | all_files | production | A branch writes only its own private storage; another branch's goes through that branch's door. Outside @api, nothing imports, paths into or calls @api's secrets store |
| handlers | all_files | production | Handler directory structure + handler independence |
| imports | all_files | everywhere | Import ordering and grouping; a production file that logs routes through prax (stdlib `logging` use fails, a file that never logs owes no prax import) |
| module_scope_side_effect *(tests; signal_disposition everywhere)* | all_files | everywhere | A side effect that runs when a `test_*.py` is imported (host reads, `os.environ`/`sys.modules`/`sys.path` writes, `os.chdir`); module-scope `signal` calls are judged in every file |
| modules | all_files | production | Module structure and naming |
| stdlib_only | branch_level | production | Each file in `CLAIMS` is proven stdlib-only: no aipass, relative or I/O import, no disk, environment or process call; a proven claim is skipped by json_structure |
| trigger | all_files | production | Trigger integration patterns |

## cli

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| cli | all_files | production | Rich console usage, no bare print() |
| cli_flags | entry_point | production | --help, --version flag handling |
| cli_ux | all_files | production | Two-tier help, each print styled on purpose, --version from the header: two_tier_help, rich_console, title_markup, purpose_line, help_pointer, usage_section, examples_section, no_internal_modules, markup_kept, help_styled, heading_styled, group_explained, highlight_deliberate, version_from_header |
| help_flag_safety | all_files | production | A help flag ANYWHERE means explain, never execute |
| help_text | all_files | production | --help content quality |
| introspection | all_files | production | No-args introspection gate |
| output_routing | all_files | production | Status output via @cli helpers, not raw console.print |
| rich_markup | all_files | production | Literal `[placeholders]` Rich silently eats at render time |
| stderr_routing | all_files | production | Proper stderr vs stdout usage |
| subcommand_help | branch_level | production | Subcommand --help interception before dispatch |

## code

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| accepted_and_never_used_parameter *(production only)* | all_files | production | A product function accepts a parameter no path in its body reads; a signature somebody else owns (a hook, a handed-off name, an ImportError shim, a name defined twice) is exempt |
| dead_code | branch_level | production | Unreachable functions and dead imports; a dotted path in the project's `.aipass/*.json` or the branch's door table (top `__init__.py`) is a reference |
| deep_nesting | all_files | everywhere | Max nesting depth 4 (AST-measured) |
| unused_function | branch_level | production | No unreferenced public functions |

## docs

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| documentation | all_files | production | Docstrings on public functions |
| docs_page | entry_point | production | Every docs/*.md in one shape: README back-link, one H1, a purpose paragraph, depth ≤3, resolving links, size under the cap, no retired defect register; plus advisory story and defect-prose lines |
| readme | entry_point | production | README.md exists and is current — plus the advisory lane: docs index, named paths, rot bait, and the eight `##` sections in order |
| readme_quality | entry_point | production | README content depth and section quality |
| template *(advisory)* | branch_level | everywhere | No unresolved spawn template markers |
| todo | all_files | everywhere | No unresolved TODO/FIXME/HACK comments |
| trinity | branch_level | production | `.trinity/` document set — schema, caps, ordering, freshness |

## errors

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| error_handling | all_files | production | Try/except patterns, error propagation |
| exception_text_in_response *(production only)* | all_files | production | Inside an `except`, the exception text or `traceback.format_exc()` reaches an HTTP response, a refusal helper or a returned dict/str (CodeQL `py/stack-trace-exposure`); web modules only |
| fallback *(advisory, production only)* | all_files | production | An `except` that answers a failure with a stand-in and neither raises, exits, shows nor carries it, plus `if not shutil.which(...): return`; waived one site per row |
| silent_catch | all_files | everywhere | No bare except/pass patterns |

## header

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| lowercase_name | branch_level | production | An agent name is lowercase wherever it runs: registry, passport, certificate and dashboard names, and code that capitalises one or prints it in capitals |
| meta | all_files | production | File header metadata block |
| naming | all_files | everywhere | snake_case, column-0 constants |
| shebang | all_files | everywhere | No shebang lines in library code |

## json

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| json_handler | branch_level | production | The canonical json shim by sha256 (a claimed branch: that shim bound with `for_branch("<own name>")`) plus bidirectional config/data/log triplet completeness |
| json_structure | all_files | production | json_handler import + log_operation calls |

## logging

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| commented_logger | all_files | everywhere | No commented-out logger/logging calls |
| debug_print | all_files | everywhere | No debug print/pprint statements |
| log_handler | all_files | production | Prax logger usage (not stdlib logging) |
| log_level | all_files | production | Correct log level usage |
| log_structure | all_files | production | Structured log message format |
| log_visibility | all_files | production | Log output in key operations |
| logged_fallback *(production only)* | all_files | production | An `except` that does not raise and returns a literal default its function's success path can also return, so a failure reads as a success; logging never acquits, sentinels pass |
| one_logger *(advisory, production only)* | all_files | production | Prax is the only logger: no stdlib `logging` import, no home-made level-method class, no hand-written `.log` file, no time-stamped stderr writer, outside the files prax and `logging_allowed.py` name |

## paths

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| caller_file_depth | all_files | production | `__file__` handed to a depth function from a layout it does not fit: another depth, outside `<branch>/apps/`, or a copy beside `apps/` on disk. One finding per call |
| developer_home | all_files | everywhere | No developer's home directory (`/home/<x>`, `/Users/<x>`, `C:\Users\<x>`) naming a real login in any text file, comments and prose included |
| fixed_depth_path | all_files | production | A fixed-depth climb off `__file__` that leaves `src/aipass`, or is joined to a name the wheel does not ship (`logs`, `*_json`, a dot name, a `.gitignore` name). One finding per site |
| hardcoded_path | all_files | everywhere | No hardcoded absolute paths |
| host_portability | branch_level | everywhere | Host assumptions: non-portable binaries, a direct `Path` subclass, a `resolve()`d path compared to home/cwd, an emptied git config, a too-new stdlib import, a `.git` existence test (apps/, tests/, lib/) |
| os_walk_onerror *(production only)* | all_files | production | An `os.walk` with no `onerror=`: an unreadable subtree drops out and the run reports success. Any named hook passes; `rglob` is counted, not judged |

## security

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| clear_text_secret_logging *(production only)* | all_files | production | A prax logger call whose message carries a secret-named value, or one built from a secret-named source in the same file (CodeQL `py/clear-text-logging-sensitive-data`); the cure for a false hit is the rename |
| hardcoded_key | all_files | everywhere | No hardcoded API keys or secrets |
| permission_flags | all_files | everywhere | No dangerous permission overrides |

## tests

The 30 rows of the `tests` group live on two pages of their own:
[aipass_standards_tests_1.md](aipass_standards_tests_1.md) (calendar_bound to literal_path) and
[aipass_standards_tests_2.md](aipass_standards_tests_2.md) (mock_console to weak_oracle).

## tooling

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| diagnostics | branch_level | everywhere | Pyright type errors; the audit adds this row itself and runs it through the audit pipeline |
| pack_registry | branch_level | sentry only | Every `*_check.py` is registered under exactly one group in `groups.py`, every registered name is backed by a file, and every file loads as a checker |
| ruff | branch_level | everywhere | Ruff lint + format compliance — a violation fails the row and counts in the score |

`diagnostics` and `pack_registry` have no `_check.py` of their own. `.github/scripts/sentry_audit.py`
pins the consulted total in `EXPECTED_STANDARDS` and fails CI when the live number differs.

---

## How a rule is added

A standard is a **triplet** in `apps/handlers/aipass_standards/`, and the `triplet` proof
(`apps/handlers/aipass_proof/triplet.py`) is what measures whether it is complete:

| File | Contract |
|---|---|
| `<name>_check.py` | `AUDIT_SCOPE` + optional `APPLIES_TO`; a `check_module(module_path, bypass_rules=None)` or `check_branch(branch_path)` returning `{passed, checks[], score, standard}`. `discover_checkers()` picks up any `*_check.py` exporting one of those two. |
| `<name>_content.py` | `get_<name>_standards() -> str`, the Rich-markup text `drone @sentry standard <name>` prints. |
| `<name>.md` | The prose: what it is, why it matters, the failure case, the bypass position. |

Then, in the same change:

1. Register the name under one group in `groups.py`, or the `pack_registry` row fails on sentry.
1. Move `EXPECTED_STANDARDS` in `.github/scripts/sentry_audit.py`, or every branch trips the
   tripwire on the next CI run.
2. Prove it both ways before it lands — break a real file, see the violation, then fix it.
   A checker that has never fired is a checker nobody has measured.
3. Decide the bypass position in the `.md`. Shape rules (`trinity`) carry none by design.
4. A standard that scores but must not gate sets `ADVISORY = True`: `branch_audit` keeps it
   out of the branch's gating average. That flag is per MODULE — switching it on a standard
   that already scores moves every branch's average, which is why the docs-index lane is a
   `check_branch_info()` info line instead (see `apps/handlers/aipass_standards/readme.md`).

**Landing a checker in one commit reds the fleet.** The rule is *advisory, then ratchet*:
measure for a week, then gate.

---

## The `ruff` standard and its bypass key

The checker file is `ruff_check.py` and its content and doc files are `ruff_content.py` /
`ruff.md`, so the audit, the checklist and `drone @sentry standard ruff` all use one name:
**`ruff`**. The bypass rule keeps the key `"ruff_check"`
(`{"standard": "ruff_check", "file": "src/aipass/<branch>"}`) because the checker reads that
key itself.

---

## One json handler, fleet-wide

Every citizen in the package ships a byte-identical `apps/handlers/json/json_handler.py`
— a shim that binds the prax-owned service and resolves nothing of its own. The
`json_handler` standard accepts a handler **only** if its sha256 matches that pinned shim; no
substring and no marker path is left in the checker.
A branch in `BY_NAME_CLAIMS` (hooks, whose shim also runs from a snapshot) instead holds that shim with its one
binding line as `_h = json_handler.for_branch("<its own name>")`, proven by swapping the line back to the hash. A registered resident outside the
package can still carry a pre-migration handler; the contract tests name each one in a skip.

The shim *binds*, never wraps: the service reads its caller at `sys._getframe(2)`, so one
extra wrapper frame would misroute every log line in the branch. The behaviour is pinned by
execution over every shim in `tests/test_json_handler_contract.py`.

---

## `test_quality` (v4) is retired

`test_quality` was a per-branch TEXT scan that awarded an item for finding a substring
anywhere under `tests/`; a substring scan manufactures tests instead of measuring them.
Its checker, content module and `.md` are in
`apps/handlers/aipass_standards/.archive/`, and it is not discovered.

Test files are judged by AST rules instead: this pack's `tests` group (the two
pages above), scored per test file, and [pytest_quality.md](pytest_quality.md), a shadow pack
that scores and gates nothing.

---

## Related

- [aipass_standards_tests_1.md](aipass_standards_tests_1.md) — the test-file rows, calendar_bound to literal_path
- [aipass_standards_tests_2.md](aipass_standards_tests_2.md) — the test-file rows, mock_console to weak_oracle
- [audit_engine.md](audit_engine.md) — how a pack is discovered, scored, cached and rendered
- [checklist_and_hooks.md](checklist_and_hooks.md) — the per-file lane the PostToolUse hook runs
- [proof_and_coverage.md](proof_and_coverage.md) — the proof pack that audits this pack
- [context_standards.md](context_standards.md) — the startup-budget pack and the layer contract
