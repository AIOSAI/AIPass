[<- Back to the README](../README.md)

# Testing — how this branch's suite is run and judged

**Branch** drone · **Code** `tests/`

---

## Running it

From the branch directory:

```bash
python -m pytest tests/ -q
```

From the repo root, which is the shape CI uses:

```bash
python -m pytest src/aipass/drone/tests -c pyproject.toml --rootdir=. -q
```

Both rootdirs are run before anything is reported green — a suite that passes from one directory
and not the other is a real defect in the fixtures, and this branch has shipped that bug before.
Live counts come from the run, not from a table: `-q` prints them, and `--collect-only -q | tail -1`
prints the collected total without executing anything.

`conftest.py` carries the isolation this branch depends on: an autouse fixture that redirects the
deletion store away from the live `.ai_central/`, the `deletable_cwd` marker Windows skips, and the
reset of the caller-identity dedupe set.

---

## What the suite covers, by area

| Area | Files |
|------|-------|
| Core routing | `test_resolver.py`, `test_router.py`, `test_activation.py`, `test_registry.py` |
| Git operations | `test_git_access.py`, `test_git_module.py`, `test_tag_handler.py`, `test_devpulse_plugins.py`, `test_system_pr.py` |
| Handlers | `test_registry_handler.py`, `test_discovery.py`, `test_executor.py` |
| Commit gate | `test_commit_gate_branch_mapping.py` |
| Infrastructure | `test_module_registry.py`, `test_config.py`, `test_generic_adapter.py` |
| Features | `test_rm.py`, `test_commands.py`, `test_scan.py` |
| Deletion record | `test_deletion_log.py` |
| Broker | `test_broker.py` |
| Standards | `test_cli_routing.py` |
| Help-flag safety | `test_help_flag_safety.py` |
| Module routing, no detour | `test_module_route_no_detour.py` |
| Caller identity provenance | `test_caller_identity_provenance.py` |
| Machine output | `test_git_json_and_remote.py` |
| External roots | `test_external_roots.py` |
| Dead-cwd hermeticity | `test_import_dead_cwd.py`, `test_no_cwd_sweep.py` |
| Registry case sweep | `test_registry_case_sweep.py` |
| Bypass anchors | `test_bypass_anchors.py` |

Every test file on disk appears in exactly one row. A per-file table with numbers in it drifts
silently in one direction — rows for departed files keep reporting and arrivals are invisible — so
the numbers are not written here; the run prints them.

---

## New test files are gated

A hook refuses a new test file by policy (`.aipass/test_write_policy.json`). Editing an existing
test file is fine. A new file needs @devpulse's permission, named with the defect or the contract
it would pin. The gate is never routed around.

---

## The standards lanes

- `drone @seedgo audit aipass @drone` — the scored pack, the one CI gates.
- `drone @seedgo audit pytest_quality @drone` — the advisory test-quality lane.
- `drone @seedgo audit context @drone` — the startup budget: README, prompt, `.trinity/` and the
  dashboard, in chars, each against the cap its owner publishes.
- `drone @seedgo checklist <file>` — one file, every eligible standard, which is also what the
  post-edit hook runs.

Documented exceptions live in `.seedgo/bypass.json`, each with a written reason. Several of them
are line-scoped and drift whenever code above them moves; that drift is a feature in one respect,
since it proves the rule is still load-bearing.

---

## The proof standard

A test that cannot fail is scenery. The bar in this branch is mutation: apply the mutant to the
source, run the targeted tests, expect red, restore. A pin that survives its mutant gets rewritten
rather than counted — the commit subject cap shipped with one that passed a copied constant,
because CPython interns small ints, and it was only the mutant that said so.
