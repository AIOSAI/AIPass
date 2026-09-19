# dashboard — refresh, template, write-through

How a branch dashboard is built, pushed and updated, and the programmatic API other branches call.

Moved out of `README.md` on 2026-09-15 (DPLAN-0347, the layer contract): the README is the
face, the depth lives here. Back to the [branch README](../README.md).

---

## Dashboard

```bash
drone @prax dashboard                    # Show dashboard sections
drone @prax dashboard refresh --all      # Refresh all branch dashboards from centrals
drone @prax dashboard refresh @flow      # Refresh a specific branch (core, then the caller's project registry)
drone @prax dashboard refresh            # Refresh the branch the CALLER stands in
drone @prax dashboard status             # Show dashboard status
drone @prax dashboard template           # Show the template schema
drone @prax dashboard template-status    # Per-branch template sync state
drone @prax dashboard push-template      # Push template to all branches
drone @prax dashboard diff-template      # Diff template vs branch dashboards
drone @prax dashboard --help             # Dashboard usage
```

`refresh --all` writes every branch's `DASHBOARD.local.json`. It accepts and
silently ignores unknown flags, so `refresh --all --dry-run` is a real
fleet-wide write, not a preview — there is no dry-run mode.

**`refresh @branch` reaches external projects (2026-09-11, FPLAN-0548).** The
name is looked up in `AIPASS_REGISTRY.json` first, exactly as before. On a
miss, prax looks in the caller's own project registry: the nearest
`*_REGISTRY.json` at or above the directory the caller stands in. A relative
path there resolves against that registry's own directory. A name declared in
both registries goes to core, and a warning names both rows. Before this, a
Vera Studio branch running `drone @prax dashboard refresh @verify` got
`Branch 'VERIFY' not found in registry` (exit 2), which is step 2 of the
post-compact re-ground. So every external branch's dashboard stayed as it was:
verify's still said `last_updated` 2026-07-09 and `new_mail` 0, while its inbox
held 5 unread. `--all` is unchanged and still covers core only.

**The caller's directory is `AIPASS_CALLER_CWD`, not the process cwd.** drone
runs every branch with its cwd set to the *target* branch, so inside prax
`Path.cwd()` is always prax. Measured the same day: a bare
`drone @prax dashboard refresh` from `src/aipass/flow` refreshed **PRAX**. Both
the project walk and the bare `refresh` now start from `_caller_dir()` in
`apps/modules/dashboard.py`. That reads `AIPASS_CALLER_CWD` first (an empty
value counts as unset) and falls back to the process cwd only for a direct run.
With neither, the bare form refuses and tells you to name the branch. It is
prax's one sanctioned working-directory read, the single entry in
`tests/test_repo_root.py`'s allowlist, so it stays in the module. The handler
`resolve_branch_path(ref, caller=None)` takes the directory as an argument and
never reads a cwd. Called without one, it is core-only, as before.

**Mail counts come from the branch's own inbox, never from the ai_mail central.**
`calculate_quick_status` counts `<branch>/.ai_mail.local/inbox.json`. The
refresh also builds an `ai_mail` section from `AI_MAIL.central.json`, but
nothing reads it and it is popped before save. So a branch with no central row,
which is every external branch today, still gets its true count. Pinned in
`tests/test_operations.py`: a central listing only FLOW, a branch inbox with 3
new, and `new_mail` 3. The comment in `refresh.py` used to say the section fed
the counts, and it misled a measurement that same day. It has been corrected.

## Programmatic Dashboard API

```python
from aipass.prax.apps.modules.dashboard import write_section

write_section(branch_path, "ai_mail", {"new": 3, "total": 5})
```

**quick_status has many writers.** prax refresh, `push-template`,
`write_section()` and other branches (@flow's push) all touch the same block.
Every prax write path now *merges*: it recomputes the keys prax owns
(`new_mail`, `opened_mail`, `active_plans`, `todo_count`, `action_required`,
`summary`) and carries every other key through untouched. The invariant, agreed
with @flow: **no writer deletes a key it did not write.** The calculation itself
lives in exactly one place
(`handlers/dashboard/status.py::calculate_quick_status`) — `refresh.py`,
`operations.py` and `template_pusher.py` all delegate to it.

**`sections.flow` has two writers too.** @flow's push and prax's refresh both
build that section wholesale, so the same invariant applies one level up. prax
mirrors @flow's five-key contract exactly — `managed_by`, `active_plans` (an int
count), `open_recent` (the 5 newest open plans, newest first), `recently_closed`
(closed inside the same 7-day window @flow uses), `total_plans` — pinned in
`tests/test_flow_section_contract.py` so the two writers cannot drift apart
again. `total_plans` is the one key prax has no honest source for, so it carries
@flow's value through instead of deriving one: the central file's per-branch
`statistics.total_closed` reads its own already-capped 5-entry list as the
closed universe, and reports 5 for a branch with 104 closed plans.

`action_required` is true when any counter the block renders in `summary` is
non-zero, todos included. It previously ignored `todo_count`, so a branch could
publish `"1 todos"` and `action_required: false` side by side — measured by
@flow against their own writer, which does count them.

`push-template` was the last independent copy, and the most dangerous one
because it writes every branch in the registry. It carried its own calculator
with no `todo_count`, assigned the block wholesale rather than merging, and
listed `commons_mentions` as a *deprecated key to delete*. prax did once own
that key, but @flow took it over instead of retiring it, so the list outlived
the ownership change: one push would have deleted a live key fleet-wide by
declared policy. Fixed 2026-08-13 — `template_pusher.DEPRECATED_QUICK_STATUS_KEYS`
now holds only `pending_bulletins`, and a key qualifies for it only when nobody
writes it.

`template_differ.py` reads the same list from the pusher (one constant, pinned in
`tests/test_dashboard_merge.py`), so `diff-template` recommends only what
`push-template` would do.

