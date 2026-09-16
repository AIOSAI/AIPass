[← Back to the cli README](../README.md)

# Known issues

Open, verified, and not worth hiding. Nothing here blocks a caller of the
display API.

- `cli_entry()` in `__init__.py` is dead wiring. It is a valid console_scripts
  target, but the packaging config points the `aipass` script at the @aipass
  branch, so nothing calls it. Keep-or-retire was still open at the last branch
  audit.
- Nothing in the fleet currently exits **2**. The code is reachable — a routed
  command that calls `error()` and returns True gets it, measured from the shell
  — but no verb this branch ships does that today, so the 2 is pinned by test
  rather than by a live command. See [the exit seam](exit_seam.md).
- Importer counts depend on the scope you measure. @hooks counts its own cli
  imports in production files; a whole-tree count of this branch's importers
  includes @hooks' dead-cwd test pin
  (`tests/test_import_dead_cwd.py`), a plain `import aipass.cli.apps.modules`.
  Production-only and all-files are different questions; say which one a number
  answers. Both are measured by grep, never quoted from memory.
- `show` is a live top-level verb of the display module and `demo` routes to the
  display demo without a module name in front of it. Both now appear on the
  entry point's help page; neither is exercised by a doc example, and the bare
  `demo` form resolves by module discovery order rather than by an explicit
  choice.
- `python -m aipass.cli` is not an entry point: `__main__.py` was archived and
  no branch in the fleet ships one. The import is the real entry point.

## Carried, not re-measured in the current pass

- `tests/parked/` is described as tracked rather than ignored. That word carries
  from the pass that created the park; this branch runs no git commands, so it
  is asserted by doctrine and not by measurement here. The collection barrier
  beside it is measured: `tests/parked/conftest.py` sets
  `collect_ignore_glob = ["*"]` and `tests/test_parked_is_not_collected.py`
  pins it with real pytest collection.

---
[← Back to the cli README](../README.md)
