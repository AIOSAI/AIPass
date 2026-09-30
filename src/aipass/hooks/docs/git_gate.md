[<- Back to the README](../README.md)

# The git gate

**Branch** hooks · **Code** `apps/handlers/security/git_gate.py`

---

## Git Gate

The `git_gate` handler (`security/git_gate.py`) enforces git access via drone to prevent state conflicts between agents. It is **enabled by default** in every project created by `aipass init`.

**What it blocks:** Raw `git` write commands (push, commit, checkout, merge, etc.) and raw `gh` commands (except `gh api`).

**What it allows raw is a CLOSED allow-list, not "read-only verbs".** `READ_ALLOWED_GIT_SUBCOMMANDS`
(`security/git_gate.py:26`) holds exactly these 21: `ls-files`, `ls-tree`, `show`, `cat-file`,
`rev-parse`, `rev-list`, `log`, `status`, `diff`, `blame`, `describe`, `for-each-ref`, `show-ref`,
`symbolic-ref`, `shortlog`, `grep`, `archive`, `count-objects`, `var`, `help`, `version`. A verb that
is not on the list is refused *whatever it does*, and several ordinary read verbs are not on it —
measured 2026-09-05 by calling `_all_git_reads()` directly: `git tag --sort=…`, `git branch -a`,
`git remote -v`, `git config --get …`, `git stash list`, `git reflog`, `git worktree list` and
`git notes list` are all **blocked**. This surprised @devpulse live on `git tag --sort` (2026-09-05).
The earlier wording here said "status, log, diff, show, blame, grep, **etc.**", which read as an open
set; it is not one. Whether the list should grow is a code question, open.

**What it reads is code, not data (1.1.0, 2026-09-16).** Before matching, the command goes through
`bash_writes.code_text()`, the branch's one shell reader: a heredoc body whose consumer only reads it (a
mail body, a `cat` into a file) is blanked, and a shell's own program text (`bash -c "…"`,
`bash <<'EOF'`) is kept, tokenized. The first cures the false fire where prose that merely quoted a
write-shaped git line refused an `ai_mail` reply; the second closes the opposite hole, where a quoted
`bash -c` script was blanked as an argument and read as no invocation at all. If the reader raises, the
gate scans the raw command as before — a gate that cannot parse must not turn permissive.

One refusal is all-or-nothing per command: `_all_git_reads()` requires *every* git invocation in the
command to be an allowed verb, so `git status && git tag` is refused whole.

**One program, many spellings (1.3.0, 2026-09-19).** The regexes are CANDIDATE finders now, matching
`git` with any dotted tail and any casing; `_invocations()` turns a candidate into a verdict by asking
`bash_writes.verb_name()` whether that spelling really names git. Measured before the cure, of
`git.exe`, `GIT`, `Git`, `git.cmd`, `/usr/bin/git.exe` and `gh.exe`, **every one was allowed** and only
the bare lowercase spelling was refused — on Windows all of them run the program, so the one mechanical
layer holding git writes behind drone was a rename away from being off (reported 09-16, cured on the
owner's go under devpulse DPLAN-0352). The executable-extension list lives once, in `bash_writes`, so a
file merely NAMED for a program (`git.py`) is still nobody's invocation and stays quiet. Read verbs are
spelling-blind in the same way: `GIT status` is allowed, like `git status`.

**What it protects:** Edits to `.claude/settings.json`, `.claude/hooks/`, and `.git/hooks/` — the enforcement layer itself.
The path is matched with `\` read as `/` and case-insensitively (1.2.0). Before that, a Windows backslash
path never matched and the edit was allowed.

**Disabling for a project:** Set `git_gate.enabled` to `false` in your project's `.aipass/hooks.json`. This disables git enforcement in isolation — all other hooks (edit_gate, rm_gate, prompt injection, etc.) continue to work normally. No sync, rebase, or PR flows depend on git_gate being active; those are handled independently by `drone @git`.

```json
"git_gate": {
    "enabled": false,
    "handler": "aipass.hooks.apps.handlers.security.git_gate.handle",
    "matcher": "Bash|Edit|MultiEdit|Write|NotebookEdit"
}
```

**Why it's on by default:** Agents reflexively reach for raw git, which causes state chaos in a multi-agent system. The gate redirects to `drone @git` which enforces access tiers (read-only for most branches, write-only for devpulse). External users who don't need multi-agent git orchestration can safely disable it.

---

## Related

- [edit_gate.md](edit_gate.md) — the write fence that runs beside it on the same event
- [bash_writes.md](bash_writes.md) — the shell reader that tells code from data
