[<- Back to the README](../README.md)

# The scripted lane — writes made through Bash

**Branch** hooks · **Code** `apps/modules/bash_writes.py`, `apps/handlers/security/edit_gate.py`

---

The fences in [edit_gate.md](edit_gate.md) apply to writes made through the shell as well as to
Edit/Write/MultiEdit/NotebookEdit: a `sed -i` into a sibling project is refused exactly as an `Edit` of
the same file is. This page covers how a Bash command's writes are read, and what the reader misses.

`apps/modules/bash_writes.py` reads a Bash command and reports the paths it can be **seen** to write;
`edit_gate` then applies the identical direction rules and prints the identical refusal. Two reading
modes:

| Mode | Commands | What is reported |
|---|---|---|
| Directed verbs | `>`, `>>`, `tee`, `sed -i`, `cp`, `mv`, `ln`, `install`, `rsync`, `dd of=`, `touch`, `mkdir`, `truncate` | The target the verb's own grammar names — so `cat /other/x > ./mine` names `./mine`, and reading a foreign file stays legal |
| Interpreters | `python`, `python3`, `node`, `perl`, `ruby`, `php`, `sh`, `bash`, `zsh`, `awk` — inline script or heredoc | **Every** path in its own command and the heredoc it opened, because arbitrary code has no grammar naming its target. Not another command's arguments: a python step standing before a `cd` does not claim a later command's argument |

`cd` inside a chain moves the ground the next segment stands on, so `cd ../Other && sed -i s/a/b/ f.json`
is resolved against `../Other`; a `cd` inside `( … )` ends with the subshell.

Every line is a command: a newline separates, so line two of a multi-line Bash call has its own
writes and its own `cd`. A backslash-newline joins two lines into one command, and a `#` opens a
comment only where a word starts outside quotes.

**One program, many spellings.** `verb_name()` is the single reading of a
command-position token: basename, lowercased, with a Windows executable extension (`.exe`, `.com`,
`.bat`, `.cmd`, `.ps1`) removed. `CP.EXE` and `cp.exe` are cp on the host that runs them, and read as
cp. `git_gate` and `rm_gate` read through this same function, so the list of executable extensions
exists once. Only
executable extensions are stripped — `some/path/git.py` is a file nobody invokes as git, and every
gate leaves it alone on purpose. Reading every host the same way is deliberate: a lowercase read of
`TEE` on Linux names a program that is not installed, so the parser reports a target for a command
that would fail — broader than the truth, which is the safe direction for a fence.

**Write-verb evidence for interpreters.** An interpreter's paths are all reported,
as above, and the reason says whether the program's own text contains a verb that CREATES a file
— read in the grammar that text is written in, shell or source. When it does not, `NO_WRITE_VERB` is
appended to the reason. `testwrite_gate` reads that and stands down (a printed path is not a
creation); `edit_gate` ignores it and keeps the full breadth, because a path an interpreter holds
still cannot be told from one it writes. The evidence is only claimed about text that is IN the
command — inline source (`-c`, `-e`) or a heredoc. A script file, and `awk`'s bare-operand program,
keep the broad reading: answering "no write verb" about text nobody read would be inventing evidence.

**The gates' reader is next door.** `rm_gate` and `git_gate` do not read commands here:
`modules/shell_reader.py` is the one shell-word reader. It returns every program a
command runs the way the shell runs it (quotes, escapes, ANSI-C, braces, a command-word glob, `eval`,
`source`, script files read at decision time), and `mutated_paths()` — what a command writes, deletes,
moves away, moves over, overlays or hard-links — for the protected lane. This module keeps the write
lane `edit_gate` and `testwrite_gate` read, the delete shapes (`_SOURCE_DELETE_SHAPES`) the reader
scans program text with, and `NOT_CAUGHT`, the residual of both. See [git_gate.md](git_gate.md) for
the gates themselves.

**What it deliberately does NOT catch.** A perfect shell parser is not the bar and is not achievable;
the residual is published as data in `bash_writes.NOT_CAUGHT` and printed by `drone @hooks` module
introspection, so this list and the code cannot drift apart:

