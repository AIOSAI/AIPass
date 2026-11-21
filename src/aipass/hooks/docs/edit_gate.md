[<- Back to the README](../README.md)

# The edit gate — who may write whose files

**Branch** hooks · **Code** `apps/handlers/security/edit_gate.py`, `apps/modules/write_ownership.py`, `apps/modules/admin_seat.py`

How a write made through a tool call is judged: who may write whose files, the project fence, and the one admin seat that crosses it.

---

## What the gate cannot see

**This gate sees only writes made through a tool call — Edit, Write, MultiEdit, NotebookEdit, and a Bash command whose write grammar it can read; a write a service makes from Python (a drone verb, @memory's rollover, any `python -m` door) never passes through it, so every service that writes files must carry its own fence.**

**Default-deny on the Bash lane.** Besides the write grammar it reads, every
operand of a program that does not only read (`modules/shell_programs.READ_ONLY_PROGRAMS`) is judged by
the same three rules: the project fence, whose file it is, and the `.trinity` memory rule. So a program
nobody listed as a writer cannot name another branch's file or a memory file off the admin seat. `cat`,
`grep`, `jq` and friends still read anywhere; `drone` is the router and passes; git and gh answer to
git_gate. `sed` is not read as a filter: its scripts can write. The exception is
`sed` whose every script is addresses (line numbers, `/regex/`, ranges of either) and `p`, `d`, `q`, `=`
with only reading flags (`sed -n 68,90p f`, `sed -n '/^## A/,/^## B/p' f`). `awk` reads when its only
flags are `-F` and `-v` and its program holds no `>`, `|`, `system`, `getline`, gawk's `@load` or
`@include`, or an indirect call (`@f(`); `-f`, `-i` or any of those makes every operand a write target
again. A provider CLI's prompt (`claude -p ../x/README.md`) is not a write target, but the value of each
of its flags is (`codex exec -o FILE` writes FILE itself, unseen by any hook): the word after a flag, the
part after `=`, or a short flag's attached text, even where no file exists yet. A switch from the CLI's
`--help` and a prompt flag are passed over, so the word after them is the prompt; the directory flags
(`-C`, `--cd`, `--add-dir`) are the launch rule's, below, which judges where the session runs.
Those shapes read anywhere, a memory file included. A `w` or `e` inside any other
script is not read: its target or command passes unseen. More reads: a shell whose
options before its script carry `-n` (`bash -n x.sh`, a syntax check; git_gate does not read the
script's commands either), `aipass init update ... --dry-run` (a preview is a read), and `read`,
whose operands are variable names. For `pytest` and `python -m pytest`, the value of `-c`,
`--config-file` or `-c=x` is a file pytest only reads; every other operand is judged, `--rootdir`
and `--confcutdir` included (the rootdir takes pytest's cache).

## A provider session starts only in the own branch

A session's directory makes it that branch's seat for every gate, so off the verified admin seat a
`claude`, `codex` or `opencode` launch from the Bash tool is refused when the directory it would run in
or reach lies outside the caller's own branch (the nearest passport directory above the session cwd).
`modules/provider_launch.py` reads, per invocation from `shell_reader`:

 - the invocation cwd after `cd`, `pushd`, subshells, `bash -c`, `script -c`, `nohup`, `setsid`, `env`, `sudo`;
 - each CLI's own directory flags, from its `--help`: codex `-C`/`--cd`, claude and codex `--add-dir`
   (claude's takes several), opencode's positional directory;
 - a carrier's directory: `env -C`/`--chdir`, `sudo -D`/`--chdir`, `systemd-run --working-directory`
   or `-p WorkingDirectory=`; with none of those and no `-d`/`--same-dir`, a unit starts in `/`
   (system) or the home dir (`--user`), per `systemd.exec`.

Refused as unknown: a cwd the reader cannot follow, a directory still holding `$` or a backtick, a
glob that matches nothing. In a command naming a provider, a detached launcher is read where it starts:
`tmux new-session`, `new-window` and `split-window` (and their aliases) start at `-c` or, without it,
at the tmux client's cwd (measured on tmux 3.6), and their shell command is re-read from there; `screen`
starts its program where it is invoked (`man screen`, chdir). Still refused: any other tmux command
(`send-keys`, `respawn-pane`, ...), tmux's own `-c`, a `;` chain, screen with `-c`, `-X`, `-x`, `-r`, `-R`
or `-ls`, and `at`, `batch`, `dtach` and `abduco`, whose help is not on this machine to read, and
`crontab`, whose lines cron runs from the home directory. Not read: a crontab file or `crontab -e`,
where the line is not in the command. A session
with no passport above its cwd has no branch and starts none. @devpulse's directory has no special
rule. The refusal names the caller and the next step (`drone @ai_mail dispatch`); `logs/edit_gate.log`
gets `provider launch refused: @<caller> -> <dir> | cmd=<command>`. The dispatch services (ai_mail's
wake, systemd units, the daemon) start sessions from Python, never through an agent's Bash tool, so this
rule never sees them. Not read: a provider started under another name (`npx @anthropic-ai/claude-code`,
`node cli.js`, a renamed binary).

## Who may write whose files

`modules/write_ownership.py` encodes the rule for both lanes:

| Seat | May write | Never |
|---|---|---|
| @devpulse (verified admin grant) | anywhere, system-wide | — |
| a project's manager row (`owner: true`), outside AIPass | their own project: its files in no branch row and its citizens' branches | another project |
| every other seat, @sentry/@spawn included | their own branch directory | another branch, a project-level file, another project |

A directory name grants nothing. A manager row grants its whole project: the files that lie in no branch row and its citizens' branches (the owner's ruling, 2026-10-26). In AIPass the manager row is the admin seat's, and it writes only as the verified grant.

Reading is never refused by this rule. A file outside every project (a temp file) is nobody's and stays open. A session at a project root has no branch identity: it is the project's own seat and writes the project, fenced at its boundary.

**Read from the registries, not from path shapes.** The caller's project is the nearest ancestor of the session cwd holding a `*_REGISTRY.json` (the marker @ai_mail's mail fence uses). The cwd is where the walk starts because it is the only identity evidence a PreToolUse hook has, the same evidence the admin rail's first leg reads. What the walk finds is then read from the registry: a branch is a row's `path`, a manager is a row's `owner` flag (spawn writes it to the registry entry, not to a passport an agent can edit). The `src/<package>/<branch>` shape is only the fallback where a project has no branches table. A registry that proves it catalogues something else (a non-empty table with no `branches` key, like `flow_json/PLAN_REGISTRY.json`) marks no project; an empty one still does.

**An unreadable registry fences loud and refuses no read.** A `*_REGISTRY.json` that cannot be read or parsed raises `RegistryUnreadable` (a `ProjectUnreadable`) from `write_ownership.project_of`: whose file a write lands in is unknown. The write fence refuses every Edit, Write and shell write in that project at ERROR, with a reason naming the registry and its owner, @spawn, instead of the broken-gate text. The memory tripwire's snapshot, which runs on every Bash call, watches the seat's own `.trinity` alone (WARNING), so this gate refuses no read and no `drone` command. A command that reads the registry itself (`drone systems`, the dispatch to @spawn) can still fail on it; the reason says to tell the user when it does. A directory on the walk that cannot be listed raises the parent `ProjectUnreadable` and is refused at WARNING with the broken-gate text.

**Project-level files** (the repo root's own files: `.aipass/`, `.claude/`, `README.md`) belong to no branch row; a branch seat is refused and pointed at the manager, and the manager's seat, a session at the project root or the admin seat writes them. @hooks' own `.aipass/hooks.json`, `.aipass/project_hooks.json` and `.claude/provider_manifest.json` go through @devpulse.

### The project boundary

A write that lands in another project is refused in every direction:

| Direction | Example | Verdict |
|---|---|---|
| Inside own project | `projects/baud` → `projects/baud/src/...` | allowed (then the ownership rule) |
| Downward (host → hosted) | `src/aipass/hooks` → `projects/baud/...` | **blocked** |
| Upward (hosted → host) | `projects/baud` → `src/aipass/drone/...` | **blocked** |
| Sideways (project → sibling) | `AIPass` → `Vera-Studio/...` | **blocked** |

Only the verified admin seat crosses. Where no project root is resolvable for the caller, the project fence does not fire: a fence that cannot locate a boundary must not invent one.

### The shell lane, and its residual

The shell lane applies the same rules to what `bash_writes` can see. Inside one project it convicts on write grammar only (redirection, `tee`, `sed -i`, `cp`/`mv` destinations, `dd of=`). An interpreter's held paths (`python -c`, a heredoc, `awk`) cannot be told from reads, and reading another branch is the daily loop, so **an interpreter that writes another branch of its own project is not refused**. The project fence still reads held paths: an interpreter naming another project's file is refused whether it reads or writes. The narrower `testwrite_gate` asks `bash_writes` whether the interpreter's own text holds a write verb and stands down when it does not; this gate deliberately does not, and the marker it ignores is named in [bash_writes.md](bash_writes.md).

**A source-read gate is open for the seconds an edit is half-applied.** The live gate imports this file per event, so while a symbol is mid-move across several edits a real event can hit a `NameError` and fail OPEN. Move code in one Edit per symbol.

**An edit to the engine's own imports is linted before it lands.** `engine_closure` lists every file the hook engine imports (`drone @hooks closure list`), and an Edit, Write or MultiEdit to one is run through ruff (`F821` and syntax) first; a hit is refused with its lines. When ruff cannot run or answer (not installed beside the hooks' interpreter, a timeout, an error exit), the edit is refused too, with the cause and the install command, and one fixed ERROR line reaches medic. An unreadable `hooks.json` or a closure file that does not parse narrows the closure, never widens what an edit may do, and logs its own fixed ERROR line; the path follows at INFO.

## The admin exemption — one seat reaches outwards

The cross-project fence stands for every agent, and **@devpulse is the sole exemption**: only the
admin seat reaches outwards.

The exemption is granted on a **verified** identity, never a claimed one. `_is_admin_seat()` consumes
@ai_mail's `is_verified_admin_caller()` — the same boolean their projects sweep gates on, which
delegates to @devpulse's `admin_grant` reference implementation and its 5-leg contract (caller,
registry-resolved cert, cert content, HMAC-SHA256 signature, registry admin flag). No second
implementation lives here, and `ADMIN_SEAT = "devpulse"` decides nothing — it appears in the log line
only. A session standing in a directory named `devpulse` with no valid grant on the machine is
refused.

**What a hook has to supply.** That rail reads identity from the env drone's router stamps
(`AIPASS_CALLER_BRANCH` / `AIPASS_CALLER_CWD`), and a PreToolUse hook is not drone-invoked: a hook process carries `AIPASS_BRANCH_NAME` and `AIPASS_SESSION_TYPE`, and neither caller
variable. Left alone the rail answers "unprovable" for every seat and the exemption never opens. So
the gate stamps `AIPASS_CALLER_CWD` from the platform's own record of the session directory — the
same species of evidence drone stamps, from the same kind of source — and lets the rail do the rest.
An existing stamp is never overwritten, and the stamp does not outlive the check.

**Residual:** the caller leg resolves through the session directory, so a
session whose cwd is devpulse's tree *and* a validly signed grant on this machine together satisfy
it. That is the grant's own stated threat model (`admin_grant.py`, "Security note": every agent here
shares one OS user; the signature buys tamper-evidence, not attack-proofing). It is also no new
reach — a session standing in devpulse's tree already writes that tree under the cross-branch fence,
which keys on the same cwd.

The exemption opens the cross-project fence and, inside a project, the cross-branch fence. Inbox writes, daemon confinement and the `.trinity` caps
are unchanged for every seat including the admin.

## Outside AIPass — what a project `aipass init` creates gets

**The Bash lane ships on.** The template `.aipass/project_hooks.json` matches `pre_edit_gate` on
`Bash|Edit|MultiEdit|Write|NotebookEdit`, so a new project runs the scripted-write fence and the memory
shell refusal. An existing project keeps its own `hooks.json`; a narrower matcher there runs neither until
it is widened and `aipass trust` re-run.

**The memory refusal names only cures that work there.** A project outside the fleet has no @memory, so
the shell refusal does not send the agent to a `drone @memory` verb or claim a cap is measured: it checks
whether @memory imports at refusal time and, if not, says "write it with the Edit or Write tool" and why.

---

## Related

- [bash_writes.md](bash_writes.md) — the same fence applied to a write made through the shell
- [trinity_memory_gate.md](trinity_memory_gate.md) — the memory caps the same handler measures
- [diagnostics.md](diagnostics.md) — the post-edit diagnostics block this gate also carries
