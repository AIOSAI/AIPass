[← Back to AIPass](../README.md)

# Projects

> Public satellite projects of AIPass — tools with their own life, born from this ecosystem.

This folder is where AIPass projects live on a development machine. Each project is created with `aipass new <name>` and is **its own git repository with its own GitHub home** — that's why you see only this README in the AIPass repo: the projects' contents are deliberately not tracked here, and the roster below points at the real repos.

## What a project is

Every project is born deployable:

- **Own git repo** — initialized at creation, published to its own GitHub repository.
- **Own registry** — a sealed `*_REGISTRY.json` seating the project's owner.
- **Resident agent** — a full AIPass citizen living at `src/<name>/<name>/`, with identity, memory, and a mailbox, ready to work the project.
- **AIPass scaffold** — the same `.aipass/` prompt structure and conventions as the main ecosystem, so any agent (or human) knows their way around immediately.

Projects use AIPass; they don't live inside its repo. The ecosystem is the workshop, these are the things it ships.

## The roster

| Project | What it is | Repo |
|---|---|---|
| **Earmark** | Read code and docs aloud in VS Code with local Piper TTS — pause, resume, pick up where you left off. Ear + bookmark: the plan is notes anchored to where you paused. First public AIPass project. | [AIOSAI/earmark](https://github.com/AIOSAI/earmark) |

## Creating one

```bash
aipass new <name>                  # empty template + resident agent
aipass new <name> --template python
aipass new <name> --no-agent
```

The project lands in `projects/<name>`, git-initialized, registry sealed, agent seated. From there it grows into whatever it needs to be — and when it's ready for the world, it gets its own public repository like the ones above.

---

[← Back to AIPass](../README.md)