- paths built from shell or program variables (`$DIR/x`) — there is nothing to resolve
- paths reached through a symlink pointing into another project
- `find -exec` / `xargs` writes, which name the write verb but not the operand (their deletes and git/gh launches are read by the gates' reader)
- background or detached writes (`nohup`, `disown`, `at`, `cron`, `systemd-run`)
- metadata-only changes: `chmod`, `chown`, `touch -t` on an existing file
- `git`, `gh`, `drone`, `aipass` — they name no write verb this parser reads; their own fences apply
- writes made by a process the command merely starts (a server, a test runner)
- paths an interpreter receives from *another* command — through a pipe, a file or an argument list
  built elsewhere; only the paths in its own command and its own heredoc are read as held
- a path spelled for the *other* operating system's filesystem — `C:\Proj\x` read on Linux names no
  drive that exists here, so it resolves relative and reads as local
- a file name with no separator inside interpreter source — a bare `local.json` after a `cd` (a bare
  word cannot be told from `json.load`; `./local.json` is read)
- a path joined in program text — `Path('.trinity') / 'local.json'` is two strings, neither a path
- write verbs the parser has no grammar for: `sponge`, `ed` / `ex`, an interactive editor
- a write made through a shape the write-verb vocabulary has no pattern for — the path is still
  reported, only the evidence is missing, and the broad callers are unaffected
- which held path a write shape belongs to — the evidence is read per interpreter, not per path
- what a script FILE does — its text is on disk, never in the command (the write lane; the gates'
  reader reads it)

The gates' reader's residual (each row verbatim in `NOT_CAUGHT`):

- a script file that changes after the check — read at decision time, so time of check is not time
  of use
- a script a command creates and runs in one breath through a verb the reader cannot parse (`tar`,
  `unzip`, `curl -o`, a compiler) — not on disk to read at decision time
- a module run with an interpreter's `-m` flag, or a program found on PATH — installed code, not
  handed in
- a launcher with no table (`npx <pkg>`, a package manager's run-script, a shell function or alias)
- a subshell's, pipeline stage's or background job's cwd, approximated by the last literal `cd`;
  after a `cd` to an expansion it is unknown
- an alias or shell state from an earlier Bash call — each call is read alone
- GitHub writes without gh are a text gate's reach only: the kernel sandbox is the real boundary

A command the parser cannot read at all (an unbalanced quote, an internal error) **allows** and logs:
a parser that has learned nothing about a command must not convict on it.

**Both separator spellings are read.** `shlex` runs in POSIX mode, where a backslash is
an *escape*: lexed that way alone, `C:\Users\me\Vera-Studio\f.json` becomes the single token
`C:UsersmeVera-Studiof.json`, a relative filename resolved under the caller's **own** project and read
as a local write — the dangerous reading, not a degraded one.

The reader does not pick a dialect. A command containing a backslash is lexed **twice** — once with
shlex's escape rules (correct for POSIX `cp a\ b.txt dest`) and once with backslashes protected
(correct for a Windows path) — and the write targets are unioned. Reading `\` as a separator only
ever *adds* path components, so a local write can never become foreign by it, while the reverse is
exactly how a foreign write became local. Separators are then normalised before `pathlib` sees the
token, on every OS: `WindowsPath("C:/a/b")` is absolute and correct, so one spelling reaches `Path`
from both dialects and the parser's reading stops depending on which machine runs it.

What is *not* portable is the **root**, which is why the drive-letter entry is in the residual list
above rather than left to be discovered. The tests pin the Windows spelling in-process on any OS by
back-slashing a real local path (`str(p).replace("/", "\\")`) — a no-op on Windows, and on Linux the
backslash spelling, still resolving to the same real file under the same real
fence.

**Git Bash's own drive spelling is read too.** Git Bash
spells drive C as `/c`: its `pwd` prints `/c/Users/me`, and every command it runs accepts that. A
Windows path cannot hold that spelling: `WindowsPath("/c/Users/me")` has a root and no drive, so read
literally it joins the seat's drive and names `C:\c\Users\me`, a directory with no registry, where a
foreign write would be allowed. `/x` or `/x/...` (one letter) reads as drive `X:` whenever the path being resolved
against is a Windows path. On POSIX, `/c` stays an ordinary directory. Paths lifted out of
interpreter source get the same reading, although python itself would not translate them: broader
than the write, which is the safe direction for a fence. The pins use a platform oracle: `bash_writes`
is made to build every path in one flavour (`PureWindowsPath` or `PurePosixPath`), so Linux reads a
command the way Windows does, and nothing about the host is asserted.

A path put *into* a command string in these suites is spelled with `as_posix()`, the form bash takes
on every OS. An unquoted `C:\Users\...` cd target loses its backslashes to bash, and the reader,
reading as bash does, would `cd` into a directory named `C:Users...`.

> **CONFIG WIRE — the lane is live.** `pre_edit_gate` carries
> `matcher: "Bash|Edit|MultiEdit|Write|NotebookEdit"` in `.aipass/hooks.json` and in the built-in gate
> set (`handlers/config/gates.py`); without `Bash` in the matcher, Bash events never reach the handler.
> The AIPass root config is read with no trust check, so editing it never takes the
> hooks dark; it is a protected file only the admin seat writes. Verify with `drone @hooks status`.

---

## Related

- [edit_gate.md](edit_gate.md) — the direction rules this reader feeds
- [trinity_memory_gate.md](trinity_memory_gate.md) — the memory rule and the tripwire that ride this lane
- [testwrite_gate.md](testwrite_gate.md) — the other gate reading the same parser
