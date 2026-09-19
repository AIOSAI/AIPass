[<- Back to the README](../README.md)

# The CLI contract — exit codes, introspection, the import door

**Branch** spawn · **Code** `apps/spawn.py`, `apps/modules/__init__.py`,
`apps/handlers/class_registry.py`, `apps/handlers/docs_page.py`

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
prints that nothing was scanned and **exits non-zero**. It exited 0 until the refusal sweep,
which made "I searched the wrong root" indistinguishable from "your fleet is already
migrated" to anything reading the exit code.

---

## Introspection

The module and command inventory is generated from the code that runs it, so it is never
written down on a page and cannot go stale: the bare branch command prints the discovered
modules with their one-line descriptions, `--help` prints the command surface, and
`--version` prints the version string. The help flag is intercepted before argument parsing,
because the parser is built with `add_help=False`.

---

## The class registry — the gateway other branches import through

`apps/handlers/` is internal to this branch; its `__init__` refuses cross-branch imports and
points callers here. Other branches that need to resolve a `citizen_class` read spawn's
registry through the modules gateway rather than mirroring the class table — a mirror makes
the reader a fleet-wide single point of failure the moment spawn renames a class.

```python
from aipass.spawn.apps.modules import get_template_dir, refuse_legacy_class

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

`tests/test_modules_gateway.py` pins the door, and `tests/test_template_import_guard.py`
pins what a newborn's own handler guard must survive on its first import.

---

## The docs page skeleton — one source, read live

Every branch's `docs/*.md` pages share one shape, scored by @seedgo's `docs_page` standard.
The skeleton that shows the shape is `templates/docs_page.md`, and seedgo renders it through
the same gateway on every call — neither side keeps a copy.

```python
from aipass.spawn.apps.modules import docs_page_template

docs_page_template()   # -> the skeleton text, read from disk on this call
                       # -> OSError when it cannot be read; there is no fallback shape
```

The skeleton sits beside `templates/citizen/`, never inside it. Everything in the citizen
tree is stamped into every newborn, so a skeleton there would arrive as a placeholder page in
every branch; beside it, no walk reaches it — not the copy, not the manifest a mint is
verified against, not the update engine. The handler reads and returns and performs no
operation of its own, so it logs nothing; the render is seedgo's operation.

What a newborn does carry is the index: `templates/citizen/docs/README.md` is a back-link,
a title and one line, and it names the standard rather than the size cap, which seedgo owns.
`tests/test_modules_gateway.py` pins the door, `tests/test_template_hygiene.py` pins the
skeleton's shape and that no mint carries it, and `tests/test_birth_receipt.py` pins that the
index copies no cap.

---

**Last Updated:** 2026-09-19
