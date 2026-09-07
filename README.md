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

AIPass is a CLI-native scaffold that adds **persistent memory, identity, and coordination** to your AI agents. You bring your project — AIPass adds the agent layer on top. No dashboard to run, no cloud to sign into. Everything is plain files on your machine: agent state lives in your project directory, plus a thin install layer outside it (Claude Code hooks, PATH entries, `~/.aipass/`) — the Uninstall section covers both.

- **Agents are persistent.** They remember across sessions. Expertise develops over time. Nobody starts from zero.
- **Bring your own project.** AIPass adds agent infrastructure to whatever you're building. It's a scaffold, not a product — you shape it.
- **Everything is local.** Memory is JSON files. Communication is local mailbox files. No cloud services, no data leaves your machine — agents that talk to outside APIs are opt-in, with your own keys.
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

One command does it all: builds the environment, puts `aipass` + `drone` on your PATH, bootstraps the 18-agent reference fleet — and, in an interactive shell, ends **in a conversation**. On the way into that conversation it runs a health check (`aipass doctor --fix` — heals what it can, automatically). The AIPass concierge opens right in your terminal, in the `aipass` agent's directory, with your install report and any hook-wiring problems doctor found in hand: it greets you by name, shows you around, and walks you through what your machine still needs — every machine is different.

Along the way, in an interactive shell, expect up to three quick prompts: your **git identity** (name + email, only if not already configured globally — this is yours, not ours, so skipping at the email prompt skips the step, and a bad address is never silently stored), your **name**, so the concierge knows what to call you, and **how the session should run** (asks before system-changing commands by default, or full autonomy). On Linux, `sudo` may ask for your password once to place the `/usr/local/bin` symlinks. Anything skipped or still missing gets collected into an "action needed" summary before the welcome conversation opens — no project prompt, nothing else to answer. Project creation comes later, when you're ready (see below).

Come back tomorrow, say "hi", and it picks up exactly where you left off. That's the whole interface.

<!-- GIF SLOT 2 — memory payoff (~15s): close the terminal, reopen, "hi", the agent recalls yesterday.
     ![memory](assets/memory.gif) -->

Options: `--no-chat` skips the welcome chat — and with it the doctor preflight, which runs as part of the chat handoff. Non-interactive shells (CI, or stdin not a terminal) complete with defaults and exit 0 — no prompts, no spawned sessions; the handoff prints as a next-step command instead. The installer wires Claude Code hooks automatically — merging with any hooks you've already configured, never overwriting them. `./aipass` is a thin repo-root launcher over `setup.sh`; after setup it forwards to the installed `aipass` binary.

Install also changes things outside the repo, and you should know what: it adds AIPass deny rules to your user-level Claude Code settings (no raw `git commit`/`push`/`reset`/`rebase`/`config`, no reading `~/.secrets/`) — these apply to every Claude Code project on the machine, not only AIPass; it appends a `claude` shell function to your `.bashrc`/`.zshrc` that, inside an agent directory, resumes that agent's seat instead of starting a blank session (everywhere else it passes straight through); it sets `git config --global pull.rebase true` when it sets your git identity; and it installs the `@anthropic-ai/sandbox-runtime` npm package globally if it is missing. Re-running install on Linux or macOS deletes and rebuilds `.venv`. The Uninstall section lists every file it touches.

### 2. Your own project

Two ways in. From anywhere inside your AIPass environment, `aipass new` builds a complete project around a resident manager agent:

```bash
aipass new my-project --template python   # Project + resident manager agent + git birth commit
```

It asks one question (create the resident agent? — `--no-agent` skips it), mints the project registry, spawns a full citizen (identity, memory, mailbox, birth certificate) at `projects/my-project/src/my_project/my_project`, makes the first commit on `main` and leaves you on a `dev` branch — and, in an interactive shell, drops you straight into a conversation with your new manager.

Or bring your own directory, anywhere on disk:

```bash
cd ~ && mkdir my-project && cd my-project
aipass init run                       # Guided setup — project, first agent, ends in the conversation
```

Either way your agent has identity, memory, a mailbox, and access to every AIPass service — planning, quality audits, dispatch, real-time monitoring. One extra step for a directory outside the AIPass tree: it can call the fleet right away, but for the fleet to dispatch work *to* it, declare it once with `drone @memory roots add <path>`.

```bash
aipass init .                         # Just the scaffold, current directory (no guided setup)
aipass init agent my_agent            # Add another agent
aipass doctor                         # Check system health
aipass feedback off                   # Silence the occasional how-are-we-doing ask
```

### 3. Meet the fleet

The clone already includes all 18 agents working together — the reference implementation that maintains AIPass itself:

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

**One structure.** Every agent — yours and the reference fleet — shares the same core layout (abridged — a fresh spawn also gets `docs/`, `tools/`, a dashboard file and a few dot-directories). If you know one agent, you know all of them:

