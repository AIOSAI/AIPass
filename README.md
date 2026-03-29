[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

# AIPass

A multi-agent operating system where AI agents live as citizens in a shared filesystem. Persistent memory, inter-agent messaging, standards enforcement, and CLI routing — no cloud required.

## Setup

### Quick (full setup)

```bash
git clone https://github.com/AIOSAI/AIPass.git
cd AIPass
./setup.sh
```

`setup.sh` creates a `.venv`, installs the package in editable mode, generates the branch registry (`AIPASS_REGISTRY.json`), bootstraps `.trinity/` identity files for all 15 branches, copies an `.env` template to `~/.secrets/aipass/.env`, installs Claude Code hooks, and creates a global symlink for `drone` (requires `sudo` — will prompt). Idempotent — safe to re-run.

After setup, `drone` is available globally via `/usr/local/bin` symlink. No venv activation needed for CLI use. `seedgo` is accessed via `drone @seedgo`. For development (running tests, importing modules), activate the venv:

```bash
source .venv/bin/activate
```

### Manual (dev)

```bash
git clone https://github.com/AIOSAI/AIPass.git
cd AIPass
pip install -e ".[dev]"   # Editable install + dev tools
./setup.sh                 # Bootstrap registry, identities, hooks
```

### Add your API keys

```bash
nano ~/.secrets/aipass/.env
```

Only needed if using the `api` branch (OpenRouter/OpenAI). Everything else works without API keys.

### Verify

```bash
drone systems          # Should list 15 core branches + 3 internal modules
```

### Docker

```bash
docker build -t aipass .
docker run -d -p 8080:8080 aipass
```

Opens a [code-server](https://github.com/coder/code-server) IDE with Python, Node.js, and Claude Code pre-installed. Auth is password-based — check `docker logs <container>` for the generated password.

Inside the container:

```bash
bash setup-workspace.sh   # Clones repo into workspace and installs
```

> **Note:** `setup-workspace.sh` clones from a fork by default. Edit the `FORK` variable in the script to point to your own fork, or change it to the upstream `AIOSAI/AIPass` URL.

## Usage

Start with devpulse — the orchestration hub:

```bash
cd src/aipass/devpulse
claude --permission-mode bypassPermissions
```

Talk to it. It dispatches to specialist branches and brings results back. You work with one agent, it coordinates the rest.

### Core Commands

```bash
drone @branch --help                                       # Any branch's capabilities
drone systems                                              # List all branches + modules
drone @ai_mail dispatch @memory "subject" "body"           # Send inter-agent mail + wake target
drone @seedgo audit aipass                                 # Run standards audit (all branches)
drone @seedgo audit aipass @branch                         # Audit a single branch
drone @flow create . "task name" dplan                     # Create a planning doc
drone @flow create . "task name"                           # Create an execution plan
drone @git pr "description"                                # Create PR via drone (atomic workflow)
drone @git status                                          # Git status scoped to your branch
drone @prax monitor                                        # Real-time log monitoring (interactive — Ctrl+C to exit)
```

Pattern: `drone @branch command [args]` — single-line, non-interactive.

### Branches

15 citizen branches, each an autonomous agent with persistent memory:

| Branch | Role | What it does |
|--------|------|-------------|
| `devpulse` | Manager | Orchestration hub — start here. Coordinates all other branches. |
| `drone` | Builder | CLI router — resolves `@name` to paths, routes commands to branches |
| `seedgo` | Builder | Standards enforcement — 33 automated checks, bypass system |
| `prax` | Builder | Logging infrastructure and real-time monitoring |
| `cli` | Builder | Terminal display, formatting, and output services |
| `flow` | Builder | Workflow management — FPLANs (execution) and DPLANs (planning) |
| `ai_mail` | Builder | Inter-agent messaging, dispatch, and wake system |
| `spawn` | Builder | Branch lifecycle — create, update, template management |
| `trigger` | Builder | Event-driven automation — 12 event types |
| `api` | Builder | LLM access via OpenRouter (requires API key) |
| `backup` | Builder | Multi-mode backup — snapshot, versioned, Google Drive |
| `daemon` | Builder | Background scheduler with plugin system |
| `memory` | Builder | Vector memory bank (ChromaDB) — search, archival |
| `commons` | Builder | Social space — posts, reactions, community features |
| `skills` | Builder | Capability framework for branch skills |

## How It Works

### Memory

Every branch has `.trinity/` files that persist across sessions:

```
.trinity/passport.json       # Identity — role, purpose, principles
.trinity/local.json          # Session history — tasks, learnings, key insights
.trinity/observations.json   # Collaboration patterns observed over time
```

New session starts, branch reads its memories, picks up where it left off. When local files reach capacity, they roll over into the `@memory` branch (ChromaDB vectors). Nothing is lost.

### Standards

Every branch is held to 33 automated standards checks via `seedgo`:

```bash
drone @seedgo audit aipass              # Full system audit
drone @seedgo audit aipass @api         # Single branch
drone @seedgo checklist apps/module.py  # Quick check on a file
```

Standards cover: architecture, CLI patterns, error handling, imports, logging, naming, test quality, documentation, and more. Branches can add justified bypasses in `.seedgo/bypass.json`.

### Structure

```
src/aipass/<branch>/
├── .trinity/           # Identity & memory (persists across sessions)
├── .aipass/            # Branch-specific system prompt
├── .ai_mail.local/     # Mailbox (inbox.json, sent/)
├── .seedgo/            # Standards bypass config
├── .claude/            # Claude Code settings (deny rules, permissions)
├── apps/
│   ├── <branch>.py     # Entry point (handle_command, introspection)
│   ├── modules/        # Business logic / orchestration
│   └── handlers/       # Implementation details
├── tests/              # Branch test suite
├── logs/               # Prax log output
└── README.md
```

All branches follow this layout. `drone` resolves `@name` to filesystem paths via `AIPASS_REGISTRY.json`.

### Communication

Branches communicate via `ai_mail` — an internal messaging system:

```bash
drone @ai_mail dispatch @target "Subject" "Body"   # Send + wake target branch
drone @ai_mail email @target "Subject" "Body"      # Send without waking (FYI only)
drone @ai_mail inbox                               # Check your inbox
```

Dispatch sends a message AND wakes the target branch (starts a Claude session in their directory). This is how devpulse coordinates work across the system.

### No Isolation

All 15 branches share the same filesystem and git repo. Each owns its directory and doesn't touch others. A PR lockfile prevents concurrent git operations. Standards enforcement keeps things consistent.

Git workflow is atomic via `drone @git pr` — one command handles: lock acquisition, branch creation, scoped staging, commit, push, PR creation, return to main, and lock release.

## Requirements

- Python 3.10+
- `sudo` access (for global CLI symlinks during setup)
- API keys optional (only needed for `api` branch — OpenRouter/OpenAI)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) recommended (hooks provide branch identity, email notifications, auto-diagnostics)

## Status

Beta. 15 branches. 141 PRs merged. 2,900+ tests. 100% compliance across 33 standards. See [HERALD.md](HERALD.md) for detailed progress and session history.

## License

MIT
