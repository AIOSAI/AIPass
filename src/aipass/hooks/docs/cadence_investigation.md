[<- Back to the README](../README.md)

# Cadence: the per-turn injection counter

The per-turn injection cadence for the prompt loaders (`tier0`, `navmap`, `identity`, `branch`, `alert`,
`email`): how the turn is counted per session, across sibling processes, and when a loader fires.

---

## 1. Per-session turn counter — session keying

`CLAUDE_CODE_SESSION_ID` is available as an env var to every hook invocation (UUID format, stable across turns, unique per session). Counter file keyed by session_id at `aipass-cadence-{session_id}.json` in the system temp dir (`tempfile.gettempdir()`).

UserPromptSubmit stdin fields: `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `prompt`. The field is `prompt` (not `user_prompt`); `session_id` IS present in hook_data.

## 2. Execution model — separate processes

**Each hook runs as a separate OS process.** The provider settings register one command per UserPromptSubmit handler (`claude.py UserPromptSubmit:tier0_kernel`, `:navmap`, `:identity_injector`, `:branch_prompt`, `:email_notification`, … — 13 entries, see [wiring.md](wiring.md)), so Claude Code spawns that many Python subprocesses near-simultaneously on each prompt.

Module-level caches do NOT persist across these processes, so a counter each sibling advanced on its own would count one turn several times.

## 3. Multi-process dedup mechanism

The counter must advance exactly once per real user turn regardless of sibling process count.

Three-layer dedup, decided by `_should_increment()` under the lock `_load_and_increment()` holds:

1. **fcntl.flock** — exclusive lock around read-modify-write of the state file. Prevents simultaneous siblings from both reading stale state.
2. **mtime debounce** (~2s) — if the state file was modified < 2 seconds ago, treat as the same turn. The first sibling increments; the rest see fresh mtime and reuse the current value.
3. **Per-turn token** — `transcript_path` file size (monotonic, identical across siblings). Only increment if BOTH the debounce window elapsed AND the token changed. Kills pathologically fast turns and identical-prompt collisions.

Special case: `turn < 0` (post-compact reset) always increments — debounce must not swallow the turn-0 all-fire guarantee.

**One decision per prompt key.** The state file stores a prompt key, sha1(transcript size + NUL + prompt
text). When both the stored state and the payload carry a key, the key decides alone: the counter
increments only on a new key, however far apart the siblings run, and a real next prompt within 2s counts.
This covers a headless first prompt, which runs before the transcript exists: every sibling reads token 0,
which turns off layer 3, so without the key a sibling arriving 2s or more after the first write would count
a second turn. Layers 2 and 3 decide when there is no key: a payload with neither a prompt nor a
`transcript_path`, or a state file written without one. The token stays the transcript size, because the
ledger and the regroup stamp read it.

Module: `apps/modules/cadence.py` (shared utility, accessed via `importlib.import_module` from handlers).

## 4. Action-gated sound

Handlers return a `"sound"` key in their result dict. The engine plays it at the output collection point (`engine.py`), so sound is tied to handler action, not invocation. A skipped loader stays silent.

## 5. Edge cases

**FIRST TURN:** `should_fire` returns True when `turn==0`. Agent always gets full context on session start.

**CONCURRENT SESSIONS:** Counter file keyed by session_id — no cross-session conflict.

**COMPACTION:** PreCompact handler (`compact.py`) resets counter to -1 via `cadence.reset_counter()`. Next turn reads -1+1=0, all loaders fire.

**FILE I/O COST:** One flock + read + conditional write of ~30 bytes per turn. Negligible vs ~3,750 tokens saved.

---

## Summary

Multi-process safe cadence via fcntl.flock + a per-prompt key, with mtime debounce + transcript-size token when there is no key. Shared module in `apps/modules/`, handlers access via importlib. Action-gated sound system-wide.
