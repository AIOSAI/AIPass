[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

# AIPass

> **An AI operating system.** Persistent memory, multi-agent orchestration, and autonomous citizens — all in one filesystem.

AIPass is a framework where AI agents live as **citizens** in a shared system. Each citizen has its own directory, identity, memories, and mailbox. They communicate, delegate work, enforce standards, and build their own capabilities over time — without stepping on each other's toes.

The goal: `pip install aipass`, run `aipass init` in any directory, and get a fully operational AI agent ecosystem. No cloud services, no external dependencies, no vendor lock-in.

## What We're Building

An operating system for AI agents. Not a chatbot wrapper. Not a prompt chain. A persistent, multi-agent environment where:

- **15 citizens** work in the same filesystem without isolation (no git worktrees, no sandboxes)
- **Dispatch locks** prevent conflicts — if an agent is working, incoming tasks queue instead of spawning duplicates
- **Persistent memory** survives across sessions via `.trinity/` files (identity, session history, collaboration patterns)
- **Standards enforcement** keeps the system consistent as it grows (seedgo runs 24+ automated checks)
- **Inter-agent messaging** lets citizens email each other, dispatch tasks, and wake each other up
- **Everything is tracked** — design plans (DPLANs), execution plans (FPLANs), and seedgo audits make changes traceable even when 500+ files change in a single session

## Current State: Beta

**It works.** The pieces are all in place and the system runs well in a single project. We're past prototyping — 15 branches are operational, tested, and communicating.

**What we're solving now:**

- **Multi-project isolation** — `aipass init` should work in any directory, creating its own registry and credentials. Right now the system assumes one project. We're adding a credential model (UUID-based registry matching) so agents always know which project they belong to, even if multiple AIPass projects exist on the same machine.
- **System-wide compliance** — as we make large-scale changes (stderr routing, import patterns, error handling), seedgo audits ensure nothing drifts. We're refining the checkers to eliminate false positives and catch real issues.
- **Cross-platform reliability** — Linux and Windows tested. macOS is structurally supported but needs a dedicated testing pass. All paths use `pathlib`, no hardcoded paths, secrets stored at `~/.secrets/aipass/`.
- **Agent agnosticism** — currently focused on [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (hooks for auto-diagnostics, prompt injection, session recovery). But AIPass is designed to not depend on any single provider. `agents.md` and `gemini.md` can bootstrap the system for Codex and Gemini — you lose hooks but keep the core. The plan is truly agnostic: any agent, anywhere, persistent memory, no vendor lock-in.

## Getting Started

### Install

```bash
git clone https://github.com/AIOSAI/AIPass.git
cd AIPass
./setup.sh
source .venv/bin/activate
```

`setup.sh` creates the venv, installs the package, generates the branch registry (15 branches), bootstraps identity files for every branch, and installs hooks. Idempotent — safe to re-run.

> **Why clone?** You can `pip install aipass`, but during beta we recommend cloning. Your agents can see the source, read other branches, and help you troubleshoot. Once the system stabilizes, `pip install` + `aipass init` will be the standard path.

Verify:

```bash
drone systems          # Should show 15 branches
```

### Start With Devpulse

Devpulse is the orchestration hub — your first relationship in the system. Start here.

```bash
cd src/aipass/devpulse
claude
```

Then just talk to it. Ask what the system is, what's been built, what branches exist, how drone works, what it knows, what it doesn't. Devpulse will investigate, dispatch other branches, and bring information back to you.

**The pattern:** You work with devpulse. Devpulse dispatches to specialists. Specialists do the work and report back. You never need to context-switch between 15 agents — devpulse is your single point of contact.

Once devpulse confirms the core systems are working (email, drone routing, flow plans), you can start exploring individual branches directly with `cd src/aipass/{branch} && claude`.

### What Each Branch Does

Every branch is a citizen — an expert in its domain with its own memories and identity.

| Branch | Role |
|--------|------|
| `devpulse` | **Start here.** Orchestration hub — coordinates everything |
| `drone` | Command routing — `drone @branch command` resolves and routes |
| `seedgo` | Standards enforcement — 24-standard audit pack, system compliance |
| `prax` | Logging and monitoring (the only logger in the system) |
| `cli` | Terminal display, stderr routing, project commands |
| `flow` | Workflow management — FPLANs (execution) and DPLANs (design) |
| `ai_mail` | Inter-agent messaging, dispatch, wake |
| `spawn` | Branch lifecycle — create, update, credential injection |
| `trigger` | Event-driven automation, circuit breaker |
| `api` | LLM access via OpenRouter |
| `backup` | Multi-mode backup (snapshot, versioned, Google Drive) |
| `daemon` | Background scheduler, cron, notifications |
| `memory` | Vector memory bank (ChromaDB) |
| `commons` | Social network — posts, rooms, artifacts |
| `skills` | Capability framework — discoverable, executable skill units |

## How It Works

### No Isolation, No Problem

Most multi-agent systems isolate agents in separate environments. AIPass doesn't. All 15 citizens work in the same filesystem, same git repo, same codebase. This is intentional.

Each citizen owns its directory (`src/aipass/{name}/`). It doesn't touch other branches' files. If it finds an issue in another branch, it sends an email. Dispatch locks prevent two instances of the same agent from running simultaneously — no toe-stepping, no race conditions.

This only works because of discipline: standards enforcement, persistent memory, and clear ownership boundaries.

### Tracking at Scale

When a session produces 500+ file changes across 10 branches, you need tracking. AIPass uses:

- **DPLANs** — design/planning documents. "Here's what we want to build and why."
- **FPLANs** — execution plans. "Here are the exact steps, and here's the status of each."
- **Seedgo audits** — automated compliance checks. Run before and after changes to measure drift.

Changes are never untracked. Every decision has a plan, every plan has a record.

### Persistent Memory

Every citizen has `.trinity/` files:

```
.trinity/passport.json       # Identity — who am I, what's my role
.trinity/local.json          # Session history — what happened, what I learned
.trinity/observations.json   # Collaboration patterns — how we work together
```

These grow over time. A citizen that's been through 20+ sessions knows things — patterns, gotchas, preferences, past decisions. When context compacts (conversation gets too long), memories survive because they're written to disk. When a new session starts, the citizen reads its memories and picks up where it left off.

## Architecture

```
src/aipass/<branch>/
├── .trinity/           # Identity & memory
├── .aipass/            # System prompt
├── .ai_mail.local/     # Mailbox
├── apps/
│   ├── <branch>.py     # Entry point (drone routes here)
│   ├── modules/        # Business logic
│   └── handlers/       # Implementation
└── README.md
```

All branches follow this structure. Drone resolves `@name` to paths via `AIPASS_REGISTRY.json` — no hardcoded paths between modules.

## Requirements

- Python 3.10+
- No external API keys required for core functionality
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) recommended (hooks provide auto-diagnostics, prompt injection, session recovery)

## License

MIT
