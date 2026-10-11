[<- Back to BACKUP](../README.md)

# The handlers fence

The access guard on `apps/handlers/__init__.py`, the door other branches use instead, and the tests that prove both.

### What the fence decides

The fence is the fleet's v2.1 template (DPLAN-0404), rendered for backup. It
reads the stack once, when the handlers package is first imported, and sorts
every frame into kin (a file under this branch), transport (importlib, the
frozen bootstrap, the standard library, site-packages) or foreign (everything
else). The first foreign frame decides: refused when no kin frame stood between
it and the fence, or when its own source line names `aipass.backup.apps.handlers`;
allowed when kin code imported on its behalf.

`apps/__init__.py` no longer carries `from . import handlers`. That line, added
fleet-wide on 2026-04-25 for a Python 3.10 `mock.patch` failure, made the apps
package the first frame every import showed the fence, so the fence never
refused anything. The transport rule replaces it.

A pseudo filename such as `<string>` is never resolved: resolved, it would read
against the process cwd, and a cwd inside this branch would make every bootstrap
frame look like kin.

The fence fires on the first import in a process only; after that the package is
served from `sys.modules`. The write-time wall is seedgo's `encapsulation` row.

### The door

Other branches reach backup through `apps/modules/door_trail.py`, which publishes
`log_operation` from `apps/handlers/audit/trail.py` and nothing else. A door is
not a command: it has no `handle_command`, so the router never offers it.

### The tests

- `tests/test_handlers_fence.py` runs `tests/support_fence.py` in a fresh
  interpreter per case: six foreign import shapes from a seat under `tmp_path`,
  each run with a tmp cwd and with the cwd at the branch root, a seat with no
  branch at all, the kin seat in five shapes, and the door from a foreign seat.
- `tests/test_dead_cwd_imports.py` runs the kin probe from a child whose cwd was
  removed under it, and expects ALLOWED.

The mutants run against both on 2026-10-08 are listed in the fleet's DPLAN-0404
reply from backup.

---

[<- Back to BACKUP](../README.md)
