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
- **Standards enforcement** keeps the system consistent as it grows (seedgo runs 34 automated checks, system-wide avg 93% compliance)
- **Diagnostic tooling** — 20 standalone scanners cover code quality, security, documentation, and compliance
- **Inter-agent messaging** lets citizens email each other, dispatch tasks, and wake each other up
- **Everything is tracked** — dev plans (DPLANs), execution plans (FPLANs), and seedgo audits make changes traceable even when 500+ files change in a single session
- **Init anywhere** — `aipass init` turns any directory into a self-contained AI workspace with its own registry, identity, and memories. No repo required. A business project, a research folder, a side project — each gets its own isolated environment that works immediately

## Current State: Beta

**It works.** All 15 branches operational. 111+ PRs merged. 48 orchestration sessions. 744 tests across the system. 173 drone commands discovered. System-wide compliance at 93% average across 34 automated standards checks.

**Recently completed:**

- **System-wide compliance sprint** — all 14 branches audited and dispatched for silent catch fixes in a single session. 13 branches completed autonomously (8 running in parallel). ~600 silent catch violations fixed across 150+ files. System average went from ~88% to 93%. Tracked via DPLAN-0052.
- **Seedgo 34-standard audit pack** — 10 new checkers integrated from diagnostic tools (silent catch, deep nesting, debug print, commented logger, unused function, dead code, help text, hardcoded key, test coverage, TODO). All auto-discovered via `*_check.py` pattern. Bypass system working with `.seedgo/bypass.json` per branch.
- **Deep nesting investigation** — spawn (12 functions: 7 justified, 5 refactorable), commons (14 functions: 9 justified, 5 refactorable), API (13 functions), ai_mail (27 functions), backup (6 functions). Justified functions bypassed, refactorable ones queued.
- **Dispatch UX redesign** — `drone @ai_mail dispatch @target "Subject" "Body"` sends + wakes in one command. `--fresh` flag for clean sessions. `email` command for mail-only (no wake). Fully tested.
- **PR v2 workflow** — commit-on-main architecture. Changes never leave your working tree. Feature branches are just pointers for GitHub's PR system. No more disappearing files.
- **Prax monitor** — fully operational with inotify file watching, branch detection, full message display. Used as secondary terminal to work around Claude Code's scroll limitation.

**What we're solving now:**

- **Deep nesting compliance** — 73% average across system. Bypass entries for justified cases, refactoring dispatches for simplifiable ones.
- **Handler standard** — 83% average. Investigation needed per branch.
- **Test coverage expansion** — 22% average. Structural gap, needs per-branch test scaffolding.
- **Cross-platform reliability** — Linux and Windows tested. macOS structurally supported. All paths use `pathlib`, secrets at `~/.secrets/aipass/`.
- **Agent agnosticism** — currently focused on [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (hooks for auto-diagnostics, prompt injection, session recovery). But AIPass is designed to not depend on any single provider. `agents.md` and `gemini.md` can bootstrap the system for Codex and Gemini — you lose hooks but keep the core.

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
| `devpulse` | **Start here.** Orchestration hub — coordinates everything, maintains 20 diagnostic tools |
| `drone` | AI-friendly CLI — every command is a single-line, non-interactive call |
| `seedgo` | Standards enforcement — 34-standard audit pack, system compliance |
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

### Diagnostic Tooling

DevPulse maintains 20 standalone scanners in its `tools/` directory — purpose-built for AI consumption. Each scanner follows the same CLI pattern (`@branch`, `--all`, `--summary`) and targets a single concern:

- **Code quality** — silent catches, dead code, unused functions, deep nesting, raw prints, commented loggers
- **Security** — hardcoded keys, partial key display, URL injection
- **Documentation** — stale help text, README freshness, prompt quality, TODO tracking
- **Consistency** — magic numbers, stale terminology, command verification, test coverage

Tools surface patterns. Patterns create conversations. Conversations improve the system. Run a scanner, get instant visibility into code quality across all 15 branches without reading a single file.

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
drone @ai_mail dispatch @memory "Bug Report" "Search fails without torch"
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
