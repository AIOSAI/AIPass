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

The door is the branch's `__init__.py`. It names what the branch hands out in `__all__` and loads each name on first access (PEP 562 `__getattr__`), never with an eager import at the top. An eager door imports every module behind it whenever anything imports the package, the branch's own files included, which is how import loops start. prax's door is the model:

```python
import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aipass.prax.apps.modules.logger import system_logger as logger

__all__ = ["logger"]

_LOGGER_MODULE = "aipass.prax.apps.modules.logger"


def __getattr__(name: str) -> Any:
    if name == "logger":
        value = importlib.import_module(_LOGGER_MODULE).system_logger
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value
```

The door's own imports of its branch are inside the branch and never findings. A `door_` module under `apps/modules/` is inside-the-branch plumbing: the front door may hand out its names, but another branch does not import it by path.

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
