# The external-repo door — `--repo <path>`

**Branch** drone · **Code** `apps/handlers/git/repo_door.py`, `apps/modules/git_module.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

Git in a repo that is not AIPass — a project inside the tree, a clone outside it — goes through one
door, held by @devpulse's admin grant (DPLAN-0344, the owner's go 2026-09-13). Six verbs take
`--repo <path>` (or `--repo=<path>`) in any slot: status, diff, log, commit, push and tag.

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
3. **Which verb** — anything outside the six is refused. `issue`, `run` and `workflow` never reach
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

The refusal texts are constants in `repo_door.py`, and `drone @git --help` renders those same
constants — one wording, two places, no copy. Pinned by `TestRepoDoorRefusals` and
`TestRepoDoorHappyPath` in `tests/test_git_access.py`, the happy path against a real repo with a
real bare origin.

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
