[<- Back to the README](../README.md)

# Pull requests — `pr list`, `pr view`, and how `merge` reads a PR's base

**Branch** drone · **Code** `apps/handlers/git/pr_read_handler.py`, `apps/plugins/devpulse_ops/merge_plugin.py`

A cloud session works on its own clone. It opens a PR against dev from a branch named
`claude/<slug>-<id>`, and the PR body opens with the dispatch mail id. Nothing reports when that
session ends, so its PR is the signal: these reads find it, and `merge` lands it on dev.

---

## `pr list` — the repo's PRs, filtered

```
drone @git pr list [--base B] [--head PREFIX] [--marker TEXT] [--state open|all] [--json]
```

| Filter | Meaning | Default |
|---|---|---|
| `--base B` | the PR's base branch, exactly; handed to gh and held again on what comes back | any |
| `--head PREFIX` | the head branch starts with PREFIX (`claude/`) | any |
| `--marker TEXT` | the PR body contains TEXT (a mail id) | any |
| `--state open\|all` | open, or every state including merged and closed; any other word is refused before gh | open |

One row per PR: number, `head -> base`, state, `ci <conclusion>`, title, created. The CI conclusion
is read from the checks on the PR's head commit: `failure` when any check failed, errored, was
cancelled or timed out; `success` when every check passed, was neutral or skipped; `pending` while
any is still running; `none` when the commit has no checks. `--json` prints the same rows as a JSON
list with the keys `number`, `head`, `base`, `state`, `ci`, `title`, `created`, plus `head_sha` (the
head commit, so a push to an open PR shows as a new sha under the same head) and `url` (the PR's page).

gh has no head-prefix or body filter, so both are applied to the newest 100 PRs gh returns
(`LIST_LIMIT`). Asking for 200 or more with bodies and checks makes GitHub's GraphQL answer 502 on
AIOSAI/AIPass. No match prints `No open pull requests match on github.com/<owner>/<name>.`

## `pr view <#>` — one PR and its body

```
#830 docs(devpulse): cloud probe, DPLAN-0492
claude/cloud-probe-dplan-0492-5vbbkw -> dev · OPEN · mergeable MERGEABLE · ci success
head 985950d5b9558266ea99964b5543a80aaeba16da · https://github.com/AIOSAI/AIPass/pull/830

<the body: the agent's report>
```

`--json` prints the same keys as a list row plus `mergeable` and `body`. `issue view <#>` also prints a PR's
body, but not its head, base, mergeable state or CI, which is why `pr view` is its own read.

## Who may read

Both are reads in the global tier (the key `pr-read`), like `issue list` and `run list`: every
seat may run them, so a monitor that polls for a cloud PR needs no owner seat. `pr <description>`,
which pushes and opens a PR, stays owner tier. A description whose first word is `list` or `view`
reads; it never becomes a PR title.

Both read the repo the command stands in, its OWNER/NAME taken from the `origin` remote. Through the
admin door, `pr list|view --repo <path>` reads that repo instead.

## `merge <PR#>` — the base decides what is pulled

`merge` reads the PR's base from gh before it does anything else:

- **Base main**, the dev→main train: `gh pr merge --merge` (with `--delete-branch` unless the head is
  dev or main), local changes stashed, `git pull --rebase` on the checked-out branch, the stash
  popped, then back to dev.
- **Base dev**, a cloud session's PR: the same merge, the stash, then dev is checked out if it is
  not already, `git pull --rebase origin dev`, the stash popped, and the repo is left on dev. main
  is not touched.
- **Any other base**, or a base gh cannot read, is refused before the merge, exactly as printed:
  `PR #<n> was not merged: its base is <base>, and drone merges only PRs into dev or main.`

The joint-decision gate is the same for both bases: a terminal gets `[y/N]`, a headless caller must
pass `--confirm`.

---

## Related

- [git_access.md](git_access.md) — the tiers and the dev branch model
- [git_interface.md](git_interface.md) — the other verbs and the `--json` machine surface
