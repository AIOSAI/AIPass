[← Back to AIPass](../README.md)

# Projects

> Your projects, built with AIPass. **Private by default** — published only if and when you choose.

This folder is where your own projects live. Create one with `aipass new <name>` and build whatever you want here — a tool, an app, an experiment, something nobody else will ever see. Each project is **its own separate git repository**, and the AIPass repo ignores everything in this folder (only this README ships). Nothing you build here can leak into the AIPass repo, appear in its history, or end up in anyone's pull request.

## What a project is

Every project is born complete:

- **Own git repo** — initialized locally at creation. Local means local: no remote, no publishing, nothing leaves your machine.
- **Own registry** — a sealed `*_REGISTRY.json` seating the project's owner.
- **Resident agent** — a full AIPass citizen living at `src/<name>/<name>/`, with identity, memory, and a mailbox, ready to work the project.
- **AIPass scaffold** — the same `.aipass/` prompt structure and conventions as the main ecosystem, so any agent (or human) knows their way around immediately.

Projects use AIPass; they don't live inside its repo. The ecosystem is the workshop — what you build in it is yours.

## Going public — optional, deliberate

If a project is ready for the world, publishing is an explicit choice: create a GitHub repository for it and push. Until you do that, it exists only on your machine.

Projects from the AIPass family that chose to go public:

| Project | What it is | Repo |
|---|---|---|
| **Earmark** | Read code and docs aloud in VS Code with local Piper TTS — pause, resume, pick up where you left off. Ear + bookmark: the plan is notes anchored to where you paused. First public AIPass project. | [AIOSAI/earmark](https://github.com/AIOSAI/earmark) |
| **aipass-site** | The [aipass.ai](https://aipass.ai) website — AIPass's front door on the web. | [AIOSAI/aipass-site](https://github.com/AIOSAI/aipass-site) |


## Creating one

```bash
aipass new <name>                  # empty template + resident agent
aipass new <name> --template python
aipass new <name> --no-agent
```

The project lands in `projects/<name>`, git-initialized, registry sealed, agent seated — and private until you decide otherwise.

---

[← Back to AIPass](../README.md)
