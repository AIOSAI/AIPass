# =================== AIPass ====================
# Name: help_pages.py
# Description: The @git help pages, one per verb and the whole page
# Version: 1.4.0
# Created: 2026-10-04
# Modified: 2026-10-17
# =============================================

"""The @git help pages: one per verb, and the whole page.

Text only. It moved out of apps/modules/git_module.py verbatim when that file
reached its 1,500-line cap (2026-10-04). git_module.get_help still answers
every call and keeps the gh passthroughs' pages, which read the gate's table.
"""

from __future__ import annotations

from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git import (
    commit_handler,
    merge_main_handler,
    release_handler,
    repo_door,
    untrack_handler,
)


def page(command: str | None = None) -> str:
    """Return the help page for *command*; None or an unknown verb gets the whole page.

    Args:
        command: Optional specific subcommand to get help for.

    Returns:
        Help text string.
    """
    json_handler.log_operation("git_help_page", {"command": command or ""})
    if command == "pr":
        return (
            "git pr <description> — Push current branch and create PR to main [owner]\n"
            "  On main: creates temp branch from slug. Otherwise: pushes branch directly. No -u flag.\n"
        )
    if command == "status":
        return (
            "git status [--all] — Show git status filtered to your branch (--all for repo-wide) [global]\n"
            "  --all also says how far the branch is from origin, as of the last fetch:\n"
            "  dev: 2 ahead, 1 behind origin/dev (as of the last fetch). No network.\n"
            "  With --json: upstream, ahead and behind (null with no origin twin).\n"
        )
    if command == "diff":
        return (
            "git diff [--staged] [--stat] [--all] [path ...] [-- gone-path ...] — Show git diff [global]\n"
            "  Filtered to your branch, or to the paths named.\n"
            "  Options:\n"
            "    --staged   Show staged changes only.\n"
            "    --stat     The summary (file | changes), not the patch.\n"
            "    --all      Show all repo changes (not just your branch).\n"
            "  A path is read against your directory first, then the repo root;\n"
            "  one that no longer exists goes after --. Any other flag is refused.\n"
            "  Example: drone @git diff --stat apps/drone.py\n"
        )
    if command == "log":
        return (
            "git log [count] [path ...] [-- gone-path ...] — Show recent git log entries (default: 10) [global]\n"
            "  count: N, -n N or -N. With paths, only the commits touching them.\n"
            "  A path is read against your directory first, then the repo root;\n"
            "  one that no longer exists goes after --.\n"
            "  A range a..b (or a...b) lists every commit in it, read-only; a count caps it.\n"
            "  Example: drone @git log 5 src/aipass/drone\n"
            "  Example: drone @git log origin/dev..HEAD\n"
        )
    if command == "tracked":
        return (
            "git tracked <path ...> — Whether git tracks, ignores or has never seen each path [global]\n"
            "  One row per path, in the order given: tracked, ignored, untracked,\n"
            "  missing (not on disk, not tracked) or outside (not in this repo).\n"
            "  A path is read against your directory first, then the repo root.\n"
            "  Example: drone @git tracked docs/plan.md logs/run.log\n"
        )
    if command == "untrack":
        return (
            "git untrack [--recursive] <path ...> — Take tracked files out of the index, files stay on disk [owner]\n"
            "  The twin of git rm --cached. Each path is read as tracked reads it; only a\n"
            "  tracked one leaves the index. Never touches the working tree, never commits.\n"
            "  Refused by name, nothing done for that path (exit 1, the others still run):\n"
            f"    {untrack_handler.REFUSE_NOT_TRACKED.format(path='<path>', state='<state>')}\n"
            f"    {untrack_handler.REFUSE_DIRECTORY.format(path='<path>')}\n"
            "  --recursive   A directory leaves the index whole (git rm --cached -r).\n"
            '  Then commit the removal with no paths: drone @git commit "<message>"\n'
            "  (paths would stage the files again). --repo <path>: the admin door, paths repo-relative.\n"
        )
    if command == "release":
        return (
            "git release list [--repo OWNER/NAME] [--since TAG] [--limit N] [--json] — Published releases [global]\n"
            "  Newest first, one row per release: tag, published_at (ISO), name, with the\n"
            f"  notes indented under it. --repo defaults to {release_handler.DEFAULT_REPO}, public only.\n"
            "  --since TAG stops at that tag (exclusive). --limit N caps the rows (default\n"
            f"  {release_handler.DEFAULT_LIMIT}). --json prints one document: ok, repo, count, releases.\n"
            "  Drafts are skipped. Read through gh api; refused, exactly as printed:\n"
            + "".join(
                f"    {text}\n"
                for text in (
                    release_handler.REFUSE_NO_GH,
                    release_handler.REFUSE_PRIVATE.format(repo="<repo>"),
                    release_handler.REFUSE_UNKNOWN.format(repo="<repo>"),
                    release_handler.REFUSE_SINCE.format(tag="<tag>", repo="<repo>"),
                )
            )
            + "  Example: drone @git release list --since v2.8.16\n"
        )
    if command == "export":
        return (
            "git export <ref> <dir> — The tracked tree at a commit, written into a directory [global]\n"
            "  Tracked files only: nothing untracked or ignored comes along.\n"
            "  <dir> must be empty (it is made if absent) and sit under the temp dir\n"
            "  or your own docs.local; a relative <dir> is read against your directory.\n"
            "  Example: drone @git export HEAD docs.local/clean_tree\n"
        )
    if command == "blame":
        return (
            "git blame <file> [-L START,END] — Who last changed each line of a file [global]\n"
            "  The file is read against your directory first, then the repo root.\n"
            "  -L takes two line numbers, 1-based and inclusive.\n"
            "  Example: drone @git blame apps/drone.py -L 10,40\n"
        )
    if command == "lock":
        return "git lock — Check current lock status [global]\n  Shows lock holder, age, stale/orphan detection.\n"
    if command == "branches":
        return "git branches — List all remote branches [global]\n"
    if command == "dev-pr":
        return (
            "git dev-pr <description> — Push dev branch and create PR to main [owner]\n"
            "  Description becomes the PR title.\n"
            "  External project, its manager's seat: refused unless on dev, no tracked\n"
            "  file modified, dev ahead of origin/main. The PR opens on origin's GitHub repo.\n"
        )
    if command == "delete-branch":
        return (
            "git delete-branch <name> — Delete a remote branch [owner]\n  Protected: main and dev cannot be deleted.\n"
        )
    if command == "close-pr":
        return "git close-pr <number> — Close a GitHub pull request by number [owner]\n"
    if command == "commit":
        return (
            "git commit <message> [--all | file1 file2 ...] — Commit changes [owner]\n"
            "  Options:\n"
            "    --all          Stage all repo changes (git add -A) before committing.\n"
            "    file1 file2    Stage only these files before committing.\n"
            "  With no flag or files, commits whatever is already staged.\n"
            f"  The subject (line 1) is refused over {commit_handler.SUBJECT_CAP} chars: keep it under\n"
            "  about 80 in type(scope): what form, blank line, then the why in the body.\n"
        )
    if command == "checkout":
        return "git checkout <main|dev> — Switch branches (main or dev only) [owner]\n"
    if command == "sync":
        return (
            "git sync [--autostash] [--main-ref] — Sync with origin/main [owner]\n"
            "  On dev: fast-forward to origin/main (stays on dev, no checkout).\n"
            "  On main: pull latest. From other branch: checkout main first.\n"
            "  Refuses if dev has diverged — no silent rewrite.\n"
            "  Options:\n"
            "    --autostash   Stash local changes before sync and restore after.\n"
            "    --main-ref    Update local main ref without checkout (from any branch).\n"
        )
    if command == "merge-main":
        return merge_main_handler.HELP
    if command == "unlock":
        return "git unlock --force — Force-release the PR lock [owner]\n"
    if command == "merge":
        return (
            "git merge <PR#> [--confirm] — Merge a PR and sync local main [owner]\n"
            "  Runs gh pr merge --merge --delete-branch, then git pull --rebase.\n"
            "  Joint-decision gate: terminal sessions get a y/N prompt; headless\n"
            "  callers must pass --confirm or the merge is refused.\n"
            "  External project, its manager's seat: merges on origin's GitHub repo, then\n"
            "  checks out dev and fast-forwards it to origin/dev.\n"
        )
    if command == "smart-sync":
        return "git smart-sync — Fetch origin and rebase if behind [owner]\n"
    if command == "fix":
        return (
            "git fix [--dry-run] — Detect and fix broken git states [owner]\n"
            "\n"
            "Detected states and actions:\n"
            "  Stuck rebase   → git rebase --abort\n"
            "  Detached HEAD  → git checkout main\n"
            "  Diverged       → git fetch + git merge origin/main\n"
            "  Dirty index    → git reset HEAD\n"
            "  Dev behind main (diverged, already pushed) is not fixed here:\n"
            "  use drone @git merge-main, which merges without a rewrite.\n"
            "\n"
            "Options:\n"
            "  --dry-run   Report without executing fixes.\n"
        )
    if command == "push":
        return (
            "git push --repo <path> — Push an external repo's checked-out branch to its origin [admin seat]\n"
            "  Same branch name on origin, never forced; git's own refusal comes back untouched.\n"
            "  Only through the external-repo door — AIPass pushes through dev-pr.\n"
        )
    if command == "tag":
        return (
            "git tag <vX.Y.Z> — Create and push an annotated release tag [owner]\n"
            "git tag --list    — List all tags (newest first) [global]\n"
            "\n"
            "In AIPass:\n"
            "  Tags origin/main. Version guard — refuses unless pyproject.toml and\n"
            "  __init__.py on origin/main both match the tag version.\n"
            "\n"
            "In an external project (projects/*, any other repo):\n"
            "  Tags that repo's current HEAD and pushes to its own origin. No version\n"
            "  guard — your manifests and release cadence are yours. Any name git\n"
            "  accepts as a tag works, not just vX.Y.Z.\n"
            "\n"
            "Both:\n"
            "  Exists guard    Refuses if tag already exists locally or on remote.\n"
        )

    return (
        "git — Tier-based git workflow (dev branch model)\n"
        "Global (all branches):\n"
        "  status [--all]         Show git status for your branch (--all: repo, ahead/behind origin)\n"
        "  diff [--staged] [--stat] [path ...]\n"
        "                         Show git diff for your branch, or for the paths named\n"
        "  log [count] [path ...] [-- gone-path ...]\n"
        "                         Show recent git log (default: 10); with paths, only the\n"
        "                         commits touching them. count: N, -n N or -N\n"
        "  log [count] <a>..<b>   Every commit in a range (a count caps it)\n"
        "  show <ref> [path]      Show a commit, or a file's contents at it\n"
        "  blame <file> [-L START,END]  Who last changed each line (optionally a range)\n"
        "  tracked <path ...>     Tracked, ignored, untracked, missing or outside, per path\n"
        "  export <ref> <dir>     The tracked tree at ref into an empty dir (temp or docs.local)\n"
        "  remote                 List remotes and their urls (credentials redacted)\n"
        "  lock                   Check lock status\n"
        "  branches               List remote branches\n"
        "  tag --list             List all tags (newest first)\n"
        "  issue list|view|status gh issue reads (view <#> [--comments])\n"
        "  run list|view|watch    gh run reads (view <id> --log | --log-failed)\n"
        "  workflow list|view     gh workflow reads\n"
        "  release list           Published releases and their notes (release --help)\n"
        "Owner (the repo's registry owner: devpulse in AIPass):\n"
        "  commit <msg> [--all | files]  Commit changes (selective or --all)\n"
        "  untrack <path ...>     Out of the index, files stay on disk (git rm --cached)\n"
        "  checkout <main|dev>    Switch branches\n"
        "  pr <desc>              Push current branch and create PR to main\n"
        "  dev-pr <desc>          Push dev and create PR to main\n"
        "  delete-branch <name>   Delete a remote branch\n"
        "  prune-temp             Delete merged citizen/* temp branches\n"
        "  close-pr <number>      Close a PR\n"
        "  merge <PR#> [--confirm]  Merge a PR (gated: y/N prompt or --confirm)\n"
        "  sync [--autostash]     Sync with origin/main (FF on dev)\n"
        "  merge-main             Merge origin/main into dev, no rewrite, no push\n"
        "  smart-sync             Fetch + rebase if behind\n"
        "  unlock --force         Force-release the PR lock\n"
        "  tag <vX.Y.Z>           Create and push release tag\n"
        "  fix [--dry-run]        Fix broken git states\n"
        "  push --repo <path>     Push an external repo's branch (the door below only)\n"
        "  issue <write>          gh issue create, close, comment, ... (issue --help)\n"
        "  run <write>            gh run rerun, cancel, delete, download\n"
        "  workflow <write>       gh workflow run, enable, disable\n"
        "  A gh subcommand in neither list is refused, never passed to gh.\n"
        "  An external project's manager, from its own seat, runs: commit,\n"
        "  untrack, checkout, sync, merge-main, unlock, merge, dev-pr, prune-temp,\n"
        "  tag, issue <write>, run <write>, workflow <write>. The rest refuse there.\n"
        "\n"
        "RAW GIT READS AND THEIR TWINS (raw git is blocked for agents; use these):\n"
        "  git log -n 5 -- <path>   drone @git log 5 <path>  (deleted path: after --)\n"
        "  git log --oneline -20    drone @git log 20\n"
        "  git show <sha>           drone @git show <sha>\n"
        "  git show <sha>:<path>    drone @git show <sha> <path>\n"
        "  git status               drone @git status [--all]\n"
        "  git diff [--staged]      drone @git diff [--staged] [--all]\n"
        "  git blame -L 10,40 <f>   drone @git blame <f> -L 10,40\n"
        "  git ls-files / check-ignore <p>  drone @git tracked <p ...>\n"
        "  git diff [--stat] -- <path>      drone @git diff [--staged] [--stat] <path ...>\n"
        "  git rev-list --count a...b       drone @git status --all  (ahead/behind origin)\n"
        "  git log origin/dev..HEAD         drone @git log origin/dev..HEAD\n"
        "  git archive <ref> | tar -x       drone @git export <ref> <dir>\n"
        "  gh issue list|view|status  drone @git issue list|view|status\n"
        "  gh run list|view|watch     drone @git run list|view|watch\n"
        "  gh workflow list|view      drone @git workflow list|view\n"
        "  gh release list|view       drone @git release list [--repo O/N] [--since TAG]\n"
        "  Paths are read against your directory first, then the repo root.\n"
        "  No twin yet: git diff <range> -- <path> (use show <sha>). Ask @drone.\n"
        "\n" + repo_door.help_block() + "\n"
        "--json — THE MACHINE SURFACE:\n"
        "  status, log, show, remote and release take --json in ANY slot; it is stripped\n"
        "  before positional parsing, so `log --json 20` parses like `log 20`.\n"
        "  One JSON document on stdout, every one carrying an `ok` verdict — a\n"
        "  refusal is a document too, so a caller can parse why it failed.\n"
        "  A help flag OUTRANKS it: `status --help --json` prints this page.\n"
        "  status --json reports git's TWO porcelain columns ('M ' staged vs\n"
        "  ' M' unstaged) which the rendered view collapses to one letter.\n"
    )
