[<- Back to the README](../README.md)

# The git interface — read doors, machine output, and the commit gate

**Branch** drone · **Code** `apps/modules/git_module.py`, `apps/handlers/git/`,
`apps/handlers/json_flags.py`

What each verb does once the tier gate in [git_access.md](git_access.md) has let it through. The
verb list and its flags are `drone @git --help`; one verb on its own is `drone @git <verb> --help`
or `drone @git help <verb>`, and an unknown verb falls through to the full page.

---

## Scoping — why `show` is different

`status`, `diff` and `log` are scoped to the caller's branch directory, which hides other branches'
noise. `show` sits at global tier because reading history is not a write, and it is deliberately
**not** scoped: scoping it would refuse the case it exists for — one citizen auditing another's
past. Auditing a deletion means reading what was deleted, and the present-tense verbs cannot.

Both the ref and the optional path are refused before any argv is built if git would read them as a
flag (empty, or a leading `-`) — the same guard the tag lanes use.

---

## Machine output — `--json` on the read doors

`status`, `log`, `show`, `remote` and `release list` answer in prose by default and in one JSON
document with `--json`. The flag rides in **any slot** and is stripped before positional parsing, so
`log --json 20` parses exactly like `log 20`. A help flag outranks it: `status --help --json` is
still a question.

Every document carries an `ok` verdict, **including refusals** — a caller that asked for JSON can
parse why it failed rather than getting a bare sentence it has to guess at. The exit code still
goes non-zero, so a shell script reading only `$?` is told the same truth.

Prose output is kept stable for human readers; a machine caller takes the document, never the
shape of a rendered row.

**`status --json` reports git's two porcelain columns, which the rendered view cannot.** The
columns are index then worktree, and they are different facts: `M ` is a staged modification, ` M`
an unstaged one. The rendered row shows one right-aligned letter and always has, so those two
collapse into the same `   M` on screen — a consumer reading the rendered row sees every staged
change as unstaged. The document carries `status` verbatim plus `index` and `worktree` split out:

```json
{"status": "M ", "path": "src/x.py", "index": "M", "worktree": " "}
```

---

## Where a repository points — `remote`

`remote` is global tier: listing remotes writes nothing. It answers where a repository points
without a caller parsing `.git/config` itself, and asking git resolves a worktree's common
directory for free.

**Credentials never travel.** An `http(s)` URL configured with credentials is answered with its
*entire* userinfo component replaced by `***`, and the raw value reaches no return, no log line and
no audit record. The whole component goes, not just a password: the common personal-access-token
form is `https://<TOKEN>@host/path`, where the secret sits in the username slot.

SSH forms are left alone deliberately — in `git@github.com:a/b.git` the `git@` is the standard
account name, not a secret, and redacting it would mangle every ordinary remote to hide nothing.

A repository with no remote is a real answer (`ok: true`, `count: 0`), not an error. A directory
with no `.git` at all answers `ok: false` on a non-zero return — a different answer, and the two
are not collapsed.

