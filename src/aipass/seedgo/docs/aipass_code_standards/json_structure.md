# JSON Structure Standards
**Status:** Production v2
**Date:** 2025-11-13

---

## The Three-JSON Pattern

**Every module gets three default JSON files:**
- `module_name_config.json` - Settings, configuration, limits
- `module_name_data.json` - Metrics, tracking data, current state
- `module_name_log.json` - Operations history (auto-rotating)

**Example:** drone_discovery module
```
drone_discovery_config.json
drone_discovery_data.json
drone_discovery_log.json
```

**Location patterns:**
- Seedgo modules: `src/aipass/seedgo/seedgo_json/`
- Branch modules: `src/aipass/{branch}/{branch}_json/`

---

## Why Three Files Instead of One?

**Different purposes, different needs:**

### 1. Different Growth Rates
- **Config:** Small, rarely changes (API keys, settings)
- **Data:** Medium, updates periodically (metrics, state)
- **Log:** Large, grows constantly (operations history)

**Problem with one file:** Logs explode in size, makes entire file huge and slow to read.

### 2. Different Use Cases
- **Config:** "What's the API key?" → Quick lookup
- **Data:** "What's current state?" → Check metrics
- **Log:** "What did it do?" → Review history

**Quick access:** Small focused files instead of searching massive JSON.

### 3. Fast Debugging
```
Something breaks:
1. Check config.json → see settings
2. Check data.json → see current state
3. Check log.json → see what it did
4. If need more → check Prax logs
```

**All without reading code or massive console output.**

---

## Setting Up json_handler.py (MANDATORY)

**When creating a new branch, json_handler.py MUST be configured correctly.**

### Critical Configuration Requirements

**Location:** `apps/handlers/json/json_handler.py` in your branch

