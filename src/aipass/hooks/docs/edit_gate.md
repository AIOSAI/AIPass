# The edit gate — who may write whose files

**Branch** hooks · **Code** `apps/handlers/security/edit_gate.py`, `apps/modules/write_ownership.py`, `apps/modules/admin_seat.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

---

## What the gate cannot see

**This gate sees only writes made through a tool call — Edit, Write, MultiEdit, NotebookEdit, and a Bash command whose write grammar it can read; a write a service makes from Python (a drone verb, @memory's rollover, any `python -m` door) never passes through it, so every service that writes files must carry its own fence.**

## Who may write whose files — the owner's ruling, 2026-09-18

The owner ruled at 22:17, after @memory's rollover was found writing Vera Studio branches' `.trinity` files (devpulse 1d041cfc). `modules/write_ownership.py` encodes it for both lanes:

| Seat | May write | Never |
|---|---|---|
| @devpulse (verified admin grant) | anywhere, system-wide | — |
| a project's manager (registry row `owner: true`: @devpulse in AIPass, @vera in Vera Studio) | anything inside her own project | any other project |
| @seedgo, @spawn | anything inside AIPass (the project whose registry is `AIPASS_REGISTRY.json`) | beyond AIPass, including projects nested in it |
| everyone else | their own branch directory | another branch, a project-level file, another project |

Reading is never refused by this rule. A file outside every project (a temp file) is nobody's and stays open. A session at a project root has no branch identity: it is the project's own seat and writes the project, fenced at its boundary.

**Read from the registries, not from path shapes.** The caller's project is the nearest ancestor of the session cwd holding a `*_REGISTRY.json` (the marker @ai_mail's mail fence uses, GH #733). The cwd is where the walk starts because it is the only identity evidence a PreToolUse hook has, the same evidence the admin rail's leg 1 reads. What the walk finds is then read from the registry: a branch is a row's `path`, a manager is a row's `owner` flag (spawn writes it to the registry entry, not to a passport an agent can edit). The `src/<package>/<branch>` shape is only the fallback where a project has no branches table. A registry that proves it catalogues something else (a non-empty table with no `branches` key, like `flow_json/PLAN_REGISTRY.json`) marks no project; an unreadable or empty one still does.

**Project-level files** (the repo root's own files: `.aipass/`, `.claude/`, `README.md`) belong to no branch row, so they are the manager's. @hooks' own `.aipass/hooks.json`, `.aipass/project_hooks.json` and `.claude/provider_manifest.json` go through @devpulse since this ruling.

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

The shell lane applies the same rules to what `bash_writes` can see. Inside one project it convicts on write grammar only (redirection, `tee`, `sed -i`, `cp`/`mv` destinations, `dd of=`). An interpreter's held paths (`python -c`, a heredoc, `awk`) cannot be told from reads, and reading another branch is the daily loop, so **an interpreter that writes another branch of its own project is not refused**. The project fence still reads held paths: an interpreter naming another project's file is refused whether it reads or writes.

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

The exemption is narrow: it opens the **cross-project** fence only. Inside AIPass @devpulse writes every
branch as the registry's manager, not as admin. Inbox writes, daemon confinement and the `.trinity` caps
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
