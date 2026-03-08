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

# Prax logger (system-wide - nearly always imported)
from aipass.prax.apps.modules.logger import system_logger as logger

# Services (CLI, etc.)
from aipass.cli.apps.modules import console, header, success, error

# Internal/local imports
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.domain1 import ops
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
from aipass.{module}.apps.modules.{name} import something
from aipass.{module}.apps.handlers.{domain} import handler
```

**WHY namespace imports:**
- Works across all environments (pip-installed package)
- No `sys.path` manipulation needed
- Explicit, traceable import paths

**Where it's used:**
```python
# Cross-branch service imports
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, header

# Internal branch imports
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.flow.apps.modules.plans import create_plan
```

**Consistency rule:** Always use `from aipass.{module}...`, never bare imports like `from prax...`

---

## No sys.path Setup Needed

AIPass is a pip-installable package. All imports use the `aipass.*` namespace and resolve automatically via the installed package.

```python
# No sys.path manipulation required
# Just import directly:
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.seedgo.apps.handlers.json import json_handler
```

**Install for development:**
```bash
pip install -e .
```

This registers the `aipass` namespace so all `from aipass.{module}...` imports work from anywhere.

---

## Prax Logger Import (Nearly Always)

**The most common import in the system:**

```python
from aipass.prax.apps.modules.logger import system_logger as logger
```

**WHY Prax is important:**
- **System-wide logging** for all branches that subscribe
- **Service provider model** - Prax provides logging as a service
- **Consistent import pattern** - Same everywhere for easy recognition
- **Nearly universal** - Used in almost every module and handler

**Usage:**
```python
logger.info("Branch created successfully")
logger.warning("Memory file not found, using defaults")
logger.error("Failed to backup branch", exc_info=True)
```

**Both forms are valid:**
```python
# Canonical (full path)
from aipass.prax.apps.modules.logger import system_logger as logger

# Shorthand (via prax/__init__.py)
from aipass.prax import logger

# Never these
import aipass.prax.system_logger  # ✗
import logging; logging.getLogger()  # ✗ Use prax, not stdlib logging
```

**Output location:** Prax manages log files, branches don't need to worry about where logs go

---

## Handler Independence Import Rule

**Core rule:** Handlers CANNOT import from parent branch modules

**Example - Seedgo:**

```python
# ✓ ALLOWED - Handler imports another handler
# seedgo/apps/handlers/domain1/ops.py
from aipass.seedgo.apps.handlers.json import json_handler

# ✓ ALLOWED - Handler imports standard library
import json
from pathlib import Path

# ✓ ALLOWED - Handler imports Prax service
from aipass.prax.apps.modules.logger import system_logger as logger

# ✓ ALLOWED - Handler imports CLI service
from aipass.cli.apps.modules import console, error

# ✗ FORBIDDEN - Handler imports parent module
from aipass.seedgo.apps.modules.create_thing import something  # BREAKS INDEPENDENCE
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
# In seedgo/apps/modules/create_thing.py
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.domain1 import ops
```

**From handlers to handlers (within same branch):**
```python
# In seedgo/apps/handlers/domain1/ops.py
from aipass.seedgo.apps.handlers.json import json_handler
```

**Cross-branch service imports:**
```python
# Services can be imported anywhere (modules or handlers)
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, header, success, error
```

**Relative imports (avoided):**
```python
# ✗ Don't use relative imports
from ...handlers.json import json_handler  # Confusing, hard to trace

# ✓ Use absolute namespace imports
from aipass.seedgo.apps.handlers.json import json_handler  # Clear, explicit
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

**Router Services (CLI Invocation Only):**
- **Drone** - NOT a library service, it's a CLI router
  - Resolves `@` targets before passing commands to branches
  - Branches NEVER import from `aipass.drone.apps.modules`
  - Invoked via subprocess: `subprocess.run(["drone", "command", ...])`

### Context-Independent Services (Import & Use Anywhere)

**These services work from any location:**

```python
# Prax Logger - context-independent
from aipass.prax.apps.modules.logger import system_logger as logger
logger.info("Works from anywhere")

# CLI Services - context-independent
from aipass.cli.apps.modules import console, header
console.print("Works from anywhere")
```

**Why they work anywhere:** These services don't need to know who's calling them. They provide generic functionality.

### Drone: CLI Router Pattern (NOT for Import)

**Drone is NOT a library service.** It's a CLI router that:
1. Resolves `@` targets to actual branch paths
2. Routes commands to the appropriate branch
3. Handles context switching and invocation

