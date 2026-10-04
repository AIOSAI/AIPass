[<- Back to the README](../README.md)

# Per-project config: the template, the trust hash, and the release notice

**Branch** hooks · **Code** `.aipass/hooks.json`, `.aipass/project_hooks.json`, `apps/handlers/config/loader.py`, `apps/handlers/config/trust_registry.py`, `apps/modules/release_notice.py`

`.aipass/hooks.json` decides what fires for a project; `.aipass/project_hooks.json` is the template `aipass init` stamps into a new one. Which config a session runs, and when trust matters, is the loader's call (below). Security never depends on trust: an untrusted, missing or unreadable config still runs the gates.

---

## Which config runs — `loader.py` (since DPLAN-0356)

`resolve_config()` walks up from the working directory:

- **Inside AIPass** (AIPASS_HOME), the root `.aipass/hooks.json` is used with NO trust check. Editing it changes what fires; it never turns the hooks off. It is a protected file: only the verified admin seat writes it (see [git_gate.md](git_gate.md)).
- **A branch-level `.aipass/hooks.json` inside AIPass is IGNORED**, with a WARNING naming it. A branch cannot switch its own gates off.
- **An external project** — a nested project root (a directory holding a `*_REGISTRY.json`, like `projects/baud`) or anything outside AIPASS_HOME — runs its own config only when the trust registry vouches for it (`aipass trust <path>`). Changing that file breaks its trust hash, and the trust-break banner fires for external projects only.
- **Never "no hooks".** An untrusted, missing or unreadable config falls back to the gate set: the gate entries of AIPASS_HOME's config, else the built-in set in `handlers/config/gates.py`, logged at ERROR.
- A trusted external project inside AIPASS_HOME gets the gates forced over its config; a trusted project outside AIPass owns its gates.
- A home config that names no gate gets the built-in gates forced over it, logged at ERROR.

`drone @hooks status` explains why a project's own config is not running, and always ends "The AIPass gate set still runs."

## auto_watchdog — retired 2026-09-07

`auto_watchdog` fired on every PostToolUse to pattern-match one command shape and inject a reminder.
Its arming path is owner-only, which made it a refusal for 17 of 18 citizens. Retired under
FPLAN-0495 item 3:

1. `apps/handlers/lifecycle/auto_watchdog.py` → `auto_watchdog(disabled).py`; its tests were parked under
   `tests/parked/` and archived to `tests/.archive/` on 2026-09-08 (FPLAN-0513) after a clean session
   cycle, along with `presence`'s. `tests/parked/` no longer exists. The dotted-path entry in both configs names the old module, so the rename alone
   disables nothing — the flip below is what retires it.
2. `"enabled": false` in **both** `.aipass/hooks.json` and `.aipass/project_hooks.json`. One line
   changed per file; nothing else was touched.

The AIPass root config needs no trust re-enrol for this (see above). Archive the handler only after a
session cycle proves nothing was connected.

## The template ruling — what a project gets, and what stays framework-only

`.aipass/project_hooks.json` is the base config `aipass init` copies into a new project. It used to be
described as a mirror of AIPass's own `.aipass/hooks.json` and had drifted 13 handlers behind it. On
2026-09-09 (DPLAN-0335 leg 2) every one of those was ruled individually rather than bulk-copied; this
table is the record. `aipass init update` merges the template into a project by union, so anything
ruled *project* below reaches Vera-Studio, wren and `projects/*` on their next apply.

