# CLI

**Purpose:** Display and output formatting service for AIPass modules. Provides consistent terminal output — headers, success/error/warning messages, section breaks, and operation templates — so every module looks the same without duplicating Rich formatting code.
**Module:** `aipass.cli`
**Last Updated:** 2026-03-29

## Usage

```python
from aipass.cli import header, success, error, warning, section

header("Creating Branch", {"Name": "feature", "Type": "module"})
success("Files created", items=12, time="2.3s")
error("Path not found", suggestion="Check spelling")
warning("Config missing, using defaults")
section("Results")
```

### Operation Templates

```python
from aipass.cli import operation_start, operation_complete

operation_start("Processing", count=10)
# ... do work ...
operation_complete(created=5, skipped=3, failed=0)
```

### Direct Console Access

```python
from aipass.cli import console

console.print("[bold cyan]Custom Rich output[/bold cyan]")
```

## Architecture

```
cli/
├── apps/
│   ├── cli.py                  # Entry point
│   ├── modules/
│   │   ├── display.py          # header, success, error, warning, section
│   │   ├── templates.py        # operation_start, operation_complete
│   │   └── init_project.py     # aipass init command routing
│   └── handlers/
│       ├── init/               # Project bootstrap logic
│       │   └── bootstrap.py
│       └── json/               # JSON file management
│           └── json_handler.py
├── cli_json/                   # Auto-created JSON output (three-file pattern)
├── dropbox/                    # Inbound file drop
├── logs/                       # Branch-level logs
└── tests/
```

- `apps/modules/` — Public API. Import from here.
- `apps/handlers/` — Internal implementation. Don't import directly.

## Commands / Usage

```bash
# Via drone
drone @cli --help                        # Show services and Rich formatting showcase
drone @cli --version                     # Show version
drone @cli aipass                        # Show aipass subcommands
drone @cli aipass init                   # Bootstrap AIPass project in current dir
drone @cli aipass init /path             # Bootstrap in target directory
drone @cli aipass init /path MyProject   # Bootstrap with custom name
drone @cli aipass init --help            # Detailed init usage

# Standalone (no drone required)
python -m aipass.cli --help              # Same help output
python -m aipass.cli aipass init /path   # Bootstrap directly
```

---

## Integration Points

### Depends On
- `aipass.prax` — Logging via `system_logger`
- `rich` — Rich library for terminal formatting (Table, Panel, Columns, Text)
- Python stdlib (`sys`, `importlib`, `pathlib`)

### Provides To
- All modules — display formatting (headers, success/error/warning, section breaks)
- All modules — operation templates (`operation_start`, `operation_complete`)
- All modules — Rich console access
- All users — `aipass init` project bootstrap command

---

*Last Updated: 2026-03-17*
