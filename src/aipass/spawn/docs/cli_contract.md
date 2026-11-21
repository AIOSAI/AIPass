[<- Back to the README](../README.md)

# The CLI contract — exit codes, introspection, the import door

**Branch** spawn · **Code** `apps/spawn.py`, `apps/modules/__init__.py`,
`apps/handlers/class_registry.py`, `apps/handlers/bootstrap_render.py`

---

## Exit codes — a refusal never exits 0

`main()` calls `reset_command_state()` on entry (the failure flag is process-level and drone
routes in-process, so a stale mark from an earlier command would otherwise convict this
one), and every routed command's code passes through `_resolved()`: a non-zero code is its
own answer and is returned untouched; a 0 is re-asked of `resolve_exit`, which answers **2**
when the command called `error()` and **0** when it did not.

| Code | Meaning |
|------|---------|
| `0` | The command did what it said |
| `1` | The command refused, or the verb is unknown |
| `2` | The command returned 0 after calling `error()` — the seam caught it |

`migrate-passports` against a root with no discoverable passports is the worked example: it
prints that nothing was scanned and **exits non-zero**, so "I searched the wrong root" is
never mistaken for "your fleet is already migrated" by anything reading the exit code.

---

## Seats — who runs a lane that rewrites another citizen

A real run of `repair --apply` (relocate, rename, clean-pollution, scan), `adopt-citizen --apply`,
`update --apply`, `sync-registry --fix` and `migrate-passports --confirm` moves, renames,
rewrites or removes files in branches that are not the caller's, so it runs from @spawn's own
verified seat or the verified admin seat only (`apps/handlers/seat_gate.py`, ai_mail's
verified-caller rail; a verifier that raises answers no). Any other seat is refused
before anything is read or written, exits 1, is told to mail @spawn or @devpulse the branch and
why, and the refusal is logged with the caller, the verb, the target and the time
(`write_refused`). Every preview stays open to every seat and ends by naming who may run it for
real. `delete` is stricter: its real run is the admin seat's alone ([retire.md](retire.md)).

---

## Introspection

The module and command inventory is generated from the code that runs it, so it is never
written down on a page and cannot go stale: the bare branch command prints the discovered
modules with their one-line descriptions, `--help` prints the command surface, and
`--version` prints the version string. The help flag is intercepted before argument parsing,
because the parser is built with `add_help=False`.

---

## The package door — what other branches import

`apps/handlers/` is internal to this branch; its `__init__` refuses cross-branch imports and
points callers at the package door, `src/aipass/spawn/__init__.py`. The door hands out each
name from its home on every access (PEP 562 `__getattr__` over a name-to-home table, no cache),
so a bare `import aipass.spawn` loads nothing under `apps/`, and a patch on the home reaches
every caller that reads through the door. `apps/modules/__init__.py` re-exports nothing.

| Names | Home |
|---|---|
| `spawn_agent` | `apps/modules/core.py` |
| `CITIZEN_CLASSES`, `FORBIDDEN_CLASSES`, `LEGACY_CLASSES`, `get_available_classes`, `get_template_dir`, `refuse_legacy_class`, `refuse_retired_or_forbidden`, `validate_class` | `apps/handlers/class_registry.py` |
| `find_registry`, `get_owner`, `is_owner`, `registry_is_writable_document` | `apps/handlers/registry.py` |
| `render_bootstrap_trinity`, `restore_citizen` | `apps/handlers/bootstrap_render.py` |

`render_bootstrap_trinity(branch_name, target, citizen_class, role, registry_path)` is the install
script's one call: it writes the `.trinity` files a core branch lacks (a tracked passport vault
first, then the template) and returns the names written. It never overwrites an existing file,
and an unreadable registry or a vault that fails validation raises. A core citizen's module renders
as `aipass.<name>`; a project citizen's stays the bare name.

`restore_citizen(branch_name, registry_path)` is the same render for a repair: the folder comes
from the citizen's registry row, and its name, class and role from its own passport vault, so no class or
role list lives outside the vaults. It writes only the missing files and returns their names. A
passport that is present but not a JSON object counts as missing: it is renamed beside itself to
`passport.json.corrupt-<id>`, so its bytes are kept, and a fresh one is rendered. An
unregistered name raises `LookupError`, and a citizen without a vault raises `FileNotFoundError`.

Other branches that need to resolve a `citizen_class` read spawn's registry through the door
rather than mirroring the class table — a mirror makes the reader a fleet-wide single point
of failure the moment spawn renames a class.

```python
from aipass.spawn import get_template_dir, refuse_legacy_class

get_template_dir("specialist")           # -> Path to the one citizen template
get_template_dir("aipass_framework")     # -> ValueError naming the retired name AND 'specialist'
get_template_dir("admin")                # -> ValueError, permanent refusal
get_template_dir("wizard")               # -> ValueError listing the registered classes
refuse_legacy_class("aipass_framework")  # -> the rename message
refuse_legacy_class("specialist")        # -> "" (not a retired name)
```

`get_template_dir` already refuses forbidden, retired and unknown values by name, so
"resolve, or tell me why not" is one call plus `try/except ValueError`. `refuse_legacy_class`
is the separate lane for callers that must distinguish "this passport has not been migrated
yet" from a hard error.

`tests/test_modules_gateway.py` pins the door, and `tests/test_handlers_fence.py` pins
spawn's own fence (`apps/handlers/__init__.py`, v2.1) in a fresh interpreter per
case. Every newborn is born with the same fence: `templates/citizen/apps/handlers/__init__.py`
is devpulse's fence template verbatim, placeholders intact, and the template ships the pair
`tests/test_handlers_fence.py` and `tests/support_fence.py` so a newborn pins its own fence
from its first run. The fence's refusal names the package door, `from aipass.<branch> import
<name>`. A newborn is also born with that door: `templates/citizen/__init__.py` is the
same PEP 562 door with an empty name table, so a bare import loads nothing under `apps/` and
every name raises `AttributeError` until one is added. `spawn update` never overwrites an
existing `.py`, so a branch's real door is reported for review, never replaced.
`tests/test_template_import_guard.py` pins the template's fence before any mint: a foreign
seat refused by name, an outside seat refused as unknown, kin allowed, the empty door passing
the template's own `door` probe from a foreign seat, a dead cwd survived, and a cwd inside the
newborn buying a foreign seat nothing.

---

## A newborn's docs index

Every branch's `docs/*.md` pages share one shape, scored by @sentry's `docs_page` standard;
`drone @sentry standard docs_page` shows it, and spawn keeps no copy. A newborn carries no page,
only the index: `templates/citizen/docs/README.md` is a back-link, a title and one line, and it
names the standard rather than the size cap, which sentry owns. `tests/test_template_hygiene.py`
pins that the index is the only file a newborn's `docs/` holds, and `tests/test_birth_receipt.py`
pins that the index copies no cap.

---

**Last Updated:** 2026-10-17