**MUST update these constants (DO NOT copy seedgo's paths):**

```python
# ❌ WRONG - Points to seedgo
SEEDGO_ROOT = Path(__file__).parents[3]  # Points to seedgo branch
SEEDGO_JSON_DIR = SEEDGO_ROOT / "seedgo_json"
JSON_TEMPLATES_DIR = SEEDGO_ROOT / "apps" / "json_templates"

# ✓ CORRECT - Points to YOUR branch
API_ROOT = Path(__file__).parents[3]  # Points to api branch
API_JSON_DIR = API_ROOT / "api_json"
JSON_TEMPLATES_DIR = API_ROOT / "apps" / "json_templates"
```

### Step-by-Step Setup Checklist

**1. Update BRANCH_ROOT constant:**

⚠️ **CRITICAL: Must use `Path(__file__).parents[N]` for branch root discovery!**

AIPass uses relative path resolution, not hardcoded paths.

```python
# ❌ WRONG - Hardcoded path
API_ROOT = Path("/home/user/workspace/AIPass/src/aipass/api")

# ✓ CORRECT - Relative path resolution
API_ROOT = Path(__file__).parents[3]  # Adjust N based on handler depth
```

**Branch path patterns:**
```python
# All branches live under src/aipass/{branch}/
# Use Path(__file__).parents[N] to navigate up from handler location
{BRANCH}_ROOT = Path(__file__).parents[3]  # from apps/handlers/json/json_handler.py
```

**2. Update JSON_DIR constant:**
```python
# Pattern: {BRANCH}_JSON_DIR points to {branch}_json/
FLOW_JSON_DIR = FLOW_ROOT / "flow_json"
API_JSON_DIR = API_ROOT / "api_json"
DRONE_JSON_DIR = DRONE_ROOT / "drone_json"
```

**3. Update TEMPLATES_DIR constant:**
```python
# Point to YOUR branch templates, not SEED's
JSON_TEMPLATES_DIR = {BRANCH}_ROOT / "apps" / "json_templates"
```

**4. Create required directories:**
```bash
mkdir -p src/aipass/{branch}/{branch}_json
mkdir -p src/aipass/{branch}/apps/json_templates/default
```

**5. Copy templates from seedgo:**
```bash
cp src/aipass/seedgo/apps/standards/aipass/json_templates/default/*.json \
   src/aipass/{branch}/apps/json_templates/default/
```

### Validation

**Run standards checker on your json_handler.py:**
```bash
drone @seedgo audit {branch}
```

**Expected result:** 100/100 on JSON STRUCTURE standard

**If failing:**
- Check BRANCH_ROOT points to your branch (not "seedgo")
- Check JSON_DIR uses {branch}_json pattern
- Check TEMPLATES_DIR uses your branch templates

### Common Mistakes

1. **Using hardcoded paths instead of `Path(__file__).parents[N]`** ← Most common error!
   - Always use relative path resolution from the handler file
   - `BRANCH_ROOT = Path("/absolute/path/to/branch")` → FAILS
   - `BRANCH_ROOT = Path(__file__).parents[3]` → PASSES

2. **Copying seedgo's handler without changing paths**
   - API and Drone both made this mistake
   - Results in files created in wrong location

3. **Using SEEDGO_ROOT variable name in other branches**
   - Should be API_ROOT, FLOW_ROOT, DRONE_ROOT, etc.

4. **Pointing TEMPLATES_DIR to seedgo's templates**
   - Each branch needs its own template copies
   - Allows branch-specific template customization

5. **Wrong JSON directory naming**
   - Must use pattern: `{branch}_json/`
   - NOT `json/`, `seedgo_json/` (for non-seedgo branches)

6. **Importing Prax logger in handlers**
   - Handlers are tier 3 - no Prax imports allowed
   - Use silent error returns (return False/None) instead of logging

---

## Config Files

**Purpose:** Module settings, configuration, limits

**Real example from seedgo:**
```json
{
  "module_name": "seedgo",
  "version": "0.1.0",
  "created": "2025-11-12",
  "config": {
    "enabled": true,
    "log_level": "info",
    "max_log_entries": 100
  }
}
```

**What belongs here:**
- Module version and metadata
- Feature toggles (enabled/disabled)
- **Log management settings** (max_log_entries - critical!)
- Resource limits (max files, timeouts)
- API models (optional)

**Size:** Small, rarely changes (typically <1KB)

---

## Data Files

**Purpose:** Metrics, tracking data, current module state

**Real example from seedgo:**
```json
{
  "created": "2025-11-12",
  "last_updated": "2025-11-12",
  "metrics": {
    "operations_count": 0,
    "success_count": 0,
    "error_count": 0
  }
}
```

**What belongs here:**
- Timestamps (created, last_updated)
- Operation counts/metrics
- Success/failure tracking
- Current state/status
- Module-specific tracking data

**Size:** Medium, updates periodically (typically <10KB)

**Handler auto-updates:** `last_updated` field set automatically on save

---

## Log Files

**Purpose:** Operations history - what module did, when, result

**Real example from seedgo:**
```json
[
  {
    "timestamp": "2025-11-12T17:57:20.688755",
    "operation": "seedgo_startup",
    "data": {
      "modules_discovered": 6
    }
  },
  {
    "timestamp": "2025-11-13T00:22:22.793686",
    "operation": "seedgo_startup",
    "data": {
      "modules_discovered": 12
    }
  }
]
```

**Structure:** Array of entries (NOT object with "entries" key)

**What belongs here:**
- Timestamped operations
- Operation name/type
- Optional data dict with details
- Module-specific operation info

**Size:** Can grow large - **MUST be managed with auto-rotation**

**Handler behavior:** Automatically rotates when exceeds `max_log_entries` from config

---

## Log Management (Critical)

**Problem:** Logs grow unbounded → thousands of entries → hundreds of KB

**Real anti-patterns (as of 2025-11-08):**
```
drone_loader_log.json: 171KB (7,001 entries) ❌
drone_registry_log.json: 183KB (7,001 entries) ❌
```

**Solution: Config-controlled auto-rotation**

**In module config.json:**
```json
{
  "config": {
    "max_log_entries": 100
  }
}
```

**Handler implementation (automatic):**
```python
from aipass.seedgo.apps.handlers.json import json_handler

# Auto-detects module name, auto-rotates based on config
json_handler.log_operation("operation_name", {"key": "value"})
```

**How rotation works:**
1. Handler reads `max_log_entries` from config (default: 100)
2. After adding new entry, checks log length
3. If exceeds limit, keeps only most recent N entries
4. Older entries dropped (FIFO - first in, first out)

**Standard limits:**
- **100 entries** - default for most modules
- **50 entries** - minimal tracking needs
- **No limit** - custom JSONs only (NOT for default logs)

**Why 50-100 is enough:**
- Recent operations show current behavior
- Bugs visible in latest entries
- Full debugging → use Prax logs (detailed, managed separately)

---

## JSON Logs vs Prax Logs

**Two different logging systems:**

### JSON log.json Files
- **Structured operations history**
- Machine-readable (JSON format)
- Module lifecycle tracking
- "What did this module do?"
- Limited entries (50-100 max)

### Prax System Logs
- **Detailed debugging output**
- Human-readable text logs
- logger.info, logger.warning, logger.error
- "Why did it fail? Show me details"
- Full detail, managed by Prax tracks system

### Console Output
- **Critical info only**
- Keeps terminal clean
- "Module missing import, API key corrupt, no internet"
- Not for debugging details

**When to use each:**
1. **Quick check** → JSON log (recent operations)
2. **Detailed debugging** → Prax logs (full context)
3. **Live monitoring** → Prax watcher (real-time log tailing)
4. **Critical alerts** → Console (clean, focused)

---

## Registry JSONs

**Purpose:** Track collections of items (branches, handlers, modules)

**Real example: AIPASS_REGISTRY.json**
```json
{
  "metadata": {
    "version": "1.0.0",
    "last_updated": "2026-03-08",
    "total_branches": 15
  },
  "branches": {
    "flow": {
      "name": "flow",
      "path": "src/aipass/flow",
      "email": "@flow",
      "status": "active"
    },
    "seedgo": {
      "name": "seedgo",
      "path": "src/aipass/seedgo",
      "email": "@seedgo",
      "status": "active"
    }
  }
}
```
**Note:** `total_branches` is auto-computed by `setup.sh` — do not hardcode it manually. The count shown above is representative; the actual value reflects whatever branches are registered at build time.

**Registry characteristics:**
- **Central source of truth** for collections
- Used by DevPulse for branch management
- Used by Drone for command routing
- **Not part of three-JSON pattern** (special purpose)
- Typically located at system root level

**Other registries in use:**
- `src/aipass/drone/drone_json/drone_registry.json` - Drone commands
- `src/aipass/prax/prax_json/prax_registry.json` - Prax tracks

**When to create registry:**
- Need to track multiple related items
- Multiple modules need same lookup data
- Central coordination required across system

---

## Custom JSONs

**Beyond config/data/log - module-specific needs**

**Examples:**
- **Ignore patterns:** `module_ignore_patterns.json`
- **Summaries:** `plan_summaries.json` (Flow)
- **Templates:** Custom template configurations

**When to create custom JSON:**
- Data doesn't fit config/data/log pattern
- Specific functionality needs dedicated structure
- Could go in config but would bloat it

**Rule:** No limit on custom JSONs - create what module needs.

**But:** Always provide default three-JSON even if not all used. Consistency over optimization.

---

## Why This System Exists

**Before three-JSON:**
- Print statements everywhere
- Console spam (millions of lines)
- Hard to debug
- No state tracking
- "Where did it fail?" → hours of searching

**With three-JSON:**
- Console stays clean (critical info only)
- Quick debugging (check JSONs, see state/history)
- Structured data (machine and human readable)
- **Sources of truth** for module state
- Debugging in minutes, not hours

**Reality:**
- No test infrastructure yet (custom system, building from scratch)
- JSONs + logs = debugging infrastructure
- Fast iteration, manual testing
- Future: pytest framework

---

## Default Structure

**Every module gets minimum three files:**
```
module_name_config.json
module_name_data.json
module_name_log.json
```

**Even if not all used** - consistency matters.

**Some modules:**
- Heavy config, light data, minimal logs
- Light config, heavy data, huge logs
- All three heavily used

**Some don't use all three** - that's fine. They exist as defaults, use what's needed.

**Consistency = speed:**
- Know where to look
- Same structure everywhere
- Quick debugging across all branches

---

## Summary

**Three-JSON pattern:**
- config.json (settings) - small, stable
- data.json (state/metrics) - medium, periodic updates
- log.json (operations history) - large, **must be managed**

**Log management critical:**
- Max 50-100 entries
- Config-controlled limits
- Rotate old entries

**JSON logs vs Prax logs:**
- JSON = structured operations history
- Prax = detailed debugging output
- Console = critical info only

**Registries & custom JSONs:**
- Registry = central collection tracking
- Custom = module-specific needs
- No limit, create what's needed

**Why it works:**
- Fast debugging (check JSONs, see state instantly)
- Clean console (no spam)
- Structured data (sources of truth)
- Consistent across system

---

## Handler Auto-Detection Pattern

**Status:** ✅ Implemented Standard (2025-11-12)

### The Core Principle

**Modules should never pass their own name to handlers.**

Handlers use Python's `inspect.stack()` to automatically detect which module is calling them.

### Why Auto-Detection?

**Bad (manual name passing):**
```python
from aipass.seedgo.apps.handlers.json import json_handler

json_handler.log_operation(
    "imports_standard",  # ❌ Module has to know its own name
    "operation",
    {"data": "value"}
)
```

**Problems:**
- Typos possible (`"import_standard"` vs `"imports_standard"`)
- Doesn't auto-adapt when file renamed
- Extra boilerplate in every module
- Defeats the "just import and use" principle

**Good (auto-detection):**
```python
from aipass.seedgo.apps.handlers.json import json_handler

json_handler.log_operation(
    "operation",  # ✅ Handler figures out module name
    {"data": "value"}
)
```

**Benefits:**
- Zero typos (no manual name)
- Auto-adapts to file renames
- Minimal code (cleaner modules)
- "Import and use" - like Prax logger

### Implementation

**Handler side (json_handler.py):**

```python
import inspect
from pathlib import Path

def _get_caller_module_name() -> str:
    """Auto-detect calling module name from call stack"""
    try:
        stack = inspect.stack()
        # Skip frames: [0]=this function, [1]=log_operation, [2]=actual caller
        if len(stack) > 2:
            caller_frame = stack[2]
            caller_path = Path(caller_frame.filename)
            module_name = caller_path.stem  # "imports_standard" from "imports_standard.py"

            if module_name and not module_name.startswith('_'):
                return module_name

        return "unknown"
    except Exception as e:
        logger.error(f"Error detecting caller: {e}")
        return "unknown"

def log_operation(operation: str, data: Dict[str, Any] | None = None, module_name: str | None = None) -> bool:
    """
    Add entry to module log with automatic rotation

    Auto-detects calling module if module_name not provided.
    """
    # Auto-detect module name if not provided
    if module_name is None:
        module_name = _get_caller_module_name()

    ensure_module_jsons(module_name)
    # ... rest of function
```

**Module side:**

```python
# Standard imports
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.seedgo.apps.handlers.json import json_handler

def handle_command(command: str, args: List[str]) -> bool:
    # Just call - handler auto-detects we're "imports_standard"
    json_handler.log_operation(
        "standard_displayed",
        {"command": command}
    )
    return True
```

### Pattern for All Handlers

**Apply this to ANY handler that needs to know the caller:**

1. Import `inspect` and `Path`
2. Add `_get_caller_module_name()` helper function
3. Make `module_name` parameter optional (default `None`)
4. Auto-detect if not provided
5. Keep backward compatibility (explicit name still works)

**Example - increment_counter:**

```python
def increment_counter(counter_name: str, amount: int = 1, module_name: str | None = None) -> bool:
    """Increment counter - auto-detects module"""
    if module_name is None:
        module_name = _get_caller_module_name()

    ensure_module_jsons(module_name)
    # ... rest
```

### When to Use Auto-Detection

**Use auto-detection when:**
- Handler needs to create/manage module-specific files
- Handler needs to log caller identity
- Handler behavior changes based on caller

**Don't use auto-detection when:**
- Handler is pure utility (no caller-specific logic)
- Explicit parameter makes more sense (e.g., `validate_json(json_path)`)

### Testing Auto-Detection

**Verify it works:**

```bash
# Delete existing JSONs
rm -f /branch/branch_json/*.json

# Run module
python3 apps/modules/my_module.py

# Check created files - should match module name
ls /branch/branch_json/
# Expected: my_module_config.json, my_module_data.json, my_module_log.json
```

### Reference Implementation

**Primary handler:** `src/aipass/seedgo/apps/standards/aipass/handlers/json/json_handler.py`

**Branch implementations:**
- `src/aipass/drone/apps/handlers/json/json_handler.py`
- `src/aipass/prax/apps/handlers/json/json_handler.py`
- (Other branches follow same pattern)

**Status:** Production-ready, tested across seedgo and core branches

**Pattern established:** 2025-11-12

---

## Comments

#@comments:2025-11-13:claude: Updated markdown to reflect production reality - verified three-JSON pattern in use across seedgo and branches

#@comments:2025-11-13:claude: Confirmed auto-rotation implementation in seedgo handler (line 181-231 in json_handler.py)

#@comments:2025-11-13:claude: Drone logs still need fixing (171KB, 7001 entries) - demonstrates the problem this standard solves

#@comments:2025-11-13:claude: Log structure is array (not object with "entries" key) - corrected in examples

#@comments:2026-01-31:claude: Added critical warning about path resolution pattern requirement. Fixed 5 branches (API, DRONE, FLOW, BACKUP_SYSTEM, DEVPULSE) affected by this undocumented requirement.

#@comments:2026-03-07:claude: Cleaned Dev-Pass references - seed->seedgo naming, removed /home/aipass/ paths, Cortex->DevPulse, updated imports to aipass.* namespace, Path.home()->Path(__file__).parents[N]
