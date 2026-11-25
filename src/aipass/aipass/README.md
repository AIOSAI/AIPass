# AIPASS

The machine concierge for AIPass: host and OS diagnosis and repair (Wi-Fi drops,
a USB port, CPU heat, battery, screen flicker, disk, docker), the doctor, the
installer and fleet health. It also creates and enrols projects inside the
installation. Your projects are devpulse's seat; this branch looks after the
machine they run on.

It is a command-line program for humans, not a service for other programs:
`aipass` is installed on your PATH and everything here starts from it.

## Quick Start

```bash
aipass                              # the live list of commands
aipass doctor                       # is this machine wired correctly?
aipass doctor --fix                 # repair commands, and the settings change asked once
aipass read <branch>                # read one component's page in the terminal
aipass init <dir> [name]            # scaffold a project in <dir>
```

## What It Does

**Install.** `aipass install` is the one-command bootstrap in five steps: home,
`setup.sh`, verify, phone face + baud-cli, and a health check that runs the full
doctor with its fix step. The provider settings change is shown and asked once
on a terminal; `--yes` gives that consent up front and exports `AIPASS_YES=1`
to `setup.sh`. With no terminal, or `--non-interactive` without `--yes`, nothing
is written and the row names `aipass doctor --fix --yes`. The install ends on a final screen:
`AIPass installed at <home>` and every row that is not a pass, including what
`setup.sh` left in `<home>/.aipass/setup_attention.txt`. It writes that list to
`<home>/src/aipass/devpulse/dropbox/install_report.json`, prints one command
that wakes devpulse on the report, and launches nothing. `aipass install --finish`
is that last step alone, the doctor and the report; `setup.sh` ends with it.
A phone face that was asked for (no `--no-baud`) and did not install fails the
install: the final screen says a requested step failed, the report records
`"outcome": "step_failed"` and `"failed_steps": ["phone face"]`, and the exit is 1. The health check runs the
home's own doctor in the home; a doctor error also ends on an error line, the
outcome `doctor_errors` and exit 1.
With a phone face installed, the install starts the phone server itself when
nothing else will, and on a terminal waits for Enter and shows a pairing QR.
`--source PATH|URL` clones AIPass from a local checkout's committed HEAD or
another URL instead of the public repo (the install sandbox).

**Scaffold.** `aipass init <target> [name]` scaffolds a project in one step;
whether it may is judged on the target, by the guard in `bootstrap.py` (no agent
branch, no existing or enclosing project), never on the directory you run it
from. `aipass init update` brings an existing project's scaffold forward, which
is a decision with rules of its own rather than a repair. `aipass init agent
<name>` creates an agent through @spawn.

**Diagnose.** `aipass doctor` aggregates the health of everything a session
needs: system, identity, services, community, structure, scaffold. It
can offer to wire what it found, and `--fix` prints the repair command for each
failing row.

**Read.** `aipass read <branch>` renders a branch's README in the terminal,
read live from the file.

Alongside those: `aipass new` and `aipass adopt` create and absorb projects,
`aipass trust` and `aipass revoke` decide which projects the hook engine will
load, and `aipass baud` installs the phone face. An unknown command is an error.

## Live Inventory

The list of modules, verbs and flags is generated from the code that runs them, so it is not written down here and cannot go stale on this page:

- `aipass` — the live command inventory.
- `aipass --help` — the full reference, each command's own `--help` beneath it.

## How To Reach Me

Run me. Bare `aipass` prints the live command inventory — generated from the
modules actually loaded, so it cannot go stale — and `aipass --help` is the
full reference, with each command's own `--help` beneath it. `aipass --version`
resolves the version live rather than repeating a number written down here.

`drone @aipass` does not resolve, by design. Drone routes between agents; this
branch is the user's own CLI and serves humans, so it ships as a
binary on your PATH instead of behind the router. Everything else in the fleet
answers to `drone @<name>`; this one answers to `aipass`.

