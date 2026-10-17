[<- Back to the README](../README.md)

# The git gate, the rm gate, and the settings backup

**Branch** hooks · **Code** `apps/handlers/security/git_gate.py`, `apps/handlers/security/rm_gate.py`, `apps/handlers/security/settings_backup.py`, `apps/modules/protected_paths.py`, `apps/modules/shell_reader.py`

How raw git and gh are refused and redirected to drone, how deletes are refused, and how a write to
`~/.claude/settings*.json` is backed up first.

---

## Git Gate

The `git_gate` handler (`security/git_gate.py`) enforces git access via drone to prevent state conflicts between agents. It ships in every project `aipass init` creates, and inside AIPass it is part of the gate set the loader forces on (see [project_config.md](project_config.md)): no project config switches it off. It fails closed — a crash refuses the call it was checking, and the engine refuses on import error and timeout (see [engine.md](engine.md)).

**What it blocks:** raw `git` and raw `gh`, read or write, for EVERY seat, the verified admin seat
included; git or gh launched from inside a program, the gh credential, and GitHub API writes, for every
seat too; and writes to the protected files off the admin seat (below).

**If drone cannot do it, it cannot be done.** No seat runs git
or gh raw: `modules/admin_seat`'s grant opens none of these lanes. A git refusal (`RAW_GIT_REFUSED`)
names the caller from its passport (or says it could not be named) and the drone twin of the verb
(`_GIT_TWINS`), as published in `drone @git --help`: `git status` is `drone @git status`, `git log`
is `drone @git log [count] [path ...]`, and likewise diff, show, blame, remote, branch, tag and the
owner verbs. Drone's read twins:

| Raw git | Its drone twin |
|---|---|
| `git ls-files`, `git check-ignore` | `drone @git tracked <path ...>` |
| `git diff` with paths or `--stat` | `drone @git diff [--staged] [--stat] <path ...>` |
| `git rev-list`, `git merge-base` | `drone @git status --all` (the ahead/behind line) |
| `git log` with a range `a..b` | `drone @git log [n] <a>..<b>` |
| `git archive` | `drone @git export <ref> <dir>` |

The diff and log rows depend on the call's words (`_SHAPED_TWINS`): a plain `git diff` or `git log`
is still named its plain twin. A verb with no twin (`for-each-ref`, `rev-parse`, `cat-file`,
`describe` …) cannot be done; the refusal says to mail @devpulse to ask @drone for one. A bare `git` (no argument) prints usage and passes. Agent Bash only: service code that
runs git as a subprocess (drone itself) never passes through a hook.

**gh.** Every raw `gh` call is refused for every seat, `gh api` GET included (`GH_REDIRECT`). Drone
owns gh: the refusal maps `gh issue`, `gh run`, `gh workflow` and `gh pr create` to their
`drone @git` twins.

**What it reads is the program the shell will run.** Both gates read the
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
that does not exist yet is allowed and logged at INFO: writing a helper and running it in
one command is everyday work, and there is nothing to read.

**An unknown wrapper is read for what it runs.** A command word that is neither a tabled
launcher nor a known plain program (`modules/shell_programs.PLAIN_PROGRAMS`: echo, grep, cat, mv, cp,
pytest, ruff …) has its operands scanned for a delete verb, git or gh, and is read from there as a
nested command. A plain program's operands are data, so `grep -rn rm .` and `echo git push` pass.

One refusal per command: the twin named is the first git invocation's.

**One program, many spellings.** `git.exe`, `GIT`, `Git`, `git.cmd`, `/usr/bin/git.exe` and `gh.exe`
all run the program on Windows, so all are read as git or gh (`bash_writes.verb_name()`, the one
executable-extension list). A file merely NAMED for a program (`git.py`) is nobody's invocation.

**git and gh from inside a program.** For every seat, an interpreter whose program text
launches git or gh — `subprocess.run(['git', …])`, `os.system('gh …')`, node `execSync`, perl
`system`, backticks — is refused (`INTERPRETER_GIT_REFUSED`), inline, in a heredoc or in a script file.

**GitHub without gh.** For every seat, reading the gh credential is refused
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
`rm_gate`:

- any `.aipass/hooks.json` under AIPASS_HOME, the root one included;
- `~/.aipass/trusted_projects.json`;
- `.claude/settings*.json`, `.claude/hooks/`, `.git/hooks/`;
- this branch's promoted copies (`.live-*`): only `drone @hooks promote` writes them;
- everything under AIPASS_HOME's `.git/`, and every sealed `*_REGISTRY.json` under it.

**Default-deny on the Bash lane.** A list of write verbs is never complete: a verb
nobody listed would pass every fence. Off the admin seat, a protected path named as an operand is refused
unless the program is on `shell_programs.READ_ONLY_PROGRAMS` (cat, head, tail, less, grep, rg, jq, wc,
stat, ls, diff, the checksum tools, `find` without an acting flag, and `drone`, the router) — and a
redirect into it is refused whatever the program. git and gh answer to this gate's own git lane.

Who may write them is the admin grant alone; there is no name list. Paths are matched with `\` read
as `/` and case-insensitively, and by FILE as well as by name: an existing file with more than one
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
  is inline, a heredoc, or a script file read at decision time.
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

## Settings Backup

`security/settings_backup.py` runs on Bash, Edit,
MultiEdit, Write and NotebookEdit, last in the PreToolUse gate set. When a call writes
`~/.claude/settings*.json` (`~` expanded, relative paths joined to the seat's cwd, symlinks followed
from either end; a Bash target as `git_gate`'s protected lane reads it), it copies the file into
`~/.claude/.backup/settings/` (0700, the copy 0600) as `<file>.<YYYY-MM-DDTHH-MM-SS>.<door>`, `-2`,
`-3` on a same-second collision, and appends one JSON line to `receipts.jsonl` there: time, door
(`edit-tool`, `write-tool`, `multiedit-tool`, `notebookedit-tool`, `bash`), file, actor (the seat's
branch, else its cwd), pid, backup, `before_sha256`, `after_sha256: null`, summary. Then it allows.
A copy or append that fails refuses the call, naming the path and the error. Nothing prunes the folder.

@aipass's Python doors (`doctor --fix`, install, setup.sh) write the same folder in the same shape;
the two share the contract, never an import. Off the admin seat `git_gate` refuses these writes first,
so a backup is only taken for a write every other gate allowed. A project's own
`.claude/settings.json` is out of scope: git keeps its history. Claude Code's own writes (`/model`,
`/config`) pass no hook; the next backup carries what they left.

---

## Related

- [edit_gate.md](edit_gate.md) — the write fence that runs beside it on the same event
- [bash_writes.md](bash_writes.md) — the write lane, and NOT_CAUGHT, the published residual
- [engine.md](engine.md) — what happens when a gate itself breaks
