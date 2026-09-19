[<- Back to the README](../README.md)

# Cadence Investigation — DPLAN-0200

Per-turn injection cadence mechanism for prompt loaders (global_loader, branch_loader).
Investigation + build. Updated post-REDO to reflect the real execution model.

---

## 1. Per-session turn counter — session keying

`CLAUDE_CODE_SESSION_ID` is available as an env var to every hook invocation (UUID format, stable across turns, unique per session). Counter file keyed by session_id at `/tmp/aipass-cadence-{session_id}.json`.

UserPromptSubmit stdin fields: `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `prompt`. The field is `prompt` (not `user_prompt`); `session_id` IS present in hook_data.

## 2. Execution model — SEPARATE PROCESSES (corrected)

**Each hook runs as a separate OS process.** `settings.json` registers distinct commands per handler: `claude.py UserPromptSubmit:global_prompt`, `:branch_prompt`, `:identity_injector`, `:email_notification`, `:auto_process` — 5 separate Python subprocesses spawned near-simultaneously by Claude Code.

Module-level caches do NOT persist across these processes. The original investigation (pre-REDO) incorrectly assumed sequential single-process dispatch. Live observation proved the counter double-incremented (33 → 35 → 37 across single turns).

## 3. Multi-process dedup mechanism

The counter must advance exactly once per real user turn regardless of sibling process count.

Three-layer dedup in `_load_and_increment()`:

1. **fcntl.flock** — exclusive lock around read-modify-write of the state file. Prevents simultaneous siblings from both reading stale state.
2. **mtime debounce** (~2s) — if the state file was modified < 2 seconds ago, treat as the same turn. The first sibling increments; the rest see fresh mtime and reuse the current value.
3. **Per-turn token** — `transcript_path` file size (monotonic, identical across siblings). Only increment if BOTH the debounce window elapsed AND the token changed. Kills pathologically fast turns and identical-prompt collisions.

Special case: `turn < 0` (post-compact reset) always increments — debounce must not swallow the turn-0 all-fire guarantee.

Module: `apps/modules/cadence.py` (shared utility, accessed via `importlib.import_module` from handlers).

## 4. Action-gated sound

Handlers return a `"sound"` key in their result dict. The engine plays it at the output collection point (`engine.py`). Removed all scattered leading `speak()` calls — sound is now tied to handler action, not invocation. A skipped loader stays silent.

## 5. Edge cases

**FIRST TURN:** `should_fire` returns True when `turn==0`. Agent always gets full context on session start.

**CONCURRENT SESSIONS:** Counter file keyed by session_id — no cross-session conflict.

**COMPACTION:** PreCompact handler (`compact.py`) resets counter to -1 via `cadence.reset_counter()`. Next turn reads -1+1=0, all loaders fire.

**FILE I/O COST:** One flock + read + conditional write of ~30 bytes per turn. Negligible vs ~3,750 tokens saved.

---

## Summary

Multi-process safe cadence via fcntl.flock + mtime debounce + transcript-size token. Shared module in `apps/modules/`, handlers access via importlib. Action-gated sound system-wide. 438 tests, seedgo 100%.

*Investigation by @hooks, 2026-06-08. Updated post-REDO 2026-06-09.*
