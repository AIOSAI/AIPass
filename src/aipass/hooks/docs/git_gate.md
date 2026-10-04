[<- Back to the README](../README.md)

# The git gate, and the rm gate beside it

**Branch** hooks · **Code** `apps/handlers/security/git_gate.py`, `apps/handlers/security/rm_gate.py`, `apps/modules/protected_paths.py`, `apps/modules/shell_reader.py`

---

## Git Gate

The `git_gate` handler (`security/git_gate.py`) enforces git access via drone to prevent state conflicts between agents. It ships in every project `aipass init` creates, and inside AIPass it is part of the gate set the loader forces on (see [project_config.md](project_config.md)): no project config switches it off. It fails closed — a crash refuses the call it was checking, and the engine refuses on import error and timeout (see [engine.md](engine.md)).

**What it blocks:** raw `git` writes for every seat, raw `git` reads off the admin seat, raw `gh` (below), and writes to the protected files (below).

**Raw reads are the admin seat's alone (since DPLAN-0356).** A raw git
command made only of allow-listed reads still passes only when the session is the verified admin seat:
`modules/admin_seat`'s 5-leg grant (@devpulse), never a directory name. Every other seat is refused,
and the refusal names the caller from its passport (or says it could not be named) and maps each common
read to its drone twin, as published in `drone @git --help` under RAW GIT READS AND THEIR TWINS:
`git log -n 5 -- <path>` is `drone @git log 5 <path>`, `git show <sha>:<path>` is
`drone @git show <sha> <path>`, and likewise status, diff and blame. A read with no twin yet (a range
diff) goes to @drone or @devpulse. Writes stay refused for every seat, the admin seat included. The
allow-list below is therefore what the admin seat may run raw. Agent Bash only: service code that runs
git as a subprocess never passes through a hook.

**gh.** `GH_ALLOWED_SUBCOMMANDS` is `("api",)`: every other raw `gh` subcommand is refused for every
seat with `GH_REDIRECT`, which maps `gh issue`, `gh run`, `gh workflow` and `gh pr create` to their
`drone @git` twins. `gh api` off the admin seat is GET-only (`_gh_api_write`): a `-X`/`--method` other
than GET, any field or body flag (`-f`, `-F`, `--field`, `--raw-field`, `--input`) or `gh api graphql`
is refused with `GH_API_REFUSED`, which names the refused part and the caller. A GET with no body
runs. The admin seat runs `gh api` unrestricted.

**What it allows raw is a CLOSED allow-list, not "read-only verbs".** `READ_ALLOWED_GIT_SUBCOMMANDS`
(`security/git_gate.py`) holds exactly these 21: `ls-files`, `ls-tree`, `show`, `cat-file`,
`rev-parse`, `rev-list`, `log`, `status`, `diff`, `blame`, `describe`, `for-each-ref`, `show-ref`,
`symbolic-ref`, `shortlog`, `grep`, `archive`, `count-objects`, `var`, `help`, `version`. A verb that
is not on the list is refused *whatever it does*, and several ordinary read verbs are not on it:
`git tag --sort=…`, `git branch -a`, `git remote -v`, `git config --get …`, `git stash list`,
`git reflog`, `git worktree list` and `git notes list` are all **blocked**. Whether the list should
grow is a code question, open.

**What it reads is the program the shell will run (since DPLAN-0356 phase 3).** Both gates read the
command through `modules/shell_reader.py`, the branch's ONE shell-word reader; there is no second copy.
It hands back every program the command runs, spelled the way the shell runs it: quotes removed,
escapes and `$'\x67it'` decoded, braces expanded, a glob in the command word (`/usr/bin/g?t`) resolved
against PATH and the cwd, a variable set earlier in the same command folded in. `eval`, `source`, `.`,
`bash -c`, `bash <<<`, a heredoc fed to a shell, `$(…)`, backticks, `find -exec`, `xargs` and the
launchers (`sudo`, `env -S`, `timeout`, `su -c` …) are read as the programs they run. A script FILE a
shell or interpreter is handed (`bash x.sh`, `python3 x.py`, `./x`) is read at decision time. A heredoc
body a reader only reads (a mail body) is data, not a command.

