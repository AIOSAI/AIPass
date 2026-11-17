# Front Door

An import that crosses from one branch into another goes through that branch's front door: its package top file, `src/aipass/<branch>/__init__.py`. Inside its own branch a file imports any path it likes.

```python
from aipass.prax import logger                                   # right: the door
from aipass.cli import console, error

from aipass.prax.apps.modules.logger import system_logger       # wrong: reaches under prax's apps/
from aipass.cli.apps.modules import console                     # wrong, modules as much as handlers
```

One spelling everywhere, so an agent that copies what it sees copies the right thing, and a branch can move anything under its `apps/` without breaking a caller.

## The door file

The door is the branch's `__init__.py`, the one door. It holds a name-to-home table, `_HOMES`, and a module `__getattr__` (PEP 562) reads that table on each access: nothing is cached on the package, so a patch on the home reaches every later read, and an unknown name raises AttributeError. It never imports eagerly at the top. An eager door imports every module behind it whenever anything imports the package, the branch's own files included, which is how import loops start. prax's door is the model:

```python
import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aipass.prax.apps.modules.logger import system_logger as logger

_LOGGER_MODULE = "aipass.prax.apps.modules.logger"

# Door name -> (home module, attribute there); None hands out the home module itself.
_HOMES = {"logger": (_LOGGER_MODULE, "system_logger")}

__all__ = sorted(_HOMES)


def __getattr__(name: str) -> Any:
    if name not in _HOMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = _HOMES[name]
    home = importlib.import_module(module_name)  # every access, never cached
    return home if attribute is None else getattr(home, attribute)


def __dir__() -> list:
    return sorted(set(globals()) | set(__all__))
```

`__all__` is built from the table, so the public list and the names the door serves cannot drift, and `__dir__` lists every door name before any has been read. The door's own imports of its branch are inside the branch and never findings.

### The door model, checked

A package top file that defines a module-level `__getattr__` is a door, and this row checks its model. Each broken fact is a finding at the line that breaks it, with its cure, and no bypass row waives it:

- **A cache.** In `__getattr__` or any function of the file it calls: a write to `globals()[...]` or `vars()[...]`, `setattr(sys.modules[...], ...)`, a write into a module-level dict (`_SEEN[name] = ...`, `.update`, `.setdefault`), a `global` statement, or a `cache` decorator. Cure: return it, store nothing; a patch on the home must reach the next reader.
- **An answered unknown name.** `getattr(home, name, default)`, an `except` that does not raise, or a path an unknown name takes to a `return` (or off the end, which returns None) before `raise AttributeError`. The path is followed through `if name in`/`name ==` branches, which serve known names, to the `if name not in ...: raise AttributeError(...)` guard.
- **`__all__`.** Missing; or a list that leaves out a table `__getattr__` reads names from (`name in TABLE`, `TABLE[...]`), so the list and the served names can drift. A door's own defs may sit beside the table: `["helper", *_HOMES]`.
- **`__dir__`.** Missing.

A package top file with no `__getattr__` is not a door and is not judged by these. Forms the reader does not follow are left unjudged, never guessed: an `if` on anything but the name, or a loop, `try` or `with` block, before the guard; an `__all__` assigned more than once, extended with `+=`, or built by anything but a literal list or tuple of strings and `*NAME` spreads, a name, or `list`/`sorted`/`tuple`/`set` of a name.

The encapsulation row convicts a runtime import of the branch's own handlers in the door (a `TYPE_CHECKING` import is acquitted). unused_function and the front-door verb read the door's `__all__`.

## Patching a door name in a test

A test patches a door name one of three ways:

- the door itself: `mock.patch("aipass.<branch>.<name>")`;
- the caller's own bound name: `patch.object(caller_module, "name")`;
- the home, reached through the name's own module: `patch.object(sys.modules[aipass.<branch>.<name>.__module__], "name")`.

