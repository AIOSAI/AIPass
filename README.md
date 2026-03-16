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
- **Init anywhere** — `aipass init` turns any directory into a self-contained AI workspace with its own registry, identity, and memories. No repo required. A business project, a research folder, a side project — each gets its own isolated environment that works immediately

## Current State: Beta

**It works.** 14 of 15 branches are operational, tested, and communicating. 53 PRs merged. 30+ orchestration sessions. We're past prototyping and into hardening — building the infrastructure that makes the system reliable at scale.

**Recently completed:**

- **CLI front door + init anywhere** — full discovery chain rebuilt so users can find and use `aipass init` through natural exploration. CLI rewritten to seedgo's auto-discovery pattern. Registered as a drone internal module — `drone @cli aipass init` works from any directory on any system, before any project exists. Creates a registry (UUID), passport, `.trinity/` memories, prompt files, and hooks. Every project is fully self-contained — no shared state, no cross-contamination between workspaces.
- **Memory introspection overhaul** — memory branch rewired to seedgo-compliant CLI discovery. Rollover and search introspection rebuilt. 18+ files ported back from archives (symbolic reasoning, templates, pool processor). Templates modernization in progress (FPLAN-0052).
- **Seedgo standards enforcement** — checklist command fixed, checker false positives addressed, handler guards added. PR #52 open.
- **Credential model** — UUID-based registry matching is live. Every project gets a unique registry ID, every citizen's passport carries it. `aipass init` creates a new project in any directory with its own credentials.
- **Stderr routing** — system-wide migration across 10 branches (48 files). CLI owns the display layer (`error()`, `warning()`, `fatal()` all route to stderr). Seedgo enforces it with an automated checker.
- **Dashboard pipeline** — Prax owns the dashboard end-to-end. Per-branch `STATUS.local.md` files sync to a central `STATUS.md` via `drone @prax status sync`.
- **Drone test suite** — 188 tests across 5 files. Interactive mode for human-facing commands. Credential verification with dedicated error hierarchy.
- **System governance** — git workflow, commit signing (`Co-Authored-By: @branch`), DPLAN/FPLAN documentation, and "How to Work" guidelines all codified in the global prompt.

**What we're solving now:**

- **Memory subsystem wiring** — symbolic reasoning, templates, and pool processor modules ported back but need full integration and testing. Templates modernization (spawn handler, v2 schema) in progress.
- **Lint cleanup** — 474 ruff violations remain (mostly unused imports from unwired modules). Blocked until seedgo audit coverage is higher — we can't confidently remove imports until we know what's actually used.
- **Dashboard CLI routing** — the Python API works but `drone @prax dashboard refresh --all` fails because argparse eats the flags before the module sees them. Known bug, fix pending.
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
claude --permission-mode bypassPermissions
```

Then just talk to it. Ask what the system is, what's been built, what branches exist, how drone works, what it knows, what it doesn't. Devpulse will investigate, dispatch other branches, and bring information back to you.

**The pattern:** You work with devpulse. Devpulse dispatches to specialists. Specialists do the work and report back. You never need to context-switch between 15 agents — devpulse is your single point of contact.

Once devpulse confirms the core systems are working (email, drone routing, flow plans), you can start exploring individual branches directly with `cd src/aipass/{branch} && claude --permission-mode bypassPermissions`.

> **Why bypassPermissions?** AIPass agents dispatch work, wake other branches, run drone commands, read and write files — all autonomously. Standard permission mode would prompt you on every action. The system is designed for autonomous operation with governance built into the architecture (standards enforcement, ownership boundaries, dispatch locks), not into permission dialogs.

> **Want a fast overview?** Every branch has its own `README.md` with architecture details, commands, integration points, and known issues. Have your agent read all 15 READMEs (`src/aipass/*/README.md`) and you'll have a solid understanding of the whole system in minutes. You can also run `drone @branch --help` on any branch to see its available commands and usage.

### What Each Branch Does

Every branch is a citizen — an expert in its domain with its own memories and identity.

| Branch | Role |
|--------|------|
| `devpulse` | **Start here.** Orchestration hub — coordinates everything |
| `drone` | AI-friendly CLI — every command is a single-line, non-interactive call |
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

### Drone — A CLI Built for AI

Drone's argument structure is designed so AI agents can operate the entire system through single-line, non-interactive commands. No interactive menus, no prompts, no multi-step wizards. Everything — sending emails, running audits, creating plans, managing backups — is a one-liner:

```bash
drone @ai_mail send @memory "Bug Report" "Search fails without torch" --dispatch
drone @seedgo audit aipass @memory
drone @flow create . "Fix search module" dplan
```

Once you learn the pattern (`drone @branch command [args]`), you know how to use every branch. The commands are self-explanatory — guess `drone @memory search "credential model"` and you'd be right. `drone @branch --help` fills in the rest.

Humans use it too. Interactive modes exist where they make sense (backup prompts, monitoring dashboards), but the core design is: AI agents shouldn't need interactive CLIs to be productive. Drop a command, get a result.

## Requirements

- Python 3.10+
- No external API keys required for core functionality
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) recommended (hooks provide auto-diagnostics, prompt injection, session recovery)

## License

MIT
