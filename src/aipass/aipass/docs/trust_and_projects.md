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
| `revoke <path>` | Remove a project from the registry; without a path it fails (exit 2) |
| `trust prune` | Drop entries whose project path no longer exists; `aipass doctor` warns of each one |

Code: [`apps/modules/trust.py`](../apps/modules/trust.py).

## Creating a project — `new`

`aipass new <name>` creates a project in `projects/`: its own repo (`main` and
`dev`, left on `dev`), the AIPass scaffold, and a resident manager-class agent.
`--template python` adds a pyproject and `src/`; `--no-agent` leaves the agent
out. `aipass new --help` lists the templates: `empty` and `python`.

The project is not installed in the venv, so the agent's code is re-rooted
from `aipass.<pkg>` to `<pkg>.<pkg>`, the package the project declares: the
literal name and the template's placeholder forms (`{BRANCH}`, `{MY_BRANCH}`,
`"aipass." + MY_BRANCH`). The entry point and the handlers-fence probe put
`src/` on the path themselves. With `PYTHONPATH` at the project's `src/`, a
fresh agent passes its own fence tests.

Code: [`apps/modules/new_project.py`](../apps/modules/new_project.py) and
[`apps/handlers/new_project/`](../apps/handlers/new_project) — registry,
template, scaffold and repo init.

## Adopting one that already exists — `adopt`

`aipass adopt <path>` turns an existing directory anywhere on disk into a
project; a bare `<name>` means `<host>/projects/<name>`. It is **additive
only**: it never rewrites a file that is already there. `--mode` picks the shape:

| Mode | Writes | Tracked files | `.gitignore` |
|------|--------|---------------|--------------|
| `framework` (default) | registry, `.aipass/` and `.claude/` scaffold, switch files, a fresh resident agent | in a repo of its own, none: every path it writes is excluded; else adds missing scaffold files | in a repo of its own, untouched; else the AIPass local-state block, unless `.updateignore` claims `.gitignore` |
| `contractor` | registry, `.aipass/hooks.json`, `tier0_kernel.md`, `tier1_navmap.md`, `.claude/settings.local.json` | none | untouched; every path it writes is listed in `.git/info/exclude` |

Framework mode in a target with its own `.git` treats it as a product: the
tracked `.gitignore` is never written, and before the seat is minted adopt
appends one root-anchored line per path it creates to `.git/info/exclude`. A
top folder it made whole is listed as that folder (`/.aipass/`, `/.claude/`),
inside a folder the product already had only the file it wrote. The list adds
the registry lock, the seat as `/src/<pkg>/<pkg>/` and `*.aipass-new`. The
`.gitignore` template's lines are never copied: `tools/`, `logs/` and their kind
would hide the product's own code. Without a repo, the `.gitignore` lane runs
after the mint, so it reads the `.updateignore` the seat is stamped with, the
same way `init update` does.

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