Never `monkeypatch.setattr` on the package (`aipass.<branch>`): its undo leaves the real value bound as a package global, and the door serves that copy from then on, past every later patch on the home.

The event bus is silenced in another branch's test one way: patch `Trigger.fire` on the class, `patch.object(Trigger, "fire")` with `from aipass.trigger import Trigger`.

## One door: a second door is convicted

A branch has one door. A module under `apps/modules/` that hands its branch's handler names outward is a second door and a finding of its own, in three shapes. The first two are found at line 1, `<module>`; the third, the mixed kind, below:

- by name: the file is `door_<anything>.py`, whatever it holds;
- by shape: its whole body is imports from its own branch's handlers (and the stdlib) plus an `__all__` of names it imported, with no function, class or other statement.

An `apps/modules/__init__.py` is not read by shape: its re-export is as often the branch's own plumbing, and each foreign import of it is already a finding. The cure: the package top file hands out the name, `from aipass.<branch> import <name>`, and the module is retired once no other branch imports it. No bypass row waives a second door, and the modules, imports, introspection and dead_code rows leave it to this one, so one defect is reported once.

### The mixed kind: a real module handing out handler names

A module's own API is what it defines. A module under `apps/modules/` with real logic whose `__all__` also names something it imported from its own branch's handlers is handing those names outward, and is the mixed kind of second door. It is one finding at the `__all__` line, never waived, naming each handed-out name and the handler it comes from. The cure: the package door hands those names out from their homes, and the module drops them from `__all__` once no other branch imports them from here; it keeps the names it defines. A `door_` or door-shaped file gets only the finding above, not this one too. The other rows still judge the module as the module it is.

What this reading cannot tell, and what covers it:

- `apps/modules/__init__.py` is not read, for the same reason as above; each foreign import of it is a front_door site.
- A module with no `__all__` that other branches import handler names from is invisible here; each such foreign import is a front_door site, which is the cover for that case.
- An `__all__` that lists a handler name only for the module's own branch would be convicted all the same: the file alone cannot tell an inside reader from an outside one. The cure is the same, list only what the module defines.

## How a branch decides its public list

The list is what other branches already reach for. `drone @sentry front-door scan` prints, per branch, every module and name other branches import from under its `apps/`; that list is the door's first `__all__`. A name nobody outside uses stays off it. The command door, `apps/<branch>.py`, is a separate thing and is unchanged.

## What counts

Read from the parse tree, never from lines:

| Via | Counted |
|-----|---------|
| statement | `import` and `from ... import`, at the top, inside a function, anywhere |
| type-only | the same inside `if TYPE_CHECKING:` (its `else` branch is a statement) |
| string | the first argument of `import_module`, `resolve_name`, `patch`, `<x>.setattr`: a literal or a module constant |

The target's branch is the segment after `aipass.`, however deep it nests: `aipass.skills.lib.<x>.apps...` is skills'. The file's branch is the directory after `src/aipass/`; a file outside every branch owns nothing, so every `aipass.` import under `apps` it makes is a finding. A docstring, comment or log message is prose and never counts. Relative imports are always the file's own branch.

## What it cannot see

- `__import__("...")` and `pytest.importorskip("...")`.
- `import_module` bound to a local name (`_IMPORT = importlib.import_module`).
- A module put into `sys.modules` by name (`monkeypatch.setitem`, `patch.dict`, a subscript).
- Python code in a string handed to a child process (`python -c "from aipass..."`).

## Scope, scoring, bypass

Production and test files both: a test that imports another branch by path is a caller like any other. Each finding is one site, a line and its enclosing function (`<module>` at the top level). A file with an unwaived site scores 0, otherwise 100; a file Python cannot parse scores 0, its imports unjudged. The row gates: it counts in the branch average like every scored row.

A bypass row waives by `lines`, by `functions`, or the whole file, standard `front_door`. A site is waived only when the target branch has no door name for it yet and the row says so.
