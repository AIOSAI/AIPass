# Import Standards
**Status:** Draft v2
**Date:** 2026-03-08

---
## Standard Import Order

**Every Python file follows this pattern:**

```python
#!/usr/bin/env python3

# [META BLOCK]

"""Module docstring"""

# Standard library imports
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Prax logger (when the file logs; stdlib logging fails the check)
from aipass.prax import logger

# Services (CLI, etc.) - through the branch's front door
from aipass.cli import console, header, success, error

# Internal/local imports
from aipass.sentry.apps.handlers.json import json_handler
from aipass.sentry.apps.handlers.domain1 import ops
```

**WHY this order:**
1. **Standard library** - Python built-ins grouped together
2. **Prax logger** - System-wide logging service
3. **Services** - CLI, other branch services (import before internal handlers)
4. **Internal imports** - After all external dependencies resolved

> **Note:** AIPass uses pip-installable namespace imports (`from aipass.{module}...`). No `sys.path` manipulation needed.

---

## Import Namespace Pattern

**The standard:**
```python
# Another branch: through its front door only
from aipass.<branch> import <name>
from aipass import <branch>          # then <branch>.<name>

# Your own branch: the apps paths
from aipass.<self>.apps.modules.<name> import something
from aipass.<self>.apps.handlers.<domain> import handler
```

**The front door (cross-branch rule, `front_door` row):**
- Another branch is imported only as `from aipass.<branch> import <name>` (or
  `from aipass import <branch>` then `<branch>.<name>`). Never a path under its `apps/`:
  `from aipass.prax.apps.modules.logger import system_logger` is convicted, modules as much as handlers.
- The package top file `src/aipass/<branch>/__init__.py` is the one door. It holds a
  name-to-home table (`_HOMES`) read on each access by a module `__getattr__` (PEP 562):
  nothing is cached on the package, and an unknown name raises AttributeError.
- Second doors are convicted: a `door_*` file under `apps/modules`, a pure re-export
  module, and a module whose `__all__` hands out handler names.
- A test patches a door name one of three ways: `mock.patch("aipass.<branch>.<name>")`, the
  caller's own bound name (`patch.object(caller_module, "name")`), or the home reached through
  the name's own module (`patch.object(sys.modules[aipass.<branch>.<name>.__module__], ...)`).
  Never `monkeypatch.setattr` on the package (`aipass.<branch>`): its undo leaves the real
  value bound as a package global, and the door serves that copy from then on.
- To silence the event bus in another branch's test: `patch.object(Trigger, "fire")` with
  `from aipass.trigger import Trigger`.

**WHY namespace imports:**
- Works across all environments (pip-installed package)
- No `sys.path` manipulation needed
- Explicit, traceable import paths

**Where it's used:**
```python
# Cross-branch service imports (front door)
from aipass.prax import logger
from aipass.cli import console, header

# Internal branch imports
from aipass.sentry.apps.handlers.json import json_handler
from aipass.sentry.apps.handlers.domain1 import ops
```

**Consistency rule:** Always use `from aipass.{module}...`, never bare imports like `from prax...`

---

## No sys.path Setup Needed

AIPass is a pip-installable package. All imports use the `aipass.*` namespace and resolve automatically via the installed package.

```python
# No sys.path manipulation required
# Just import directly:
from aipass.prax import logger
from aipass.sentry.apps.handlers.json import json_handler
```

**Install for development:**
```bash
pip install -e .
```

This registers the `aipass` namespace so all `from aipass.{module}...` imports work from anywhere.

---

## Prax Logger Import (When the File Logs)

