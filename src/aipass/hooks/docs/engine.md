[<- Back to the README](../README.md)

# The engine

**Branch** hooks · **Code** `apps/modules/engine.py`, `apps/modules/promote.py`, `apps/handlers/bridges/mount.py`, `apps/handlers/config/gates.py`, `apps/handlers/config/output_merge.py`

The dispatch path from a normalized event to a handler, how a source edit becomes live code, why a broken gate refuses while a broken injector is skipped, and how the stdouts become one document.

---

## How It Works

1. Provider settings invoke the bridge one of two ways: `claude.py <Event>` (one fan-out entry, all enabled handlers — tool events) or `claude.py <Event>:<hook_name>` (one entry per handler — UserPromptSubmit, PreCompact, SessionStart). There is no bare `claude.py UserPromptSubmit` entry; it is 13 named ones.
2. The bridge loads `handlers/bridges/mount.py` by path, which serves the promoted copy (below) as `aipass.hooks.apps`, then calls `engine.run_event(arg, stdin)`
3. `run_event` resolves the config with `loader.resolve_config()` (see [project_config.md](project_config.md) — never "no hooks") and calls `engine.dispatch(event_type, stdin_data, config)`
4. Engine runs matching hooks sequentially, logs each to JSONL
5. First hook returning `{"decision": "block"}` with exit code 2 = bail (block the action)
6. A hook that fails to import, raises, times out, or exits 2 without JSON: a fail-closed gate is answered with a BLOCK (Gates Fail Closed, below); an injector is logged and skipped, and the next hook runs
7. Hook stdouts returned to the platform as ONE document (`handlers/config/output_merge.py`). Claude Code parses a hook's stdout as a single document: two JSON objects on two lines are a non-blocking hook error and NEITHER is applied. So:
   - a single output passes through untouched, and plain-only outputs are newline-joined;
   - once any handler answers in JSON, the answer is one object: `additionalContext` joined in handler order by a blank line, `systemMessage` joined by a newline, other keys first-handler-wins (a conflict is logged);
   - the merged context stays within Claude Code's 10,000 UTF-16-unit display limit. The post-compact re-ground is placed first, and a context that would cross the limit is dropped with a WARNING naming it — never silently.

## Promote — source edits are not live until promoted

Every hook process runs the PROMOTED copy of `apps/`, never the tree being edited, so a half-edited source file cannot crash a live gate. `drone @hooks promote` (`apps/modules/promote.py`) makes a copy live:

1. ruff `F821,F823,E9` (undefined names, syntax) over `apps/`
2. every source file compiles (`compileall`)
3. the branch's full suite passes, run against the source
4. `apps/` is copied to `<branch>/.live-<stamp>/`
5. the real bridge is smoke-tested against the copy: a raw `rm` must be refused and a Read allowed
6. `<branch>/.live-current` is rewritten atomically to name the copy

Any failed check refuses and leaves the live copy untouched. The newest 3 copies are kept. `drone @hooks promote status` shows which copy every hook process is running. The bridges (`claude.py`, `codex.py`) run from the source tree and hold nothing but argv, stdin, the mount and the `run_event` call; with no `.live-current` (a fresh clone) the source tree serves.

The workflow: edit -> test -> `drone @hooks promote`.

`drone @hooks promote rollback` points `.live-current` back at the newest kept copy older than the live one, after the same bridge smoke passes on it. It refuses, exits 1 and leaves the pointer as it is when nothing was ever promoted, when no older copy is kept, or when the older copy fails its smoke:

```
check_smoke: ok — <the smoke's detail>
live: .live-20200102T000000Z (was .live-20200103T000000Z)
```

## A Raising Handler's Log Lines

A handler that raises (any exception, `SystemExit` included, caught on its worker thread) is logged as two lines. The ERROR line holds its identity alone, so its fingerprint at @trigger never moves with the exception's text or the line number:

```
ERROR | [HOOKS] handler raised fault[<event>.<hook>.<handler dotted path>.<ExcType>@<file basename>] in <function> line <n>
INFO  | [HOOKS] handler raised, its text: <handler dotted path> <ExcType>: <text, newlines escaped, cut at 500 chars>
```

The marker holds no whitespace and no `]` (either is written `_`). A handler that outlives its timeout logs `handler timed out fault[<event>.<hook>.<handler>.HandlerTimeout@<module>.py] after <n>s` at ERROR. `logs/engine.jsonl` keeps the raw exception text in the row's `stderr_preview`. A `KeyboardInterrupt` on the calling thread is never caught.

## Gates Fail Closed

`apps/handlers/config/gates.py` says, in code and never in config, which hooks are gates and how each fails:

