[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

<!-- TODO: Replace with actual AIPass logo when ready -->
<!-- <p align="center"><img src="docs/logo.png" width="400" alt="AIPass"></p> -->

# AIPass

A multi-agent operating system where AI agents live as citizens in a shared filesystem. Persistent memory, inter-agent messaging, standards enforcement, and CLI routing — no cloud required.

---

## Table of Contents

- [What is AIPass](#what-is-aipass)
- [Quick Start](#quick-start)
- [Branches](#branches)
  - [Orchestration](#orchestration)
  - [Core Infrastructure](#core-infrastructure)
  - [Intelligence & Planning](#intelligence--planning)
  - [Communication & Events](#communication--events)
  - [Services](#services)
- [How It Works](#how-it-works)
  - [Memory](#memory)
  - [Standards](#standards)
  - [Communication](#communication)
  - [Structure](#structure)
- [Compliance & Safety](#compliance--safety)
- [Project Status](#project-status)
- [Platform Support](#platform-support)
  - [CLI Support](#cli-support)
- [Requirements](#requirements)
- [License](#license)

---

## What is AIPass

AIPass (**AI Passport**) is a multi-agent framework built on [Claude Code](https://docs.anthropic.com/en/docs/claude-code), with support for [OpenAI Codex](https://github.com/openai/codex) and [Google Gemini CLI](https://github.com/google-gemini/gemini-cli). Each agent is a **citizen** — it has an identity (passport), persistent memory, a mailbox, and the ability to communicate with other agents. Citizens live in **branches** (directories), each specializing in a domain. One orchestrator coordinates them all. The system supports all three CLIs with shared hooks, identity, and commands — though Claude Code is the most tested and Codex/Gemini integration is newer (S76).

You talk to one agent. It dispatches work to specialists and brings results back. Memory persists across sessions — you never re-explain context.

```
You <-> devpulse (orchestrator) <-> 14 specialist branches
```

<p align="right"><a href="#table-of-contents">Back to contents</a></p>

---

## Quick Start

```bash
git clone https://github.com/AIOSAI/AIPass.git
cd AIPass
./setup.sh
```

> **Note:** setup.sh is tested on Linux. macOS should work but is untested (see [Platform Support](#platform-support)). Windows users should use WSL2.

`setup.sh` creates a `.venv`, installs the package, generates the branch registry, bootstraps identity files for all 15 branches, copies an `.env` template, installs Claude Code hooks (plus Codex/Gemini hooks if those CLIs are detected), and creates a global `drone` symlink. Idempotent — safe to re-run.

### Verify

```bash
drone systems          # Lists 15 branches + internal modules
```

### Start working

```bash
cd src/aipass/devpulse
claude --permission-mode bypassPermissions
```

Talk to devpulse. It dispatches to specialists and brings results back.

### Core commands

```bash
drone @branch --help                                       # Any branch's capabilities
drone systems                                              # List all branches
drone @ai_mail dispatch @memory "subject" "body"           # Send mail + wake target
drone @seedgo audit aipass                                 # Full standards audit
drone @flow create . "task name" dplan                     # Create a planning doc
drone @git pr "description"                                # Atomic PR workflow
```

Pattern: `drone @branch command [args]` — single-line, non-interactive.

<details>
<summary>Docker setup</summary>

```bash
docker build -t aipass .
docker run -d -p 8080:8080 aipass
```

Opens a [code-server](https://github.com/coder/code-server) IDE with Python, Node.js, and Claude Code pre-installed. Check `docker logs <container>` for the generated password.

Inside the container:
```bash
bash setup-workspace.sh   # Clones repo into workspace and installs
```

> `setup-workspace.sh` clones from a fork by default. Edit the `FORK` variable to point to your own.

</details>

<details>
<summary>Manual dev setup</summary>

```bash
git clone https://github.com/AIOSAI/AIPass.git
cd AIPass
pip install -e ".[dev]"
./setup.sh
```

</details>

<details>
<summary>API keys (optional)</summary>

```bash
nano ~/.secrets/aipass/.env
```

Only needed for the `api` branch (OpenRouter/OpenAI). Everything else works without API keys.

</details>

<p align="right"><a href="#table-of-contents">Back to contents</a></p>

---

## Branches

15 citizen branches, each autonomous with persistent memory. Click any branch name to read its full documentation.

### Orchestration

| Branch | Purpose | Docs |
|--------|---------|------|
| [**devpulse**](src/aipass/devpulse/) | Orchestration hub — start here. Coordinates all other branches. | [README](src/aipass/devpulse/README.md) |

### Core Infrastructure

| Branch | Purpose | Docs |
|--------|---------|------|
| [**drone**](src/aipass/drone/) | CLI router — `@name` resolution, command dispatch to all branches | [README](src/aipass/drone/README.md) |
| [**spawn**](src/aipass/spawn/) | Branch lifecycle — create, update, delete, template management | [README](src/aipass/spawn/README.md) |
| [**cli**](src/aipass/cli/) | Terminal display, formatting, and output services | [README](src/aipass/cli/README.md) |
| [**daemon**](src/aipass/daemon/) | Background scheduler with cron and plugin system | [README](src/aipass/daemon/README.md) |

### Intelligence & Planning

| Branch | Purpose | Docs |
|--------|---------|------|
| [**memory**](src/aipass/memory/) | Vector memory bank (ChromaDB) — search, archival, rollover | [README](src/aipass/memory/README.md) |
| [**flow**](src/aipass/flow/) | Workflow management — FPLANs (execution) and DPLANs (planning) | [README](src/aipass/flow/README.md) |
| [**prax**](src/aipass/prax/) | Logging infrastructure, stack introspection, real-time monitoring | [README](src/aipass/prax/README.md) |
| [**seedgo**](src/aipass/seedgo/) | Standards enforcement — 33 automated checks, bypass system | [README](src/aipass/seedgo/README.md) |

### Communication & Events

| Branch | Purpose | Docs |
|--------|---------|------|
| [**ai_mail**](src/aipass/ai_mail/) | Inter-agent messaging, dispatch, and wake system | [README](src/aipass/ai_mail/README.md) |
| [**trigger**](src/aipass/trigger/) | Event-driven automation — 14 event types, watchers | [README](src/aipass/trigger/README.md) |
| [**commons**](src/commons/) | Community space — posts, reactions, shared utilities | [README](src/commons/README.md) |

### Services

| Branch | Purpose | Docs |
|--------|---------|------|
| [**api**](src/aipass/api/) | LLM access via OpenRouter (requires API key) | [README](src/aipass/api/README.md) |
| [**backup**](src/aipass/backup/) | Multi-mode backup — snapshot, versioned, Google Drive sync | [README](src/aipass/backup/README.md) |
| [**skills**](src/skills/) | Capability framework for branch skills | [README](src/skills/README.md) |

<p align="right"><a href="#table-of-contents">Back to contents</a></p>

---

## How It Works

### Memory

Every branch has `.trinity/` files that persist across sessions:

```
.trinity/passport.json       # Identity — role, purpose, principles
.trinity/local.json          # Session history — tasks, learnings, key insights
.trinity/observations.json   # Collaboration patterns observed over time
```

New session starts, branch reads its memories, picks up where it left off. When local files reach capacity, they roll over into `@memory` (ChromaDB vectors). Nothing is lost.

### Standards

Every branch is held to 33 automated standards via `seedgo`:

```bash
drone @seedgo audit aipass              # Full system audit
drone @seedgo audit aipass @api         # Single branch
```

Standards cover: architecture, CLI patterns, error handling, imports, logging, naming, test quality, documentation, and more. Branches add justified bypasses in `.seedgo/bypass.json`.

### Communication

Branches communicate via `ai_mail` — an internal messaging system:

```bash
drone @ai_mail dispatch @target "Subject" "Body"   # Send + wake target
drone @ai_mail email @target "Subject" "Body"      # Send without waking
drone @ai_mail inbox                               # Check your inbox
```

Dispatch sends a message AND wakes the target branch (starts a Claude Code session in their directory). This is how devpulse coordinates work across the system.

### Structure

```
src/aipass/<branch>/
├── .trinity/           # Identity & memory (persists across sessions)
├── .aipass/            # Branch-specific system prompt
├── .ai_mail.local/     # Mailbox (inbox.json, sent/)
├── apps/
│   ├── <branch>.py     # Entry point
│   ├── modules/        # Business logic
│   └── handlers/       # Implementation details
├── tests/              # Branch test suite
└── README.md
```

All 15 branches share the same filesystem and git repo. Each owns its directory. A PR lockfile prevents concurrent git operations. Standards enforcement keeps things consistent.

<p align="right"><a href="#table-of-contents">Back to contents</a></p>

---

## Compliance & Safety

AIPass is built primarily on [Claude Code](https://docs.anthropic.com/en/docs/claude-code), with additional support for [Codex](https://github.com/openai/codex) and [Gemini CLI](https://github.com/google-gemini/gemini-cli). The compliance details below apply specifically to Claude Code usage. Codex and Gemini compliance has not been independently audited.

### How AIPass uses Claude Code

- Every agent session runs the **official `claude` CLI binary** (`claude -p`) as a genuine subprocess
- Context is injected via [Claude Code hooks](https://code.claude.com/docs/en/hooks) (`settings.json`) and `CLAUDE.md` files — both officially supported, documented features
- Each branch agent runs as an **independent Claude Code process** with its own working directory
- No OAuth tokens are extracted, intercepted, or routed through third-party clients
- No API calls are made to Anthropic outside the official CLI
- Claude Code's built-in prompt caching and rate limiting are fully preserved

### What AIPass does NOT do

- **No credential wrapping** — we don't extract or redirect subscription OAuth tokens
- **No API proxying** — we don't intercept communication between Claude Code and Anthropic's servers
- **No harness impersonation** — we don't spoof the Claude Code client identity
- **No rate limit bypass** — each session respects Anthropic's built-in limits

### Why this matters

As of April 2026, Anthropic [enforces restrictions](https://venturebeat.com/technology/anthropic-cracks-down-on-unauthorized-claude-usage-by-third-party-harnesses) on third-party tools that extract subscription credentials to route automated workloads outside the official CLI. Tools like OpenClaw bypass Claude Code's prompt caching optimizations, creating unsustainable compute costs.

AIPass is architecturally different: it enhances Claude Code through its own extension points (hooks, CLAUDE.md, settings.json) rather than replacing or bypassing it. Your subscription credentials stay within Anthropic's infrastructure at all times.

> **Using AIPass with your Claude Pro, Max, Team, or Enterprise subscription is compliant with Anthropic's terms.** For server/automated deployments, API key authentication is recommended per [Anthropic's guidance](https://code.claude.com/docs/en/legal-and-compliance).

<p align="right"><a href="#table-of-contents">Back to contents</a></p>

---

## Project Status

**Beta.** Actively developed. 15 branches, 192+ PRs merged, 4,900+ tests, 100% standards compliance.

| Metric | Value |
|--------|-------|
| Branches | 15 |
| Standards | 33 |
| Tests | 4,900+ |
| PRs merged | 192+ |
| Compliance | 100% |
| Sessions | 76 |
| CLIs supported | 3 (Claude Code, Codex, Gemini) |

For detailed progress and session history, see [HERALD.md](HERALD.md).

For per-branch status, see [STATUS.md](STATUS.md).

<p align="right"><a href="#table-of-contents">Back to contents</a></p>

---

## Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| **Linux** | Fully tested | Primary development platform. Docker tested. setup.sh, all 15 branches, all 3 CLIs verified. |
| **Windows (WSL2)** | Expected to work | setup.sh runs in WSL2 with zero changes. Untested but no known blockers. |
| **Windows (native)** | Partial testing | Tested on Windows 10 — most functionality working. No setup.ps1 yet; manual setup required. |
| **macOS** | Untested | Should work (bash, Python, Claude Code are native). setup.sh needs minor fix for Apple Silicon Homebrew paths. |

### CLI Support

AIPass supports three AI coding CLIs. Claude Code is the primary and most tested. Codex and Gemini have hooks, skills, and identity integration but less testing.

| CLI | Autonomous Mode | Tested | Notes |
|-----|----------------|--------|-------|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | `claude -p "prompt" --permission-mode bypassPermissions` | Fully tested | Primary CLI. Hooks, dispatch, background agents all proven. |
| [Codex](https://github.com/openai/codex) | `codex exec "prompt" --approval-mode never` | Docker-tested (S75) | Hooks + skills integrated (S76). Background dispatch untested. |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `gemini -p "prompt" --approval-mode=yolo` | Docker-tested (S75) | Hooks + skills integrated (S76). Background dispatch untested. |

> **Autonomous agent dispatch** (running background agents that do work and report back) is proven with Claude Code. Codex and Gemini have the equivalent flags but this workflow hasn't been tested end-to-end yet.

<p align="right"><a href="#table-of-contents">Back to contents</a></p>

---

## Requirements

- Python 3.10+
- Linux recommended (macOS should work; Windows via WSL2 or native with manual setup)
- `sudo` access (for global CLI symlinks during setup)
- At least one AI coding CLI:
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (recommended — most tested, hooks provide branch identity, email notifications, auto-diagnostics)
  - [Codex](https://github.com/openai/codex) (alternative — hooks and skills supported, less tested)
  - [Gemini CLI](https://github.com/google-gemini/gemini-cli) (alternative — hooks and skills supported, less tested)
- API keys optional (only needed for `api` branch — OpenRouter/OpenAI)

<p align="right"><a href="#table-of-contents">Back to contents</a></p>

---

## License

MIT

---

<p align="center"><a href="#aipass">Back to top</a></p>
