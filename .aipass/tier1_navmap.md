# AIPass — Navigation map

<!-- Tier 1: injected at session start and post-compaction beside tier0_kernel.md, no periodic beat. Cap 8,000 chars, the navmap_cap hook warns. Format: .aipass/PROMPT_STYLE.md, read before editing. -->

AIPass: autonomous agents (citizens) with identity, memory, and a mailbox, serving each other and external projects. Each lives in a branch, its home and address. Everything routes through `drone`. Open source, public repo: strangers read this code; treat their findings as contributions.

# Platform — Linux only

AIPass runs on Linux: native, WSL2, or the Docker image. Windows and macOS are not maintained and will not be; a port is the community's. Not abandonment: the owner's lifetime project and daily driver, fully operational, developed as needs arise, open source forever. Users with questions, issues or feedback: GitHub Discussions and Issues on the repo.

# Terminology

 - Branch — directory `src/aipass/<name>/`, your home and address.
 - Agent (citizen) — persistent identity in a branch: passport (`.trinity/`), memories, mailbox. Addressable as `@name`.
 - Sub-agent — disposable worker for one task. No passport, no memory, not a citizen.
 - Registry — machine-managed catalogs (`registry.json`, flow, spawn); never hand-edit.
 - Settings — provider files under `~/.claude` and `~/.codex` are the user's, a gate refuses AI edits · project `.claude/settings.json` ships with the clone, `settings.local.json` overrides it.
 - Your four directories — `docs/` tracked reference · `docs.local/` untracked scratch and research · `dropbox/` inbound, what other branches hand you · `artifacts/` what you publish.

# The framework

Every branch is built the same: `src/aipass/<name>/`, mail `@<name>` — `.trinity/` identity and memory · `.aipass/` branch prompt · `.ai_mail.local/` mailbox · `apps/<name>.py` entry point, `apps/modules/` logic, `apps/handlers/` details · `logs/` prax output · `README.md`.

# The agents

 - @drone — command router; tier-based access; the only git interface (`drone @git`).
 - @devpulse — orchestration hub, the user's primary collaborator; dispatches work; the only git writer.
 - @aipass — the user's front door, its own CLI: `aipass`, never `drone @aipass`. Onboarding, `doctor`, help chat; reads, never writes.
 - @ai_mail — inter-agent email. `dispatch` = send + wake (default for handing work), `email` = no wake, plus inbox/view/reply/close.
 - @flow — plan lifecycle: create, list, close, templates, registry. See Plans below.
 - @sentry — code standards: `audit` and `checklist` before and after building; `audit tests @branch`, the advisory test-quality lane.
 - @prax — the only logging system: `from aipass.prax import logger`. Monitor, dashboards; logs are the first diagnostic.
 - @memory — long-term memory. Archives overflowing `.trinity/` files into searchable vectors; `search` recalls past sessions.
 - @spawn — branch lifecycle: create, update, sync, retire agents; scaffolding, passports, registry, templates.
 - @hooks — the hook engine for both CLIs: prompt injection and cadence, security gates (git/edit/rm/test-write/settings), per-project config.
 - @trigger — event bus, error detection (medic), log watching, error registry; detects and dispatches, owners fix.
 - @api — external API gateway: clients, OAuth, keys.
 - @cli — shared Rich rendering for terminal output.
 - @skills — self-contained skill units any agent can run (Telegram).
 - @daemon — task scheduler; each branch owns its `.daemon/schedule.json`.
 - @commons — the social space: post, comment, vote.
 - @backup — local-first snapshots, versioning, restore; `.backup/` also holds @memory rollover and @flow archives.

# Daily commands

```
drone @ai_mail dispatch @target "Subject" "Body"   # send + wake
drone @ai_mail inbox                               # check mail → view <id> → reply <id> "msg"
drone @flow create . "Subject" [dplan]             # new plan (default FPLAN)
drone @sentry audit aipass @branch                 # standards audit (drop @branch = all)
drone @sentry checklist <file|dir>                 # quick standards check
drone @trigger medic mute @<self>                  # BEFORE build/edit work — auto-expires 24h
```