- `FAIL_CLOSED`: `edit_gate.handle`, `git_gate.handle`, `rm_gate.handle`, `testwrite_gate.handle`, `registry_gate.handle`, `edit_gate.tripwire_snapshot`, `edit_gate.tripwire`. When one fails to import, raises, times out, or exits 2 without a decision, the engine (`_gate_failure`, `_refuse_broken_gate`) answers with a BLOCK carrying the `BROKEN_GATE` text and logs `GATE BROKEN` at ERROR, the line @trigger escalates.
- `FAIL_OPEN`, each with its reason: `presence_gate` (a broken one would refuse every prompt, including the one that fixes it) and `subagent_gate` (a block at SubagentStop would trap the sub-agent in a loop).
- Everything else is an injector (prompt, lifecycle, notification handlers): a crash is logged and skipped, and one broken injector never blocks the rest.

Each fail-closed gate also refuses the call it guards when it crashes internally (its own `GATE_CRASHED` text). One layer up, the bridge refuses a PreToolUse call when the engine cannot load at all (block JSON and exit 2; Codex: a deny envelope); every other event exits 0 with the reason on stderr. The refusal is sent before the break is recorded, and nothing the record does can undo it ([wiring.md](wiring.md#when-a-bridge-breaks)).

## A Blocked Seat

When the engine cannot load, every PreToolUse in every session of the fleet is refused with `HOOKS BROKEN`, until a person fixes it. No agent can repair it: each agent's tools pass through the same bridge, so the agent can still read prompts and answer, but cannot run a command or edit a file. The repair is the owner's, from a terminal outside any agent session (a plain shell runs no hooks):

1. Read the cause: `tail -5 src/aipass/hooks/logs/bridge.log` (from the repo root). Each line names the exception and the event.
2. If the line names the promoted hooks copy (a module under `.live-<stamp>`), point back to the previous copy: `drone @hooks promote rollback`, or by hand, `ls -d src/aipass/hooks/.live-2*` lists the 3 kept, and `echo .live-<earlier stamp> > src/aipass/hooks/.live-current` serves it on the next hook call.
3. If it names another branch's source (prax most often: the bridges import it live, never from a snapshot), restore that file in the same terminal, with git or by hand.
4. Prove the gate answers again: `echo '{"tool_name":"Read","tool_input":{"file_path":"README.md"},"cwd":"'"$PWD"'"}' | .venv/bin/python src/aipass/hooks/apps/handlers/bridges/claude.py PreToolUse; echo "exit $?"` prints `exit 0`. A `HOOKS BROKEN` text and `exit 2` means it is still down.
5. The agents need nothing: their next tool call goes through.

A bridge file that is itself half-edited cannot answer at all; the shell guard on the PreToolUse row refuses for it, with `HOOKS BROKEN: claude.py exited <n> without an answer` (the table in [wiring.md](wiring.md#when-a-bridge-breaks)). Edit a bridge only from a terminal, and run step 4 after.

## Dynamic Dispatch

Handlers are called **dynamically at runtime** — the engine uses `importlib.import_module()` + `getattr()` on the dotted handler path from `hooks.json` (e.g., `aipass.hooks.apps.handlers.prompt.identity.handle`). Handlers are never statically imported. This means static analysis tools (including sentry's dead_code checker) cannot see that they are used: run unshielded, `dead_code` reports dispatched handlers as unreferenced, which is this indirection and not rot. Shielded, `dead_code` audits 100%.

`hooks.json` wires 42 entries under 40 distinct names — two names are wired twice: `auto_process` on UserPromptSubmit and PreCompact, `post_compact_regrounding` on PostToolUse and PostCompact. **41 of the 42 are `enabled: true`**: `feedback_pulse` is off by choice in this repo. The AIPass root `.aipass/hooks.json` is read with no trust check, so editing it changes what fires and never turns the hooks off; it is a protected file, written by the admin seat alone. Firing evidence is a *narrow* window — `logs/engine.jsonl` rotates at `JSONL_MAX_BYTES = 500_000` keeping one `.1` backup (prax `jsonl_writer.py`), so it holds minutes to tens of minutes of live traffic and absence from it is **not** evidence of a dead wire. A short window routinely misses the PreCompact-only handlers (`pre_compact`, `pre_compact_rollover`, `pre_compact_prep`) and the SessionStart ones (`cadence_reset`, `release_notice`), whose events fire rarely. `feedback_pulse` does appear, but as `{"action": "skipped_disabled"}`: it is wired `enabled: false` in this repo, so it is dispatched and declines.

## Related

- [wiring.md](wiring.md) — how the event reaches the bridge in the first place
- [diagnostics.md](diagnostics.md) — the two streams every dispatch is written to
