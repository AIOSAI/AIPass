[<- Back to the README](../README.md)

# The external-repo door — `--repo <path>`

**Branch** drone · **Code** `apps/handlers/git/repo_door.py`, `apps/modules/git_module.py`

Git in a repo that is not AIPass — a project inside the tree, a clone outside it — goes through one
door, held by @devpulse's admin grant. Twelve verbs take
`--repo <path>` (or `--repo=<path>`) in any slot: status, diff, log, tracked, commit, untrack, push,
tag, fetch, sync, merge-upstream, and the read side of gh's `run`.

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
3. **Which verb** — anything outside the twelve is refused. `issue`, `workflow` and `release` never
   reach the door: their `--repo OWNER/NAME` names a GitHub repo, not a path. `run` reaches it only
   when the value names a directory (see below).
4. **Which repo** — absolute, or relative to the AIPass root (never the cwd). It must exist, be a
   directory, be a git top level, and not be AIPass: refused if `AIPASS_REGISTRY.json` sits at its
   top level, or if it is the caller's own root (a clean clone has no registry).

Every exit writes one line to AIPass's own `.ai_central/git_repo_door.jsonl` — caller, cwd, verb,
args, repo, HEAD before and after, exit code, the paths `--theirs` took — **refusals included**. The
AIPass home anchors it, never the caller's cwd, so a door use leaves nothing in the repo it served.
`AIPASS_DELETION_LOG` moves it beside that log instead.

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
remote-tracking refs change. After a push the remote rejects ("fetch first"), it shows what the
remote has.

**`sync` only fast-forwards.** It refuses a tracked change in the working tree before it fetches
anything (untracked files do not block), then fetches and runs `git merge --ff-only` onto the
upstream. A diverged branch, with commits on both sides, is refused with both lists printed:
no rebase, no merge commit, no stash, no reset. Diverged is the owner's call. This is not AIPass's
own `sync` or `smart-sync`, which keep their dev-branch behaviour, and `--repo` on the AIPass repo is
refused as it is for every door verb. Both verbs take no other arguments, and both refuse a
detached HEAD by name.

**The upstream.** `fetch`, `sync` and `merge-upstream` read the same stand: the branch's
configured upstream, or, when none is configured (a branch created locally never gets
`branch.<name>.remote`), `origin/<branch>` compared by name, which the stand line marks
`(by name; none configured)`. `.git/config` is never written. A branch with neither is refused by
name.

**`merge-upstream` is the cure for diverged.** A project's branch diverges as a matter of course
when PRs are merged on GitHub while this seat commits locally. It refuses a tracked change first, with sync's words, then fetches. Behind only, it
fast-forwards as sync does. Nothing behind, it says there is nothing to merge. Diverged, it runs
`git merge --no-edit` onto the upstream and prints the merge commit and the commits brought in. A
conflict is read (`git diff --name-only --diff-filter=U`), then `git merge --abort` puts HEAD, index
and tree back as they were, and the refusal names the conflicted paths: resolving is the owner's, by
hand. It never rebases, resets, stashes or pushes; push is its own verb.

**`--theirs <path> ...` takes the upstream's side for named files.** `drone @git merge-upstream
--repo <path> --theirs app/package.json app/package-lock.json` runs the same checks and the same
merge. When every conflicted path is listed, each gets `git checkout --theirs` and `git add`, and
`git commit --no-edit` completes the merge with git's own message: one merge commit with both
parents. The answer names the paths taken and the new HEAD. When any conflicted path is unlisted,
the merge is aborted as above and the refusal names every conflicted path, marking the unlisted
ones `(not in --theirs)`. A listed path that did not conflict is reported as not needed, never an
error. Paths are repo-relative: a bare `--theirs`, a leading slash, or a path resolving outside the
repo is refused before anything is fetched. Nothing is forced and nothing is pushed.

**`tracked` and `untrack` take a file back out of the index**, such as one a catch-all commit swept
in and a soft reset left staged. Through the door both verbs run the handler they run at home, rooted at the named repo: paths are repo-relative, a tracked file leaves
the index and stays on disk, every other class is refused by name, and nothing is committed.

**The door's git never hangs and never prompts.** Every call the door's own runner makes carries a
timeout: 120 s for `fetch` and `merge`, which talk to the remote or run merge drivers, 60 s for the
local reads. The child's environment is a copy of drone's with `GIT_TERMINAL_PROMPT=0`, so a
credential prompt fails at once instead of waiting on a terminal nobody is at. A call that runs out
of time is the verb's failure, naming git's verb, the seconds and the repo (`fetch failed in <repo>:
git fetch timed out after 120 s in <repo>`), so a dead remote never holds drone until its own
command timeout kills the parent and leaves git running.

**`run` reads only.** `run list`, `run view <id> [--log | --log-failed]` and `run watch <id>` read
the repo's GitHub Actions runs, so a tag pushed through the door can be watched through it. The door reads the repo's `origin` URL, https or ssh, with or
without `.git`, derives OWNER/NAME, and hands gh `--repo OWNER/NAME`. An origin that does not name a
github.com repo is refused rather than guessed at, and the URL is never printed, because an https
remote can carry a token. `rerun`, `cancel`, `delete` and `download` stay home-only, and so does gh's
`-R`. `projects/baud` reads as a path or as OWNER/NAME, so the disk decides: a value naming a
directory, absolute or relative to the AIPass root, is the door's. Anything else reaches gh
untouched. A mistyped path therefore comes back as gh's own "could not resolve"
error, not as a door refusal. gh's `-R` is refused in every spelling beside the door's path:
`-R VALUE`, `-R=VALUE` and the attached `-RVALUE`. `run watch` keeps the passthrough's 60-second
timeout, at home and through the door alike.

The refusal texts are constants in `repo_door.py`, and `drone @git --help` renders those same
constants — one wording, two places, no copy. Pinned by `TestRepoDoorRefusals`,
`TestRepoDoorHappyPath`, `TestRepoDoorFetchAndSync`, `TestRepoDoorMergeUpstream` and
`TestRepoDoorRunReads`, `TestRepoDoorGitRunner` and `TestRepoDoorTrackedAndUntrack` in
`tests/test_git_access_gh_door.py`, against real repos with a real bare origin and a second clone standing in for another machine. gh alone is faked: the tests assert the
argv the door builds.

---

## Two design constraints

**A module routed in-process has no caller stamp.** `@git` runs inside drone, so the
`AIPASS_CALLER_*` variables the rail reads are unset unless the door stamps them. It stamps them
itself and restores them in a `finally`, so the rail sees the same shape it sees for a routed child.

**A new flag can eat a passthrough's own flag.** The door's `--repo` must never swallow gh's
`--repo OWNER/NAME` on `issue`, `run`, `workflow` and `release`. The exclusion is explicit in
`handle_command` and pinned at the dispatch level, not at a helper.

---

## Related

- [git_access.md](git_access.md) — the owner tier this door deliberately does not use
- [git_interface.md](git_interface.md) — the verbs themselves
- [rm_and_the_record.md](rm_and_the_record.md) — the other ledger in `.ai_central/`
