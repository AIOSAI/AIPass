[← Back to AIPass](../../../README.md)

# HOOKS

**Purpose:** Hook infrastructure for AIPass. One dispatch engine routes every hook event across
platforms (Claude Code, Codex) with per-project configuration, full logging and gates that fail closed. On
one side it injects the grounding an agent wakes up with; on the other it fences the writes an agent
makes.
**Module:** `aipass.hooks`
**Version:** 1.3.0

---

## Quick Start

```bash
drone @hooks status     # What is wired to fire in this project
drone @hooks log        # The most recent entries from the diagnostics stream
drone @hooks verify     # Provider settings against project config, non-zero on ERROR
drone @hooks promote    # Check, copy and make edited hook code live
drone @hooks --help     # Every verb, generated from the code that runs it
```

A platform bridge mounts the promoted copy of the hook code, the engine resolves the config (walking
up from the working directory; never "no hooks"), dispatches the handlers whose matcher fits, and
writes the outcome of each one to JSONL. A broken injector is logged and skipped; a broken gate
refuses what it guards. Source edits are not live until `drone @hooks promote`.

---

## What It Does

- **Grounds the session.** The branch prompt, the kernel, the fleet navmap, the passport identity
  block, the date, alert banners and a mid-turn re-ground after compaction, each rendered under a cap
  its owner publishes and fired on a cadence rather than every turn.
- **Fences writes.** A write into a file the seat does not own (another project, another branch, a
  project-level file), raw git and raw `gh`, reads too, for every seat, the admin seat included (if
  drone cannot do it, it cannot be done), raw `rm` for every seat and every other delete off the admin seat, the files that switch the
  gates, sealed registries and new test files are refused at PreToolUse — on the tool lane and on
  the shell lane both, because a fence only one of them can see is not a fence.
- **Measures memory writes.** A write to a `.trinity` file is judged against @memory's published
  caps, and a shell write that slips past the reader is reported afterwards by a tripwire.
- **Bridges platforms.** One thin normalization layer per provider, no business logic, so a second
  platform costs a bridge rather than a fork.
- **Logs every dispatch** to a JSONL stream that is the source of truth for hook diagnostics, with a
  quieter copy in prax for warnings, blocks and crashes.
- **Hands each project the switch, never over the gates.** `.aipass/hooks.json` decides what fires
  where; inside AIPass the gates run whatever a project config says, and security never depends on
  trust.

Not the platform's hook system — this bridges it rather than replacing it. Not the handlers' business
logic: each handler is self-contained and the engine only dispatches. Never another branch's files.

---

## Live Inventory

The list of modules and commands is generated from the code that runs them, so it is not written down
here and cannot go stale:

- `drone @hooks` — the self-map: every discovered module with its one-line description, and the data
  each gate publishes about what it deliberately cannot catch.
- `drone @hooks --help` — the full command surface: every verb, its arguments and its flags.

---

## How To Reach Me

- Mail: `drone @ai_mail email @hooks "Subject" "Body"` — a gate that refused work it should have
  allowed, a hook that did not fire, a prompt block that arrived cut or not at all.
- **A false refusal is a defect here, not a fault in your branch.** Say which command or file, and
  paste the refusal text verbatim: every gate names itself and its reason, so the text alone usually
  identifies the lane.
- **Adding or renaming a handler?** `.aipass/hooks.json` alone is not enough for UserPromptSubmit,
  SessionStart or PreCompact — those events are wired per handler in provider settings, which no
  branch may edit. Ask, and the exact entries come back with the answer. See
  [docs/wiring.md](docs/wiring.md).
- Caps other branches read from this branch are named as constants, never as numbers to copy:
  `BRANCH_CHAR_BUDGET`, `IDENTITY_CHAR_BUDGET` and `INTEGRATION_CHAR_BUDGET` in
  `apps/modules/grounding_content.py`. The contract for all three is
  [docs/prompt_injection.md](docs/prompt_injection.md).

---

## Commands

There is no command list on this page, deliberately: a hand-typed copy of the branch's own help output
rots the next time a verb is added or renamed. The generated surface above under **Live Inventory** is
always current, and the depth behind each verb is in the documentation index below. When a verb exists
and `--help` does not name it, the bug is in `--help`.

---

## Architecture

