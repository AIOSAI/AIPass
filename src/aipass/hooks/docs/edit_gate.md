# The edit gate — the project boundary

**Branch** hooks · **Code** `apps/handlers/security/edit_gate.py`, `apps/modules/admin_seat.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

---

## Edit Gate — the project boundary

The `edit_gate` handler (`security/edit_gate.py`) fences writes at two levels. Inside one project it enforces the branch boundary (`hooks` cannot write to `drone`; `devpulse`, `seedgo`, `spawn` are trusted cross-writers). Across projects it enforces the project boundary.

A **project root** is the nearest ancestor directory holding a `*_REGISTRY.json` — the same marker `@ai_mail` uses to refuse cross-project mail. The two fences share a definition on purpose: an agent that is refused a send must not be allowed the equivalent write (GH #733).

The project fence is directional, unlike the mail fence:

| Direction | Example | Verdict |
|---|---|---|
| Inside own project | `projects/baud` → `projects/baud/src/...` | allowed |
| Downward (host → hosted) | `src/aipass/devpulse` → `projects/baud/...` | allowed |
| Upward (hosted → host) | `projects/baud` → `src/aipass/drone/...` | **blocked** |
| Sideways (project → sibling) | `projects/baud` → `projects/earmark/...` | **blocked** |

Trust runs downward. Downward writes also have to stay open because the host tree carries artifact registries of its own — `flow/flow_json/PLAN_REGISTRY.json`, `.backup/snapshots/` — which a strict rule would read as foreign projects to the very branches that own them.

Where no project root is resolvable on either side, the gate allows the write: a fence that cannot locate a boundary must not invent one.

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

The exemption is narrow: it opens the **cross-project** fence only. Inbox writes, the cross-branch
fence, daemon confinement and the `.trinity` caps are unchanged for every seat including the admin.

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
