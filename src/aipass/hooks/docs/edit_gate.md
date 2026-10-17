[<- Back to the README](../README.md)

# The edit gate — who may write whose files

**Branch** hooks · **Code** `apps/handlers/security/edit_gate.py`, `apps/modules/write_ownership.py`, `apps/modules/admin_seat.py`

---

## What the gate cannot see

**This gate sees only writes made through a tool call — Edit, Write, MultiEdit, NotebookEdit, and a Bash command whose write grammar it can read; a write a service makes from Python (a drone verb, @memory's rollover, any `python -m` door) never passes through it, so every service that writes files must carry its own fence.**

**Default-deny on the Bash lane (DPLAN-0356 phase 4, P2).** Besides the write grammar it reads, every
operand of a program that does not only read (`modules/shell_programs.READ_ONLY_PROGRAMS`) is judged by
the same three rules: the project fence, whose file it is, and the `.trinity` memory rule. So a program
nobody listed as a writer cannot name another branch's file or a memory file off the admin seat. `cat`,
`grep`, `jq` and friends still read anywhere; `drone` is the router and passes; git and gh answer to
git_gate. `awk` and `sed` are not read as filters: their scripts can write. The one exception is
`sed` whose every script is addresses and `p`, `d`, `q`, `=` with only reading flags (`sed -n 68,90p f`).
That shape reads anywhere, a memory file included (hooks todo 80). A `w` or `e` inside any other
script is not read: its target or command passes unseen. Two more reads (2026-10-16): a shell whose
options before its script carry `-n` (`bash -n x.sh`, a syntax check; git_gate does not read the
script's commands either), and `aipass init update ... --dry-run` (the owner: a preview is a read).

## Who may write whose files — the owner's ruling, 2026-09-18

The owner ruled at 22:17, after @memory's rollover was found writing Vera Studio branches' `.trinity` files (devpulse 1d041cfc). `modules/write_ownership.py` encodes it for both lanes:

| Seat | May write | Never |
|---|---|---|
| @devpulse (verified admin grant) | anywhere, system-wide | — |
| a project's manager row (`owner: true`), outside AIPass | their own branch and their project's files in no branch row | another branch, another project |
| every other seat, @seedgo/@spawn included | their own branch directory | another branch, a project-level file, another project |

Since DPLAN-0356 (`write_ownership` 2.0.0) a directory name grants nothing. A manager row granted nothing either until 2026-10-16 18:45: the owner's go superseded item 5 for files in no branch row, after @aipass_site, @vera and @baud were refused their own project files and told to mail themselves (`write_ownership` 2.4.0). Another branch's row stays its branch's. In AIPass the manager row is the admin seat's, and it writes only as the verified grant.

Reading is never refused by this rule. A file outside every project (a temp file) is nobody's and stays open. A session at a project root has no branch identity: it is the project's own seat and writes the project, fenced at its boundary.

**Read from the registries, not from path shapes.** The caller's project is the nearest ancestor of the session cwd holding a `*_REGISTRY.json` (the marker @ai_mail's mail fence uses, GH #733). The cwd is where the walk starts because it is the only identity evidence a PreToolUse hook has, the same evidence the admin rail's leg 1 reads. What the walk finds is then read from the registry: a branch is a row's `path`, a manager is a row's `owner` flag (spawn writes it to the registry entry, not to a passport an agent can edit). The `src/<package>/<branch>` shape is only the fallback where a project has no branches table. A registry that proves it catalogues something else (a non-empty table with no `branches` key, like `flow_json/PLAN_REGISTRY.json`) marks no project; an unreadable or empty one still does.

**Project-level files** (the repo root's own files: `.aipass/`, `.claude/`, `README.md`) belong to no branch row; a branch seat is refused and pointed at the manager, and the manager's seat, a session at the project root or the admin seat writes them. @hooks' own `.aipass/hooks.json`, `.aipass/project_hooks.json` and `.claude/provider_manifest.json` go through @devpulse since this ruling.

### The project boundary

A write that lands in another project is refused in every direction:

| Direction | Example | Verdict |
|---|---|---|
| Inside own project | `projects/baud` → `projects/baud/src/...` | allowed (then the ownership rule) |
| Downward (host → hosted) | `src/aipass/hooks` → `projects/baud/...` | **blocked** since 2026-09-18 |
| Upward (hosted → host) | `projects/baud` → `src/aipass/drone/...` | **blocked** |
| Sideways (project → sibling) | `AIPass` → `Vera-Studio/...` | **blocked** |

Downward was trusted until the ruling, so every AIPass citizen could edit `projects/baud`. Only the verified admin seat crosses now. Where no project root is resolvable for the caller, the project fence does not fire: a fence that cannot locate a boundary must not invent one.

### The shell lane, and its residual

The shell lane applies the same rules to what `bash_writes` can see. Inside one project it convicts on write grammar only (redirection, `tee`, `sed -i`, `cp`/`mv` destinations, `dd of=`). An interpreter's held paths (`python -c`, a heredoc, `awk`) cannot be told from reads, and reading another branch is the daily loop, so **an interpreter that writes another branch of its own project is not refused**. The project fence still reads held paths: an interpreter naming another project's file is refused whether it reads or writes. The narrower `testwrite_gate` now asks `bash_writes` whether the interpreter's own text holds a write verb and stands down when it does not; this gate deliberately does not, and the marker it ignores is named in [bash_writes.md](bash_writes.md).

**A source-read gate is open for the seconds an edit is half-applied.** The live gate imports this file per event, so while a symbol was being moved on 2026-09-18 five real events hit a `NameError` and failed OPEN (@devpulse's trigger digest: tripwire unwatched x4, one bash scan allowing). Move code in one Edit per symbol.

## The admin exemption — one seat reaches outwards

The owner's ruling, 2026-08-30 (compassed as @devpulse entry 322): the cross-project fence stays for
every agent, and **@devpulse is the sole exemption** — *"It is only you who can reach outwards.
Nobody else."*

The exemption is granted on a **verified** identity, never a claimed one. `_is_admin_seat()` consumes
@ai_mail's `is_verified_admin_caller()` — the same boolean their projects sweep gates on, which
delegates to @devpulse's `admin_grant` reference implementation and its 5-leg contract (caller,
registry-resolved cert, cert content, HMAC-SHA256 signature, registry admin flag). No second
implementation lives here, and `ADMIN_SEAT = "devpulse"` decides nothing — it appears in the log line
only. A session standing in a directory named `devpulse` with no valid grant on the machine is
refused.

**What a hook has to supply.** That rail reads identity from the env drone's router stamps
(`AIPASS_CALLER_BRANCH` / `AIPASS_CALLER_CWD`), and a PreToolUse hook is not drone-invoked — measured
2026-08-30: a hook process carries `AIPASS_BRANCH_NAME` and `AIPASS_SESSION_TYPE`, and neither caller
variable. Left alone the rail answers "unprovable" for every seat and the exemption never opens. So
the gate stamps `AIPASS_CALLER_CWD` from the platform's own record of the session directory — the
same species of evidence drone stamps, from the same kind of source — and lets the rail do the rest.
An existing stamp is never overwritten, and the stamp does not outlive the check.

**Residual, stated rather than discovered:** leg 1 resolves through the session directory, so a
session whose cwd is devpulse's tree *and* a validly signed grant on this machine together satisfy
it. That is the grant's own stated threat model (`admin_grant.py`, "Security note": every agent here
shares one OS user; the signature buys tamper-evidence, not attack-proofing). It is also no new
reach — a session standing in devpulse's tree already writes that tree under the cross-branch fence,
which keys on the same cwd.

The exemption opens the cross-project fence and, inside a project, the cross-branch fence. Inbox writes, daemon confinement and the `.trinity` caps
are unchanged for every seat including the admin.

## Outside AIPass — what a project `aipass init` creates gets

**The Bash lane ships on (2026-09-16).** The template `.aipass/project_hooks.json` matched
`pre_edit_gate` on `Edit|MultiEdit|Write|NotebookEdit` only, so a new project never ran the scripted-write
fence or the memory shell refusal. It now matches `Bash|…` like this repo does. Existing projects keep
their own `hooks.json` until they widen the matcher and re-run `aipass trust`.

**The memory refusal names only cures that work there.** A project outside the fleet has no @memory, so
the shell refusal no longer sends the agent to a `drone @memory` verb or claims a cap is measured: it checks
whether @memory imports at refusal time and, if not, says "write it with the Edit or Write tool" and why.

---

## Related

- [bash_writes.md](bash_writes.md) — the same fence applied to a write made through the shell
- [trinity_memory_gate.md](trinity_memory_gate.md) — the memory caps the same handler measures
- [diagnostics.md](diagnostics.md) — the post-edit diagnostics block this gate also carries
