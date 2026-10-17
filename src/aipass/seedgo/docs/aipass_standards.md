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
verified against `discover_checkers()` on every regeneration, never carried forward: a
count can match by accident while a row is missing. If this table and the directory
disagree, the directory is right.

**The corpus is `apps/` plus `tests/`** — `test_*.py` and `conftest.py`, under the same
exclusions `apps/` gets. Every checker declares an `APPLIES_TO`; `everywhere` is the default
for a checker that forgets, because forgetting should cost noise and never a missed bug.

The rows whose `Applies to` is `tests` live on two pages of their own, because with them this
page would exceed the docs-page size cap:
[aipass_standards_tests_1.md](aipass_standards_tests_1.md) (calendar_bound to literal_path) and
[aipass_standards_tests_2.md](aipass_standards_tests_2.md) (module_scope_side_effect to weak_oracle).
The table below carries every other row.

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| accepted_and_never_used_parameter *(production only)* | all_files | production | A product function accepts a parameter and no path in its body reads it. `cleanup_deleted_files(..., should_ignore, ...)` documents the callable and never calls it, while `copy/snapshot.py:93` builds a lambda to pass in; ONE defect, two lines, and the verdict lands on the ACCEPTING side where the cure lives. HOW A PROTOCOL IS TOLD APART, four shapes that all say somebody else owns this signature: the branch never calls the function (`pytest_runtest_logfinish` is pytest's hookspec — whether it should exist at all is `unused_function`'s verdict, not this one's); the name is handed off as a VALUE, a bare mention that is not a call, not its own `def` line and NOT an import (an import is not a hand-off); the def sits inside an `except ImportError` handler, so it is a shim that must match the real module; the name is defined more than once in the branch. Ordinary exemptions: `self`/`cls`, `*args`/`**kwargs`, dunders, decorated, a stub body, and any `_`-prefixed parameter. The corpus is stripped of strings and comments with the tokenizer — so a docstring or comment that names a function never counts as a hand-off |
| architecture | all_files | production | Module/handler separation, entry point structure; `shared/` beside `apps/` is the library layer |
| clear_text_secret_logging *(production only)* | all_files | production | CodeQL `py/clear-text-logging-sensitive-data` (specimen: PR #774): the CALLER line. A prax logger call whose message (argument, f-string piece, `%`/`.format()`/`+` operand) is a Name/Attribute/Call named as a secret (whole segment: secret(s), token(s), password(s), passwd, api_key, apikey, credential(s), bearer, auth_header, access_key, private_key, trusted, confidential; not untrusted), or a value built in the same file from a secret-named SOURCE: a module-level binding (`SECRETS_BASE = ...`) or an attribute read (`secrets_store.SECRETS_BASE`), a token word seeding neither, or the result of a call on CodeQL's source words secret(s)/trusted/confidential (`secret = _get_secret(bot_id)`), not one holding hash/md5/sha/random/encode/encrypt/public/user/login/logging/clear/redact or a setter verb (set_secret); never a parameter, loop/with target or local. One parameter seed: in a file defining a secret lister (`list_secrets(provider)`), inside a secret reader (a get/read/load/fetch segment on the call-seed words, no setter verb, no `list` segment), a required positional parameter the lister does not take (`slug`, never `provider`) in the log call's MESSAGE (first argument or `msg=`: f-string piece, `%`/`+` side, `.format()`, str/repr) is a row; a `%s` argument is not. That seed judges the message only, which is CodeQL's reach; the other seeds judge arguments too. From a source it follows assignments, comprehensions, the wrappers sorted/list/tuple/set/dict/str/repr/join/format/f-strings, same-file returns and parameters, attributes, and the same-file hop (a built argument to a same-file function whose return carries that parameter taints that call's result, per call: `strays = non_secret_keys(secret)`), and reads and adds on a built value: `.get/.pop/.setdefault/.items/.keys/.values` carry the receiver on (`records = stored.get("tokens")`), `.append/.extend/.add/.insert(i, x)` bind the named list or set, a dict literal or `dict(...)` holding a built value is built (str/repr/f-string/`%r` stay rows; `len()`, `type(x).__name__` and a slice of ≤4 chars stay clean); a non_/not_ prefix acquits nothing. Identifiers acquit (token_id, n_tokens, secret_path, TOKEN_SLUG), so do redactions (redact/mask/scrub, `len()`, a slice of ≤4 chars). A cross-file value (`token_id` from another module) is out of reach. The cure for a false hit is the rename |
| cli | all_files | production | Rich console usage, no bare print() |
| cli_flags | entry_point | production | --help, --version flag handling |
| cli_ux | entry_point | production | CLI navigation + output quality (Nav/Output scoring) |
| commented_logger | all_files | everywhere | No commented-out logger/logging calls |
| dead_code | branch_level | production | Unreachable functions and dead imports; a dotted path in the project's `.aipass/*.json` is a reference |
| debug_print | all_files | everywhere | No debug print/pprint statements |
| deep_nesting | all_files | everywhere | Max nesting depth 4 (AST-measured) |
| developer_home | all_files | everywhere | No developer's home directory (`/home/<x>`, `/Users/<x>`, `C:\Users\<x>`, any slash) naming a real login in any text file — comments and prose included; `TEXT_FILES = True` lets the checklist judge non-`.py` text, and `drone @seedgo home-paths scan` gates the whole tracked tree in CI |
| docs_page | entry_point | production | Every docs/*.md in one shape: a README back-link and one H1, a purpose paragraph, depth ≤3, links resolve, size under the context pack's cap, and no retired defect register by name — plus advisory story and defect-prose lines |
| documentation | all_files | production | Docstrings on public functions |
| encapsulation | all_files | production | No cross-branch imports, proper isolation |
| error_handling | all_files | production | Try/except patterns, error propagation |
| exception_text_in_response *(production only)* | all_files | production | CodeQL `py/stack-trace-exposure` (specimen: PR #774): inside an `except`, the bound exception (or an attribute, `str()`/`repr()`, f-string, local carrying it) or `traceback.format_exc()` reaches `HTTPException(detail=)`, a `*Response` content, a `deny`/`refuse`/`error_response`/`respond` helper, or a returned dict/str. Only modules importing fastapi/starlette or defining a route; any other file declines. Logger-only and `type(e).__name__` acquit. A cross-branch flow (through `ReadCache.get`) is out of its reach; the `.md` says why |
| gateway_boundary | all_files | production | A branch writes its OWN private storage; another branch's goes through that branch's door |
| handlers | all_files | production | Handler directory structure + handler independence |
| hardcoded_key | all_files | everywhere | No hardcoded API keys or secrets |
| hardcoded_path | all_files | everywhere | No hardcoded absolute paths |
| help_flag_safety | all_files | production | A help flag ANYWHERE means explain, never execute |
| help_text | all_files | production | --help content quality |
| host_portability | branch_level | everywhere | Linux-only host assumptions — `/proc` reads (direct or through a bound name), non-portable binaries, a test skip that names Windows on a Linux recipe, a direct `Path` subclass (3.10/3.11), and a `resolve()`d path compared in the same function with `Path.home()` / `Path.cwd()` / `os.getcwd()` / `tempfile` as given (arm E, file-local) (corpus: apps/, tests/ **and** lib/) |
| imports | all_files | everywhere | Import ordering and grouping |
| introspection | all_files | production | No-args introspection gate |
| json_handler | branch_level | production | The canonical json shim by sha256 + bidirectional config/data/log triplet completeness |
| json_structure | all_files | production | json_handler import + log_operation calls |
| log_handler | all_files | production | Prax logger usage (not stdlib logging) |
| log_level | all_files | production | Correct log level usage |
| log_structure | all_files | production | Structured log message format |
| log_visibility | all_files | production | Log output in key operations |
| logged_fallback *(production only)* | all_files | production | `silent_catch`'s sibling: an `except` that does not raise and ENDS in `return` of a literal default (constant, empty container, or a string built from the exception) in a function whose success path can return the SAME value -- an equal literal (same type: `False` is not `0`) in a return outside every handler, or a name first bound to it. Logging never acquits. Sentinels pass (`None` beside dict returns, `-1` beside counts); raises, generators, `finally` returns, calls/params and assign-and-fall-through are not read. |
| meta | all_files | production | File header metadata block |
| modules | all_files | production | Module structure and naming |
| naming | all_files | everywhere | snake_case, column-0 constants |
| os_walk_onerror *(production only)* | all_files | production | An `os.walk` call with no `onerror=` (or `onerror=None`) — `scandir` errors are swallowed, so an unreadable subtree drops out and the run reports success. Specimen @backup `scan/walk.py:34`. A third positional arg or `**kwargs` acquits; any named hook passes (a hook that only logs is not a cure, the page says so; the checker cannot see it). `rglob` has no hook: counted, not judged |
| output_routing | all_files | production | Status output via @cli helpers, not raw console.print |
| permission_flags | all_files | everywhere | No dangerous permission overrides |
| readme | entry_point | production | README.md exists and is current — plus the advisory lane: docs index, named paths, rot bait, and the eight `##` sections in order |
| readme_quality | entry_point | production | README content depth and section quality |
| rich_markup | all_files | production | Literal `[placeholders]` Rich silently eats at render time |
| ruff | branch_level | everywhere | Ruff lint + format compliance — a violation fails the row and counts in the score |
| shebang | all_files | everywhere | No shebang lines in library code |
| silent_catch | all_files | everywhere | No bare except/pass patterns |
| stderr_routing | all_files | production | Proper stderr vs stdout usage |
| subcommand_help | branch_level | production | Subcommand --help interception before dispatch |
| template *(advisory)* | branch_level | everywhere | No unresolved spawn template markers |
| todo | all_files | everywhere | No unresolved TODO/FIXME/HACK comments |
| trigger | all_files | production | Trigger integration patterns |
| trinity | branch_level | production | `.trinity/` document set — schema, caps, ordering, freshness |
| unused_function | branch_level | production | No unreferenced public functions |
| windows_compat | all_files | everywhere | Cross-platform compatibility (no Unix-only APIs); advisory info lines, never scored: lock race (apps/), mock repr path and text fixture bytes oracle (tests/) |

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

**Landing a checker in one commit reds the fleet.** The rule is *advisory, then ratchet*:
measure for a week, then gate.

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

Every citizen in the package ships a byte-identical `apps/handlers/json/json_handler.py`
(DPLAN-0325) — a shim that binds the prax-owned service and resolves nothing of its own. The
`json_handler` standard accepts a handler **only** if its sha256 matches that pinned shim; no
substring and no marker path is left in the checker. A registered resident outside the
package can still carry a pre-migration handler; the contract tests name each one in a skip.

The shim *binds*, never wraps: the service reads its caller at `sys._getframe(2)`, so one
extra wrapper frame would misroute every log line in the branch. The behaviour is pinned by
execution over every shim in `tests/test_json_handler_contract.py`.

---

## `test_quality` (v4) is retired

`test_quality` was a per-branch TEXT scan that awarded an item for finding a substring
anywhere under `tests/`; a substring scan manufactures tests instead of measuring them
(DPLAN-0323). Its checker, content module and `.md` are in
`apps/handlers/aipass_standards/.archive/`, and it is not discovered.

Test files are judged by AST rules instead: this pack's `APPLIES_TO = tests` rows (the two
pages above), scored per test file, and [pytest_quality.md](pytest_quality.md), a shadow pack
that scores and gates nothing.

---

## Related

- [aipass_standards_tests_1.md](aipass_standards_tests_1.md) — the test-file rows, calendar_bound to literal_path
- [aipass_standards_tests_2.md](aipass_standards_tests_2.md) — the test-file rows, module_scope_side_effect to weak_oracle
- [audit_engine.md](audit_engine.md) — how a pack is discovered, scored, cached and rendered
- [checklist_and_hooks.md](checklist_and_hooks.md) — the per-file lane the PostToolUse hook runs
- [proof_and_coverage.md](proof_and_coverage.md) — the proof pack that audits this pack
- [context_standards.md](context_standards.md) — the startup-budget pack and the layer contract