**The rule:** a file that logs routes its log calls through prax. The check convicts
stdlib logging, never the absence of an import (owner's ruling, 2026-11-15):

- **FAILS** when the file imports stdlib `logging` and logs with it (`logging.getLogger(...)`,
  `logging.info(...)`, `from logging import getLogger`), or calls a level method
  (`debug` / `info` / `warning` / `warn` / `error` / `exception` / `critical` / `log`) on a name
  bound to a stdlib logger (`log = logging.getLogger(__name__)`, `self.log = ...`).
- **PASSES** when the file has no log calls (no prax import is required, so an unused one
  is dead code, not compliance), or its log calls go through either prax binding below.
- Read from the AST of the whole file: a `logging` call inside a string is no call, and
  `parser.error(...)` on a non-logger name is not convicted. Test files, handlers, doors,
  `__init__.py` and files under 20 code lines are not asked.

**The most common import in the system:**

```python
from aipass.prax import logger
```

**WHY Prax is important:**
- **System-wide logging** for all branches that subscribe
- **Service provider model** - Prax provides logging as a service
- **Consistent import pattern** - Same everywhere for easy recognition
- **Nearly universal** - Used in almost every file that logs

**Usage:**
```python
logger.info("Branch created successfully")
logger.warning("Memory file not found, using defaults")
logger.error("Failed to backup branch", exc_info=True)
```

**Two forms pass** — this check is about **routing**, not binding style. The full
`apps` path also routes through prax, but the `front_door` row convicts it as a
cross-branch import:
```python
# RECOMMENDED — @prax's ruling 2026-08-30. Both door forms route identically,
# so consistency is the tiebreak.
from aipass.prax import logger

# Full path — convicted by front_door, and the one form that CRASHES under a
# mocked `aipass.prax` (see the warning below).
from aipass.prax.apps.modules.logger import system_logger as logger  # ✗ front_door

# Module form — valid. Resolves `.logger` at call time (see the testability note),
# but that alone does not make it mockable.
from aipass import prax
...
prax.logger.debug("...")

# Never these
import aipass.prax.system_logger  # ✗
import logging; logging.getLogger()  # ✗ Use prax, not stdlib logging
```

**Testability note — the recommended form is mockable by exactly one target.** The
object forms bind the logger **object** into the consumer's globals at import time. The
module form holds a *module* and resolves `.logger` at **call** time.

That difference decides which mocking technique can reach a consumer. Measured against a
real consumer of the recommended form (`aipass/backup/.../json_handler.py:18`), by object
identity, with the real `prax` imported:

| technique | reaches the consumer? |
|---|---|
| `patch("aipass.prax.logger")` | **no** |
| `patch("aipass.prax.apps.modules.logger.system_logger")` | **no** |
| `setitem(sys.modules, "aipass.prax", ...)` | **no** |
| `setitem(sys.modules, "aipass.prax.apps.modules.logger", ...)` | **no** |
| `patch("<the consuming module>.logger")` | **yes** |

Those first four are the four techniques actually in use across this fleet's conftests.
**All four reach nothing** — the consumer keeps the real `SystemLogger` for the whole
session and real writes escape into `@prax`'s live state directory.

The fifth row is not "nobody", and @spawn corrected me on it (2026-08-31): they already
had exactly one correct call site — `tests/test_file_ops.py:176`, a `@patch` decorator
naming `file_ops.logger`, written before any of this came up. The technique was in the
fleet; it just was not in the *shared fixture*, which is where it mattered. Someone
arriving at the right answer without publishing it is the same failure mode as this
standard recommending a form without the technique that goes with it.

The rule underneath is simpler than "rebindable vs not": **the last dot must be resolved
at call time.** Patching upstream of a binding never reaches past it. The door in
`aipass/prax/__init__.py` resolves `logger` from its `_HOMES` table on each access, but
`from aipass.prax import logger` copies the object into the consumer at import time, so
a later patch on the package or the home misses that copy.

**So if you use an object form — and 385 files do, against 0 using the module form —
mock it per consumer, by that consumer's own dotted path:**

```python
patch("aipass.<branch>.apps.handlers.<mod>.logger")
```

Raised by **@memory 2026-08-30**, who proposed the module form as a fix, tested it,
found it insufficient alone, and mailed the correction before anyone spent a session on
it. Their fleet numbers (1552 writes in `@memory`) reproduced here: **one** `@daemon`
test under plain `pytest` performed **23 atomic writes into the real `prax_json/`**,
attributed by audit hook rather than inferred from a before/after diff — on a live
machine, ambient writes make that diff unattributable, and the control run drifted just
as much as the treatment.

The logging check does **not** rank the two door forms. Which form is *recommended* is
`@prax`'s logging contract to set; the logging check accepts both, and the full path is
convicted by the `front_door` row, not by this check.

**Warning — the full-path form (convicted by front_door) crashes against a mocked `aipass.prax`.** If a fixture
puts a stand-in module in `sys.modules["aipass.prax"]`, the mock has no `apps`
submodule, so the deep import raises rather than resolving:

```
ModuleNotFoundError: No module named 'aipass.prax.apps'; 'aipass.prax' is not a package
```

The other two forms import cleanly under the same mock. Reported and measured by
`@prax` 2026-08-30, reproduced here.

**The escaping writes are not the import form's fault.** `@prax` measured that
importing `prax` writes **nothing** in any of the three spellings — the writes come
from the **first call**, which starts the file watcher and auto-creates per-module
JSON (26 writes on call one, 0 on call two, identical across all three forms). The
actual cause is a **half-built seam in `prax` itself**: `config/load.py` already
redirects *log files* to `/tmp/aipass_test_logs/` when it detects pytest, but
`json_handler.PRAX_JSON_DIR` is a module-level constant built from `__file__` with no
pytest branch. Measured on one `logger.info()` under `PYTEST_CURRENT_TEST`:
**4 writes redirected, 24 writes into the real `prax_json/`.** `@prax` owns the fix
(APLAN-0009) and it needs no cooperation from callers.

**A module-level env-var seam has to win an import race — and it usually loses.**
The same "captured at import" defect that freezes a logger binding also freezes a *path*.
This shape is wrong:

```python
# ✗ resolved ONCE, at import time
DIR = Path(os.environ.get("AIPASS_TEST_LOG_DIR") or _DEFAULT)
```

It measures **green in isolation** — set the variable before anything imports the
module and it redirects correctly — and changes nothing in a real run, because a
`conftest.py` that sets the variable still loses to anything that imported the module
first. Reproduced here, same module, both orders:

| when the env var is set | module-level constant | resolved at call time |
|---|---|---|
| before any import | `/tmp/redirected/x` | `/tmp/redirected/x` |
| **after something imported it** | `/real/live/tree/x` ❌ | `/tmp/redirected/x` ✅ |

Resolve at **call** time instead:

```python
# ✓ resolved per call — no import race to lose
def _dir() -> Path:
    return Path(os.environ.get("AIPASS_TEST_LOG_DIR") or _DEFAULT)
```

Found by `@prax` 2026-08-30 while shipping the `PRAX_JSON_DIR` redirect (json_handler
1.2.0): their conftest set the variable before any import and the constant *still*
resolved to the live tree, because something imported `json_handler` first. Moving
resolution to call time took one `logger.info()` under pytest from **24 real writes to
0**, and prax's own collection from **107 atomic renames to 0**.

`@prax` also reports the test-side half, which is the same lesson twice: a mutation
reverting the path builder to read the import-time constant **survived every test**
until the **use site** was pinned rather than the pure resolver. Testing a predicate is
not testing that anything calls it.

**Output location:** Prax manages log files, branches don't need to worry about where logs go

---

## Handler Independence Import Rule

**Core rule:** Handlers CANNOT import from parent branch modules

**Example - Sentry:**

```python
# ✓ ALLOWED - Handler imports another handler
# sentry/apps/handlers/domain1/ops.py
from aipass.sentry.apps.handlers.json import json_handler

# ✓ ALLOWED - Handler imports standard library
import json
from pathlib import Path

# ✓ ALLOWED - Handler imports Prax service (front door)
from aipass.prax import logger

# ✓ ALLOWED - Handler imports CLI service (front door)
from aipass.cli import console, error

# ✗ FORBIDDEN - Handler imports parent module
from aipass.sentry.apps.modules.create_thing import something  # BREAKS INDEPENDENCE
```

**WHY this matters:**
- **Marketplace transportability** - Handlers can be moved to other branches
- **No circular dependencies** - Clean one-way flow
- **Self-contained units** - Handlers work independently

**Pattern:**
```
Modules import handlers ✓
Handlers import handlers ✓
Handlers import modules ✗
```

---

## Internal Import Patterns

**From modules to handlers:**
```python
# In sentry/apps/modules/create_thing.py
from aipass.sentry.apps.handlers.json import json_handler
from aipass.sentry.apps.handlers.domain1 import ops
```

**From handlers to handlers (within same branch):**
```python
# In sentry/apps/handlers/domain1/ops.py
from aipass.sentry.apps.handlers.json import json_handler
```

**Cross-branch service imports:**
```python
# Services can be imported anywhere (modules or handlers), through the front door
from aipass.prax import logger
from aipass.cli import console, header, success, error
```

**Relative imports (avoided):**
```python
# ✗ Don't use relative imports
from ...handlers.json import json_handler  # Confusing, hard to trace

# ✓ Use absolute namespace imports
from aipass.sentry.apps.handlers.json import json_handler  # Clear, explicit
```

---

## External Services - Invocation Context

Some AIPass services need to know **which branch is calling them** to provide proper context-aware functionality. This requires specific invocation patterns beyond simple imports.

### Service Categories

**Library Services (Import & Use):**
- **Prax** - Logging service
- **CLI** - Console formatting and output
- **API** - LLM calls and AI interactions
- **Memory** - Vector storage and search

**Router Services (CLI First, Package Door for Names):**
- **Drone** - a command router first, with a package door
  - Resolves `@` targets before passing commands to branches
  - Reach another branch through `drone @branch command`: `subprocess.run(["drone", "command", ...])`
  - A name drone's door hands out is imported as `from aipass.drone import <name>`, never from `aipass.drone.apps...`

### Context-Independent Services (Import & Use Anywhere)

**These services work from any location:**

```python
# Prax Logger - context-independent
from aipass.prax import logger
logger.info("Works from anywhere")

# CLI Services - context-independent
from aipass.cli import console, header
console.print("Works from anywhere")
```

**Why they work anywhere:** These services don't need to know who's calling them. They provide generic functionality.

### Drone: a Command Router with a Package Door

**Drone is a command router first.** It:
1. Resolves `@` targets to actual branch paths
2. Routes commands to the appropriate branch
3. Handles context switching and invocation

**✓ CORRECT - Invoke Drone as CLI:**
```python
import subprocess

# Drone resolves @ and routes the command
subprocess.run(["drone", "email", "send", "@recipient", "Subject", "Message"])
subprocess.run(["drone", "log", "show"])
subprocess.run(["drone", "@sentry", "some-command"])
```

**✓ CORRECT - A name from drone's package door:**
```python
from aipass.drone import normalize_branch_arg, route_command
```

**✗ FORBIDDEN - Never import from drone's apps/:**
```python
# ✗ WRONG - under drone's apps/, convicted by front_door; use from aipass.drone import <name>
from aipass.drone.apps.modules import resolve_target  # NO!
from aipass.drone.apps.modules.router import route_command  # NO!

# Branches should NOT handle @ resolution themselves
# That's Drone's job - it resolves @ before passing to branches
```

**Why Drone is different:**
- **Prax/CLI/API/Memory**: Library services providing functionality via imports
- **Drone**: command router first that resolves targets and invokes other tools; its door hands out names such as `resolve_branch`, `normalize_branch_arg`, `route_command` and the registry errors
- Branches receive already-resolved paths/commands from Drone
- Branches don't need @ handling code - Drone does that BEFORE calling them

---

### Context-Dependent Services (PWD Detection Required)

**AI_MAIL** uses PWD (Present Working Directory) detection to determine sender identity and configuration. This means **you must invoke AI_MAIL from your branch directory** for proper operation.

#### The Pattern: Call from Branch Directory

```python
# ✓ CORRECT - Call from your branch directory
# Working dir: src/aipass/sentry/

import subprocess
subprocess.run(["drone", "@ai_mail", "send", "@drone", "Subject", "Message"])

# AI_MAIL walks up from your CWD, finds branch identity, knows you're @sentry
# Your email sends FROM @sentry (not @devpulse or @ai_mail)
```

```python
# ✗ WRONG - Call from wrong directory
# Working dir: / (no branch context)

subprocess.run(["drone", "@ai_mail", "send", "@drone", "Subject", "Message"])

# AI_MAIL can't find branch identity, falls back to @devpulse
# Email sends from wrong identity
```

#### How PWD Detection Works

1. **AI_MAIL starts** at your current working directory
2. **Walks up** the directory tree looking for `.trinity/passport.json`
3. **Finds** (e.g.) `passport.json` at `src/aipass/sentry/.trinity/`
4. **Derives identity**: Branch name = "sentry", email = "@sentry"
5. **Uses correct sender**: Email sends FROM @sentry

#### Best Practice: Use Drone for AI_MAIL

**Recommended approach:**
```python
# Drone handles PWD detection automatically
import subprocess
subprocess.run(["drone", "email", "send", "@recipient", "Subject", "Message"])

# Drone:
# 1. Detects which branch is calling
# 2. Changes to that branch's directory
# 3. Invokes AI_MAIL from correct context
# 4. Email sends with proper identity
```

#### Direct Python Invocation (Advanced)

If calling AI_MAIL directly without Drone:

```python
import subprocess
from pathlib import Path

# Ensure you're in your branch directory
branch_dir = Path(__file__).parent.parent  # Adjust based on file depth
result = subprocess.run(
    ["drone", "@ai_mail", "send", "@recipient", "Subject", "Message"],
    cwd=str(branch_dir),  # Force working directory to branch root
    capture_output=True
)
```

**Key insight:** The `cwd=` parameter ensures AI_MAIL runs from the correct directory for PWD detection.

#### When to Use Which Approach

| Scenario | Recommended Approach | Why |
|----------|---------------------|-----|
| Simple email from module | `drone email send ...` | Drone handles context automatically |
| Email from handler | `drone email send ...` | Handlers shouldn't know branch structure |
| Complex automation | Direct call with `cwd=branch_dir` | Full control over context |
| Interactive scripts | Ensure `os.chdir(branch_dir)` first | Interactive sessions need explicit CWD |

#### Files Auto-Generated by AI_MAIL

When you call AI_MAIL from your branch directory, it auto-generates:

```
src/aipass/sentry/
├── .ai_mail.local/
│   ├── inbox.json                # Your inbox
│   └── sent/                     # Your sent folder
```

**Pattern:** Each branch gets its own isolated email configuration and mailbox.

---

### Future Context-Dependent Services

This PWD detection pattern will be used by other services that need per-branch configuration:

- **AI_MAIL**: Sender identity (current - implemented)
- **Future services**: Database configs, API keys, branch-specific settings

**Design principle:** Services that need "who am I?" should use PWD detection + auto-generated config pattern pioneered by AI_MAIL.

---

## Third-Party Libraries

**Philosophy:** Pragmatic - install what you need, when you need it

**No complex standards:**
- No version pinning requirements (yet)
- No requirements.txt management process (yet)
- Install as you build

**Workflow:**

1. **Build something** → See red squiggly lines in IDE
2. **Check import** → See what library is missing
3. **Install it** → `pip install library_name`
4. **Continue building**

**Example:**
```python
# Writing code
from questionary import select  # Red squiggly line
from rich.console import Console  # Red squiggly line

# Terminal
pip install questionary
pip install rich

# Back to coding - lines now work
```

**AI/Human split:**
- Sometimes AI handles imports and installs them
- Sometimes human sees console errors and installs
- 50-50 split, no rigid process
- Just get what's needed

**When packages aren't obvious:**
```bash
# Import name != package name sometimes
from PIL import Image  # Package is "pillow" not "PIL"
pip install pillow

# Ask for help if unclear
"I need to import X but not sure what package to install"
```

**Virtual environment:**
- AIPass is pip-installable: `pip install -e .`
- Shebang: `#!/usr/bin/env python3`
- All branches share the same package namespace
- Packages install once, available everywhere

---

## Standard Library Organization

**Group by category:**

```python
# File/path operations
from pathlib import Path
import os
import shutil

# Data handling
import json
from datetime import datetime

# Type hints
from typing import Dict, List, Optional, Tuple, Any

# System operations
import sys
import subprocess
```

**Alphabetical within categories:**
```python
# ✓ Good - grouped and alphabetical
from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Dict, List

# ✗ Bad - random order
import json
from pathlib import Path
from datetime import datetime
from typing import Dict
import shutil
```

**WHY:** Easy to scan, find duplicates, see what's imported at a glance

---

## Import Anti-Patterns

**Don't do these:**

```python
# ✗ Wildcard imports
from aipass.flow.apps.handlers.json import *  # What did I import? Who knows!

# ✗ Hardcoded paths
sys.path.insert(0, "/home/user/project")  # Breaks on other machines

# ✗ Relative imports
from ...handlers import something  # Hard to trace, confusing

# ✗ Import entire modules when you need one function
import aipass.sentry.apps.handlers.json.json_handler  # Long, repetitive
# Better:
from aipass.sentry.apps.handlers.json import json_handler

# ✗ Circular imports (handler imports module that imports handler)
# Module imports handler ✓
# Handler imports module ✗  # BREAKS INDEPENDENCE
```

---

## Quick Reference

| Import Type | Pattern | Required? |
|-------------|---------|-----------|
| Prax logger | `from aipass.prax import logger` | **When the file logs**; an unused one is not required |
| CLI service | `from aipass.cli import console, header` | When needed |
| API service | `from aipass.api import load_config` | When needed |
| Any other branch | `from aipass.<branch> import <name>` - never a path under its `apps/` | Always (front_door) |
| **Drone** | `subprocess.run(["drone", "cmd", ...])`; door names via `from aipass.drone import <name>` | **Routed via CLI first; never `aipass.drone.apps...`** |
| Standard lib | Grouped by category, alphabetical | Yes |
| Internal | Absolute imports (not relative) | Yes |
| Handler→Module | **FORBIDDEN** (breaks independence) | Never |

---

## Summary

**Import order:** Standard lib → Prax → Services → Internal

**Namespace pattern:** `from aipass.{module}...` - never bare imports or hardcoded paths

**Front door:** Another branch only as `from aipass.<branch> import <name>`; its `apps/` paths are convicted

**Prax logger:** Imported by every file that logs - `from aipass.prax import logger` or `from aipass import prax`; stdlib `logging` use fails, a file that never logs owes no import

**Service imports:** CLI, API, Memory imported as libraries; Drone routed via CLI first, door names via `from aipass.drone import <name>`

**Drone is special:** a command router first, with a package door. Never import from aipass.drone.apps...

**Handler independence:** Same-branch handler→handler ✓, Handler→service (Prax/CLI/API/Memory) ✓, Handler→own-branch-module ✗

**Third-party libraries:** Pragmatic approach - install what you need as you build

**Consistency:** Same patterns everywhere enables instant comprehension across entire system

---

## Bypass Rows

A row with no `lines` or `functions` waives the whole file. A scoped row waives sites. Each
`AIPASS_ROOT` read, `sys.path` hack, handler import of its own branch's modules and bare import is
its own site at its line; these sit in the import section (before the first `def` or `class`), so
their function is `<file>`. Each stdlib logging call is a site at its line, inside the function
that holds it (`<file>` at module level). A row with `"lines": [n]` waives the site on line n;
`"functions": ["load"]` waives the logging calls inside `load`; `"functions": ["<file>"]` waives
every module-level site. Import order is a relation between two lines, not one site: only a
`"functions": ["<file>"]` row waives it, and a `lines` row never does. Every site no row names
still convicts, and the message names the first open one.

---

## Comments

#@comments:2025-11-13:claude: Updated examples to use sentry/ instead of fictional old-name references
#@comments:2025-11-13:claude: Added Services import section (CLI) to match actual codebase patterns
#@comments:2025-11-13:claude: Toned down "critical" language around Prax to "nearly always" for accuracy
#@comments:2026-03-07:claude: Cleaned old references - updated to AIPass namespace imports, removed sys.path/AIPASS_ROOT patterns, fixed hardcoded home paths, old->sentry naming
#@comments:2026-03-08:claude: Resolved the user's "whole file needs updating" flag - fixed old branch names (3 occurrences), removed stale AIPASS_ROOT reference, corrected handler independence summary to reflect that handlers CAN import cross-branch services, bumped to Draft v2
#@comments:2026-03-31:claude: Cleaned stale references in comments and docs throughout sentry standards
