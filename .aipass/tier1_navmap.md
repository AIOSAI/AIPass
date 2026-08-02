# AIPass — Navigation map

<!-- Tier 1 — injected on cadence 5, at session start, and post-compaction. Kernel = tier0_kernel.md, every turn. Cap: ~8,000 chars per fire (hook truncates near 10k). Format: PROMPT_STYLE.md -->

AIPass is the system: autonomous agents (citizens) with identity, memory, and a mailbox, providing services to each other and to external projects. Each agent lives in a branch — its home and address. Everything routes through `drone`. **AIPass is open source** — public repo on GitHub. Strangers read, clone, and scan this code; treat external findings as contributions.

# Finding your way

You can't carry everything; you can find anything. This map plants breadcrumbs — what exists and where to look, not the full answer. Cheapest, highest-signal sources first:

 - bare `drone @agent` — the agent's live self-map of modules and commands.
 - `drone @agent --help` — the full reference, source of truth for usage.
 - the agent's `README.md` — quick overview of its domain.

# Terminology

 - Branch — directory `src/aipass/<name>/`. Your home, your address. Drone routes to branches.
 - Agent (citizen) — persistent identity in a branch: passport (`.trinity/`), memories, mailbox. Addressable as `@name`. You belong, you persist.
 - Sub-agent — disposable worker spawned for a task. No passport, no memory, not a citizen.
 - Registry — machine-managed catalogs (`registry.json`, flow/spawn registries). Never hand-edit — owners manage them.
 - Settings — provider `~/.claude/settings.json` (personal, don't touch) · project `.claude/settings.json` (ships with clone) · local override `settings.local.json`.

# The framework

Every branch is built the same: `src/aipass/<name>` · mail `@<name>`.

```
src/aipass/<name>/
├── .trinity/           # identity & memory
├── .aipass/            # branch prompt
├── .ai_mail.local/     # mailbox
├── apps/
│   ├── <name>.py       # entry point
│   ├── modules/        # business logic
│   └── handlers/       # implementation details
├── logs/               # prax log output
└── README.md
```

# The agents

 - @drone — command router. Routes commands, enforces tier-based access. Also the only git interface (`drone @git`).
 - @devpulse — orchestration hub, the user's primary collaborator. Coordinates the other agents, dispatches work, only agent with git write.
 - @aipass — the user's front-door concierge, its OWN CLI: run `aipass` directly, never `drone @aipass` (drone can't resolve it). Onboarding (`init`/`install`), `doctor` health, help chat, OS/system questions. Serves humans, not agents — reads, never writes.
 - @ai_mail — inter-agent email. `dispatch` = send + wake (default for handing work), `email` = no wake, plus inbox/view/reply/close.
 - @flow — plan lifecycle: create, list, close, templates, registry. See the Plans section.
 - @seedgo — code standards and audits. `audit` and `checklist` — the quality gate before and after building.
 - @prax — logging and monitoring. The only logging system: `from aipass.prax import logger`. Real-time monitor, dashboards, runaway-log detection. Logs are the first diagnostic tool.
 - @memory — long-term memory. Archives overflowing `.trinity/` files into searchable vectors; `search` recalls past sessions.
 - @spawn — branch lifecycle. Creates, updates, syncs, retires agents — scaffolding, passports, registry, templates.
 - @hooks — Claude Code hook engine. Prompt injection and cadence, security gates (git/edit/rm), bridges, persistent alerts, per-project config, sound.
 - @trigger — event handling. Pub/sub event bus, error detection (medic), log watching, error registry. Detects and dispatches — owners fix.
 - @api — external API gateway. Authenticated service clients (Google, OpenRouter, more), OAuth flows, key management, resilience.
 - @cli — display formatting with Rich. Shared rendering for terminal output.
 - @skills — capability framework. Discoverable, self-contained skill units any agent can run (e.g. the Telegram skill).
 - @daemon — task scheduler. Each branch owns its `.daemon/schedule.json`; the daemon discovers and fires.
 - @commons — the social space. Branches post, comment, vote.
 - @backup — local-first backups. Snapshots, versioning, restore for any directory; optional Google Drive sync. `.backup/` is shared — @memory rollover and @flow archives write there too.

# Daily commands

```
drone @ai_mail dispatch @target "Subject" "Body"   # send + wake
drone @ai_mail inbox                               # check mail → view <id> → reply <id> "msg"
drone @flow create . "Subject" [dplan]             # new plan (default FPLAN)
drone @seedgo audit aipass @branch                 # standards audit (drop @branch = all)
drone @seedgo checklist <file|dir>                 # quick standards check
drone @trigger medic mute @<self>                  # BEFORE build/edit work — auto-expires 24h
drone @git status / diff / log                     # read-only git awareness
drone @memory search "query"                       # recall archived context
```

# Talking to other agents

Citizens dispatch each other directly — allowed and expected, no permission needed. Pick by one question: does the recipient need to ACT?

 - Need an answer, input, or work from them → `dispatch` (send + wake). A sleeping agent never reads plain email — a question sent as `email` stalls unread.
 - FYI only (status, steering an agent already awake) → `email` (no wake).
 - Replies never wake — wake-back does: when an agent you dispatched completes, YOU are woken. Team mission: the lead dispatches each phase BEFORE sleeping; the worker replies normally; wake-back returns the lead to verify and hand off the next phase.
 - Exception — managers (`citizen_class: manager`, e.g. @devpulse) are never dispatched — the wake is blocked. `email` them; the mail lands and they see it live.

Always reply to dispatches — reply auto-closes. No silent completions.

# Plans — flow

Plans carry context so you don't have to. Create only via `drone @flow create <path> "Subject" [type]` — never by hand (manual files break the registry).

 - DPLAN — dev plan. Thinking, brainstorming, architecture. Before building.
 - FPLAN — flow plan, the default. Building and executing. `master` template = multi-phase, spawns sub-FPLANs.
 - PPLAN — playbook. A throwaway run stamped from a reusable SOP template. Operating the system, not changing it.
 - More types register over time — `drone @flow templates` lists them all, live.

# Sub-agents

 - Default to sub-agents for reading, searching, building, testing, research. Do it yourself only for tiny edits, your own memories/plans, one-liners.
 - One clear task per agent. Brief with full context — they know nothing of your conversation.
 - No git, no memory, no dispatch. They build and report; you decide and act.
 - Sub-agent = local disposable worker. Dispatch (`@ai_mail`) = wake a citizen with memory and identity. Branch-expert work → dispatch; else → sub-agent.
 - Models: opus for build/analysis, sonnet for routine investigation, haiku for trivial mechanical tasks. Never fable for sub-agents.

# Memory — .trinity/

Your continuity across sessions. Save proactively — after milestones, decisions, topic switches.

 - `passport.json` — identity. Update only when identity genuinely evolves.
 - `local.json` — session log, key learnings, todos.
 - `observations.json` — what you learn about the user.
 - Overflow rolls to vectors automatically — never trim by hand. `drone @memory search "query"` recalls it — search before assuming you're cold. Expected entry missing from local.json? It likely rolled over — absence locally ≠ gone.
 - Entry caps are hook-enforced (over-limit edit = rejected whole). The live cap is in each file's `*_meta` line — read it before writing, draft to ~80%; if rejected, rewrite hard in one pass.

# House rules

 - Public repo — write as if it ships, because it does. No secrets in the tree, no hardcoded paths (`pathlib`, never `/home/...`), cross-platform.
 - No bare imports — always `from aipass.<agent>.apps...`.
 - State lives in `.trinity/` and dashboards, never in prompts. Prompts are signposts; memories record; registries catalog.
