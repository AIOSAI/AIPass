[<- Back to the README](../README.md)

# Git access — tiers, refusals, and the dev branch model

**Branch** drone · **Code** `apps/plugins/devpulse_ops/auth.py`, `apps/modules/git_module.py`

Drone is the only git interface in AIPass: raw `git` and `gh` are blocked by a hook, reads
included, and every verb arrives here. Which verbs exist is `drone @git --help`; who may run them is this page.

---

## Three tiers

Auth is centralised in `verify_git_access()` and checked **once**, at the top of
`git_module.handle_command()`, before any handler is called.

| Tier | Who | What it covers |
|------|-----|----------------|
| **Global** | All branches | the read doors and the passthroughs — status, diff, log, show, blame, tracked, export, remote, lock, branches, tag listing, release list, label list, alerts list, and the `gh` reads |
| **Owner** | The project's registry-declared owner — **earned, never hardcoded** (devpulse in AIPass) | everything that writes: commit, untrack, checkout, the PR verbs, branch deletion, prune-temp, sync, merge-main, merge, smart-sync, unlock, tag, fix, release edit, label create, alerts dismiss, and the `gh` writes |
| **CI cure** | The one citizen whose registry entry carries `ci_cure: true` (@trigger in AIPass) | `ci-cure` alone: commit a CI cure on dev and push dev |

Owner tier is **earned per repo** from four facts in the caller's own project registry:
`citizen_class: manager`, registry tenancy, an entry carrying `owner: true`, and path-binding of
the passport to the recorded home. There is no caller allowlist anywhere in the branch.

The ci-cure tier is earned the same way, minus the manager class: registry tenancy, an entry
carrying `ci_cure: true` (the JSON boolean), and path-binding. The fact must sit on exactly one
entry of the registry; two holders refuse both. `AIPASS_GIT_AUTH_MODE=warn` never lifts a ci-cure
refusal. Outside AIPass's own registry the verb is a capability refusal: its fence is AIPass's tree.

`drone @git ci-cure <run_id> @<owner> "<message>" <path ...>` commits exactly the named paths on
`dev` (`git commit --only`, so anything else staged stays staged), pushes `dev` to origin, and
prints the new sha on the first line of stdout. Every path is repo-relative and sits under
`src/aipass/<owner>/` or is `CHANGELOG.md`; no `..`, no glob, and git reads pathspecs literally. The
message's first line starts `fix(<owner>): `, names the numeric run id, and fits the commit subject
cap. A branch other than `dev` is a capability refusal at WARNING; every other refusal is ERROR, and
none commits anything. It opens no PR and never merges, syncs, tags, reruns or takes `--repo`. Every
call, refused or run, is one row in `.ai_central/git_ci_cures.jsonl` with the caller, the arguments,
the outcome (`pushed`, `failed` for a commit whose push failed, `refused`) and, once committed, the
run id, owner, paths and sha. The refusal texts are `drone @git ci-cure --help`. Pinned in
`tests/test_git_ci_cure.py` against a real repo and a local bare origin.

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

**Which verbs refuse outside AIPass:** `pr`, `close-pr`, `smart-sync`, `fix`, `delete-branch` —
they assume our PR conventions, our lock or our events, so against an arbitrary repo they would
half-run and leave a mess. Every other owner verb runs for the project's manager from its own seat;
`auth.external_owner_verbs()` is the list, and both the refusal and `drone @git --help` print it.
The admin seat's door into an external repo is `--repo` — see
[external_repo_door.md](external_repo_door.md).

**`dev-pr` and `merge` in an external repo** run the same dev → main model, aimed at the repo's own
GitHub slug from its origin URL (`external_pr_handler.py`). `dev-pr` refuses before any push unless
HEAD is `dev`, no tracked file is modified, and dev holds commits `origin/main` does not (it fetches
main first); then it pushes dev and opens the PR with `gh pr create -R OWNER/NAME`. `merge` keeps the
joint-decision gate, merges with `gh pr merge -R OWNER/NAME --merge` (deleting the head branch only
when it is known and not `dev` or `main`), then checks out `dev` and fast-forwards it to `origin/dev`.
A local step that fails after GitHub merged exits 1 and still names the merge. No PR lock, no sync
with AIPass, and no `pr_merged` event: that event syncs AIPass's own status page. Pinned in
`tests/test_git_module_merge.py` against a real repo and a bare origin, gh stubbed.

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
| `merge_plugin` | `merge` | Straight-merge a PR and sync local main; an external repo takes `external_pr_handler` |
| `sync_plugin` | `smart-sync` | Fetch, detect divergence, rebase |
| `fix_plugin` | `fix` | Repair a stuck rebase or a detached HEAD |

`auth.py` is the gate they share. A second plugin directory, `hook_sounds/`, is disabled in place:
its files carry a `.disabled` suffix, and hook sounds live in the hooks branch.

---

## Related

- [git_interface.md](git_interface.md) — what the verbs themselves do
- [external_repo_door.md](external_repo_door.md) — git in a repo that is not AIPass
- [caller_identity.md](caller_identity.md) — attribution, which is not authority
