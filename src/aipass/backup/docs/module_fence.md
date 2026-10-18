[<- Back to BACKUP](../README.md)

# The handlers fence

The access guard on `apps/handlers/__init__.py`, the door other branches use instead, and the tests that prove both.

### What the fence decides

The fence is the fleet's handlers-fence template, rendered for backup. It
reads the stack once, when the handlers package is first imported, and sorts
every frame into kin (a file under this branch), transport (importlib, the
frozen bootstrap, the standard library, site-packages) or foreign (everything
else). The first foreign frame decides: refused when no kin frame stood between
it and the fence, or when its own source line names `aipass.backup.apps.handlers`;
allowed when kin code imported on its behalf.

`apps/__init__.py` does not import the handlers package. Such an import would
make the apps package the first frame every import showed the fence, so the
fence would never refuse anything. A `mock.patch` on a handlers path, which
imports from `unittest/mock.py`'s frame, passes as transport instead.

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
- `test_the_apps_package_does_not_import_its_handlers` in
  `tests/test_handlers_fence.py` pins the `apps/__init__.py` rule above.

---

[<- Back to BACKUP](../README.md)