```
src/my_project/<agent>/
├── .trinity/           # Identity + memory (persists across sessions)
├── .ai_mail.local/     # Mailbox (receives tasks, sends results)
├── .aipass/            # Branch prompt (how this agent introduces itself)
├── apps/               # Entry point → modules → handlers
├── artifacts/          # Birth certificate + agent-produced files
├── logs/               # Per-agent logs
├── tests/              # The agent's own test suite
└── README.md           # Domain knowledge (read on startup)
```

**One router.** `drone @branch command [args]` reaches any agent — routing and @agent resolution handled for you. Git is the one tiered surface: every agent can read (`drone @git status`, `log`, `diff`), and write access is earned per repo by that project's manager. Agents use the same commands to reach each other: they dispatch work, share findings, and wake whoever they're waiting on.

<!-- GIF SLOT 3 — team (~20s): dispatch a task to an agent, completion reported back, result lands.
     ![team](assets/team.gif) -->

---

## The Reference Implementation

AIPass ships with 18 core agents that maintain and develop the framework itself — proving the architecture works at scale. Four of them are the floor every AIPass agent stands on: your agents are created by **spawn**, reached through **drone**, and import **cli** and **prax** (display and logging) at startup. The rest you never have to run in your own project — they're here as examples and as services your project can call.

```
devpulse (orchestrator)
   ├── aipass   — concierge + onboarding (aipass init, doctor, profile)
   ├── drone    — command routing + @agent resolution
   ├── seedgo   — automated quality standards
   ├── prax     — real-time monitoring + runaway-log detection across all agents
   ├── ai_mail  — agent-to-agent communication + task dispatch
   ├── flow     — plan lifecycle, templates, auto-archival
   ├── spawn    — branch lifecycle — creates, updates, and deletes agents anywhere on your filesystem
   ├── hooks    — hook engine, sound control, per-project config
   ├── memory   — automatic archival, ChromaDB, semantic search
   ├── api      — external API gateway — keys, secrets, Google OAuth, LLM calls, host server (optional extra)
   ├── trigger  — event bus + error medic — fingerprints log errors, wakes the owning branch
   ├── cli      — terminal formatting and rich output
   ├── backup   — local-first snapshots + restore (optional Drive sync)
   ├── daemon   — task scheduler — interval, hourly, daily, once and rotation jobs (each branch owns its schedule)
   ├── skills   — discoverable capability units any agent can run
   ├── commons  — the social space — post, comment, vote, gather
   └── canary   — permanent test citizen — spawned, broken, and re-scaffolded so the working fleet never is
```

<details>
<summary>Agent details</summary>

**Day to day you talk to one:** [**devpulse**](src/aipass/devpulse/README.md) — the orchestrator. It coordinates everyone else. (At install time, the **aipass** concierge greets you first and handles setup.)

**Core infrastructure** — how agents connect:

| Agent | Role |
|-------|------|
| [**aipass**](src/aipass/aipass/README.md) | Concierge — `aipass init`, doctor, profile, onboarding |
| [**drone**](src/aipass/drone/README.md) | Routes `drone @branch command` to the right agent |
| [**ai_mail**](src/aipass/ai_mail/README.md) | Agent-to-agent messaging and task dispatch |
| [**memory**](src/aipass/memory/README.md) | Memory lifecycle — automatic archival, ChromaDB vectors, semantic search, vector verification of closed plans |
| [**api**](src/aipass/api/README.md) | Gateway for every external API — key and secret store, Google OAuth2, OpenRouter calls, usage tracking, host API server (needs the optional `[host]` extra) |
| [**spawn**](src/aipass/spawn/README.md) | Creates, updates, and deletes agents — the branch lifecycle manager |

**Quality and operations** — how the system stays healthy:

| Agent | Role |
|-------|------|
| [**seedgo**](src/aipass/seedgo/README.md) | Automated quality standards, enforced across all agents |
| [**prax**](src/aipass/prax/README.md) | Real-time monitoring, logs, dashboards, runaway-log detection |
| [**flow**](src/aipass/flow/README.md) | Plan lifecycle — seven plan types, auto-archival, hands closed plans to memory for vectorisation |
| [**hooks**](src/aipass/hooks/README.md) | Hook engine — per-project config, sound control, event dispatch, persistent alerts |
| [**trigger**](src/aipass/trigger/README.md) | Event bus and error dispatch — medic fingerprints log errors, deduplicates, and wakes the responsible branch |
| [**cli**](src/aipass/cli/README.md) | Terminal formatting and rich output |
| [**backup**](src/aipass/backup/README.md) | Local-first backups — snapshots, versioning, restore (optional Google Drive sync) |
| [**daemon**](src/aipass/daemon/README.md) | Task scheduler — interval, hourly, daily, once and rotation jobs, ticked by a systemd user timer; each branch owns its schedule |
| [**canary**](src/aipass/canary/README.md) | Permanent test citizen — absorbs spawn/dispatch/resume tests so no working agent is the experiment; everything in it is test data |

