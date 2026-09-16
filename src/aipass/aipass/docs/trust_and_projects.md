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
DPLAN-0244 design) — this branch is a consumer of it, which is why the
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

`aipass adopt <name>` turns an existing `projects/<name>` directory into a full
project. It is **additive only**: it writes the scaffold a project is missing
and never rewrites your files. `--no-agent` skips the resident agent,
`--dry-run` prints what adoption would do and writes nothing.

Code: [`apps/modules/adopt.py`](../apps/modules/adopt.py) and
[`apps/handlers/new_project/adopt.py`](../apps/handlers/new_project/adopt.py).

---

[← Back to the AIPASS README](../README.md)