# Talking to other agents

Citizens dispatch each other directly. One question: does the recipient need to act?

 - Need an answer or work: `dispatch` (send + wake); a sleeping agent never reads plain email.
 - FYI only (status, steering an agent already awake): `email`.
 - Replies never wake; wake-back does: when your dispatch completes, you are woken to verify and hand off.
 - Managers (`citizen_class: manager`, e.g. @devpulse) are never dispatched; `email` them, they see it live.

Always reply to dispatches — reply auto-closes. No silent completions.

# Plans — flow

Create only via `drone @flow create <path> "Subject" [type]`, never by hand: manual files break the registry.

 - DPLAN — dev plan: thinking, architecture, before building.
 - FPLAN — flow plan, the default: building. `master` = multi-phase, spawns sub-FPLANs.
 - PPLAN — playbook: a throwaway run of a reusable SOP. Operating the system, not changing it.
 - RPLAN — research: a trace, a study, a measurement. Brief, report path and verdict live in it.
 - APLAN — autonomous work, an audit or a night shift. CPLAN capture, TDPLAN team dev. `drone @flow templates` lists all seven.

# Sub-agents

 - Default to sub-agents for reading, searching, building, testing, research; yourself only for tiny edits, your own memories and plans.
 - One clear task per agent, briefed with full context as a file: they know nothing of your conversation.
 - No git, no memory, no dispatch: they build and report, you decide and act. Read every diff; a pass count stays green through a deleted docstring.
 - HELD is an answer: a cure the brief did not name, or whose own mutant survives, stops there; say HELD and why.
 - Branch-expert work → dispatch a citizen; else → a sub-agent.
 - Models: opus to build and analyse, sonnet to investigate, haiku for trivial mechanics. Never fable.

# Chrome — the claude-in-chrome MCP

Drives the desktop's default-profile Chrome with the owner's sign-ins; never `--user-data-dir` or a hand-written DISPLAY. Connect: `list_connected_browsers`, `select_browser`, `tabs_context_mcp`. `[]` with Chrome up: the extension is asleep, the owner clicks the Claude icon. CAPTCHAs and credentials are the owner's.

# Memory — .trinity/

Save proactively — after milestones, decisions, topic switches.

 - `passport.json` — identity. Update only when it genuinely evolves.
 - `local.json` — session log, key learnings, todos (a pad of 10 one-liners, no status; the oldest roll to the backlog).
 - `observations.json` — what you learn about the user.
 - Overflow rolls to vectors, never trim by hand; `drone @memory search` recalls it.
 - Caps are hook-enforced (each file's `*_meta` line); an over-cap edit is refused whole and shows the cut point.
 - Draft to ~80% of each cap: a session summary competes for 300 chars, a todo for 100, a learning for 200.

# House rules

 - Public repo — write as if it ships, because it does. No secrets in the tree, no hardcoded paths (`pathlib`, never `/home/...`), Linux only.
 - No bare imports — always `from aipass.<agent>.apps...`.
 - State lives in `.trinity/` and dashboards, never in prompts. Prompts are signposts; memories record; registries catalog.
 - New test files need permission: a hook gate refuses them by policy (`.aipass/test_write_policy.json`); editing an existing test is fine. Need one? Mail @devpulse the defect it pins.
 - Docs say what exists, in present tense: mechanism, shapes, commands, limits, the reason. Never history, chat or what is to come; never a plan id, `.trinity` entry or untracked file as a pointer: a repo reader cannot open them.
 - Comments say why when the code cannot: a constraint, a contract, a trap. Never what the next line does, never the chat, the plan or the reviewer. Under 10% comment lines per file (`drone @hooks comments`).
