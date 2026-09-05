# JSON Handler Integrity Standard

## Purpose

Catches silent handler drift. Every branch's `apps/handlers/json/json_handler.py` must be a canonical handler capable of creating the full config/data/log triplet — not a stripped log-only fork that passes json_structure but cannot create config or data files.

## What Is Checked

### 1. Handler Capability (one must be true, strongest evidence first)

- **The canonical shim, by hash:** `sha256(file)` equals the bytes pinned in
  DPLAN-0325 section 3. This is the endpoint of the migration and the only path
  that proves anything: identical bytes are checked by identity, so a shim
  cannot drift by one character without saying so. Every path below asks
  whether a spelling appears *somewhere* in the file, which a docstring
  satisfies — measured 2026-09-03, a file whose entire content was a docstring
  saying it does NOT call `ensure_json_exists` passed the old check.
- **Binds the one service (transitional):** carries
  `from aipass.prax import json_handler` and no branch tokens — no
  `{branch}_json`, no `_JSON_DIR`, no `MAX_LOG_ENTRIES`, no `_create_default`,
  no `JsonHandler(`. Accepts a shim whose bytes differ cosmetically while the
  sweep is in flight; retires with part B.
- **Shared shim (retiring):** imports from `aipass.aipass.shared.json_handler`
  (the v3.0.0 pattern).
- **Standalone with triplet surface:** defines or re-exports
  `ensure_module_jsons` and/or `ensure_json_exists`.

A handler that only defines `log_operation()` without the triplet-creating functions is a **log-only fork** — it can write operation logs but cannot create config or data files. This is the exact failure case that caused memory's 25-log / 0-config / 0-data drift.

**Bind, never wrap.** The shim's names are bound (`save_json = _h.save_json`),
not wrapped (`def save_json(...): return _h.save_json(...)`). The service reads
the calling module at `sys._getframe(2)` to name the document it writes, so a
wrapper adds exactly one frame and silently sends every `log_operation` in that
branch into `json_handler_log.json`. Proved on a synthetic package 2026-09-03:
bind answers `caller_module`, wrap answers `shim_wrap`. The contract suite
(`seedgo/tests/test_json_handler_contract.py`) fails a wrapping shim on the IDENTITY axis; the symptom, if it
ever escaped, is an orphan `_log.json` with no config or data sibling — which
check 3 below catches.

### 2. Template Capability

A branch that ships `templates/citizen/apps/handlers/json/json_handler.py` — today only @spawn — has that file judged by the rule above. Nothing audited it before DPLAN-0325, which is how the template kept stamping a shape the fleet had already left: every citizen minted from it inherited that shape at birth. The template is checked unrendered, so its branch token is the `{{BRANCH}}` placeholder.

### 3. Disk Triplet Completeness

For each `*_log.json` in the branch's `{branch}_json/` directory, matching `*_config.json` and `*_data.json` must also exist. Catches the symptom (missing files on disk) even if the handler check alone misses it.

## Scope

`branch_level` — checked once per branch during audit.

## Scoring

Percentage of the checks that passed. Most branches run three (exists,
capability, disk triplets); a branch shipping the citizen template runs four.

| Score | Meaning |
|-------|---------|
| 100 | Every check passed |
| 66 | Handler capable but disk triplets incomplete |
| 33 | Log-only fork (cannot create triplets) |
| 0 | No handler file + no disk triplets |

Pass threshold: 75%. With four checks the ladder is 100 / 75 / 50 / 25 / 0.

## Known Exemptions

- **@hooks** — bypassed. The reason recorded here said "no json_handler.py"; measured
  2026-09-03, hooks ships one at the canonical path (245 lines) and 24 documents in
  `hooks_json/`. The bypass is live and the branch is still exempt by its owner's
  ruling — only the stated reason was wrong, and a bypass whose reason no longer
  matches the tree is unreadable from the outside.
- **@backup** — log-only fork, and the only branch the capability check still fails.
  Bypassed pending migration decision; `backup_json/` holds 2 documents, not the
  0/0/0 recorded here.

## Fix

Copy the canonical shim from DPLAN-0325 section 3 — the same bytes in every
branch. Do not retype it; the check is a hash.

```python
from aipass.prax import json_handler

_h = json_handler.for_module(__file__)

read_json = _h.read_json
save_json = _h.save_json
log_operation = _h.log_operation
# ... bind the remaining public names ...
```

Nothing else belongs in the file: no `_JSON_DIR`, no `MAX_LOG_ENTRIES`, no
`_create_default`, no branch name. The service derives this branch's document
directory from the shim's own `__file__` and honours `AIPASS_TEST_LOG_DIR` per
call, so a branch that needs more than the default owns it in a module of its
own rather than growing this one.

## History

- 2026-09-03: DPLAN-0325 — the fleet moves to ONE json service (prax-owned).
  Two passing shapes become four accept paths ordered by strength, with the
  canonical shim's sha256 as the endpoint. The citizen template becomes an
  audit subject. The older paths retire with part B of the sweep.
- 2026-06-14: Created after memory's silent handler drift was discovered and fixed. Memory had a 103-line v1.0.0 log-only fork that passed json_structure at 100% but produced 0 config / 0 data files.
