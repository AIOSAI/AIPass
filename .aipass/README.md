# `.aipass/` — project prompt & hook config

This folder holds the **project-level prompt** and **hook configuration** for the AIPass
repo, plus the **templates** `aipass init` stamps into every new project. It is the
*project* layer; each branch additionally has its own branch prompt at
`src/aipass/<branch>/.aipass/aipass_local_prompt.md`.

> **Nothing here is dead weight.** Every file is live injection, live config, or a
> required new-project template. Superseded files live in `.archive/` (never deleted).

## One prompt system, every runtime

There is **one** source of prompt truth — the **tier files** — and **all** runtimes inject
the same content. We do **not** keep separate prompts per CLI. Only the *delivery* differs:

| Runtime | How the same content is delivered |
|---|---|
| **Claude Code** | **Tiered**: `tier0_kernel.md` + `tier1_navmap.md` at every fresh context and post-compaction, no periodic beat |
| **Codex CLI** | Injected **once at SessionStart** (no per-turn cadence): the same tier content, combined |

> ⚠️ **Migration in progress.** The Codex SessionStart hook
> (`.codex/hooks/session_start_identity.py`) currently still reads the legacy
> `aipass_global_prompt.md`. @hooks is wiring it onto the tier files. **Retire for one
> runtime = retire for all** — once Codex is on the tiers, `aipass_global_prompt.md` is
> read by nothing and moves to `.archive/`.

## Files

### Live — this repo's prompt + config
| File | What it is |
|---|---|
| `tier0_kernel.md` | **The kernel** — tiny identity + `drone --help` reflex + don't-get-lost rules. The always-on core, for every runtime. |
| `tier1_navmap.md` | **The navmap** — full agent roster, framework, terminology. The periodic/fuller layer, for every runtime. |
| `hooks.json` | Claude Code **handler registration** for this repo — which prompt/gate/notification handlers fire on which events. |
| `PROMPT_STYLE.md` | The writing-style guide every prompt here follows. |
| `.gitignore` | Whitelist guard — only files listed here are tracked; everything else in `.aipass/` is ignored. |
| `aipass_global_prompt.md` | **Legacy single global — being retired.** Disabled for Claude Code; Codex still reads it until its migration lands, then archived. **Not** the source of truth. |

### Templates — stamped into new projects by `aipass init` (`bootstrap.py`)
| File | Stamps → | Notes |
|---|---|---|
| `project_hooks.json` | new project's `.aipass/hooks.json` | **REQUIRED** — without it a new project's hooks never fire. Mirrors the live wiring (tier0 + navmap enabled, global disabled). |
| `project_AGENTS.md` | new project's `AGENTS.md` | the one instruction file, read by Claude Code and every other coding agent; `{name}` filled. |
| `project_global_prompt.md` | new project's `aipass_global_prompt.md` | **Legacy** — same retirement path as the global above (new projects ship tiers-only once Codex is migrated). |

## What a new project gets (`aipass init`)

`bootstrap.py` seeds a fresh project with the tiered system:
- `tier0_kernel.md` + `tier1_navmap.md` → the prompt content (every runtime)
- `hooks.json` (from `project_hooks.json`) → tier0 + navmap enabled, global disabled
- `AGENTS.md` (from `project_AGENTS.md`, else the host `AGENTS.md`, else generated)
- `aipass_global_prompt.md` (from `project_global_prompt.md`) → legacy, retiring with the above

`aipass init update` backfills the tier files + refreshes hooks for existing projects.

## Changing a prompt here

Run the **prompt-change playbook** so a change reaches every runtime and every seed path:

```
drone @flow create . "What changed" prompt_change
```

Golden rule: **live ≠ seeded.** Editing this folder fixes *this* repo only. New projects
come from the `project_*` templates + `bootstrap.py`; fresh clones get their machine-local
wiring from `setup.sh` + `.claude/provider_manifest.json` + `cadence.py` defaults. And
**every runtime** (Claude Code + Codex) must point at the same tier content.

## Archive & recovery

Superseded files move to `.archive/` (never deleted — house rule). Recover from there, or
from git history, any time. Current archive: the pre-tiering
`aipass_global_prompt.BACKUP-2026-06-09-S211.md` snapshot.
