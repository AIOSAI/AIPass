[← Back to AIPass](../../../README.md)

# Drone

**Purpose:** The command router for AIPass. Resolves an `@name` to a real path at runtime, routes the command there, and owns every git operation behind a tier-based access gate — the one interface through which the whole fleet reaches git.
**Module:** `aipass.drone`
**Version:** 1.1.0
**Created:** 2026-03-05

---

## What It Does

- **Routes everything.** `drone @<target> <command>` reaches any registered branch or internal
  module. A branch is dispatched as a subprocess; a module runs in-process. Which lane is taken is
  decided before the call, never discovered by failing one.
- **Resolves `@names`.** Symbolic addressing against the project registry, with external projects
  merged in, so the same command works from a repo that is not this one.
- **Owns git.** Read verbs for every branch, write verbs for the project's registry-declared owner,
  a door for repositories that are not AIPass, and one audit line per use of it.
- **Deletes, and records it.** `drone rm` is the only sanctioned delete path in the fleet, and
  every delete and every refusal lands in an audit store and in the logs.
- **Discovers.** Commands are read from the branches themselves, so the inventory is generated
  rather than written down.

Not a task runner, not a scheduler, and never a writer of another branch's files.

---

## Quick Start

```bash
drone systems                     # Every registered branch and module
drone @seedgo audit aipass        # Route a command to a branch
drone @flow --help                # The full reference for any target
drone @git status                 # Read-only git, available to every branch
```

---

## Live Inventory

The list of modules and commands is **generated from the code that runs them**, so it is not
written down here and cannot go stale:

- `drone @drone` — the self-map: every discovered module with its one-line description.
- `drone @drone --help` — the routing surface: the built-ins, the flags, the timeout override.
- `drone @git --help` — every git verb, its tier, the machine surface and the external-repo door,
  including each refusal exactly as it prints.
- `drone rm --help` — the delete rules, the carve-outs and the stale-temp sweep.

---

## How To Reach Me

- Mail: `drone @ai_mail email @drone "Subject" "Body"` — a route that resolves to the wrong place,
  a refusal you believe is wrong, a verb you need that does not exist.
- **A refusal is a message, not a wall.** Every git refusal names the caller and the reason, and
  the two species mean different things: *not authorized* is about who you are, *cannot run here*
  is about which repository you are standing in. Quote the line you got.
- Write access to git belongs to the project's registry-declared owner, and it is earned from the
  registry rather than granted by name. If you need something committed, mail the owner.

---

## Commands

There is no command list on this page, deliberately: a hand-typed copy of a branch's own help
output rots the next time a verb is added. The generated surface is the one above under **Live
Inventory**, and it is always current.

---

## Architecture

Three layers. `apps/drone.py` is the entry point and the routing decision tree: built-ins first,
then `@target` resolution, then the module lane. `apps/modules/` holds one orchestrator per
concern — `resolver` and `config` for addressing, `router` for dispatch, `registry` and
`module_registry` for what exists, `discovery` and `scan` for what a branch can do, `commands` for
shortcuts, `git_module` for the whole git surface, `rm` for contained deletes and `broker` for the
daemon that performs them on request. `apps/handlers/` holds the implementation, grouped one
directory per concern: `git/` (a handler per verb), `broker/` (socket daemon, client, protocol and
the server-side path resolver), `scanning/`, `command_registry/` and the json shim every branch
shares. `apps/plugins/devpulse_ops/` sits outside the three layers on purpose: auth-gated
administration, not routing.

The directory tree and this branch's gotchas live in its prompt
(`.aipass/aipass_local_prompt.md`) — one place, so they cannot disagree with themselves.

---

## Documentation

Depth lives in [docs/](docs/), one file per module or handler group:

| Doc | What it covers |
|---|---|
| [docs/routing_and_resolution.md](docs/routing_and_resolution.md) | The routing decision tree, the two kinds of module, registry resolution, the Python API, interactive commands, the help-flag rule, external projects |
| [docs/caller_identity.md](docs/caller_identity.md) | Who a routed command is attributed to, why provenance travels with the name, and what each log level means |
| [docs/subprocess_timeouts.md](docs/subprocess_timeouts.md) | The deadline ladder: the default, the idle grace, the ceiling, and why output extends life |
| [docs/git_access.md](docs/git_access.md) | The two tiers, how owner tier is earned per repo, the two refusal species, the dev branch model, the plugins |
| [docs/git_interface.md](docs/git_interface.md) | What each verb does: scoping, the `--json` machine surface, remote redaction, the commit subject cap, the pre-commit lane, tag lanes, gh passthrough |
| [docs/external_repo_door.md](docs/external_repo_door.md) | `--repo <path>`: the admin-seat door into a repository that is not AIPass, and its ledger |
| [docs/rm_and_the_record.md](docs/rm_and_the_record.md) | The delete record, the sibling-branch guard, the contains-a-citizen fence, and stale mode |
| [docs/broker.md](docs/broker.md) | The broker delete lane and its server-side path verification on every host |
| [docs/testing.md](docs/testing.md) | How the suite is run and judged, the standards lanes, the mutation bar |

---

## Integration Points

### Depends On
- `AIPASS_REGISTRY.json` and `AIPASS_ROOTS.json` — branch resolution and the external tier
- `.trinity/passport.json` — the identity git authority reads
- the `gh` CLI — GitHub operations
- `aipass.prax` — structured logging, and the json service the local shim binds
- `aipass.cli` — Rich console formatting
- Python stdlib: `pathlib`, `subprocess`, `importlib`, `json`, `threading`

### Provides To
- Every branch — command routing, module and branch discovery, and the only interface to git
- `aipass.seedgo`, `aipass.cli`, `aipass.spawn` — in-process module routing declared in
  `apps/handlers/routing_config.json`
- `@devpulse` — the write verbs, the PR lock and the external-repo door
- The whole fleet — the sanctioned delete path and its audit trail

---

**Last Updated:** 2026-09-15

---
[← Back to AIPass](../../../README.md)
