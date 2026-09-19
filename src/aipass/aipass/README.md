# AIPASS

The friendly front door for AIPass. It walks a new user through setup, checks
whether a machine is wired correctly, answers how-things-work questions out of
the project's own documentation, and creates projects inside the installation.

It is a command-line program for humans, not a service for other programs:
`aipass` is installed on your PATH and everything here starts from it.

## Quick Start

```bash
aipass                              # the live list of commands
aipass doctor                       # is this machine wired correctly?
aipass help what does drone do      # ask a question, get the real docs
aipass read <branch>                # read one component's page in the terminal
aipass init run                     # guided setup, resumable
```

## What It Does

Four jobs, in the order a new machine meets them.

**Install.** `aipass install` is the one-command bootstrap: clone, `setup.sh`,
hooks, the phone face, and a welcome chat with this concierge at the end.

**Set up.** `aipass init run` walks the ten stages — welcome, system detect,
profile, style questions, tool choice, first agent, ping sweep, smoke test,
handoff, done. Every stage saves its answer, so an interrupted run resumes.
`aipass init update` brings an existing project's scaffold forward, which is a
decision with rules of its own rather than a repair.

**Diagnose.** `aipass doctor` aggregates the health of everything a session
needs: system, identity, services, community, structure, scaffold, sandbox. It
can offer to wire what it found, and `--fix` prints the repair command for each
failing row.

**Explain.** `aipass help <question>` answers out of the live documentation —
no model call, no cached answers, a citation with every section. `aipass read`
renders a whole page. Free text works too: a multi-word question that matches
no command becomes one.

Alongside those: `aipass profile` remembers who you are, `aipass new` and
`aipass adopt` create and absorb projects, `aipass trust` and `aipass revoke`
decide which projects the hook engine will load, `aipass baud` installs the
phone face, `aipass handoff` launches your chosen CLI, and `aipass feedback`
toggles the reminder pulse.

## How To Reach Me

Run me. Bare `aipass` prints the live command inventory — generated from the
modules actually loaded, so it cannot go stale — and `aipass --help` is the
full reference, with each command's own `--help` beneath it. `aipass --version`
resolves the version live rather than repeating a number written down here.

`drone @aipass` does not resolve, by design. Drone routes between agents; this
branch is the user's own front-door CLI and serves humans, so it ships as a
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
for the two setup doors, `doctor.py` with `_doctor_fix.py` (the remediation
report) and `_doctor_wire.py` (the provider rows and the wire prompt),
`help_chat.py` and `read.py` for the documentation lane, `new_project.py` and
`adopt.py` for projects, `trust.py` for enrolment, `baud.py` for the phone
face, `handoff.py` for the CLI launch, `profile.py` for what is remembered
about you, and `feedback.py`, which delegates to @hooks outright.

Under them, `apps/handlers/` holds the implementation groups: `system_detect/`,
`structure_scan/`, `sandbox_check/` and `admin_lane.py` for what doctor reads;
`init/` for scaffolding and `new_project/` for project creation;
`readme_map/` for live documentation reads; `baud/` for fetch, verify, unpack,
binary, install and point; `cross_os/` for the pre-flight lane;
`handoff_platform/` for the OS-dispatched session launch; `provider_wire.py`
and `provider_reconcile.py` for the provider settings; `ping_sweep/` for
reachability; `help_flag.py`, `module_root.py`, `json/` and `ui/` for the
plumbing. `shared/` is a separate contract — stdlib-only, because other
branches import it.

The directory tree lives in the branch prompt, where it is re-derived from the
real tree rather than copied.

## Documentation

Depth lives in [docs/](docs/), one page per command group:

| Page | What it covers |
|---|---|
| [init_and_install.md](docs/init_and_install.md) | Every entry form of `install` and `init`, including the ones no help page names |
| [scaffold_update.md](docs/scaffold_update.md) | The update ritual, the manifest hash rule, seeds, `.updateignore` |
| [doctor.md](docs/doctor.md) | The seven groups, the flags, the provider wiring door, what it refuses |
| [help_chat.md](docs/help_chat.md) | The keyword model behind `aipass help`, and `aipass read` |
| [trust_and_projects.md](docs/trust_and_projects.md) | The enrolled hash, and `new` / `adopt` |
| [baud_phone_face.md](docs/baud_phone_face.md) | Fetch, verify, unpack, swap, point — and every refusal |
| [admin_setup.md](docs/admin_setup.md) | The admin lane: the five legs, the threat model, lighting it |
| [shared_contract.md](docs/shared_contract.md) | `shared/`, the part of this branch @spawn imports |
| [known_issues.md](docs/known_issues.md) | Open items, each verified against live code |
| [probe_hygiene.md](docs/probe_hygiene.md) | How this branch probes the system without mutating it |

## Integration Points

### Depends On

- `@drone` — routing; every outbound command in this branch is a `drone`
  subprocess call
- `@spawn` — agent creation (`init run`, `init agent`, `new`), registry sync
  during `install`, and doctor's owner/identity check and repair
- `@hooks` — `feedback` delegates to it outright; the trusted-project registry
  is its module; doctor and the cross-OS pre-flight read its status
- `@ai_mail` — test-convention ping emails (`ping_sweep`)
- `@prax` — logging, imported by nearly every module and handler
- `@trigger` — soft dependency: a fire on write-failure cleanup, wrapped so it
  degrades
- `pytest` — doctor shells out to collect the suite

`@seedgo` and `@flow` are part of this branch's working practice — audits
before "done", plans for builds — but no code path here calls either.

### Provides To

Humans, first — the CLI is the product and nothing in the fleet drives it. The
one exception is `shared/`, which @spawn imports in production code; that
contract is [shared_contract.md](docs/shared_contract.md).

---

**Last Updated:** 2026-09-15

---

[← Back to AIPass](../../../README.md)
