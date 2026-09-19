[<- Back to the README](../README.md)

# Caller identity — who a routed command is attributed to

**Branch** drone · **Code** `apps/handlers/router_handler.py`

Every routed command is attributed to a caller, stamped into `AIPASS_CALLER_BRANCH` and the
`[CALLER:X]` log tag. Attribution only — nothing here grants authority; git's owner tier reads
passports directly (see [git_access.md](git_access.md)).

---

## Two signals, one precedence

`resolve_caller_identity()` weighs:

| Signal | Question it answers | Precedence |
|--------|--------------------|------------|
| `AIPASS_BRANCH_NAME` | Who this process **is** (assigned at spawn) | Wins |
| cwd `.trinity/passport.json` | Who lives **where** the process stands (inferred) | Fallback |
| cwd `*_REGISTRY.json` | Which **project** the process is in — never a citizen | Last resort |

Assigned identity beats location: an agent that cds into another branch is still itself.

---

## The provenance travels with the name

`resolve_caller_identity_signal()` returns a `CallerIdentity(name, source)` where source is
`assigned` | `passport` | `project`, and `execute_branch_command()` stamps it as
**`AIPASS_CALLER_IDENTITY_SOURCE`** alongside `AIPASS_CALLER_BRANCH`. `resolve_caller_identity()`
still returns the bare name for attribution sites (the `[CALLER:X]` tag, the deletion record);
anything that must *decide* on an identity takes the signal.

Why it exists: these two cases arrived byte-identical downstream, and they are not the same claim.

| Case | `CALLER_BRANCH` | Source | What it is |
|---|---|---|---|
| agent assigned `@commons`, standing in `/tmp` | `commons` | `assigned` | a **credential** — valid from any directory (S102) |
| nobody assigned, standing at the repo root | `aipass` | `project` | a **directory name** that collides with the citizen `@aipass` |

The second sent a dispatch out as `@aipass` on 2026-08-21; ai_mail's contact lookup found the real
citizen row and stamped it "verified", and the wake-back woke the wrong branch — eleven turns of
work and nothing warned (DPLAN-0315 item 3). A consumer cannot re-derive this: it is a different
process with a different cwd. Unstamped, ai_mail's identity fence had to refuse **both**, which
re-broke the very S102 case it protects.

---

## Log severity follows meaning, not novelty

| Situation | Level | Why |
|-----------|-------|-----|
| Assigned identity vs a **passport** naming someone else | `WARNING` | Two citizens claim one process — genuinely abnormal, stays loud |
| Assigned identity while standing in a **project** root | `INFO` | Not a conflict. A project name is location, not a rival claim of identity — the ordinary shape of every long-lived service |
| No passport and no registry found | `INFO` | An anonymous caller is a correct outcome. Attribution reads `unknown`; whoever refuses work for want of an identity owns the page |

Identity messages are logged **once per process per signature**. Neither signal can change under a
running process, so a repeat restates the first. Suppression is per-process only, so a real
conflict recurring across separate invocations still accumulates and still escalates. The per-call
`[CALLER:X]` tag and stamp are never suppressed — every call stays individually attributable.

There is no public reset for the dedupe set: production never needs to forget what it has already
logged. The suite clears `_LOGGED_IDENTITY_SIGNATURES` directly from an autouse fixture in
`tests/conftest.py`.

---

## A routed command runs in the target's directory

`execute_branch_command()` passes `cwd=branch_path`, so a routed module walking up for a project
lands on the TARGET's tree, not the caller's. The caller's own directory travels separately as
`AIPASS_CALLER_CWD`. That is the contract, and it is why a lane that needs the caller's project
(the deletion record, the external-repo door) reads the stamp rather than the cwd.

---

## Related

- [routing_and_resolution.md](routing_and_resolution.md) — the routing lanes that do the stamping
- [rm_and_the_record.md](rm_and_the_record.md) — where the name lands in an audit record
