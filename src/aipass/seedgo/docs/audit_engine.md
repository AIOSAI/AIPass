[<- Back to the README](../README.md)

# The audit engine

**Branch** seedgo · **Code** `apps/handlers/audit/`, `apps/handlers/bypass/`, `apps/modules/standards_audit.py`

Everything below is the machinery *behind* `drone @seedgo audit <pack> [@branch]`. The verbs
themselves are in `drone @seedgo --help`; the bare `drone @seedgo` prints the live module and
pack inventory.

---

## The pieces

| File | What it does |
|---|---|
| `audit/branch_audit.py` | The per-branch scoring engine. `discover_checkers()` loads every `*_check.py` in a pack directory that exports `check_module` or `check_branch`; the branch score is the mean over consulted standards, with `ADVISORY = True` standards kept out of it. |
| `audit/discovery.py` | Branch discovery, CWD-first registry. |
| `audit/audit_display.py` | Rich result formatting — the score grid, the violation detail, the info lines. |
| `audit/incremental_cache.py` | Content-hash cache: a branch whose inputs did not change replays its stored score instead of re-running every checker. |
| `audit/artifact.py` | The untruncated violation set → `.seedgo/last_audit_<branch>.json`, because the console view is capped and the full set is what you actually debug against. |
| `module_root.py` | The guarded `module_file()` — the one import-time `__file__` resolve in the branch. |
| `registry_scan.py` | Case-EXACT registry discovery — the one reader every lane uses. |

---

## Module and pack discovery

**Modules.** `discover_modules()` in `apps/seedgo.py` loads every `.py` in `apps/modules/`.
Each module's `handle_command(command, args)` is called in discovery order and the first one
returning `True` wins. Nothing is registered by hand, which is why the bare-branch
introspection can list the verbs truthfully.

**Packs.** A checker pack is a `handlers/*_standards/` directory with a `pack.json`.
`standards_audit` strips the `_standards` suffix for command routing
(`aipass_standards/` → `audit aipass`); `standards_query` uses the full directory name
(`standards_query aipass_standards`). Four packs live here today and the bare branch command
counts them for you.

**CWD-first registry.** `_find_registry()` walks the CWD's parents first — that is what lets
the audit run inside an external project — then falls back to the `__file__` parents. It
globs `*_REGISTRY.json` rather than hardcoding a filename.

---

## Two lanes, and a finding can exist in only one

The **audit** walks a branch's `apps/**/*.py`; `tests/` is not in its corpus. The
PostToolUse **checklist** hook checks whatever file was just edited, including tests. A
bypass rule can therefore be live in one lane and dead in the other — the mistake a naive
rot detector makes.

A pack declares its own corpus in `pack.json`, and the banner printed over its scores is that
declaration, not the engine's file count.

---

## The incremental cache and `external_inputs()`

The cache keys a branch's score on the content of everything a checker reads. `README.md`,
`apps/**/*.py` and `tests/**/*.py` are watched by default; a checker that reads anything else
declares it:

- `BRANCH_INPUTS` — globs inside the audited branch. `readme_check` adds `docs/*.md`, so
  adding or deleting a docs file busts the cache instead of serving last run's index line.
- `BRANCH_INPUT_NAMES` — presence only, no content. `json_handler` scores which filenames
  exist and never reads them; some of those files are written DURING the audit, so
  fingerprinting their bytes would mark every branch dirty on every run and quietly disable
  the cache. An add or a delete still busts it.
- `external_inputs()` — absolute files OUTSIDE the branch. `startup_budget` names the owner
  files that publish caps, so moving a cap at its owner re-scores every branch; `trinity`
  names @memory's config and gold templates.

Without those two channels a cache hit is a stale answer wearing a fresh timestamp.

---

## The info channel (non-scored)

A checker may expose `check_branch_info(branch_path) -> list[str]`. `branch_audit` collects
those lines into `info_lines` and `audit_display` renders them dim, **always** — including at
100%. They carry no score and no pass/fail by construction, so a checker can surface context
it deliberately does not judge.

- `json_structure` lists the operator files in `{branch}_json/custom_config/` — names only;
  the content is operator-owned and never judged.
- `readme` carries the docs-index, named-path and rot-bait lane of DPLAN-0347. Each line is
  prefixed `(advisory)` because info lines are stored and re-rendered one at a time: a line
  quoted on its own must still arrive marked as advice.

---

## Bypass — documented exception

`.seedgo/bypass.json`, per branch. Each entry has a file, a standard, optional line numbers
and a **required reason**. Checkers call `is_bypassed()` per violation;
`bypass/utils.matching_rule()` is the single scope-aware matcher. Bypass is an intentional,
documented deviation — not a way to ignore a rule.

`bypass/inert.py` derives inert (unreachable) rules from the checker ASTs: a rule that could
never match anything the checker can produce is noise, and it says so.

A score of 100 with documented exceptions under it is a real score, not a clean sheet — read
the rules with it.

---

## `.seedgoignore` — throwaway paths, no reason required

Drop a `.seedgoignore` into any directory to exclude matching files and directories from
scans, audits and the per-file checklist. Same gitignore-style patterns and per-directory
nesting semantics as a real `.gitignore` (via `pathspec`): scope is that directory's subtree,
and a nested file ADDS to any ancestor's excludes rather than replacing them. A global
default (`tools/`) applies fleet-wide with zero setup — every branch's throwaway prototyping
space is deliberate, not standards-compliant by design.

Unlike bypass, an ignored file is removed from consideration entirely and needs no reason.
It does **not** touch diagnostics: ruff and pyright keep running on ignored files so auto-fix
still catches real errors while you write; only standards checks skip them. The engine is
`bypass/ignore_handler.load_ignore_entries()` / `is_seedgo_ignored()`.

---

## Diagnostics

`diagnostics` is consulted as a standard but has no `*_check.py`: pyright runs through the
audit pipeline (`apps/handlers/diagnostics/`, `apps/modules/diagnostics_audit.py`). Standalone
diagnostics is disabled.

---

## Refusals

An unknown command, pack, flag or branch REFUSES by name and exits non-zero (the owner's
ruling, the 2026-09-07 fleet sweep): exit 7 for an argument nobody recognised, 3 for a target
with nothing to check, 2 for a lane that could not run. `CommandRefused` lives in
`apps/modules/__init__.py`; `apps/seedgo.py` turns it into the exit code.

---

## Related

- [aipass_standards.md](aipass_standards.md) — the scored pack this engine runs
- [context_standards.md](context_standards.md) — the advisory startup-budget pack
- [checklist_and_hooks.md](checklist_and_hooks.md) — the other lane