What the reader cannot name with confidence — a command word that is an unfolded expansion
(`$UNSET x`, `$(cat verb)`), a shell fed through a pipe, a script that exists but is unreadable, not
a regular file, or over 512 KB — is refused off the admin seat (`rm_gate`'s `UNREAD_REFUSED`). A script
that does not exist yet is allowed and logged at INFO (phase 4, P1): writing a helper and running it in
one command is everyday work, and there is nothing to read.

**An unknown wrapper is read for what it runs (phase 4, P3).** A command word that is neither a tabled
launcher nor a known plain program (`modules/shell_programs.PLAIN_PROGRAMS`: echo, grep, cat, mv, cp,
pytest, ruff …) has its operands scanned for a delete verb, git or gh, and is read from there as a
nested command. A plain program's operands are data, so `grep -rn rm .` and `echo git push` pass.

One refusal is all-or-nothing per command: every git invocation in it must be an allowed read, so
`git status && git tag` is refused whole. A bare `git` (no argument) prints usage and passes.

**One program, many spellings.** `git.exe`, `GIT`, `Git`, `git.cmd`, `/usr/bin/git.exe` and `gh.exe`
all run the program on Windows, so all are read as git or gh (`bash_writes.verb_name()`, the one
executable-extension list). A file merely NAMED for a program (`git.py`) is nobody's invocation.

**git and gh from inside a program (R5).** Off the admin seat, an interpreter whose program text
launches git or gh — `subprocess.run(['git', …])`, `os.system('gh …')`, node `execSync`, perl
`system`, backticks — is refused (`INTERPRETER_GIT_REFUSED`), inline, in a heredoc or in a script file.

**GitHub without gh (R6).** Off the admin seat, reading the gh credential is refused
(`CREDENTIAL_REFUSED`: `gh auth token`, `gh auth status --show-token`, `secret-tool`/`keyring`/`security`
lookups, python `keyring.get_password`, `hosts.yml`, `.git-credentials`), and so is an HTTP client
sending a non-GET method or a body to `api.github.com` (`GITHUB_HTTP_REFUSED`: curl, wget, httpie, or
an interpreter's request). A text gate cannot close this fully; `bash_writes.NOT_CAUGHT` says so, and
the kernel sandbox ([sandbox.md](sandbox.md)) is the real boundary.

**What it protects: the files that switch the gates.** `modules/protected_paths.py` names them, and
`git_gate` refuses any change to one of them on the edit tools (NotebookEdit included) AND on the Bash
lane, off the verified admin seat (`PROTECTED_REFUSED`). A change is a write, a delete, a move away, a
move over, a recursive copy over, or making a hard link to it; a directory deleted or moved whole
counts when a protected file is inside it. The protected lane decides each on its own, without
`rm_gate` (R2):

- any `.aipass/hooks.json` under AIPASS_HOME, the root one included;
- `~/.aipass/trusted_projects.json`;
- `.claude/settings*.json`, `.claude/hooks/`, `.git/hooks/`;
- this branch's promoted copies (`.live-*`): only `drone @hooks promote` writes them;
- since phase 4: everything under AIPASS_HOME's `.git/`, and every sealed `*_REGISTRY.json` under it.

**Default-deny on the Bash lane (phase 4, P2).** Listing write verbs was permanently incomplete: one
nobody listed passed every fence. Off the admin seat, a protected path named as an operand is refused
unless the program is on `shell_programs.READ_ONLY_PROGRAMS` (cat, head, tail, less, grep, rg, jq, wc,
stat, ls, diff, the checksum tools, `find` without an acting flag, and `drone`, the router) — and a
redirect into it is refused whatever the program. git and gh answer to this gate's own git lane.

Who may write them is the admin grant alone; there is no name list. Paths are matched with `\` read
as `/` and case-insensitively, and by FILE as well as by name (R1): an existing file with more than one
link is compared by (device, inode) against every protected file, so a hard link in a seat's own
directory is protected under its second name too. An external project's own `hooks.json` is not listed: trust decides
whether it runs.

**Why it is on:** agents reflexively reach for raw git, which causes state chaos in a multi-agent
system. The gate redirects to `drone @git`, which enforces access tiers. No refusal text tells an
agent how to switch a gate off.

---

## rm Gate

`security/rm_gate.py` (Bash only) refuses deletes and records each refused one. It fails closed like
`git_gate`.

- **Raw `rm`**, recursive or not, is refused for every seat, the admin seat included — `find -exec rm`
  and `xargs rm` are raw rm. The admin seat is taught `drone rm <path>`.
- **`drone rm`** is refused off the verified admin seat.
- **Every other delete** is refused off the admin seat with the same text: `rmdir`, `unlink`,
  `shred` and their kin wherever a program runs (shell_reader names it, however it is spelled),
  `find -delete`, and an interpreter's delete (`os.remove`, `shutil.rmtree`, `Path.unlink`; node
  `fs.rmSync`; perl or php `unlink`; ruby `FileUtils.rm_rf`; a shell-out to `rm`) whether its program
  is inline, a heredoc, or a script file read at decision time (R4).
- **A program the reader cannot read** is refused off the admin seat (`UNREAD_REFUSED`).
- What is still not seen — a delete through an alias or `getattr`, a script that changes after the
  check — is named in `bash_writes.NOT_CAUGHT`.
- `mv`, renaming and `mkdir` are never deletes. `git rm` answers to `git_gate`.

Every refusal off the admin seat ends with `_DONT_DELETE`, verbatim:

```
Don't delete. Move or rename instead — that is the safety feature: the owner sees the files and decides.
  rename it    name(disabled).ext       e.g. mv old.py 'old(disabled).py'
  archive it   move it into a .archive/ folder beside it
               (create the folder if it isn't there: mkdir -p .archive && mv old.py .archive/)
  or both.     Archived files can stay forever.

It must truly go? Mail @devpulse with the path and why:
  drone @ai_mail email @devpulse "Delete request" "<path>: <why>"

This refused attempt is recorded.
```

Every refused attempt is one INFO line per deleting clause
(`DELETE refused | lane=… | branch=… | cwd=… | cmd=…`). Service code that runs `drone rm` as a
subprocess never passes through a hook.

---

## Related

- [edit_gate.md](edit_gate.md) — the write fence that runs beside it on the same event
- [bash_writes.md](bash_writes.md) — the write lane, and NOT_CAUGHT, the published residual
- [engine.md](engine.md) — what happens when a gate itself breaks
