[<- Back to the README](../README.md)

# `shared/` — the stdlib-only part of this branch other branches import

*Why `shared/` is stdlib-only by contract, and who breaks if it is not.*

`shared/` is a real cross-branch dependency: **@spawn imports three of its four
modules** in production code —

- [`shared/json_ops.py`](../shared/json_ops.py) (`backup_json`, `deep_merge`,
  via `spawn/apps/handlers/update_ops.py`),
- [`shared/project_home.py`](../shared/project_home.py) (`_detect_aipass_home`,
  via `handlers/placeholders.py`),
- [`shared/registry_discovery.py`](../shared/registry_discovery.py)
  (`find_registry` via `handlers/registry.py`, `registries_in` via
  `handlers/delete_ops.py`).

This branch's `.seedgo/bypass.json` names the same dependency in its
`backup_json` rule. The fourth module is
[`shared/scaffold_content.py`](../shared/scaffold_content.py), the template
text `apps/handlers/init/` re-exports.

One door into `apps/` exists as well, and it is not under this contract:
@api's host verbs import [`apps/modules/new_project.py`](../apps/modules/new_project.py)
for `create_project` and `TEMPLATES`, which the module resolves from its
handler on first use. Nothing else in `apps/` is imported by another branch.

`shared/` is stdlib-only **by contract**, not by preference. It loads before
drone exists — the installer and the scaffold path both reach it before a
routing layer is available — and @spawn is downstream of it, so an import added
here lands in someone else's process.
`tests/test_shared_bootstrap_safety.py` is the guard.
`tests/test_import_dead_cwd.py` covers a second failure mode for every module
in the branch, `shared/` included: they must still import when the process's
cwd has been deleted underneath them.

`shared/` holds no json handler. The branch's json goes through the
branch-local shim at [`apps/handlers/json/`](../apps/handlers/json), which binds
the fleet's prax-owned json service — modules read and write json through that,
never through `json` directly.

---

[← Back to the AIPASS README](../README.md)