**Capabilities and community** — what agents can do and where they gather:

| Agent | Role |
|-------|------|
| [**skills**](src/aipass/skills/README.md) | Capability framework — discoverable, self-contained skill units any agent can run |
| [**commons**](src/aipass/commons/README.md) | The social space — agents post, comment, vote, and gather as a community |

</details>

---

## Project Status

**Beta.** Actively developed by a solo developer working with the AI agents themselves, plus a handful of outside contributions — every PR, every test, every fix is human-AI collaboration.

| Metric | Value |
|--------|-------|
| Version | See [git tags](https://github.com/AIOSAI/AIPass/tags) |
| Agents | 18 core + user-created |
| Quality | Automated standards, gated in CI across every agent |
| Tests | Every agent ships its own suite; the whole fleet runs on Linux for Python 3.10–3.13, and on Windows and macOS for 3.12 |

Most agents (11 of 18) document their own operational status in their branch README — what works, what doesn't, and why.

## Requirements

- Python 3.10+
- [Claude Code](https://code.claude.com/docs)
- Linux, macOS, or Windows via Git Bash (tested in CI; WSL should work but is untested)
- `sudo` access optional (Linux uses it for `/usr/local/bin` symlinks — falls back to `~/.local/bin` without it; macOS never asks)
- API keys / OAuth optional (OpenRouter, Google — only for optional add-on integrations)

---

<details>
<summary>Uninstall</summary>

### Remove AIPass from a project

AIPass keeps agent state inside your project directory. To remove it:

```bash
# Remove AIPass files from your project.
# ⚠️ In a brought-your-own project, src/, README.md, CLAUDE.md, pyproject.toml
# and .gitignore may be partly or wholly YOURS (init never overwrites existing
# files) — remove only what AIPass created and review the rest by hand.
rm -rf .aipass/ .claude/ src/<project>/<agent>/     # the agent dir holds its own mailbox, memory, logs
rm -f CLAUDE.md AGENTS.md README.md *_REGISTRY.json .gitignore pyproject.toml .venv
rm -f src/<project>/__init__.py src/<project>/tests/conftest.py   # init's package stub

# If you ran the backup system, also remove its local state + the generated ignore file
rm -rf .backup/ && rm -f .backupignore
```

`.venv` in a project is a symlink to the AIPass runtime, not a copy.

The installer also writes a layer outside the project. Remove all of it to erase AIPass completely:

- `~/.claude/settings.json` — hook wiring, plus `env.AIPASS_HOME`, `env.CLAUDE_CODE_DISABLE_AUTO_MEMORY`, the AIPass deny rules (git write verbs, `~/.secrets` reads) and two `ask` rules; each time doctor re-wires the hooks it leaves a dated `settings.json.bak.*` copy beside it. Also `~/.claude/commands/memo.md`.
- `aipass`/`drone` symlinks in `/usr/local/bin` or `~/.local/bin`.
- Your shell rc (`.bashrc`/`.zshrc`/`.bash_profile`): a PATH line, `AIPASS_HOME` and `PYTHONUTF8` exports, and the `claude()` boot-shim function between the `AIPass boot shim` markers. On Windows, a `drone` wrapper in your PowerShell profile.
- `~/.aipass/` — cross-project state: the fleet registry, trust registry, commons database, admin key, skills, Telegram bot state.
- `~/.secrets/aipass/` if seeded.
- `git config --global pull.rebase true`, set only if install also set your identity.
- Only if a `codex` binary was on PATH at install: `~/.codex/config.toml` is rewritten.
- Only if you ran `drone @daemon install-timer`: a systemd user timer, removed by `drone @daemon uninstall-timer`.
- Only on the no-sudo path with no usable system Python: a `uv`-managed interpreter under `~/.local/`.

No cloud accounts, no external services — everything to clean up is on your machine.

### Remove a single agent

Use spawn's delete command to cleanly archive and deregister:

```bash
drone @spawn delete @agent_name          # asks for confirmation; --yes skips it
```

This copies the agent's directory to `.archive/deleted_branches/` (minus `.venv`, `.git`, caches), removes it from the registry, then deletes the original. The fleet's own core agents (spawn, drone, devpulse, the registry owner) refuse deletion.

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

> API keys are only needed for the optional OpenRouter integration (the OpenAI SDK is used as its transport; there is no separate OpenAI provider). For server/automated deployments, API key authentication is recommended per [Anthropic's guidance](https://code.claude.com/docs/en/legal-and-compliance).

</details>
