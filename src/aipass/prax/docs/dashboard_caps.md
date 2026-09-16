# Dashboard caps — the contract for every section writer

`DASHBOARD.local.json` is read by its branch on every greeting, so its size is a
cost paid per session, per branch, forever. Two caps bound it. Both live once, in
`prax/apps/handlers/dashboard/operations.py`, and are re-exported for everyone
outside prax from `aipass.prax.apps.modules.dashboard` (handlers are internal).

Units are **chars** — `len()` over the rendered text, the number `wc -m` reports.
Never bytes, never tokens.

Owner: @prax (DPLAN-0347, boardroom thread 16, 2026-09-15).

## The import

```python
from aipass.prax.apps.modules.dashboard import SUBJECT_CAP, DASHBOARD_CHAR_BUDGET, cap_subject
```

| Name | Value | Meaning |
|---|---|---|
| `SUBJECT_CAP` | `120` | Longest plan or commit subject a dashboard section may carry |
| `DASHBOARD_CHAR_BUDGET` | `6000` | Rendered dashboard size that earns a warning |
| `TRUNCATION_MARKER` | `"..."` | What a cut subject ends with, counted inside the cap |
| `cap_subject(text)` | — | The cut itself |

Import the number; never retype it. A second copy is what drifts.

## Cap 1 — the subject cut

`cap_subject()` is exactly:

1. `text.strip()`; empty in, empty out.
2. Take the **first line** only (`splitlines()[0].strip()`) — a body under a
   subject never reaches a glance.
3. `len(first) <= SUBJECT_CAP` → return it unchanged. The boundary belongs to
   the subject: a subject of exactly 120 chars is published whole.
4. Otherwise `first[: SUBJECT_CAP - len(TRUNCATION_MARKER)].rstrip() + TRUNCATION_MARKER`.
   The marker is inside the cap, so the result is **never longer than 120**, and
   `rstrip()` means it can be shorter when the cut lands on a space.

**Truncate, never refuse.** Refusing a subject drops the plan from the glance,
and the full text is one `drone @flow list` or `git log -1` away. Refusing an
essay at authorship is @flow's `create`, a different fix.

Applies to every subject a dashboard section publishes:

- `sections.flow.open_recent[].subject`
- `sections.flow.recently_closed[].subject`
- `sections.git.last_commit_msg` (devpulse plugin)

`sections.flow` has **two writers** — prax's refresh
(`handlers/dashboard/refresh.py`) and @flow's push
(`flow/apps/handlers/dashboard/push_branch_dashboard.py`) — and both assign the
section wholesale. A cap on one side alone re-inflates on the other side's next
plan operation, so both land in one commit.

## Cap 2 — the whole-file budget

`save_dashboard()` renders the JSON, and when the rendered text is **over**
`DASHBOARD_CHAR_BUDGET` it logs one prax WARNING naming the branch, the measured
size and the budget. Then it writes the file whole.

**Warn, never refuse, never trim.** A refused save leaves a stale dashboard, and
stale is the failure already on the board: zero new mail reported while three
wait in the inbox. The budget is a signal to the owner, not a gate.

A writer that does not call prax's `save_dashboard()` (@flow's push writes the
file itself) mirrors the measurement on its own write: same budget, same
warn-only shape.

## Pins

- `prax/tests/test_operations.py` — `TestCapSubject`, `TestDashboardCharBudget`
- `prax/tests/test_flow_section_contract.py` — `TestSubjectCap`
- `prax/tests/test_devpulse_dashboard_plugin.py` — the plugin reads the shared cap
