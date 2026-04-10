[![Status](https://img.shields.io/badge/status-beta-yellow)](HERALD.md)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/aipass)](https://pypi.org/project/aipass/)
[![CLIs](https://img.shields.io/badge/CLIs-Claude%20%7C%20Codex%20%7C%20Gemini-purple)](#cli-support)
[![Give Feedback](https://img.shields.io/badge/Give-Feedback-brightgreen)](https://github.com/AIOSAI/AIPass/issues/new?template=feedback.yml)

# AIPass

**Your AI agents remember yesterday.**

A local multi-agent framework where your AI assistants keep their memory between sessions, work together on the same codebase, and never ask you to re-explain context.

---

## Contents

- [The Problem](#the-problem)
- [What AIPass Does](#what-aipass-does)
- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
- [The 10 Agents](#the-10-agents)
- [CLI Support](#cli-support)
- [Project Status](#project-status)
- [Requirements](#requirements)
- [Subscriptions & Compliance](#subscriptions--compliance)

---

## The Problem

Your AI has memory now. It remembers your name, your preferences, your last conversation. That used to be the hard part. It isn't anymore.

The hard part is everything that comes after. You're still one person talking to one agent in one conversation doing one thing at a time. When the task gets complex, *you* become the coordinator — copying context between tools, dispatching work manually, keeping track of who's doing what. You are the glue holding your AI workflow together, and you shouldn't have to be.

Multi-agent frameworks tried to solve this. They run agents in parallel, spin up specialists, orchestrate pipelines. But they isolate every agent in its own sandbox. Separate filesystems. Separate worktrees. Separate context. One agent can't see what another just built. Nobody picks up where a teammate left off. Nobody works on the same project at the same time. The agents don't know each other exist.

That's not a team. That's a room full of people wearing headphones.

What's missing isn't more agents — it's *presence*. Agents that have identity, memory, and expertise. Agents that share a workspace, communicate through their own channels, and collaborate on the same files without stepping on each other. Not isolated workers running in parallel. A persistent society with operational rules — where the system gets smarter over time because every agent remembers, every interaction builds on the last, and nobody starts from zero.

## What AIPass Does

AIPass is a local CLI framework that gives your AI agents **identity, memory, and teamwork**. Verified with Claude Code, Codex, and Gemini CLI. Designed for terminal-native coding agents that support instruction files, hooks, and subprocess invocation.

**Start with one agent that remembers:**

Your AI reads `.trinity/` on startup and writes back what it learned before the session ends. That's the whole memory model — JSON files your AI can read and write. Next session, it picks up where it left off. No database, no API, no setup beyond one command.

```bash
mkdir my-project && cd my-project
aipass init
```

Your project gets its own registry, its own identity, and persistent memory. Each project is isolated — its own agents, its own rules. No cross-contamination between projects.

**Add agents when you need them:**

```bash
aipass init agent my-agent            # Full agent: apps, mail, memory, identity
```

| What you need | Command | What you get |
|---------------|---------|-------------|
| A new project | `aipass init` | Registry, project identity, prompts, hooks, docs |
| A full agent | `aipass init agent <name>` | Apps scaffold, mailbox, memory, identity — registered in project |
| A lightweight agent | `drone @spawn create <name> --template birthright` | Identity + memory only (no apps scaffold) |

**What makes this different:**

- **Agents are persistent.** They have memories and expertise that develop over time. They're not disposable workers — they're specialists who remember.
- **Everything is local.** Your data stays on your machine. Memory is JSON files. Communication is local mailbox files. No cloud dependencies, no external APIs for core operations.
- **One pattern for everything.** Every agent follows the same structure. One command (`drone @branch command`) reaches any agent. Learn it once, use it everywhere.
- **Projects are isolated by design.** Each project gets its own registry. Agents communicate within their project, not across projects.
- **The system protects itself.** Agent locks prevent double-dispatch. PR locks prevent merge conflicts. Branches don't touch each other's files. Quality standards are embedded in every workflow. Errors trigger self-healing.

**Say "hi" tomorrow and pick up exactly where you left off.** One agent or fifteen — the memory persists.

---

## Quick Start

### Start your own project

```bash
pip install aipass

mkdir my-project && cd my-project
aipass init                           # Creates project: registry, prompts, hooks, docs
aipass init agent my-agent            # Creates your first agent inside the project
cd my-agent
claude                                # Or: codex, gemini — your agent reads its memory and is ready
```

That's it. Your agent has identity, memory, a mailbox, and knows what AIPass is. Say "hi" — it picks up where it left off. Come back tomorrow, it remembers.

### Explore the full framework

Clone the repo to see all 10 agents working together — the reference implementation:

```bash
git clone https://github.com/AIOSAI/AIPass.git
cd AIPass
./setup.sh                            # Creates venv, installs, bootstraps 10 agents
drone systems                         # See all agents

cd src/aipass/devpulse
claude                                # Talk to the orchestrator
```

```bash
# Things you can do:
drone @seedgo audit aipass              # Run 33 quality checks across all agents
drone @flow create . "Add user auth"    # Create a work plan
drone systems                           # List every agent and what it does
```

---

## How It Works

**One agent:** Your AI reads `.trinity/` on startup and picks up where it left off. But memory files have limits. When they fill up, the memory agent automatically archives older entries into a searchable vector database (ChromaDB). Nothing is lost — it just moves from active memory to long-term recall.

**A team:** When one agent isn't enough, every agent shares the same structure:

```
src/aipass/<agent>/
├── .trinity/           # Identity + memory (persists across sessions)
├── .ai_mail.local/     # Mailbox (receives tasks, sends results)
├── apps/               # Entry point → modules → handlers
└── README.md           # Domain knowledge (the agent reads this on startup)
```

Identical layout everywhere. If you know one agent, you know all of them. One command reaches anyone:

```bash
drone @branch command [args]    # Every agent, every task. Drone handles routing.
```

```bash
drone @seedgo audit aipass                    # Run quality checks on everything
drone @flow create . "Refactor auth module"   # Create a work plan
drone @ai_mail dispatch @memory "Archive old sessions" "Find sessions older than 30 days"
```

**Two ways to work:**

- **Team mode (most of the time):** Talk to `devpulse`, dispatch work across the team. Agents work in parallel and report back.
- **Direct mode (for deeper work):** `cd src/aipass/memory && claude` — work one-on-one with a specialist when the problem needs focused domain expertise.

**AIPass ships with 10 core agents** that maintain and develop the framework — the reference implementation proving the architecture works at scale:

```
devpulse (orchestrator)
   ├── drone    — command routing + @agent resolution
   ├── seedgo   — 33 automated quality standards
   ├── prax     — real-time monitoring across all agents
   ├── ai_mail  — agent-to-agent communication + task dispatch
   ├── flow     — plan lifecycle, templates, auto-archival
   ├── spawn    — creates new agents anywhere on your filesystem
   ├── memory   — automatic archival, ChromaDB, semantic search
   ├── trigger  — event-driven automation + self-healing
   └── cli      — terminal formatting and rich output
```

These agents work on the **same filesystem, same project, same time** — no sandboxes, no worktrees. This is the pattern your projects inherit.

---

## The 10 Agents

You don't need to memorize this list. Start with `devpulse`, use `drone` to reach any agent, and learn the rest as your workflow expands.

**You interact with one:** [**devpulse**](src/aipass/devpulse/README.md) — the orchestrator. You talk to it, it coordinates everyone else.

**Core infrastructure** — how agents connect:

| Agent | Role |
|-------|------|
| [**drone**](src/aipass/drone/README.md) | Routes `drone @branch command` to the right agent |
| [**ai_mail**](src/aipass/ai_mail/README.md) | Agent-to-agent messaging and task dispatch |
| [**memory**](src/aipass/memory/README.md) | Memory lifecycle — automatic archival, ChromaDB vectors, semantic search |
| [**spawn**](src/aipass/spawn/README.md) | Creates new agents from templates |

**Quality and operations** — how the system stays healthy:

| Agent | Role |
|-------|------|
| [**seedgo**](src/aipass/seedgo/README.md) | 33 automated quality standards, enforced across all agents |
| [**prax**](src/aipass/prax/README.md) | Real-time monitoring, logs, dashboards |
| [**flow**](src/aipass/flow/README.md) | Plan lifecycle — 6 template types, auto-archival, vector verification |
| [**trigger**](src/aipass/trigger/README.md) | Event-driven automation + self-healing |
| [**cli**](src/aipass/cli/README.md) | Terminal formatting and rich output |

---

## CLI Support

AIPass works with three AI coding CLIs. Claude Code is the most tested.

| CLI | Autonomous Mode | Status |
|-----|----------------|--------|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | `claude -p "prompt" --permission-mode bypassPermissions` | Fully tested |
| [Codex](https://github.com/openai/codex) | `codex exec "prompt" --dangerously-bypass-approvals-and-sandbox` | Integrated, less tested |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `gemini -p "prompt" --approval-mode=yolo` | Integrated, less tested |

setup.sh auto-detects which CLIs are installed and configures hooks for each.

---

## Project Status

**Beta.** Actively developed by a solo developer working with the AI agents themselves — every PR, every test, every fix is human-AI collaboration.

| Metric | Value |
|--------|-------|
| Agents | 10 |
| Quality standards | 33 automated checks |
| Tests | 4,900+ (across all agents) |
| PRs merged | 192+ (created by agents, reviewed by human) |

Each agent documents its own operational status in its branch README — what works, what doesn't, and why.

For detailed session history, see [HERALD.md](HERALD.md).

---

## Requirements

- Python 3.10+
- At least one AI CLI: Claude Code (recommended), Codex, or Gemini CLI
- `sudo` access (for global CLI symlinks)
- API keys optional (OpenRouter/OpenAI — for optional add-on agents)
- **Platforms:** Linux (fully tested), macOS (untested, should work), Windows via WSL2

---

<details>
<summary>Subscriptions & Compliance</summary>

### Use your existing subscription

AIPass runs on your **existing CLI subscription** — Claude Pro/Max, Codex, or Gemini. No API keys required for core functionality. No extra costs beyond your existing subscription.

This works because AIPass runs each CLI as an **official subprocess** — the same binary you'd run yourself in a terminal. It doesn't extract credentials, proxy API calls, or intercept tokens. Your subscription stays within the provider's infrastructure at all times.

### What AIPass does NOT do

- Extract or redirect subscription OAuth tokens
- Intercept CLI-to-provider communication
- Bypass rate limits or prompt caching
- Impersonate official CLI clients

Claude Code is proprietary but officially supports hooks and subprocess usage. Codex and Gemini CLI are open source (Apache 2.0).

> API keys are only needed for optional add-on agents (OpenRouter/OpenAI). For server/automated deployments, API key authentication is recommended per [Anthropic's guidance](https://code.claude.com/docs/en/legal-and-compliance).

</details>
