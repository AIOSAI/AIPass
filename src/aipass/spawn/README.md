[← Back to AIPass](../../../README.md)

# SPAWN

**Purpose:** The agent factory and branch lifecycle manager for AIPass. Mints citizens from
the one template, updates branches from it, retires them into the archive, and keeps the
registry agreeing with the filesystem.
**Module:** `aipass.spawn`
**Version:** 2.1.0
**Created:** 2026-03-05

---

## Quick Start

```bash
drone @spawn create /path/to/my_agent --role "Analyst" --purpose "Data reports"
drone @spawn update @my_agent              # preview; --apply executes
drone @spawn sync-registry                 # registry against filesystem
drone @spawn delete @my_agent --dry-run    # preview a retirement
```

---

## What It Does

- **Mints citizens.** A new branch is copied from `templates/citizen/`, every
  `{{PLACEHOLDER}}` is replaced, an identity is minted once and written twice (passport and
  registry entry), the tree is verified against the template's own manifest, and a birth
  receipt is stamped before the citizen is ever registered. A mint that cannot be completed
  refuses instead of half-registering.
- **Updates branches from the template.** Preview-only until `--apply`. Missing files are
  added, JSON is deep-merged, `.py` is skipped by design, markdown is compared and reported
  but never written, and a branch's own `.updateignore` is honoured before every other rule.
- **Retires citizens.** Archive the whole tree including its memories, then deregister — and
  refuse outright while the passport still says the citizen is registered.
- **Keeps the registry true.** Scan, repair, relocate, and migrate passports to the current
  schema; each write-capable lane previews first and needs an explicit flag to act.
- **Owns the birth shape.** The template is the source of truth for what a citizen is, and a
  newborn is pinned to start inside every startup cap the fleet's other branches publish.

It never edits a living branch's code: `.py` and `.md` are the owner's, and a template
change reaches them through a dispatch, not through this engine.

---

## Live Inventory

The list of modules and commands is **generated from the code that runs them**, so it is not
written down on this page and cannot go stale:

- `drone @spawn` — the self-map: every discovered module with its one-line description.
- `drone @spawn --help` — the command surface, its flags and its examples.
- `drone @spawn --version` — the version string.

---

## How To Reach Me

- Mint, update or retire a citizen: run the verbs above, or hand the work over with
  `drone @ai_mail dispatch @spawn "Subject" "Body"`.
- A template change that must reach living branches is a conversation, not an update run:
  say which file and which branches, and it comes back with a measurement.
- A branch that wants files protected from updates writes its own `.updateignore` — no
  permission needed from here.

---

## Commands

There is no command list on this page, deliberately: a hand-typed copy of the branch's own
help output rots the next time a verb lands. The generated surface is above under **Live
Inventory**, and each verb's behaviour is documented under [docs/](docs/) below.

---

## Architecture

Three layers. `apps/spawn.py` is a thin entry point: it intercepts the help and version
flags before parsing, routes a verb to the first module that claims it, and resolves the
exit code so a refusal can never leave as success. `apps/modules/` holds one coordinator per
surface — `core` (mint and adopt), `update`, `delete`, `sync_registry`,
`regenerate_registry`, `migrate_passports`, `export_seeds`, `repair` and `grant_admin` —
each parsing arguments and delegating. `apps/handlers/` holds the implementation, grouped by
concern: the template lanes (`file_ops`, `placeholders`, `meta_ops`, `mint_verify`,
`class_registry`, `docs_page`), the identity lanes (`registry`, `passport_migration`, `seed_ops`,
`receipt_ops`, `adoption_ops`), the engines (`update_ops`, `update_ignore`, `delete_ops`,
`sync_registry_ops`, `regenerate_registry_ops`, `repair_ops`), and the primitives
(`json_ops`, `atomic_write`, `metadata`, and the fleet json shim under `json/`).

`templates/citizen/` is the one template both classes mint from, and its
`.spawn/.template_registry.json` manifest is what a mint is verified against — change a
template file and regenerate that manifest in the same pass. `templates/docs_page.md`, the
docs page skeleton, sits beside it so that no mint ever stamps it.

The full directory tree lives in this branch's own prompt
(`.aipass/aipass_local_prompt.md`) — one place, so it cannot disagree with itself.

---

## Documentation

Depth lives in [docs/](docs/), one file per module or handler group:

| Doc | What it covers |
|---|---|
| [docs/birth.md](docs/birth.md) | Citizen classes, the mint pipeline step by step, the birth receipt, the newborn budget contract, adoption, the Python API |
| [docs/update_engine.md](docs/update_engine.md) | The template walk, `.updateignore`, markdown drift, the list policy, the passport heal, create-only paths |
| [docs/registry_and_repair.md](docs/registry_and_repair.md) | Registry entry shapes, sync and fix modes, passport migration, seeds, template registry regeneration, repair, the admin ceremony |
| [docs/retire.md](docs/retire.md) | Archive then deregister, what travels with a citizen, the three protection layers |
| [docs/cli_contract.md](docs/cli_contract.md) | Exit codes and the refusal seam, introspection, the class-registry import door, the docs page skeleton door |
| [docs/tests_and_quality.md](docs/tests_and_quality.md) | What each test file pins, and the command that produces every number |

---

## Integration Points

### Depends On

- **aipass.prax** — logging through `system_logger`, and the fleet json service that
  `apps/handlers/json/json_handler.py` binds as a byte-identical shim
- **aipass.cli** — console output, refusal formatting and exit-code state
- **aipass.aipass.shared** — `deep_merge` and `backup_json`, registry discovery, and the one
  shared home detector used by the placeholder engine
- **aipass.memory** (optional) — meta tabs at create; the import is guarded and degrades to
  empty when it is unavailable

### Provides To

- Every branch — creation, template updates, retirement, and citizenship itself
- Every branch — the class-registry gateway for resolving a `citizen_class`
- **@seedgo** — the docs page skeleton its `docs_page` standard renders, read live through
  the same gateway
- Registry CRUD on `AIPASS_REGISTRY.json` and any project's own `*_REGISTRY.json`

---

**Last Updated:** 2026-09-19

---
[← Back to AIPass](../../../README.md)
