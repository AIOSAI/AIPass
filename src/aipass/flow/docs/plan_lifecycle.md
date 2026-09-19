[← Back to Flow](../README.md)

# Plan Lifecycle — create, close, list, restore

How a plan is named, which verb forms execute, how a bare number resolves against per-type registries, and what the close pipeline does in the foreground versus the detached background runner. Owned by `create_plan`, `close_plan`, `list_plans`, `restore_plan` and `post_close_runner`.

---

```bash
# Create plans
drone @flow create . "Subject"                  # Create FPLAN (default)
drone @flow create . "Subject" master           # Create FPLAN master template
drone @flow create . "Design topic" dplan       # Create DPLAN
drone @flow create . "Field note" cplan         # Create CPLAN (any registered shorthand)

# Close plans
drone @flow close FPLAN-0042                    # Close specific plan
drone @flow close DPLAN-0005                    # Close a DPLAN
drone @flow close --all                         # Close every open plan in YOUR project
drone @flow close --all --dry-run               # Preview what would close
drone @flow close --all --exclude-type APLAN    # Hold a whole plan type back (repeatable)
drone @flow close --dry-run FPLAN-0042          # Preview single close

# List plans
drone @flow list open                           # List open plans (all types)
drone @flow list all                            # List all plans

# Template management
drone @flow templates                           # List registered types
drone @flow scan                                # Find unregistered directories
drone @flow register <dir> <PREFIX>             # Register new plan type
drone @flow unregister <dir>                    # Remove plan type

# Registry
drone @flow registry scan                       # Scan filesystem, detect mismatches
drone @flow registry status                     # Show registry health

# Other
drone @flow restore FPLAN-0042                  # Reopen a closed plan
drone @flow aggregate                           # Cross-branch plan aggregation
drone @flow post                                # Background post-close processing
drone @flow --help                              # Full help
drone @flow --version                           # Version string
```

**Use the short verb.** Only the short form executes: `list`, `close`, `create`,
`restore`, `registry`, `aggregate`, and — all four owned by `template_manager` —
`templates`, `scan`, `register`, `unregister`. The module's full name
(`list_plans`, `close_plan`, …) resolves for `--help` but is rejected by the
dispatcher — `post`/`post_close_runner` is the sole module accepting both. The
`--help` screen claimed otherwise until 2026-09-15.

**A bare number is not an identity.** Every per-type registry numbers from
`0001`, so `0012` names a row in each of them and a bare number resolves against
`fplan_registry.json` by default. Pass the typed ID (`close TDPLAN-0012`) when
the plan is not an FPLAN. The prefix is read by an **anchored** match
(`^([A-Z]+PLAN)-` in `apps/handlers/plan/registry_routing.py`), so `TDPLAN-0012`
resolves to `tdplan_registry.json` and never collides with `DPLAN-0012`. A row
whose `file_path` carries no prefix offers no type evidence at all; the bulk and
restore paths refuse such a row rather than guess.

---


## Close Pipeline

On `drone @flow close` — the console prints five numbered steps, with vector
intake fired unlabelled between steps 3 and 4:

1. **`[1/5]` Template check** — *reports only, never deletes.* An empty
   template gets the warning "looks like an empty template — closing and
   archiving normally" and then flows through the identical pipeline. The old
   fast-delete branch was removed deliberately: `is_template_content()` is a
   heuristic, and its false positives permanently destroyed FPLAN-0370 and
   FPLAN-0371.
2. **`[2/5]` Mark closed** — sets `status` and the `closed` timestamp, saves the
   type's registry. **Close always succeeds from this point;** every later step
   is non-blocking.
3. **`[3/5]` Archive** — move to `.backup/processed_plans/` (foreground; sets
   `processed`/`processed_date`/`cleanup_completed`/`cleanup_date` and saves in
   one write)
4. *(unlabelled)* **Vector intake** — spawns `apps/modules/post_close_runner.py`
   detached; console shows only "Vectorizing in background"
5. **`[4/5]` Dashboard updates** — local, central, and branch dashboards
6. **`[5/5]` Finalizing** — append to `CLOSED_PLANS.local.json`, fire the
   `plan_closed` trigger event

**Close does not verify vectorisation, and cannot report it.** The runner is
launched with `subprocess.Popen(..., stdout=DEVNULL, stderr=DEVNULL,
start_new_session=True)` (`_spawn_background_runner`, `close_helpers.py`), so
its result is unreadable by the closing process by construction — a failed
vectorisation is silent. Nothing in flow calls `is_plan_vectorized()`; that
function lives in `@memory` and is reached only by the separate
`drone @memory verify <label>` command, which is where a real answer comes from.

Closed plans are archived to `<repo-root>/.backup/processed_plans/`, a shared runtime namespace managed by `@backup` (see `src/aipass/backup/README.md`) and consumed by `@memory` for vectorization.

---