| Handler | Event | Ruling | Why |
|---|---|---|---|
| `temporal` | UserPromptSubmit | **project** | One line off the host clock. No AIPass state, no project assumptions, no dependency. |
| `context_gauge` | UserPromptSubmit | **project** | Reads the Claude Code transcript and nudges `/prep` before the compact ceiling. That is a Claude Code fact, not an AIPass one — every project manager compacts. |
| `persistent_alert` | UserPromptSubmit | **project** | Reads the project's *own* `.aipass/alerts.json`; the walk-up stops at the project root. No file means silent, so it costs nothing and hands projects an alert channel they currently cannot use. |
| `pre_compact_prep` | PreCompact | **project** | Stamps the compacting branch's own `.trinity/local.json`. Memory that survives compaction is the platform's headline promise, and it is not AIPass-specific. |
| `post_compact_regrounding` | PostToolUse | **project** | Re-injects branch/identity/kernel/navmap after a compact — the four files `init` scaffolds into every project — in parts of at most 9,000 chars, one per tool call, branch first. Claude Code shows the agent only a 2,000-char preview of a hook context over 10,000 (issue #752); every part logs `[HOOKS] regroup fired loader=… part=k/N bytes=… chars=…` to `hooks_cadence.log`. Also the carrier for the `release_notice` compact path. |
| `registry_gate` | PreToolUse | **project** | Every project has a `*_REGISTRY.json` (measured 2026-09-09: all four under `projects/`, plus Vera-Studio). Without this gate a project's sealed registry is an ordinary editable file. |
| `feedback_pulse` | UserPromptSubmit | **project**, ships `enabled: false` | Its own docstring scopes it to "external user projects (not the AIPass host)" — it belongs here more than in the framework file. Off by default, same as in the framework, so a project opts in. |
| `presence_gate` | UserPromptSubmit | framework-only | Enforces one interactive brain per branch across the AIPass fleet. A solo project has no competing citizen to fence, and a false block costs the user their session. Revisit if a project ever runs several citizens. |
| `presence_release` | Stop | framework-only, **retire candidate** | `presence_gate.handle_stop` is a documented no-op (Stop fires every turn; CC-native session files do the cleanup). Shipping it would buy a per-turn dispatch for nothing. Flagged for removal from the framework file too. |
| `auto_process` | UserPromptSubmit + PreCompact | framework-only | Spawns @memory's vectorize/rollover child. @memory is an AIPass branch, and its deps (`numpy`, `chromadb`, `fastembed`) are an optional extra a project will not have. |
| `compass_recall` | UserPromptSubmit | framework-only | Queries @devpulse's compass FTS, an AIPass-internal decision store. A project has no compass, so the handler would query nothing on every turn. |
| `user_message_relay` | UserPromptSubmit | framework-only | @skills' Telegram guest handler; needs per-branch chat registration and the `telegram` extra. Not a scaffold default. |
| `telegram_response` | Stop | framework-only | Same reason — delivery into the owner's Telegram chats. |
| `auto_watchdog` | PostToolUse | **dropped** | Retired 2026-09-07 (see above). Its handler file is already `auto_watchdog(disabled).py`, so the dotted path in the template resolved to nothing. Removed from the template on 2026-09-09; still present and `enabled: false` in `.aipass/hooks.json`, a protected file only the admin seat writes. |
| `release_notice` | SessionStart | **added** | DPLAN-0335 leg 2 — see below. |

Result: the template went from 18 handler entries to 25.

## `release_notice` — a manager hears that AIPass moved

`apps/handlers/lifecycle/release_notice.py` (wiring) over `apps/modules/release_notice.py` (the
deciding) tells a **project manager** that the installed AIPass is newer than the AIPass that wrote
their scaffold. It reads two files — the nearest `.trinity/passport.json` and the project root's
`.aipass/scaffold_manifest.json` — and writes none. It never runs the update: applying is the owner's
or @devpulse's call (the owner, 2026-09-09).

It is silent for every one of these: a passport whose `citizen_class` is not `manager`; a cwd with no
passport above it; a cwd outside any `*_REGISTRY.json` root; the AIPass source repo itself (`src/aipass`
plus a root `pyproject.toml` — `aipass init update` refuses its own repo, so a notice there could never
be cleared, and @devpulse's passport says `manager`); and a scaffold already at the installed version.
An absent or unparseable manifest counts as **behind** — a project that cannot say which AIPass wrote it
has not been stamped by leg 3 yet. Versions compare as zero-padded integer tuples rather than through
`packaging.version`, because `packaging` is not in this project's declared `dependencies` and a hook must
not rest on whatever pip left in the venv.

Two doors, one code path:

| Door | Wiring | Provider entry needed |
|---|---|---|
| SessionStart (`source` `startup` / `clear`; `resume` and `compact` skipped) | `project_hooks.json` → `SessionStart.release_notice` | **Yes** — `claude.py SessionStart:release_notice`, in the provider manifest and live settings since 2026-09-09. SessionStart is wired per handler: without that entry this hook is configured but never dispatched. |
| Post-compact regroup | `post_compact_regrounding` opens its branch section with the block, so it lands in part 1 of the re-ground on every seat | No — PostToolUse is a fan-out event |

---

## Related

- [wiring.md](wiring.md) — the per-handler provider entries a new SessionStart or PreCompact handler needs