**`remote set <name> <url>`** is the one write, owner tier (the gate's `remote-write`), so a
project's manager runs it in its own repo and the admin seat reaches another repo with `--repo`.
It adds the remote when the name is absent and re-points it with `set-url` when present; the same
url again is reported unchanged. The url must name a github.com repository in one of three forms,
`https://github.com/OWNER/NAME`, `git@github.com:OWNER/NAME` or `ssh://git@github.com/OWNER/NAME`
(`.git` optional), and an https url with userinfo is refused, because a token there would be
stored in `.git/config` in clear. Every set lands one line in `git_remote_sets.jsonl` in AIPass's
`.ai_central`: caller, repo, name, the old url (redacted) and the new one, and the outcome.

---

## The commit subject cap — the why goes in the body

`drone @git commit` refuses a message whose **subject** (line 1, after git's own leading-blank-line
cleanup) is over the cap. Exit 1, nothing staged, nothing committed. The refusal text is the rule
itself: keep the subject under about 80 chars in `type(scope): what` form, blank line, then the why
in the body — a body of any length is fine and wanted.

The number is **prax's** `SUBJECT_CAP`, imported from `aipass.prax.apps.modules.dashboard` and
never copied into drone: a commit subject and a plan subject are the same glance (the dashboard's
`last_commit_msg`, the oneline log, the PR list), so they are the same cap. Pinned by reading the
import line out of the source, because a hand-copied number survives an identity check: CPython
interns small ints.

Where it sits matters as much as the number. `subject_refusal()` runs **first** in
`commit_handler.commit_changes()` — before the repo is resolved, before `--all`'s ruff pass, before
the per-branch pytest gate. A message's shape is knowable without touching a repo, and a refusal
that has already spent three minutes of pytest teaches nothing. The external-repo door inherits it
unchanged: `--repo <path> commit` routes through the same function, and its ledger line records the
refusal like any other outcome.

Pinned by `TestCommitSubjectCap` in `tests/test_git_access_handlers.py` (including the boundary: a
subject exactly at the cap commits).

---

## `untrack` — out of the index, never off the disk

A `.gitignore` line never untracks a file the index already holds, and raw git is blocked for every
seat. `drone @git untrack <path ...>` is the door to `git rm --cached`, owner tier, beside `commit`. Each path is classified exactly as `tracked` classifies it. Only a tracked file leaves the
index; an untracked, ignored, missing or outside path is refused by name with its class and nothing
is done for it, and a directory is refused unless `--recursive` is given, because one directory can
untrack a whole tree. Refusals do not stop the accepted paths, and any refusal makes the exit 1.

The verb never touches the working tree and never commits. Its last line names the next step:
`drone @git commit "<message>"` with **no paths**. Commit with paths runs `git add` on them, which
stages a still-present file straight back into the index, or fails outright on one that is now
ignored. No PR lock is taken, because `commit` takes none; the operation log records each run as
every verb's does, and there is no separate owner-verb ledger to write. `untrack` and `tracked` also
run through the external-repo door (`--repo <path>`, admin seat, paths repo-relative, every use in
its ledger; see [external_repo_door.md](external_repo_door.md)). Pinned by `TestUntrack` in
`tests/test_git_module.py`, against a real repo.

## `restore` — named tracked files back to a commit, never a deletion

`drone @git restore [--source <ref>] <path ...>` is the door to
`git restore --source <ref> --staged --worktree`, owner tier, beside `untrack`. Without `--source`
the target is HEAD; the ref may be a sha or an expression such as `9fc0e3b5^`. Each named file
returns to that commit's content, index included. A directory means the tracked files under it.
Paths are classified as `tracked` classifies them, and every path is checked before any file is
touched: one refusal stops the whole call. `.`, `./` and any path holding `*`, `?` or `[` are
refused by name, as are a path outside the repo, one neither tracked nor on disk, a ref that names
no commit, and any flag but `--source`. There is no force flag. A file tracked now but absent at the
source is refused, because restoring it would delete it, and deletion belongs to `drone rm`. The
verb refuses on `main`.

It prints each file it put back with its source, then the count, or `nothing to restore` when every
named path already matches. Untracked files under a named path are left alone and listed as
`untracked, left in place: <path>`. Every call, refusals included, writes one row to AIPass's
`.ai_central/git_restores.jsonl`: timestamp, caller, cwd, repo, source, the paths asked for, and
the paths restored and left, or the refusal. Pinned by `TestRestore` in
`tests/test_git_access_gh_door.py`, against a real repo.

---

## The `--all` pre-commit lane

`commit --all` stages the whole repo, which is the correct default since dispatched agents work
across several branch directories. Before it stages, it runs ruff `check` as a gate over whichever
of `src/` and `tests/` exist at the repo root (an external project keeps its tests under
`src/<pkg>/`), and a lint-dirty tree is refused with nothing changed. Only after the gate passes do
`check --fix` and `format` run, and only on the Python files `git status` lists as changed; the
result's stdout names every file they rewrote. Then pytest runs for every branch whose files changed, mapping a changed file to
its branch by walking up for `.trinity/`. Templates ship complete branch skeletons, so the
**outermost** hit inside the project wins: citizens never nest, and the innermost hit can be a
template skeleton inside @spawn.

A branch with no `tests/` directory is skipped, not failed. A per-branch pytest budget bounds the
gate: the largest suite in the fleet runs a few minutes, and a cap below a green suite's real
runtime turns the gate into a false red that blocks every commit touching that branch.

---

## Tag lanes — AIPass vs an external repo

`tag` is one verb with two release lanes, chosen by the repo the command will actually run in
(`repo_context.is_aipass_repo()` — the root holds `AIPASS_REGISTRY.json` or it does not). A
`projects/*` seat gets the external lane.

| | AIPass repo | External project seat |
|---|---|---|
| What gets tagged | `origin/main` | that repo's current **HEAD**, any branch |
| Version guard | `pyproject.toml` and `src/aipass/__init__.py` on origin/main must match | **none** — manifests and cadence belong to the repo owner |
| Name rule | `vX.Y.Z` | anything `git check-ref-format` accepts |
| Duplicate guard | refuses if the tag exists locally or on the remote | same, and the remote check's exit code is verified — an unreachable remote refuses instead of tagging blind |
| Push | to origin | same, to that repo's own origin |

Both lanes create **annotated** tags. Names git would read as a flag (empty, leading `-`) are
refused before any argv is built.

Why no version guard outside AIPass: an external repo has its own manifests and its own release
lane. Reading ours out of someone else's tree would be an invented rule, so version discipline
stays with the repo owner.

Both lanes are covered by `tests/test_tag_handler.py`, where `TestAipassSeatUnchanged` pins the
AIPass lane argv-for-argv so translation elsewhere cannot move it.

---

## gh passthrough, the two rewrites and the long watch

`issue`, `run` and `workflow` pass straight through to the `gh` CLI with a 60-second timeout. Three
exceptions:

**`issue view <n>`.** gh's default view is a GraphQL query requesting `repository.issue.projectCards`,
a Projects-classic field GitHub rejects outright, so the call returns the deprecation notice and no
issue at all, `--comments` too. `_rewrite_issue_view()` renders the same view
from pinned `--json` fields plus a `--template`, so the dead field is never requested. `--comments`
becomes a requested field rather than a flag (it conflicts with `--json`). Callers who already chose
a rendering — `--json`, `--jq`, `--template`, `--web` — keep their own invocation untouched;
unrelated flags are preserved. No other issue subcommand is rewritten.

**`run view --log` / `--log-failed`.** gh 2.45 finds each step's log by file name inside the run's
log archive, and GitHub's archive holds job-level files only, so gh prints nothing and exits 0.
When `run view` with a log flag comes back empty on a clean exit, drone reads the jobs API
through `gh api`: each job's full log (only the failed jobs for `--log-failed`), every line led by
the job name and a tab, with a notice on stderr saying so. `-R/--repo`, `--job` and `--attempt` are
honoured, and a job whose log the API refuses fails the command by name (`TestRunLogFallback` in
`tests/test_git_module.py`).

**`run watch <id>`.** A CI run takes about 30 minutes, so watch waits up to 45 before it gives up,
and gh polls every 60 seconds unless the caller passes its own `-i/--interval`. Its output is not
captured: gh's own run state reaches the terminal on every poll, so a human sees it is alive. Past
the ceiling the command fails with `gh run timed out after 2700s`.

These three verbs take gh's **own** `--repo OWNER/NAME`, which is why they are not external-repo
door verbs.

---

## `release list` — published releases, every seat

`drone @git release list [--repo OWNER/NAME] [--since TAG] [--limit N] [--json]` is global tier, like
`run list` and `log`, so project citizens read it too: a release watcher reads AIPass's release
tags and notes through it. `--repo` is GitHub's OWNER/NAME, never a path, so `release` sits beside the gh
passthroughs where the external-repo door does not take the flag; it defaults to AIOSAI/AIPass.
Rows come newest first, tag, `published_at` and name, with the notes indented under each; `--json`
gives one document with the raw rows. Drafts are skipped. `--since TAG` stops before that tag, and
the pages are read on past `--limit` until it is seen, so a mistyped tag is refused rather than
hidden behind a full page.

It is backed by `gh api repos/OWNER/NAME/releases`, 100 to a page, because `gh release list`
carries no notes. The repo's own record is read first: public data only, so a private repo is
refused even when gh's account could read it. An unknown repo (GitHub's 404), a missing gh and a
gh failure are each refused with the reason. Pinned by `TestReleaseList` in
`tests/test_git_module.py`, with gh stubbed as GitHub would answer.