**✓ CORRECT - Invoke Drone as CLI:**
```python
import subprocess

# Drone resolves @ and routes the command
subprocess.run(["drone", "email", "send", "@recipient", "Subject", "Message"])
subprocess.run(["drone", "log", "show"])
subprocess.run(["drone", "@seedgo", "some-command"])
```

**✗ FORBIDDEN - Never import from Drone:**
```python
# ✗ WRONG - Drone is not a library service
from aipass.drone.apps.modules import resolve_target  # NO!
from aipass.drone.apps.modules.router import route_command  # NO!

# Branches should NOT handle @ resolution themselves
# That's Drone's job - it resolves @ before passing to branches
```

**Why Drone is different:**
- **Prax/CLI/API/Memory**: Library services providing functionality via imports
- **Drone**: CLI router that resolves targets and invokes other tools
- Branches receive already-resolved paths/commands from Drone
- Branches don't need @ handling code - Drone does that BEFORE calling them

---

### Context-Dependent Services (PWD Detection Required)

**AI_MAIL** uses PWD (Present Working Directory) detection to determine sender identity and configuration. This means **you must invoke AI_MAIL from your branch directory** for proper operation.

#### The Pattern: Call from Branch Directory

```python
# ✓ CORRECT - Call from your branch directory
# Working dir: src/aipass/seedgo/

import subprocess
subprocess.run(["drone", "@ai_mail", "send", "@drone", "Subject", "Message"])

# AI_MAIL walks up from your CWD, finds branch identity, knows you're @seedgo
# Your email sends FROM @seedgo (not @devpulse or @ai_mail)
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
3. **Finds** (e.g.) `passport.json` at `src/aipass/seedgo/.trinity/`
4. **Derives identity**: Branch name = "seedgo", email = "@seedgo"
5. **Uses correct sender**: Email sends FROM @seedgo

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
src/aipass/seedgo/
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
import aipass.seedgo.apps.handlers.json.json_handler  # Long, repetitive
# Better:
from aipass.seedgo.apps.handlers.json import json_handler

# ✗ Circular imports (handler imports module that imports handler)
# Module imports handler ✓
# Handler imports module ✗  # BREAKS INDEPENDENCE
```

---

## Quick Reference

| Import Type | Pattern | Required? |
|-------------|---------|-----------|
| Prax logger | `from aipass.prax.apps.modules.logger import system_logger as logger` or `from aipass.prax import logger` | **Nearly always** |
| CLI service | `from aipass.cli.apps.modules import console, header` | When needed |
| API service | `from aipass.api.apps.modules import llm_call` | When needed |
| **Drone** | `subprocess.run(["drone", "cmd", ...])` | **CLI only - NEVER import** |
| Standard lib | Grouped by category, alphabetical | Yes |
| Internal | Absolute imports (not relative) | Yes |
| Handler→Module | **FORBIDDEN** (breaks independence) | Never |

---

## Summary

**Import order:** Standard lib → Prax → Services → Internal

**Namespace pattern:** `from aipass.{module}...` - never bare imports or hardcoded paths

**Prax logger:** Nearly always imported - canonical or shorthand form both valid

**Service imports:** CLI, API, Memory imported as libraries; Drone invoked via CLI only

**Drone is special:** NOT a library service - it's a CLI router. Never import from aipass.drone.apps.modules

**Handler independence:** Same-branch handler→handler ✓, Handler→service (Prax/CLI/API/Memory) ✓, Handler→own-branch-module ✗

**Third-party libraries:** Pragmatic approach - install what you need as you build

**Consistency:** Same patterns everywhere enables instant comprehension across entire system

---

## Comments

#@comments:2025-11-13:claude: Updated examples to use seedgo/ instead of fictional cortex/ references
#@comments:2025-11-13:claude: Added Services import section (CLI) to match actual codebase patterns
#@comments:2025-11-13:claude: Toned down "critical" language around Prax to "nearly always" for accuracy
#@comments:2025-11-29:claude: Added Service Categories section clarifying Drone is NOT a library service
#@comments:2025-11-29:claude: Added explicit "Drone: CLI Router Pattern" section with FORBIDDEN import examples
#@comments:2025-11-29:claude: Clarified that branches should NEVER import from aipass.drone.apps.modules - Drone resolves @ before calling them
#@comments:2026-03-07:claude: Cleaned Dev-Pass references - updated to AIPass namespace imports, removed sys.path/AIPASS_ROOT patterns, fixed /home/aipass/ paths, seed->seedgo naming
#@comments:2026-03-08:claude: Resolved patrick's "whole file needs updating" flag - fixed Memory Bank→Memory (3 occurrences), removed stale AIPASS_ROOT reference, corrected handler independence summary to reflect that handlers CAN import cross-branch services, bumped to Draft v2
