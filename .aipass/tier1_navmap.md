# AIPass — Navigation map

<!-- Tier 1: injected at session start and post-compaction beside tier0_kernel.md, no periodic beat. Cap 8,000 chars, the navmap_cap hook warns. Format: .aipass/PROMPT_STYLE.md, read before editing. -->

AIPass: autonomous agents (citizens) with identity, memory, and a mailbox, serving each other and external projects. Each lives in a branch, its home and address. Everything routes through `drone`. Open source, public repo: strangers read this code; treat their findings as contributions.

# Terminology

 - Branch — directory `src/aipass/<name>/`, your home and address.
 - Agent (citizen) — persistent identity in a branch: passport (`.trinity/`), memories, mailbox. Addressable as `@name`.
 - Sub-agent — disposable worker for one task. No passport, no memory, not a citizen.
 - Registry — machine-managed catalogs (`registry.json`, flow/spawn registries). Never hand-edit.
 - Settings — provider files under `~/.claude` and `~/.codex` are the user's, a gate refuses AI edits · project `.claude/settings.json` ships with the clone · `settings.local.json` overrides locally.
 - Your four directories — `docs/` tracked reference · `docs.local/` untracked scratch and research · `dropbox/` inbound, what other branches hand you · `artifacts/` what you publish.

# The framework

Every branch is built the same: `src/aipass/<name>/`, mail `@<name>` — `.trinity/` identity and memory · `.aipass/` branch prompt · `.ai_mail.local/` mailbox · `apps/<name>.py` entry point, `apps/modules/` logic, `apps/handlers/` details · `logs/` prax output · `README.md`.

# The agents

 - @drone — command router; tier-based access; the only git interface (`drone @git`).
 - @devpulse — orchestration hub, the user's primary collaborator; dispatches work; the only git writer.
 - @aipass — the user's front door, its own CLI: run `aipass` directly, never `drone @aipass`. Onboarding, `doctor`, help chat. Serves humans; reads, never writes.
 - @ai_mail — inter-agent email. `dispatch` = send + wake (default for handing work), `email` = no wake, plus inbox/view/reply/close.
 - @flow — plan lifecycle: create, list, close, templates, registry. See Plans below.
 - @seedgo — code standards: `audit` and `checklist` before and after building; `audit tests @branch`, the advisory test-quality lane.
 - @prax — the only logging system: `from aipass.prax import logger`. Monitor, dashboards, runaway-log detection. Logs are the first diagnostic.
 - @memory — long-term memory. Archives overflowing `.trinity/` files into searchable vectors; `search` recalls past sessions.
 - @spawn — branch lifecycle: create, update, sync, retire agents; scaffolding, passports, registry, templates.
 - @hooks — the hook engine for both CLIs: prompt injection and cadence, security gates (git/edit/rm/test-write/settings), per-project config.
 - @trigger — event bus, error detection (medic), log watching, error registry. Detects and dispatches — owners fix.
 - @api — external API gateway: authenticated clients, OAuth, key management.
 - @cli — shared Rich rendering for terminal output.
 - @skills — self-contained skill units any agent can run (e.g. Telegram).
 - @daemon — task scheduler. Each branch owns its `.daemon/schedule.json`; the daemon fires it.
 - @commons — the social space: post, comment, vote.
 - @backup — local-first snapshots, versioning, restore. `.backup/` is shared with @memory rollover and @flow archives.

# Daily commands

```
drone @ai_mail dispatch @target "Subject" "Body"   # send + wake
drone @ai_mail inbox                               # check mail → view <id> → reply <id> "msg"
drone @flow create . "Subject" [dplan]             # new plan (default FPLAN)
drone @seedgo audit aipass @branch                 # standards audit (drop @branch = all)
drone @seedgo checklist <file|dir>                 # quick standards check
drone @trigger medic mute @<self>                  # BEFORE build/edit work — auto-expires 24h
```

# Talking to other agents

Citizens dispatch each other directly. One question: does the recipient need to act?

 - Need an answer or work from them: `dispatch` (send + wake). A sleeping agent never reads plain email.
 - FYI only (status, steering an agent already awake): `email` (no wake).
 - Replies never wake; wake-back does: when an agent you dispatched completes, you are woken. A lead dispatches each phase before sleeping and is woken to verify and hand off.
 - Managers (`citizen_class: manager`, e.g. @devpulse) are never dispatched; `email` them, they see it live.

Always reply to dispatches — reply auto-closes. No silent completions.

# Plans — flow

Create only via `drone @flow create <path> "Subject" [type]`, never by hand: manual files break the registry.

 - DPLAN — dev plan: thinking, architecture, before building.
 - FPLAN — flow plan, the default: building. `master` = multi-phase, spawns sub-FPLANs.
 - PPLAN — playbook: a throwaway run of a reusable SOP. Operating the system, not changing it.
 - RPLAN — research: a trace, a study of an external repo, a measurement. Brief, report path and verdict live in it.
 - APLAN — autonomous work, an audit or a night shift. CPLAN capture, TDPLAN team dev. `drone @flow templates` lists all seven, live.

# Sub-agents

 - Default to sub-agents for reading, searching, building, testing, research. Do it yourself only for tiny edits, your own memories and plans.
 - One clear task per agent, briefed with full context as a file: they know nothing of your conversation, and a paraphrase is where a rule loses its clause.
 - No git, no memory, no dispatch. They build and report; you decide and act. Read every sub-agent's diff: a pass count and a file list stay green through a deleted docstring and an oracle that cannot fail.
 - HELD is an answer. A cure the brief did not name, or whose own mutant survives, stops there: leave the line, say HELD and why.
 - Branch-expert work → dispatch a citizen (memory, identity); else → a sub-agent.
 - Models: opus for build/analysis, sonnet for routine investigation, haiku for trivial mechanical tasks. Never fable for sub-agents.

# Memory — .trinity/

Save proactively — after milestones, decisions, topic switches.

 - `passport.json` — identity. Update only when it genuinely evolves.
 - `local.json` — session log, key learnings, todos (a pad of 10 one-liners, no status; the oldest roll to the backlog).
 - `observations.json` — what you learn about the user.
 - Overflow rolls to vectors, never trim by hand; `drone @memory search "query"` recalls it. Absent locally is not gone.
 - Caps are hook-enforced, live in each file's `*_meta` line; an over-cap edit is refused whole and shows the cut point: trim that tail.
 - `sessions.summary`, `observations.note`: count the draft in tens as you write, trim before the edit; a whole session competes for 300 chars.
 - `todos.task`, `key_learnings.value`: draft to ~80%.

# House rules

 - Public repo — write as if it ships, because it does. No secrets in the tree, no hardcoded paths (`pathlib`, never `/home/...`), cross-platform.
 - No bare imports — always `from aipass.<agent>.apps...`.
 - State lives in `.trinity/` and dashboards, never in prompts. Prompts are signposts; memories record; registries catalog.
 - New test files need permission: a hook gate refuses them by policy (`.aipass/test_write_policy.json`); editing an existing test is fine. Need one? Mail @devpulse with the defect it pins. Never route around the gate.
 - Docs say what exists: mechanism, shapes, commands, limits, the reason, in present tense. Never history, chat or what is to come; never a plan id, a `.trinity` entry or an untracked file as a pointer, since a reader of the repo cannot open them.
 - Comments say why when the code cannot: a constraint, a contract, a trap. Never what the next line does, never the chat, the plan or the reviewer; that history goes in the commit and the plan. Budget under 10% comment lines per file; a hook says when a file is over (`drone @hooks comments`).