Something wrong on this page, or a command that disagrees with its help text?
`drone @ai_mail dispatch @aipass "Subject" "Body"` reaches the branch that owns
the code.

## Commands

There is no command table on this page. A hand-typed list rots the first time a
flag changes, and this program already prints an authoritative one — see **How
To Reach Me** above for the two commands that produce it live.

## Architecture

A thin dispatcher with one module per command. `apps/aipass.py` discovers
modules, routes the first argument, and owns nothing else: bare invocation and
`--help` are its only output. The modules are `install.py` and `init_flow.py`
for install and scaffolding, `doctor.py` with `_doctor_fix.py` (the remediation
report), `_doctor_wire.py` (the provider rows and the wire prompt) and
`_doctor_smoke.py` (the opt-in live turn per provider),
`read.py` for live README reads, `new_project.py` and
`adopt.py` for projects, `trust.py` for enrolment, `baud.py` for the phone
face with `_phone_print.py` (the install's phone lines and pairing QR).

Under them, `apps/handlers/` holds the implementation groups: `system_detect/`,
`structure_scan/` and `admin_lane.py` for what doctor reads;
`init/` for scaffolding and `new_project/` for project creation;
`readme_map/` for live documentation reads; `baud/` for fetch, verify, unpack,
binary, install and point; `provider_wire.py`
and `provider_reconcile.py` for the provider settings, with `settings_backup.py`
for the backup and receipt each of their writes takes first; `opencode_cli.py`
for the OpenCode rows; `help_flag.py`, `json/` and `ui/` for the
plumbing. `shared/` holds the install-time helpers under a separate contract — no branch
but prax at import, and the AIPass home from drone's resolver.

The directory tree lives in the branch prompt, where it is re-derived from the
real tree rather than copied.

## Documentation

Depth lives in [docs/](docs/), one page per command group:

| Page | What it covers |
|---|---|
| [init_and_install.md](docs/init_and_install.md) | Every entry form of `install` and `init`, including the ones no help page names |
| [scaffold_update.md](docs/scaffold_update.md) | The update ritual, the manifest hash rule, `.updateignore` |
| [doctor.md](docs/doctor.md) | The seven groups, the flags, the provider wiring door, what it refuses |
| [trust_and_projects.md](docs/trust_and_projects.md) | The enrolled hash, and `new` / `adopt` |
| [baud_phone_face.md](docs/baud_phone_face.md) | Fetch, verify, unpack, swap, point — and every refusal |
| [admin_setup.md](docs/admin_setup.md) | The admin lane: the five legs, the threat model, lighting it |
| [shared_contract.md](docs/shared_contract.md) | `shared/`, the install-time helpers, and the AIPass home they answer |
| [probe_hygiene.md](docs/probe_hygiene.md) | How this branch probes the system without mutating it |
| [two_clis.md](docs/two_clis.md) | One citizen on Claude Code, Codex and OpenCode: what each reads, the ritual spellings, the compact flow |

## Integration Points

### Depends On

- `@drone` — routing; every outbound command in this branch is a `drone`
  subprocess call
- `@spawn` — agent creation (`init agent`, `new`), registry sync
  during `install`, and doctor's owner/identity check and repair
- `@hooks` — the trusted-project registry is its module; doctor runs its
  `verify` and `smoke`
- `@prax` — logging, imported by nearly every module and handler
- `@trigger` — soft dependency: a fire each time install removes its lock,
  wrapped so it degrades
- `pytest` — doctor shells out to collect the suite

`@sentry` and `@flow` are part of this branch's working practice — audits
before "done", plans for builds — but no code path here calls either.

### Provides To

Humans, first — the CLI is the product and nothing in the fleet drives it. One
exception: the package door `from aipass.aipass import create_project, TEMPLATES`,
for @api's host verbs, in [shared_contract.md](docs/shared_contract.md). No other
branch imports `shared/`.

---

**Last Updated:** 2026-11-21

---

[← Back to AIPass](../../../README.md)
