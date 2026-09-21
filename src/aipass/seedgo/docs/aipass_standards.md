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

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| architecture | all_files | production | Module/handler separation, entry point structure |
| calendar_bound | branch_level | everywhere | A test that asserts a date literal against code that computes with the clock, and does not own the clock — true only while the calendar agrees (corpus: tests/ and lib/*/tests/) |
| cli | all_files | production | Rich console usage, no bare print() |
| cli_flags | entry_point | everywhere | --help, --version flag handling |
| cli_ux | entry_point | everywhere | CLI navigation + output quality (Nav/Output scoring) |
| commented_logger | all_files | everywhere | No commented-out logger/logging calls |
| dead_code | branch_level | everywhere | Unreachable functions and dead imports |
| debug_print | all_files | everywhere | No debug print/pprint statements |
| deep_nesting | all_files | everywhere | Max nesting depth 4 (AST-measured) |
| docs_page | entry_point | everywhere | Every docs/*.md in one shape: a README back-link and one H1, a purpose paragraph, depth ≤3, links resolve, size under the context pack's cap, and no retired defect register by name — plus advisory story and defect-prose lines |
| documentation | all_files | production | Docstrings on public functions |
| encapsulation | all_files | production | No cross-branch imports, proper isolation |
| error_handling | all_files | everywhere | Try/except patterns, error propagation |
| gateway_boundary | all_files | production | A branch writes its OWN private storage; another branch's goes through that branch's door |
| handler_import | branch_level | everywhere | apps/__init__.py contains `from . import handlers` |
| handlers | all_files | production | Handler directory structure + handler independence |
| hardcoded_key | all_files | everywhere | No hardcoded API keys or secrets |
| hardcoded_path | all_files | everywhere | No hardcoded absolute paths |
| help_flag_safety | all_files | production | A help flag ANYWHERE means explain, never execute |
| help_text | all_files | everywhere | --help content quality |
| host_portability | branch_level | everywhere | Linux-only host assumptions — `/proc` reads (direct or through a bound name), non-portable binaries, and a test skip that names Windows on a Linux recipe (corpus: apps/, tests/ **and** lib/) |
| imports | all_files | everywhere | Import ordering and grouping |
| introspection | all_files | everywhere | No-args introspection gate |
| json_handler | branch_level | everywhere | The canonical json shim by sha256 + bidirectional config/data/log triplet completeness |
| json_structure | all_files | everywhere | json_handler import + log_operation calls |
| log_handler | all_files | everywhere | Prax logger usage (not stdlib logging) |
| log_level | all_files | everywhere | Correct log level usage |
| log_structure | all_files | everywhere | Structured log message format |
| log_visibility | all_files | everywhere | Log output in key operations |
| meta | all_files | production | File header metadata block |
| modules | all_files | production | Module structure and naming |
| naming | all_files | everywhere | snake_case, column-0 constants |
| output_routing | all_files | everywhere | Status output via @cli helpers, not raw console.print |
| permission_flags | all_files | everywhere | No dangerous permission overrides |
| readme | entry_point | everywhere | README.md exists and is current — plus the advisory lane: docs index, named paths, rot bait, and the eight `##` sections in order |
| readme_quality | entry_point | everywhere | README content depth and section quality |
| rich_markup | all_files | production | Literal `[placeholders]` Rich silently eats at render time |
| router_assert *(tests only)* | all_files | tests | A test whose every assertion is a command router returning `is True` — `is False` is never convicted. Scores nothing in `audit aipass` (the corpus is `apps/`); it convicts in the checklist lane on the write, and reports the standing backlog unscored |
| ruff *(advisory)* | branch_level | everywhere | Ruff linter compliance — surfaces violations, never gates the score |
| shebang | all_files | everywhere | No shebang lines in library code |
| silent_catch | all_files | everywhere | No bare except/pass patterns |
| stderr_routing | all_files | everywhere | Proper stderr vs stdout usage |
| subcommand_help | entry_point | everywhere | Subcommand --help interception before dispatch |
| template *(advisory)* | branch_level | everywhere | No unresolved spawn template markers |
| todo | all_files | everywhere | No unresolved TODO/FIXME/HACK comments |
| trigger | all_files | production | Trigger integration patterns |
| trinity | branch_level | everywhere | `.trinity/` document set — schema, caps, ordering, freshness |
| unused_function | branch_level | everywhere | No unreferenced public functions |
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
