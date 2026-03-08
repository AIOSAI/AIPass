# DPLAN Files - Extracted from Dev-Pass

Extracted from Dev-Pass devpulse on 2026-03-08.

These files need adaptation for AIPass before use.

Original imports use `aipass_os.dev_central.devpulse` -- must be converted to `aipass.flow`.

## Source Location

```
/home/patrick/Projects/Dev-Pass/aipass_os/dev_central/devpulse/
```

## What Was Extracted

### Handler Files (apps/handlers/dplan/)
These were the `apps/handlers/plan/` handlers from Dev-Pass devpulse.
In Dev-Pass, the same `plan/` directory handled both DPLANs and FPLANs.
Here they are placed under `dplan/` to sit alongside Flow's existing `plan/` (FPLAN) handlers.

| File | Purpose |
|------|---------|
| `close.py` | DPLAN close operations (mark complete, archive) |
| `counter.py` | Plan numbering (sequential, multi-type DPLAN/BPLAN) |
| `create.py` | Plan file creation with template rendering |
| `dashboard.py` | DPLAN dashboard integration (counts, central push) |
| `display.py` | Help text and introspection |
| `list.py` | Plan listing with type/tag/status filters |
| `registry.py` | DPLAN registry and summaries (JSON persistence) |
| `status.py` | Status extraction from plan files (checkboxes) |
| `template.py` | Template loading and rendering (DPLAN + BPLAN) |

### Module Files (apps/modules/)
| File | Original Name | Purpose |
|------|---------------|---------|
| `dplan_flow.py` | `dev_flow.py` | Main DPLAN orchestrator module (thin orchestrator pattern) |
| `dplan_post_close_runner.py` | `post_close_runner.py` | Background post-close processing (Memory Bank archival) |

### Templates (templates/)
| File | Purpose |
|------|---------|
| `dplan_default.md` | Default DPLAN template with sections: Vision, Current State, What Needs Building, Design Decisions, etc. |
| `bplan_default.md` | Default BPLAN (business plan) template with sections: Executive Summary, Market Analysis, Revenue Model, etc. |

### JSON Data (flow_json/)
These are reference data files from the Dev-Pass environment. They contain Dev-Pass-specific plan data
and should be treated as structural examples, not live data.

| File | Purpose |
|------|---------|
| `dplan_registry.json` | Registry of all DPLANs with metadata (47 plans from Dev-Pass) |
| `dplan_summaries.json` | Cached AI-generated summaries for closed plans |

## Key Differences from FPLANs

- **DPLANs** are design/planning documents (what to build, why, design decisions)
- **FPLANs** are build/execution plans (how to build it, steps, acceptance criteria)
- **BPLANs** are business plans (market analysis, revenue model, go-to-market)
- DPLANs typically transition to FPLANs when "Ready for Execution"

## Import Conversions Needed

All files currently use Dev-Pass import patterns that must be changed:

```python
# OLD (Dev-Pass)
from aipass_os.dev_central.devpulse.apps.handlers.plan.create import create_plan
from prax.apps.modules.logger import system_logger as logger
from cli.apps.modules import console, header, success, error

# NEW (AIPass) -- needs to be determined by Flow
from aipass.flow.apps.handlers.dplan.create import create_plan
# Logger and CLI imports TBD
```

## Hardcoded Paths to Fix

Several files reference Dev-Pass paths:
- `Path.home() / "aipass_os" / "dev_central" / "dev_planning"` -- plan storage root
- `Path.home() / "aipass_core" / "backup_system" / "processed_plans"` -- archive dir
- `Path.home() / "aipass_os" / "AI_CENTRAL"` -- central dashboard
- `Path.home() / "BRANCH_REGISTRY.json"` -- branch resolution
- Shebang lines: `#!/home/aipass/.venv/bin/python3`
