# The git interface — read doors, machine output, and the commit gate

**Branch** drone · **Code** `apps/modules/git_module.py`, `apps/handlers/git/`,
`apps/handlers/json_flags.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

What each verb does once the tier gate in [git_access.md](git_access.md) has let it through. The
verb list and its flags are `drone @git --help`.

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

`status`, `log`, `show` and `remote` answer in prose by default and in one JSON document with
`--json`. The flag rides in **any slot** and is stripped before positional parsing, so
`log --json 20` parses exactly like `log 20`. A help flag outranks it: `status --help --json` is
still a question.

Every document carries an `ok` verdict, **including refusals** — a caller that asked for JSON can
parse why it failed rather than getting a bare sentence it has to guess at. The exit code still
goes non-zero, so a shell script reading only `$?` is told the same truth.

Consumers were previously scraping the rendered output (@api's host lane was keyed on the *shape*
of a status row). That migration has completed: `api/apps/handlers/host/git_reads.py` takes the
document and reads no rendered drone row anywhere. Prose output is unchanged by design — every
existing reader keeps working — but new callers should take the document.

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

`remote` is global tier: listing remotes writes nothing. It exists because there was no door for
the question at all — @api's host lane read `.git/config` as an INI file and hand-rolled its own
worktree-following to locate it. Shelling the question through git resolves a worktree's common
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

---

## The commit subject cap — the why goes in the body

`drone @git commit` refuses a message whose **subject** (line 1, after git's own leading-blank-line
cleanup) is over the cap. Exit 1, nothing staged, nothing committed. The refusal text is the rule
itself: keep the subject under about 80 chars in `type(scope): what` form, blank line, then the why
in the body — a body of any length is fine and wanted.

The number is **prax's** `SUBJECT_CAP`, imported from `aipass.prax.apps.modules.dashboard` and
never copied into drone: a commit subject and a plan subject are the same glance (the dashboard's
`last_commit_msg`, the oneline log, the PR list), so they are the same cap. Pinned by reading the
import line out of the source, because a hand-copied number survives an identity check — CPython
interns small ints, and that mutant lived until the pin changed.

Where it sits matters as much as the number. `subject_refusal()` runs **first** in
`commit_handler.commit_changes()` — before the repo is resolved, before `--all`'s ruff pass, before
the per-branch pytest gate. A message's shape is knowable without touching a repo, and a refusal
that has already spent three minutes of pytest teaches nothing. The external-repo door inherits it
unchanged: `--repo <path> commit` routes through the same function, and its ledger line records the
refusal like any other outcome.

`pr_handler.create_pr()` composes its own commit message and measures it **before** it acquires the
PR lock — a PR commit lands in the same oneline log as any other, and a refusal holding the
repo-wide lock would block every other citizen while it teaches.

DPLAN-0347 / FPLAN-0593 Phase 3. Pinned by `TestCommitSubjectCap` in `tests/test_git_access.py`
(including the boundary: a subject exactly at the cap commits) and by two cases in `TestPRHandler`
in `tests/test_git_module.py`.

---

## The `--all` pre-commit lane

`commit --all` stages the whole repo, which is the correct default since dispatched agents work
across several branch directories. Before it stages, it runs ruff (`check --fix`, `format`, then
`check` as a gate) and then pytest for every branch whose files changed, mapping a changed file to
its branch by walking up for `.trinity/`. Templates ship complete branch skeletons, so the
**outermost** hit inside the project wins — citizens never nest, and the innermost rule sent the
gate running pytest inside @spawn's template.

A branch with no `tests/` directory is skipped, not failed. A per-branch pytest budget bounds the
gate: the largest suite in the fleet runs a few minutes, and a cap below a green suite's real
runtime turns the gate into a false red that blocks every commit touching that branch.

---

## Tag lanes — AIPass vs an external repo

`tag` is one verb with two release lanes, chosen by the repo the command will actually run in
(`repo_context.is_aipass_repo()` — the root holds `AIPASS_REGISTRY.json` or it does not). The gate
that used to refuse `tag` from a `projects/*` seat is gone: it now translates.

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
stays with the repo owner (DPLAN-0290 item 1, the user's ruling).

Both lanes are covered by `tests/test_tag_handler.py`, where `TestAipassSeatUnchanged` pins the
AIPass lane argv-for-argv so translation elsewhere cannot move it. The external lane was
additionally proven end to end against a throwaway repo with a real bare origin by a local
acceptance script (that directory is git-ignored, so it is not in a clone).

---

## gh passthrough, and the two rewrites

`issue`, `run` and `workflow` pass straight through to the `gh` CLI. Two exceptions:

**`issue view <n>`.** gh's default view is a GraphQL query requesting `repository.issue.projectCards`,
a Projects-classic field GitHub now rejects outright: the call returned the deprecation notice and
no issue at all, and `--comments` failed the same way. `_rewrite_issue_view()` renders the same view
from pinned `--json` fields plus a `--template`, so the dead field is never requested. `--comments`
becomes a requested field rather than a flag (it conflicts with `--json`). Callers who already chose
a rendering — `--json`, `--jq`, `--template`, `--web` — keep their own invocation untouched;
unrelated flags are preserved. No other issue subcommand is rewritten.

**`run view --log` / `--log-failed`.** gh 2.45 finds each step's log by file name inside the run's
log archive, and GitHub's archive now holds job-level files only, so gh printed nothing and exited
0. When `run view` with a log flag comes back empty on a clean exit, drone reads the jobs API
through `gh api`: each job's full log (only the failed jobs for `--log-failed`), every line led by
the job name and a tab, with a notice on stderr saying so. `-R/--repo`, `--job` and `--attempt` are
honoured, and a job whose log the API refuses fails the command by name (`TestRunLogFallback` in
`tests/test_git_module.py`).

Note the collision that shaped the door: these three verbs take gh's **own** `--repo OWNER/NAME`,
which is why they are not external-repo door verbs.

---

## Related

- [git_access.md](git_access.md) — who may run which verb
- [external_repo_door.md](external_repo_door.md) — the `--repo <path>` door and its ledger
