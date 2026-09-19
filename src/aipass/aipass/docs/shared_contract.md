[<- Back to the README](../README.md)

# `shared/` — the one part of this branch other branches import

*Why `shared/` is stdlib-only by contract, and who breaks if it is not.*

The old claim that *no* `.py` source elsewhere imports this branch was wrong,
and was corrected on 2026-09-05 by grepping the tree. `shared/` is a real
cross-branch dependency: **@spawn imports three of its four modules** in
production code —

- [`shared/json_ops.py`](../shared/json_ops.py) (`backup_json`, `deep_merge`,
  via `spawn/apps/handlers/json_ops.py`),
- [`shared/project_home.py`](../shared/project_home.py) (`_detect_aipass_home`,
  via `handlers/placeholders.py`),
- [`shared/registry_discovery.py`](../shared/registry_discovery.py)
  (`find_registry`, via `handlers/registry.py`).

This branch's own `.seedgo/bypass.json` has said so since 2026-08-09 in the
`backup_json` rule; the README simply disagreed with it. The fourth module is
[`shared/scaffold_content.py`](../shared/scaffold_content.py), the template
text `apps/handlers/init/` re-exports. Nothing outside `shared/` is imported by
anyone — `apps/` really is humans-only.

Consequence worth stating: `shared/` is stdlib-only **by contract**, not by
preference. It loads before drone exists — the installer and the scaffold path
both reach it before a routing layer is available — and @spawn is downstream of
it, so an import added here lands in someone else's process.
`tests/test_shared_bootstrap_safety.py` is the guard.
`tests/test_import_dead_cwd.py` covers a second failure mode for every module
in the branch, `shared/` included: they must still import when the process's
cwd has been deleted underneath them.

`json_handler` is not in the list: it was retired to `shared/.archive/` on
2026-09-04 (DPLAN-0325). The live one is the branch-local shim at
[`apps/handlers/json/`](../apps/handlers/json), which binds the fleet's
prax-owned json service — modules read and write json through that, never
through `json` directly.

---

[← Back to the AIPASS README](../README.md)
