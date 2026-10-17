[<- Back to the README](../README.md)

# The checklist lane and the hook that runs it

**Branch** seedgo · **Code** `apps/modules/checklist.py`, `apps/handlers/cli/help_flags.py`
**Verb** `drone @seedgo checklist <file|dir>`

---

## The checklist

`checklist` runs every eligible standard against ONE file (or every `*.py` under one
directory) and prints a per-standard verdict. It is the lane a human uses while writing, and
it is the lane the PostToolUse hook uses automatically.

Branch-level standards with no per-file check (`unused_conftest_fixture`, `dead_code`, ...) cannot
run here; after the verdicts, behind a blank line, one closing line names the ones that apply to
the file (`Not judged here (branch-level, run by ...): ...`), so a clean
"All N standards passed" is never read as the audit's verdict. It changes no count.

It is not the audit. The audit walks the branch's corpus (`apps/` plus `tests/`, see
[audit_engine.md](audit_engine.md)) and reports per branch; the checklist takes whatever one
path it is handed. A bypass rule can
be live in one lane and inert in the other, and a standard can pass one while failing the
other — that difference is real and is not a bug to be smoothed over.

`.seedgoignore` applies here too; ruff and pyright do not, so auto-fix still sees real errors
in an ignored file. See [audit_engine.md](audit_engine.md).

---

## Hook architecture — whose is it

The **hooks branch** (`src/aipass/hooks/`) owns all hook infrastructure: engine, bridge and
the native handlers. Seedgo audits hooks against standards; it does not own the hook system
and does not mirror that branch's roster: a copy of someone else's registry rots quietly; the
directory does not. Read `src/aipass/hooks/apps/handlers/`, or ask @hooks.

The event handlers sit in category directories under that root (`prompt/`, `lifecycle/`,
`security/`, `notification/`); `bridges/`, `config/`, `json/` and `cli/` beside them are
infrastructure rather than event handlers.

---

## How an event reaches a handler

Provider settings route every event through the bridge
(`src/aipass/hooks/apps/handlers/bridges/claude.py`), which dispatches to the native Python
handlers. Event registrations live in `.claude/provider_manifest.json` under
`cli.claude.hooks` and are keyed by **hook alias, not filename**:
`UserPromptSubmit:branch_prompt` fires `prompt/branch_loader.py`, `identity_injector` fires
`prompt/identity.py`. The two lists do not line up by name, which is the second reason not to
restate them here.

---

## The one that concerns this branch

`lifecycle/auto_fix.py` (PostToolUse) runs `drone @seedgo checklist <file>` against every
edited file. That gate is what `checklist` feeds, and it is why the checklist lane's
performance and its refusal vocabulary matter more than the audit's.

hooks also owns the branch-prompt cap that `startup_budget` reads — see
[context_standards.md](context_standards.md).

---

## Related

- [audit_engine.md](audit_engine.md) — the other lane
- [aipass_standards.md](aipass_standards.md) — what both lanes run
