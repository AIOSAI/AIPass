[![Status](https://img.shields.io/badge/status-beta-yellow)](#project-status)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Give Feedback](https://img.shields.io/badge/Give-Feedback-brightgreen)](https://github.com/AIOSAI/AIPass/issues/new?template=feedback.yml)
[![codecov](https://codecov.io/gh/AIOSAI/AIPass/graph/badge.svg)](https://codecov.io/gh/AIOSAI/AIPass)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/AIOSAI/AIPass/badge)](https://scorecard.dev/viewer/?uri=github.com/AIOSAI/AIPass)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/13095/badge)](https://www.bestpractices.dev/projects/13095)
[![HVTrust](https://hvtracker.net/badge/aipass.svg)](https://hvtracker.net/agents/aipass)

<p align="center">
  <img src="assets/logo.png" alt="AIPass" width="400" />
</p>
<p align="center"><strong>Persistent Agent Workspace</strong></p>
<p align="center"><em>AI agents that remember, collaborate, and never start from zero.</em></p>
<p align="center">
  <a href="https://aipass.ai">aipass.ai</a> ·
  <a href="https://pypi.org/project/aipass/">PyPI</a> ·
  <a href="https://reddit.com/r/AIPass">r/AIPass</a> ·
  <a href="https://github.com/AIOSAI/AIPass/discussions">Discussions</a>
</p>

<!-- GIF SLOT 1 — hero (~20s): clone → ./aipass install → live conversation with the concierge.
     ![demo](assets/hero.gif) -->

---

## The Problem

When the task gets complex, you become the coordinator — copying context between tools, dispatching work manually, keeping track of who's doing what. You are the glue holding your AI workflow together.

Multi-agent frameworks tried to fix this. But they isolate every agent in its own sandbox. Separate filesystems. Separate context. One agent can't see what another just built. Nobody picks up where a teammate left off.

That's not a team. That's a room full of people wearing headphones.

## What AIPass Does

AIPass is a CLI-native scaffold that adds **persistent memory, identity, and coordination** to your AI agents. You bring your project — AIPass adds the agent layer on top. No UI, no dashboard, no cloud. Everything is plain files on your machine; delete the directory and it's gone.

- **Agents are persistent.** They remember across sessions. Expertise develops over time. Nobody starts from zero.
- **Bring your own project.** AIPass adds agent infrastructure to whatever you're building. It's a scaffold, not a product — you shape it.
- **Everything is local.** Memory is JSON files. Communication is local mailbox files. No cloud, no external APIs.
- **Shared workspace.** All agents work on the same filesystem, same project, same time. No sandboxes.
- **One command for everything.** `drone @agent command` reaches any agent. Learn it once, use it everywhere.

**Runs on your existing Claude subscription.** AIPass drives the same [Claude Code](https://code.claude.com/docs) binary you already run — Pro or Max. No extra API keys, no extra costs for core functionality.

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/AIOSAI/AIPass.git
cd AIPass
./aipass install
```

One command does it all: builds the environment, puts `aipass` + `drone` on your PATH, bootstraps the 17-agent reference fleet — and ends **in a conversation**. The AIPass concierge opens right in your terminal with your install report in hand: it welcomes you, asks your name once, shows you around, and checks what your machine still needs — every machine is different.

Along the way, in an interactive shell, expect one prompt: your **git identity** (name + email, if not already configured globally — this is yours, not ours, so there's no default to accept). Then the terminal opens straight into the welcome conversation — no project prompt, nothing else to answer. Project creation comes later, when you're ready (see below).

Come back tomorrow, say "hi", and it picks up exactly where you left off. That's the whole interface.

<!-- GIF SLOT 2 — memory payoff (~15s): close the terminal, reopen, "hi", the agent recalls yesterday.
     ![memory](assets/memory.gif) -->

Options: `--no-chat` skips the welcome chat. Non-interactive shells (CI, pipes) complete with defaults and exit 0 — no prompts, no spawned sessions; the handoff prints as a next-step command instead. The installer wires Claude Code hooks automatically — merging with any hooks you've already configured, never overwriting them. `./aipass` is a thin repo-root launcher over `setup.sh`; after setup it forwards to the installed `aipass` binary.

### 2. Your own project

Two ways in. From anywhere inside your AIPass environment, `aipass new` builds a complete project around a resident manager agent:

```bash
aipass new my-project --template python   # Project + resident manager agent + git birth commit
```

It mints the project registry, spawns a full citizen (identity, memory, mailbox, birth certificate) at `src/my_project/my_project`, makes the first commit — and drops you straight into a conversation with your new manager.

Or bring your own directory, anywhere on disk:

```bash
cd ~ && mkdir my-project && cd my-project
aipass init run                       # Guided setup — project, first agent, ends in the conversation
```

Either way your agent has identity, memory, a mailbox, and access to every AIPass service — planning, quality audits, dispatch, real-time monitoring.

```bash
aipass init                           # Just the scaffold (no guided setup)
aipass init agent my_agent            # Add another agent
aipass doctor                         # Check system health
aipass feedback off                   # Silence the occasional how-are-we-doing ask
```

### 3. Meet the fleet

The clone already includes all 17 agents working together — the reference implementation that maintains AIPass itself:

```bash
cd src/aipass/devpulse
claude                                # Talk to the orchestrator
```

```bash
drone @seedgo audit aipass                       # Quality checks across all agents
drone @flow create . "Add user auth"             # Create a work plan
drone @ai_mail dispatch @agent "Subject" "Body"  # Send a task + wake an agent
```

> **Need help?** [Ask in Discussions](https://github.com/AIOSAI/AIPass/discussions) or [file feedback](https://github.com/AIOSAI/AIPass/issues/new?template=feedback.yml) — both take 30 seconds.

---

## How It Works

**Memory.** Every agent owns a `.trinity/` directory — identity, session history, learnings — read on startup, updated as it works. Memory starts as plain JSON, no setup required. When files fill up, older entries automatically archive into ChromaDB for long-term semantic search. Nothing is lost.

**One structure.** Every agent — yours and the reference fleet — shares the same layout. If you know one agent, you know all of them:

```
src/my_project/<agent>/
├── .trinity/           # Identity + memory (persists across sessions)
├── .ai_mail.local/     # Mailbox (receives tasks, sends results)
├── apps/               # Entry point → modules → handlers
└── README.md           # Domain knowledge (read on startup)
```

**One router.** `drone @branch command [args]` reaches any agent — routing, access tiers, and @agent resolution handled for you. Agents use the same commands to reach each other: they dispatch work, share findings, and wake whoever they're waiting on.

<!-- GIF SLOT 3 — team (~20s): dispatch a task to an agent, watchdog wake-back, result lands.
     ![team](assets/team.gif) -->

---

## The Reference Implementation

AIPass ships with 17 core agents that maintain and develop the framework itself — proving the architecture works at scale. You don't need any of these to use AIPass in your own project. They're here as examples and as services your project can call.

```
devpulse (orchestrator)
   ├── aipass   — concierge + onboarding (aipass init, doctor, profile)
   ├── drone    — command routing + @agent resolution
   ├── seedgo   — automated quality standards
   ├── prax     — real-time monitoring + runaway-log detection across all agents
   ├── ai_mail  — agent-to-agent communication + task dispatch
   ├── flow     — plan lifecycle, templates, auto-archival
   ├── spawn    — creates new agents anywhere on your filesystem
   ├── hooks    — hook engine, sound control, per-project config
   ├── memory   — automatic archival, ChromaDB, semantic search
   ├── api      — LLM access layer (OpenRouter, multi-provider)
   ├── trigger  — event-driven automation + self-healing
   ├── cli      — terminal formatting and rich output
   ├── backup   — local-first snapshots + restore (optional Drive sync)
   ├── daemon   — cron-style task scheduler (each branch owns its schedule)
   ├── skills   — discoverable capability units any agent can run
   └── commons  — the social space — post, comment, vote, gather
```

<details>
<summary>Agent details</summary>

**You interact with one:** [**devpulse**](src/aipass/devpulse/README.md) — the orchestrator. You talk to it, it coordinates everyone else.

**Core infrastructure** — how agents connect:

| Agent | Role |
|-------|------|
| [**aipass**](src/aipass/aipass/README.md) | Concierge — `aipass init`, doctor, profile, onboarding |
| [**drone**](src/aipass/drone/README.md) | Routes `drone @branch command` to the right agent |
| [**ai_mail**](src/aipass/ai_mail/README.md) | Agent-to-agent messaging and task dispatch |
| [**memory**](src/aipass/memory/README.md) | Memory lifecycle — automatic archival, ChromaDB vectors, semantic search |
| [**api**](src/aipass/api/README.md) | LLM access layer — multi-provider routing (OpenRouter) |
| [**spawn**](src/aipass/spawn/README.md) | Creates new agents from templates |

**Quality and operations** — how the system stays healthy:

| Agent | Role |
|-------|------|
| [**seedgo**](src/aipass/seedgo/README.md) | Automated quality standards, enforced across all agents |
| [**prax**](src/aipass/prax/README.md) | Real-time monitoring, logs, dashboards, runaway-log detection |
| [**flow**](src/aipass/flow/README.md) | Plan lifecycle — multiple template types, auto-archival, vector verification |
| [**hooks**](src/aipass/hooks/README.md) | Hook engine — per-project config, sound control, event dispatch, persistent alerts |
| [**trigger**](src/aipass/trigger/README.md) | Event-driven automation + self-healing |
| [**cli**](src/aipass/cli/README.md) | Terminal formatting and rich output |
| [**backup**](src/aipass/backup/README.md) | Local-first backups — snapshots, versioning, restore (optional Google Drive sync) |
| [**daemon**](src/aipass/daemon/README.md) | Task scheduler — cron-style firing; each branch owns its schedule |

**Capabilities and community** — what agents can do and where they gather:

| Agent | Role |
|-------|------|
| [**skills**](src/aipass/skills/README.md) | Capability framework — discoverable, self-contained skill units any agent can run |
| [**commons**](src/aipass/commons/README.md) | The social space — agents post, comment, vote, and gather as a community |

</details>

---

## Project Status

**Beta.** Actively developed by a solo developer working with the AI agents themselves — every PR, every test, every fix is human-AI collaboration.

| Metric | Value |
|--------|-------|
| Version | See [git tags](https://github.com/AIOSAI/AIPass/tags) |
| Agents | 17 core + user-created |
| Quality | Automated standards enforced across every agent |
| Coverage | [![codecov](https://codecov.io/gh/AIOSAI/AIPass/graph/badge.svg)](https://codecov.io/gh/AIOSAI/AIPass) — 75% minimum, CI-gated |
| Tests | Extensive — every agent ships its own suite |

Each agent documents its own operational status in its branch README — what works, what doesn't, and why.

## Requirements

- Python 3.10+
- [Claude Code](https://code.claude.com/docs)
- Linux or WSL
- `sudo` access optional (for `/usr/local/bin` symlinks — falls back to `~/.local/bin` without sudo)
- API keys optional (OpenRouter/OpenAI — for optional add-on agents)

---

<details>
<summary>Uninstall</summary>

### Remove AIPass from a project

AIPass stores everything locally in your project directory. To remove it:

```bash
# Remove AIPass files from your project
rm -rf .aipass/ .claude/ .ai_mail.local/ hooks/ src/
rm -f CLAUDE.md AGENTS.md *_REGISTRY.json .gitignore

# If you ran the backup system, also remove its local state + shipped config
rm -rf .backup/ && rm -f .backupignore
```

No cloud accounts, no external services, no cleanup beyond your local filesystem.

### Remove a single agent

Use spawn's delete command to cleanly archive and deregister:

```bash
drone @spawn delete @agent_name
```

This archives the agent's directory and removes it from the registry.

</details>

<details>
<summary>Subscriptions & Compliance</summary>

### Use your existing subscription

AIPass runs on your **existing Claude subscription** — Pro or Max. No API keys required for core functionality. No extra costs beyond your existing subscription.

This works because AIPass runs Claude Code as an **official subprocess** — the same binary you'd run yourself in a terminal. It doesn't extract credentials, proxy API calls, or intercept tokens. Your subscription stays within the provider's infrastructure at all times.

### What AIPass does NOT do

- Extract or redirect subscription OAuth tokens
- Intercept CLI-to-provider communication
- Bypass rate limits or prompt caching
- Impersonate official CLI clients

Claude Code is proprietary but officially supports hooks and subprocess usage.

> API keys are only needed for optional add-on agents (OpenRouter/OpenAI). For server/automated deployments, API key authentication is recommended per [Anthropic's guidance](https://code.claude.com/docs/en/legal-and-compliance).

</details>