Three layers. `apps/hooks.py` is a thin router: it discovers the modules beside it and dispatches each
command to the one that claims it. `apps/modules/` holds one business-logic module per concern —
`engine` (the dispatcher itself), `engine_closure` (the files the engine imports, and the edit
check that keeps a NameError out of them), `door_trust_registry` (the one modules file aipass may
import for the trust registry), `cadence` (which turn a loader fires on), `injection_ledger` (what a
seat was told, per turn), `grounding_content` (the
injected blocks and their budgets), `write_ownership` (whose file a write lands in, read from the registries),
`bash_writes`, `shell_reader`, `shell_programs` and `testwrite_targets` (what a shell command can be
seen to write, the programs it runs, and which writes are new tests), `admin_seat` and `testgate_policy` (who is exempt,
and what the policy says), `promote` (source to live code), `protected_paths` (the files that switch
the gates), `comment_scan` and `comments` (the comment budget), `hookstatus`, `hooksound`, `alert_dismiss`, `feedback`, `context_window`,
`cc_sessions`, `cc_transcripts`, `diagnostics_state`, `hook_test`, `release_notice`, `sandbox` and
`wire_verify`. `apps/handlers/` holds the implementation, one directory per concern: `bridges/` per
platform, `prompt/` for injection, `security/` for the gates, `lifecycle/` for session and compaction
events, `notification/` for sound and mail, plus `config/`, `cli/` and the `json/` service every
branch shares.

Handlers are imported dynamically by dotted path at dispatch time, never statically, which is why no
handler is referenced anywhere in this tree and why static analysis cannot see them as used. Every
module-level `__file__` resolution goes through `apps/handlers/module_root.py`, because a hook must
import in a process whose working directory is gone.

The directory tree lives in this branch's own prompt (`.aipass/aipass_local_prompt.md`) — one place,
so it cannot disagree with itself.

---

## Documentation

Depth lives in [docs/](docs/), one file per gate or module group:

| Doc | What it covers |
|---|---|
| [docs/wiring.md](docs/wiring.md) | The two-tier model, each event's wiring shape, entry names vs handler filenames |
| [docs/engine.md](docs/engine.md) | Dispatch, promote, gates fail closed while injectors skip, the merged output, the import-time cwd rule |
| [docs/project_config.md](docs/project_config.md) | Which config runs and when trust matters, the project template and what it ships, the release notice |
| [docs/git_gate.md](docs/git_gate.md) | Raw git and gh refused for every seat, the drone twins, the protected files, the rm gate, and the settings backup |
| [docs/edit_gate.md](docs/edit_gate.md) | Who may write whose files, the project fence, the admin seat, what the gate cannot see |
| [docs/bash_writes.md](docs/bash_writes.md) | What a shell command can be seen to write, and what it misses |
| [docs/trinity_memory_gate.md](docs/trinity_memory_gate.md) | Memory writes: the shell refusal, the tripwire, and judging a write on what it authors |
| [docs/testwrite_gate.md](docs/testwrite_gate.md) | Agents do not create tests: the policy file, the fail-closed reasoning |
| [docs/prompt_injection.md](docs/prompt_injection.md) | The injection caps and where each is read from, the loud fail-open, the alert banners |
| [docs/diagnostics.md](docs/diagnostics.md) | The two log streams and the post-edit diagnostics block |
| [docs/comments.md](docs/comments.md) | The comment budget: the metric, the over-budget answer, the `comments` verb |
| [docs/sandbox.md](docs/sandbox.md) | The kernel filesystem boundary: policy per role, what is writable, the launch seam |
| [docs/boot_shim.md](docs/boot_shim.md) | The one script here that writes outside the repo |
| [docs/cadence_investigation.md](docs/cadence_investigation.md) | The per-turn injection counter and why it is keyed per session |
| [docs/cadence_redo_brief.md](docs/cadence_redo_brief.md) | The brief that rebuilt cadence after the suite modelled the wrong execution model |

---

## Integration Points

### Depends On

- `aipass.prax` — structured logging through `system_logger`, and the JSONL writer behind the
  diagnostics stream.
- `aipass.cli` — Rich console rendering for every command surface.
- `aipass.memory` — the published field shape and file budgets the `.trinity` caps are measured
  against. Read at call time through their own module; no cap is copied into this branch.
- `aipass.ai_mail` — the verified admin-caller rail the cross-project exemption consumes. There is no
  second implementation here.
- Python stdlib: `pathlib`, `importlib`, `json`, `shlex`, `subprocess`, `threading`.

### Provides To

- Every Claude Code and Codex session in the fleet — grounding injection, the security gates, and the
  record of every hook that fired.
- `aipass.ai_mail` — `build_policy`, `build_srt_config` and `resolve_bwrap_command` at the agent
  launch boundary.
- Every project `aipass init` creates — the template config, and the gates that ship enabled in it.

---

**Last Updated:** 2026-09-30

---
[← Back to AIPass](../../../README.md)
