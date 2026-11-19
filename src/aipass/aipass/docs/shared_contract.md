[<- Back to the README](../README.md)

# `shared/` — this branch's install-time helpers

*What `shared/` holds, why it loads no branch but prax, and where its AIPass home comes from.*

`shared/` is aipass's own install-time helpers, used by `init`, `new`, `adopt`,
`doctor` and `read`:

- [`shared/scaffold_content.py`](../shared/scaffold_content.py) — the template
  text `apps/handlers/init/` re-exports.
- [`shared/project_home.py`](../shared/project_home.py) — the AIPass home
  (`_detect_aipass_home`), project-path checks and the `.claude` settings content.
- [`shared/registry_discovery.py`](../shared/registry_discovery.py) — `find_registry`
  (walk up to a `*_REGISTRY.json`) and `registries_in` (the registries in one directory).

No other branch imports `shared/`.

## The import rule

`shared/` loads no branch but prax at import. Prax is the one exception because it
is the only logging system and ships in the same wheel: wherever `shared/` can be
imported, prax can too. Any other branch is loaded inside the function that uses it,
never at the top, and an ImportError there raises:

- drone's `is_registry_filename`, inside `registries_in`;
- drone's `resolve_aipass_home`, inside `_detect_aipass_home`;
- hooks' `enroll`, inside `_enroll_project`.

`tests/test_shared_bootstrap_safety.py` is the guard: importing `shared/` and the init
handlers loads no branch but prax, and every one that logs uses prax's logger.

## Registries in a directory

`registries_in` lists a directory with glob (no file-type filter; an unreadable or
missing directory lists nothing) and keeps only the names drone's
`is_registry_filename` accepts: a name ending exactly, case-sensitively, in
`_REGISTRY.json`. On a case-insensitive filesystem glob also answers
`x_registry.json`; that name is dropped.

## The AIPass home

`_detect_aipass_home` returns drone's `resolve_aipass_home` answer. First answer wins:

1. `AIPASS_HOME`, as given;
2. the parent of the interpreter's venv, when it holds an `AIPASS_REGISTRY.json`;
3. the newest enrolled home in `~/.aipass/trusted_projects.json`.

When all three fail it logs an ERROR naming what was tried and returns None. Every
caller refuses on None and names `AIPASS_HOME=/path/to/AIPass`: `init`, `init update`,
`new` and `adopt` raise before they write anything; `doctor` shows an `aipass home`
FAIL row and skips the checks that need the home; `aipass read` prints the error and
exits non-zero.

## Not under this contract

The package top file, [`__init__.py`](../__init__.py), hands out `create_project` and
`TEMPLATES` (`from aipass.aipass import create_project`), each read from
`apps/handlers/new_project/` on every access, never cached; a bare `import aipass.aipass`
loads nothing under `apps/`. The two names are what @api's host verbs call.

`shared/` holds no json handler. The branch's json goes through the branch-local shim
at [`apps/handlers/json/`](../apps/handlers/json), which binds the fleet's prax-owned
json service.

---

[← Back to the AIPASS README](../README.md)
