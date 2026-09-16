# The scripted lane — writes made through Bash

**Branch** hooks · **Code** `apps/modules/bash_writes.py`, `apps/handlers/security/edit_gate.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

---

Until 2026-08-30 every fence in [edit_gate.md](edit_gate.md) was invisible to a write made through the shell, because the gate
matched only Edit/Write/MultiEdit/NotebookEdit. @devpulse measured it live: their `Edit` into a
sibling project was correctly refused and `sed -i` on the same file went straight through — for all
18 citizens, not just the admin seat.

`apps/modules/bash_writes.py` reads a Bash command and reports the paths it can be **seen** to write;
`edit_gate` then applies the identical direction rules and prints the identical refusal. Two reading
modes:

| Mode | Commands | What is reported |
|---|---|---|
| Directed verbs | `>`, `>>`, `tee`, `sed -i`, `cp`, `mv`, `ln`, `install`, `rsync`, `dd of=`, `touch`, `mkdir`, `truncate` | The target the verb's own grammar names — so `cat /other/x > ./mine` names `./mine`, and reading a foreign file stays legal |
| Interpreters | `python`, `python3`, `node`, `perl`, `ruby`, `php`, `sh`, `bash`, `zsh`, `awk` — inline script or heredoc | **Every** path in its own command and the heredoc it opened, because arbitrary code has no grammar naming its target. Not another command's arguments: until 2026-09-10 it read the whole command line, so a python step standing before a `cd` claimed the later pytest argument and resolved it from the wrong directory (devpulse 213c64fd) |

`cd` inside a chain moves the ground the next segment stands on, so `cd ../Other && sed -i s/a/b/ f.json`
is resolved against `../Other`; a `cd` inside `( … )` ends with the subshell.

Every line is a command. Until 2026-09-10 a newline never separated (the lexer counted it as blank
space), so line two of a multi-line Bash call was glued onto line one: its write was invisible to both
gates and its `cd` never moved. A backslash-newline still joins two lines into one command, and a `#`
opens a comment only where a word starts outside quotes (the lexer's own rule cut the line at any `#`).

**What it deliberately does NOT catch.** A perfect shell parser is not the bar and is not achievable;
the residual is published as data in `bash_writes.NOT_CAUGHT` and printed by `drone @hooks` module
introspection, so this list and the code cannot drift apart:

- paths built from shell or program variables (`$DIR/x`) — there is nothing to resolve
- paths reached through a symlink pointing into another project
- `find -exec` / `xargs`, which name the write verb but not the operand
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

A command the parser cannot read at all (an unbalanced quote, an internal error) **allows** and logs:
a parser that has learned nothing about a command must not convict on it.

**Both separator spellings are read (2026-08-31).** `shlex` runs in POSIX mode, where a backslash is
an *escape* — so it ate every separator of a Windows path and
`C:\Users\me\Vera-Studio\f.json` arrived as the single token `C:UsersmeVera-Studiof.json`. That is
not a degraded reading, it is the dangerous one: a drive-absolute foreign path became one relative
filename, resolved under the caller's **own** project, and read as a local write. Every catch
category in the table returned exit 0 on Windows, and the class had never been green there since the
day it shipped. Found by @devpulse in `windows-test.yml` (which runs the whole tree, unlike main CI);
reproduced on Linux at the parser level, because the bug never needed a Windows runner — only a
backslash.

The fix does not pick a dialect. A command containing a backslash is lexed **twice** — once with
shlex's escape rules (correct for POSIX `cp a\ b.txt dest`) and once with backslashes protected
(correct for a Windows path) — and the write targets are unioned. Reading `\` as a separator only
ever *adds* path components, so a local write can never become foreign by it, while the reverse is
exactly how a foreign write became local. Separators are then normalised before `pathlib` sees the
token, on every OS: `WindowsPath("C:/a/b")` is absolute and correct, so one spelling reaches `Path`
from both dialects and the parser's reading stops depending on which machine runs it.

What is *not* portable is the **root**, which is why the drive-letter entry is in the residual list
above rather than left to be discovered. The tests pin the Windows spelling in-process on any OS by
back-slashing a real local path (`str(p).replace("/", "\\")`) — a no-op on Windows, and on Linux the
exact spelling that killed the parser, still resolving to the same real file under the same real
fence.

**Git Bash's own drive spelling is read too (2026-09-10, FPLAN-0537, devpulse 401ee814).** Git Bash
spells drive C as `/c`: its `pwd` prints `/c/Users/me`, and every command it runs accepts that. A
Windows path cannot hold that spelling: `WindowsPath("/c/Users/me")` has a root and no drive, so it
joined the seat's drive and named `C:\c\Users\me`. That directory has no registry, so `edit_gate`
**allowed** a foreign write spelled that way, and `testwrite_gate` called an edit of an existing test
a creation. `/x` or `/x/...` (one letter) now reads as drive `X:` whenever the path being resolved
against is a Windows path. On POSIX, `/c` stays an ordinary directory. Paths lifted out of
interpreter source get the same reading, although python itself would not translate them: broader
than the write, which is the safe direction for a fence. The pins use a platform oracle: `bash_writes`
is made to build every path in one flavour (`PureWindowsPath` or `PurePosixPath`), so Linux reads a
command the way Windows does, and nothing about the host is asserted.

A path put *into* a command string in these suites is spelled with `as_posix()`, the form bash takes
on every OS. `str()` once handed windows-setup an unquoted `C:\Users\...` cd target. Bash eats those
backslashes, and the reader, reading as bash does, `cd`'d into a directory named `C:Users...`, where
an existing test looked new (PR #762).

> **CONFIG WIRE — landed 2026-08-30, the lane is live.** `pre_edit_gate` now carries
> `matcher: "Bash|Edit|MultiEdit|Write|NotebookEdit"` in `.aipass/hooks.json` (the matcher `git_gate`
> and `registry_gate` already had). Before that widening, Bash events never reached the handler at
> all and the scripted lane was dark no matter what the code did. Because any byte change to
> `hooks.json` invalidates the trust hash in `~/.aipass/trusted_projects.json`, the edit was followed
> immediately by `aipass trust <path-to-this-repo>` — an un-re-enrolled config edit takes
> *every* hook dark. Verify with `drone @hooks hookstatus`; re-run `aipass trust` after any further
> edit to that file.

---

## Related

- [edit_gate.md](edit_gate.md) — the direction rules this reader feeds
- [trinity_memory_gate.md](trinity_memory_gate.md) — the memory rule and the tripwire that ride this lane
- [testwrite_gate.md](testwrite_gate.md) — the other gate reading the same parser
