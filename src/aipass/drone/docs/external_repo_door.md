[<- Back to the README](../README.md)

# The external-repo door — `--repo <path>`

**Branch** drone · **Code** `apps/handlers/git/repo_door.py`, `apps/modules/git_module.py`

Git in a repo that is not AIPass — a project inside the tree, a clone outside it — goes through one
door, held by @devpulse's admin grant (DPLAN-0344, the owner's go 2026-09-13). Nine verbs take
`--repo <path>` (or `--repo=<path>`) in any slot: status, diff, log, commit, push, tag, fetch, sync
and merge-upstream.

---

## Four questions, in this order

1. **Who** — @ai_mail's verified-caller rail, `is_verified_admin_caller()`: the five-leg grant,
   asked on every use, never cached. `@git` runs inside drone rather than as a routed child, so the
   door first stamps `AIPASS_CALLER_CWD`, `AIPASS_CALLER_BRANCH` and
   `AIPASS_CALLER_IDENTITY_SOURCE` the way the router stamps a child (fresh, same resolver) and
   restores them after. `verify_git_access()` is not consulted, because its owner tier answers for
   the repo you stand in. A project manager standing in its own repo is refused by name.
2. **The flag** — a bare `--repo`, or two of them, is refused rather than falling through to the
   standing repo.
3. **Which verb** — anything outside the nine is refused. `issue`, `run` and `workflow` never reach
   the door: their `--repo OWNER/NAME` is gh's own flag.
4. **Which repo** — absolute, or relative to the AIPass root (never the cwd). It must exist, be a
   directory, be a git top level, and not be AIPass: refused if `AIPASS_REGISTRY.json` sits at its
   top level, or if it is the caller's own root (a clean clone has no registry).

Every exit writes one line to `.ai_central/git_repo_door.jsonl`, beside the deletion log — caller,
cwd, verb, args, repo, HEAD before and after, exit code — **refusals included**.

---

## What the door does not do

**No lock.** The AIPass PR lock would stall AIPass's train for someone else's repo, and a lock file
inside the target is an untracked file the next `commit --all` there would stage. Git's own
`index.lock` serialises the writes.

**`commit` never pushes**, as at home: `push` is its own verb, and it pushes the checked-out branch
to `origin` under the same name, never forced. `commit --all` runs the same lint and test gate it
runs anywhere, and the subject cap applies unchanged (see
[git_interface.md](git_interface.md)). File paths are repo-relative.

**`fetch` moves nothing local.** It runs `git fetch origin`, then prints the checked-out branch's
ahead/behind count against its upstream and the commits on each side, newest first. Only the
remote-tracking refs change. It exists because a push the remote rejects ("fetch first") left this
seat with no way to see what the remote had (FPLAN-0642, 2026-10-13).

**`sync` only fast-forwards.** It refuses a tracked change in the working tree before it fetches
anything (untracked files do not block), then fetches and runs `git merge --ff-only` onto the
upstream. A diverged branch, with commits on both sides, is refused with both lists printed:
no rebase, no merge commit, no stash, no reset. Diverged is the owner's call. This is not AIPass's
own `sync` or `smart-sync`, which keep their dev-branch behaviour, and `--repo` on the AIPass repo is
refused as it is for every door verb. Both verbs take no other arguments, and both refuse a
detached HEAD or a branch with no upstream by name.

**`merge-upstream` is the cure for diverged.** The owner merges bot PRs on GitHub while this seat
commits locally, so a project's branch diverges as a matter of course (baud, 2026-10-13: ahead 4,
behind 7). It refuses a tracked change first, with sync's words, then fetches. Behind only, it
fast-forwards as sync does. Nothing behind, it says there is nothing to merge. Diverged, it runs
`git merge --no-edit` onto the upstream and prints the merge commit and the commits brought in. A
conflict is read (`git diff --name-only --diff-filter=U`), then `git merge --abort` puts HEAD, index
and tree back as they were, and the refusal names the conflicted paths: resolving is the owner's, by
hand. It never rebases, resets, stashes or pushes; push is its own verb.

The refusal texts are constants in `repo_door.py`, and `drone @git --help` renders those same
constants — one wording, two places, no copy. Pinned by `TestRepoDoorRefusals`,
`TestRepoDoorHappyPath`, `TestRepoDoorFetchAndSync` and `TestRepoDoorMergeUpstream` in `tests/test_git_access_gh_door.py`, against
real repos with a real bare origin and a second clone standing in for another machine.

---

## Two lessons worth keeping

**A module routed in-process has no caller stamp.** `@git` runs inside drone, so the
`AIPASS_CALLER_*` variables the rail reads are simply unset — every seat would have been refused.
The door stamps them itself and restores them in a `finally`, which is why the rail sees the same
shape it sees for a routed child.

**A new flag can eat a passthrough's own flag.** `--repo` would have swallowed gh's
`--repo OWNER/NAME` on `issue`, `run` and `workflow`; the suite stayed green because the existing
pin tested the rewrite helper rather than `handle_command`. The exclusion is now explicit and
pinned at the dispatch level.

---

## Related

- [git_access.md](git_access.md) — the owner tier this door deliberately does not use
- [git_interface.md](git_interface.md) — the verbs themselves
- [rm_and_the_record.md](rm_and_the_record.md) — the other ledger in `.ai_central/`