---

## The GitHub chores — `release edit`, `label`, `alerts`

Three verbs run a repo's GitHub chores through gh. Each reads the repo the caller stands in and
takes its OWNER/NAME from that repo's `origin`, never from an argument, so a write lands on the
repo whose ownership the gate checked. The write subcommands are owner tier, keyed
`release-write`, `label-write` and `alerts-write`: devpulse in AIPass, a project's manager in its
own repo. `--repo <path>` is the external-repo door, admin seat only. The reads are global.

| Verb | Tier | Runs |
|------|------|------|
| `release edit <tag>` | owner | `gh release edit <tag> --notes-file -` |
| `label list [--json]` | global | `gh label list --json name,color,description` |
| `label create <name> [--color hex] [--description text]` | owner | `gh label create` |
| `alerts list [--state open\|dismissed\|all] [--json]` | global | `gh api repos/OWNER/NAME/code-scanning/alerts` |
| `alerts dismiss <n> --reason R --comment 'text'` | owner | `gh api -X PATCH .../code-scanning/alerts/<n>` |

**`release edit`** rewrites a published release's notes with the CHANGELOG.md block for its tag,
by publish.yml's rule: the block whose `## [` header carries the tag between non-version
characters (so v2.8.2 never claims v2.8.20), up to the next header, `---` lines dropped. Over
120,000 characters it is cut on an entry boundary and ends with a pointer at the full block, since
GitHub refuses a body over 125,000. It refuses a tag no header carries and a tag that is not a
published release, prints the old and new note lengths, and sends nothing when the notes already
match.

**`label create`** reads the labels first and compares names without case, as GitHub does: a
label already there is reported present, exit 0, and nothing is sent. `--color` takes six hex
digits, with or without `#`.

**`alerts dismiss`** requires `--comment`, which goes to GitHub with the reason, so every
dismissal says why there; a missing or blank comment is refused by name, as is one over GitHub's
280 characters. `--reason` takes `false_positive`, `wont_fix` or `used_in_tests`, sent in GitHub's
words. Only an open alert is dismissed. `alerts list` prints number, rule id, severity, state and
`file:line`, one row each.

Every write subcommand writes one line to AIPass's own `.ai_central/git_gh_writes.jsonl`, a no-op
included: caller, verb, repo, OWNER/NAME, outcome (`written` or `unchanged`), and the verb's own
fields (tag and both lengths; label, color and description; number, rule, reason and comment).
Through the door the door's own ledger records the use as well. Pinned by `TestReleaseEdit`,
`TestLabel`, `TestAlerts` and `TestChoresThroughTheDoor` in `tests/test_git_access_gh_door.py`.

---

## Related

- [git_access.md](git_access.md) — who may run which verb
- [external_repo_door.md](external_repo_door.md) — the `--repo <path>` door and its ledger
