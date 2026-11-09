[<- Back to the README](../README.md)

# Trust, and the projects that carry it

*Which projects the hook engine will load, the hash that decides it, and the
two commands that create a project in the first place.*

## The enrolled hash

Enrolment is what lets a project's `.aipass/hooks.json` be loaded by the hook
engine. The registry is a file in your home — `~/.aipass/trusted_projects.json`
— and each entry records the project path, the date it was enrolled, the path
of the config, and `config_hash`: the sha256 of that project's
`.aipass/hooks.json` **as it looked when it was enrolled**.

That hash is the whole point. A project whose `hooks.json` no longer matches
its recorded hash is a project whose hook config changed after you trusted it,
and the engine can tell — trust is granted to a config, not to a directory
name. A project with a `hooks.json` and no entry at all is simply unenrolled;
nothing loads.

`aipass init` auto-enrols the project it scaffolds, and an `init update`
re-enrols after it writes, because the file it just rewrote has a new hash.

The registry module itself belongs to @hooks
(`aipass.hooks.apps.handlers.config.trust_registry`, a frozen interface by
design) — this branch is a consumer of it, which is why the
cross-branch import is a written bypass rule rather than an accident.

| Command | What it does |
|---|---|
| `trust` | Show the registry — project, short hash, enrolled date |
| `trust <path>` | Enroll a project. No `.aipass/hooks.json`, no enrolment |
| `revoke <path>` | Remove a project from the registry |
| `trust prune` | Drop entries whose project path no longer exists |

Code: [`apps/modules/trust.py`](../apps/modules/trust.py).

## Creating a project — `new`

`aipass new <name>` creates a project in `projects/`: its own repo (`main` and
`dev`, left on `dev`), the AIPass scaffold, and a resident manager-class agent.
`--template python` adds a pyproject and `src/`; `--no-agent` leaves the agent
out. The templates are listed by `aipass init --list`.

Code: [`apps/modules/new_project.py`](../apps/modules/new_project.py) and
[`apps/handlers/new_project/`](../apps/handlers/new_project) — registry,
template, scaffold and repo init.

## Adopting one that already exists — `adopt`

`aipass adopt <path>` turns an existing directory anywhere on disk into a
project; a bare `<name>` means `<host>/projects/<name>`. It is **additive
only**: it never rewrites a file that is already there. `--mode` picks the shape:

| Mode | Writes | Tracked files | `.gitignore` |
|------|--------|---------------|--------------|
| `framework` (default) | registry, `.aipass/` and `.claude/` scaffold, switch files, a fresh resident agent | adds missing scaffold files | the AIPass local-state block is added first |
| `contractor` | registry, `.aipass/hooks.json`, `tier0_kernel.md`, `tier1_navmap.md`, `.claude/settings.local.json` | none | untouched; every path it writes is listed in `.git/info/exclude` |

Contractor mode needs the target's own git repo, and a project whose stack is
not AIPass's. A tracked AIPass file (anything under `.aipass/`, a registry,
`.updateignore`) is a **clash**: named in the plan, never overwritten, and a
real run refuses until it is untracked. A fresh resident would sit in the
project's `src/`, so contractor mode takes `--citizen @name` or `--no-agent`.

`--citizen @name` brings an existing citizen instead of minting one: adopt runs
`drone @spawn adopt-citizen @name <path>` and embeds its preview. @spawn seats
the registry, the citizen's branch and their exclude lines. A refusal from
@spawn stops adopt before its first write.

Trust: either mode enrols the project when adopt writes `.aipass/hooks.json`.
An existing `hooks.json` keeps the enrolment it has; after it changes,
`aipass trust <path>` re-enrols it.

`--dry-run` writes nothing and prints every path as `create`, `append`, `skip`
or `clash`, each with its reason.

Code: [`apps/modules/adopt.py`](../apps/modules/adopt.py) and
[`apps/handlers/new_project/adopt.py`](../apps/handlers/new_project/adopt.py).

---

[← Back to the AIPASS README](../README.md)
