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
source .venv/bin/activate
```

`setup.sh` creates a venv, installs the package, generates the branch registry (15 branches), bootstraps `.trinity/` identity files, copies an empty `.env` template to `~/.secrets/aipass/.env`, and installs Claude Code hooks. Idempotent — safe to re-run.

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

### Verify

```bash
drone systems          # Should show 15 branches
```

### Docker

```bash
docker build -t aipass .
docker run -d -p 8080:8080 aipass
```

Opens a code-server IDE with Python, Node, and Claude Code pre-installed. Password is auto-generated — check `docker logs <container>` for the config path.

Inside the container:

```bash
bash setup-workspace.sh   # Clones repo and installs
```

## Usage

Start with devpulse — the orchestration hub:

```bash
cd src/aipass/devpulse
claude --permission-mode bypassPermissions
```

Talk to it. It dispatches to specialist branches and brings results back. You work with one agent, it coordinates the rest.

### Core Commands

```bash
drone @branch --help                    # Any branch's commands
drone systems                           # List all branches
drone @ai_mail dispatch @memory "subject" "body"   # Send inter-agent mail
drone @seedgo audit aipass              # Run standards audit
drone @flow create . "task name" dplan  # Create a plan
drone @git pr                           # Create PR via drone
```

Pattern: `drone @branch command [args]` — single-line, non-interactive.

### Branches

| Branch | What it does |
|--------|-------------|
| `devpulse` | Orchestration hub — start here |
| `drone` | CLI router — routes commands to branches |
| `seedgo` | Standards enforcement — 34 automated checks |
| `prax` | Logging and monitoring |
| `cli` | Terminal display and formatting |
| `flow` | Workflow management (FPLANs, DPLANs) |
| `ai_mail` | Inter-agent messaging and dispatch |
| `spawn` | Branch lifecycle and identity |
| `trigger` | Event-driven automation |
| `api` | LLM access via OpenRouter |
| `backup` | Backup system (snapshot, versioned, Drive) |
| `daemon` | Background scheduler |
| `memory` | Vector memory bank (ChromaDB) |
| `commons` | Social space for branches |
| `skills` | Capability framework |

## How It Works

### Memory

Every branch has `.trinity/` files that persist across sessions:

```
.trinity/passport.json       # Identity — role, purpose, principles
.trinity/local.json          # Session history — tasks, learnings
.trinity/observations.json   # Collaboration patterns over time
```

New session starts, branch reads its memories, picks up where it left off.

### Structure

```
src/aipass/<branch>/
├── .trinity/           # Identity & memory
├── .aipass/            # Branch prompt
├── .ai_mail.local/     # Mailbox
├── apps/
│   ├── <branch>.py     # Entry point
│   ├── modules/        # Business logic
│   └── handlers/       # Implementation
└── README.md
```

All branches follow this layout. `drone` resolves `@name` to paths via `AIPASS_REGISTRY.json`.

### No Isolation

All 15 branches share the same filesystem and git repo. Each owns its directory and doesn't touch others. Dispatch locks prevent conflicts. Standards enforcement keeps things consistent.

## Requirements

- Python 3.10+
- API keys optional (needed for `api` branch — OpenRouter/OpenAI)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) recommended for hooks

## Status

Beta. 15 branches operational. 130+ PRs merged. 1,600+ tests. 96% avg compliance across 34 standards checks.

## License

MIT
