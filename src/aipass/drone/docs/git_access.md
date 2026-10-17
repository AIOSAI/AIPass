[<- Back to the README](../README.md)

# Git access — tiers, refusals, and the dev branch model

**Branch** drone · **Code** `apps/plugins/devpulse_ops/auth.py`, `apps/modules/git_module.py`

Drone is the only git interface in AIPass: raw `git` and `gh` are blocked by a hook, reads
included, and every verb arrives here. Which verbs exist is `drone @git --help`; who may run them is this page.

---

## Two tiers

Auth is centralised in `verify_git_access()` and checked **once**, at the top of
`git_module.handle_command()`, before any handler is called.

| Tier | Who | What it covers |
|------|-----|----------------|
| **Global** | All branches | the read doors and the passthroughs — status, diff, log, show, blame, tracked, export, remote, lock, branches, tag listing, release list, and the `gh` reads |
| **Owner** | The project's registry-declared owner — **earned, never hardcoded** (devpulse in AIPass) | everything that writes: commit, untrack, checkout, the PR verbs, branch deletion, prune-temp, sync, merge-main, merge, smart-sync, unlock, tag, fix, and the `gh` writes |

Owner tier is **earned per repo** from four facts in the caller's own project registry:
`citizen_class: manager`, registry tenancy, an entry carrying `owner: true`, and path-binding of
the passport to the recorded home. There is no caller allowlist anywhere in the branch.

**A command in neither tier is unreachable, not merely ungated.** `verify_git_access()` refuses
anything it cannot find in a tier as `Unknown git command`, so registering a verb and wiring it to
a handler does not make it callable. `test_every_registered_command_holds_a_tier` asserts that
every registered verb holds a tier.

---

## Two refusal species — authority vs capability

Owner tier refuses for two reasons that are not interchangeable: conflating them gives a false page
*and* a real hole.

| | **Authority** | **Capability** |
|---|---|---|
| What happened | the caller is not, or cannot be shown to be, this repo's owner | the caller **is** the proven owner, but the verb is not translated for this repo |
| Where it is decided | any of the four owner checks | only **after** all four pass |
| Log level | `ERROR` — fault-shaped, someone should look | `WARNING` — by design, nothing is broken |
| Message | `Branch 'x' is not authorized for 'pr': <reason>` | `Branch 'x' cannot run 'pr' in this repo: <reason>` |
| `AIPASS_GIT_AUTH_MODE=warn` | **lifts it** — rolling back the authority migration is exactly that switch's job | **does not lift it**, and cannot: the capability branch raises before `warn_only` is ever read |

Why the wording differs: a proven owner sent to audit their passport is a false trail — they never
had an authority problem. Why the rollback is scoped: a flag that lifted every refusal species would
let `pr` run to completion inside an external repo. A rollback named for one migration has no
business re-arming a half-run of our merge flow in someone else's repository.

**Which verbs refuse outside AIPass:** `dev-pr`, `pr`, `close-pr`, `merge`, `smart-sync`, `fix`,
`delete-branch` — they assume a `dev` branch, our PR conventions, or `pyproject` versioning, so
against an arbitrary repo they would half-run and leave a mess. `commit`, `sync` and `tag` work
from an external seat, and the refusal names those three so a manager who hits the wall learns what
they *can* use. For an external repo, the door is `--repo` — see
[external_repo_door.md](external_repo_door.md).

**WARNING is not silence.** @trigger's `watch_branch_log_warnings` feeds branch-log WARNINGs into
the escalation digest — ten occurrences of one signature in sixty minutes mails @devpulse. A
capability wall walked into repeatedly still reaches an operator, as a digest rather than a page
here.

---

## The dev branch model

All work happens on `dev`. Only devpulse has write access. Agents build and report; devpulse
commits.

**Flow:** work on dev → stack changes → `dev-pr` → merge the PR → `sync` realigns dev from main.

**`pr` vs `dev-pr`:** `pr` works from any branch — on main it auto-creates a temp branch from the
description slug (`main:<slug>`), on other branches it pushes directly. It does not use `-u`, so
main's upstream tracking stays on `origin/main`. `dev-pr` is specific to the dev→main workflow.

Three enforcement layers, and they are independent: the git gate (a PreToolUse hook) blocks raw
git and gh commands; the tier system above restricts write verbs to the registry-declared owner;
and every branch prompt tells agents they have no git access.

---

## Plugins — `apps/plugins/devpulse_ops/`

Plugins live outside the three-layer structure by design: they are auth-gated operations for system
administration, not routing logic.

| Plugin | Verb | Purpose |
|--------|------|---------|
| `merge_plugin` | `merge` | Straight-merge a PR and sync local main |
| `sync_plugin` | `smart-sync` | Fetch, detect divergence, rebase |
| `fix_plugin` | `fix` | Repair a stuck rebase or a detached HEAD |

`auth.py` is the gate they share. A second plugin directory, `hook_sounds/`, is disabled in place:
its files carry a `.disabled` suffix, and hook sounds live in the hooks branch.

---

## Related

- [git_interface.md](git_interface.md) — what the verbs themselves do
- [external_repo_door.md](external_repo_door.md) — git in a repo that is not AIPass
- [caller_identity.md](caller_identity.md) — attribution, which is not authority
