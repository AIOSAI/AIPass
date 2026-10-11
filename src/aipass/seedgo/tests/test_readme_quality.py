# =================== AIPass ====================
# Name: test_readme_quality.py
# Description: Tests for readme_quality_check.py
# Version: 1.0.2
# Created: 2026-07-17
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/aipass_standards/readme_quality_check.py — README content quality from a stranger's view."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that readme_quality_check.py parses and imports

from pathlib import Path

import pytest
from unittest.mock import MagicMock

from aipass.seedgo.apps.handlers.aipass_standards import readme_quality_check
from aipass.seedgo.apps.handlers.bypass import utils as _bypass_utils


@pytest.fixture(autouse=True)
def _pin_bypass_log(monkeypatch):
    """Point is_bypassed's json_handler at a mock for every test here.

    The bypass tests call the real is_bypassed, which appends to the
    repo-tracked seedgo_json/utils_log.json via the json_handler global in
    its OWN module -- xdist workers racing on that shared file corrupt it
    (JSONDecodeError: Extra data). sys.modules patching never reaches a
    function's globals, so the pin must land on the utils module object.
    """
    mock_handler = MagicMock()
    mock_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(_bypass_utils, "json_handler", mock_handler)


def _branch_with_readme(tmp_path, readme_content, branch_name="mybranch"):
    """Create a branch directory with apps/branch.py and README.md."""
    branch_dir = tmp_path / branch_name
    branch_dir.mkdir()
    apps_dir = branch_dir / "apps"
    apps_dir.mkdir()
    entry = apps_dir / f"{branch_name}.py"
    entry.write_text("def main(): pass\n", encoding="utf-8")

    readme = branch_dir / "README.md"
    readme.write_text(readme_content, encoding="utf-8")

    return str(entry)


# ============================================================
# Skip / edge cases
# ============================================================


def test_init_file_skipped(tmp_path):
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    f = apps_dir / "__init__.py"
    f.write_text("# init\n", encoding="utf-8")
    result = readme_quality_check.check_module(str(f))
    assert result["passed"] is True
    assert result["score"] == 100


def test_no_readme(tmp_path):
    branch_dir = tmp_path / "mybranch"
    branch_dir.mkdir()
    apps_dir = branch_dir / "apps"
    apps_dir.mkdir()
    f = apps_dir / "mybranch.py"
    f.write_text("def main(): pass\n", encoding="utf-8")
    result = readme_quality_check.check_module(str(f))
    assert result["passed"] is False
    assert result["score"] == 0
    assert all(not c["passed"] for c in result["checks"])


# ============================================================
# Good README — all checks pass
# ============================================================

GOOD_README = """# MyBranch

A tool that processes data files and generates reports for the AIPass ecosystem.

## Quick Start

```bash
drone @mybranch process data.csv
drone @mybranch report --format html
```

## Commands

| Command | Description |
|---------|-------------|
| process | Process input files |
| report  | Generate reports |
"""


def test_good_readme_passes_all(tmp_path):
    path = _branch_with_readme(tmp_path, GOOD_README)
    result = readme_quality_check.check_module(path)
    assert result["passed"] is True
    assert result["score"] == 100
    names = {c["name"] for c in result["checks"] if c["passed"]}
    assert "quick_start" in names
    assert "stranger_accessible" in names
    assert "what_description" in names


# ============================================================
# Missing Quick Start
# ============================================================

NO_QUICKSTART = """# MyBranch

A useful tool for data processing.

## Commands

```bash
drone @mybranch do-stuff
```
"""


def test_missing_quick_start(tmp_path):
    path = _branch_with_readme(tmp_path, NO_QUICKSTART)
    result = readme_quality_check.check_module(path)
    checks = {c["name"]: c["passed"] for c in result["checks"]}
    assert checks["quick_start"] is False
    assert checks["what_description"] is True


# ============================================================
# Quick Start without code block
# ============================================================

QUICKSTART_NO_CODE = """# MyBranch

Something useful.

## Quick Start

Run the command to get started. See the docs for more info.
"""


def test_quick_start_no_code_fails(tmp_path):
    path = _branch_with_readme(tmp_path, QUICKSTART_NO_CODE)
    result = readme_quality_check.check_module(path)
    checks = {c["name"]: c["passed"] for c in result["checks"]}
    assert checks["quick_start"] is False


# ============================================================
# Quick Start with code block passes
# ============================================================

QUICKSTART_WITH_CODE = """# MyBranch

Something useful.

## Quick Start

```
mybranch run
```
"""


def test_quick_start_with_code_passes(tmp_path):
    path = _branch_with_readme(tmp_path, QUICKSTART_WITH_CODE)
    result = readme_quality_check.check_module(path)
    checks = {c["name"]: c["passed"] for c in result["checks"]}
    assert checks["quick_start"] is True


# ============================================================
# Getting Started variant accepted
# ============================================================

GETTING_STARTED = """# MyBranch

Does things.

## Getting Started

```bash
mybranch init
```
"""


def test_getting_started_accepted(tmp_path):
    path = _branch_with_readme(tmp_path, GETTING_STARTED)
    result = readme_quality_check.check_module(path)
    checks = {c["name"]: c["passed"] for c in result["checks"]}
    assert checks["quick_start"] is True


# ============================================================
# Stranger accessible — too many internal names
# ============================================================

TOO_MANY_INTERNALS = """# MyBranch

Integrates with drone for routing, devpulse for orchestration,
and seedgo for standards compliance. Uses prax for logging.
"""


def test_too_many_internal_names_fails(tmp_path):
    path = _branch_with_readme(tmp_path, TOO_MANY_INTERNALS)
    result = readme_quality_check.check_module(path)
    checks = {c["name"]: c for c in result["checks"]}
    assert checks["stranger_accessible"]["passed"] is False
    assert "drone" in checks["stranger_accessible"]["message"]


# ============================================================
# Stranger accessible — within limit
# ============================================================

FEW_INTERNALS = """# MyBranch

A data processing tool for AIPass. Uses drone for command routing.

## Quick Start

```
drone @mybranch process
```
"""


def test_few_internal_names_passes(tmp_path):
    path = _branch_with_readme(tmp_path, FEW_INTERNALS)
    result = readme_quality_check.check_module(path)
    checks = {c["name"]: c["passed"] for c in result["checks"]}
    assert checks["stranger_accessible"] is True


# ============================================================
# Stranger accessible — aipass project name excluded
# ============================================================

AIPASS_PROJECT_NAME = """# MyBranch

Standards compliance platform for AIPass. Audits all agents
against code standards and reports violations.

## Quick Start

```
drone @mybranch audit
```
"""


def test_aipass_project_name_not_counted(tmp_path):
    path = _branch_with_readme(tmp_path, AIPASS_PROJECT_NAME)
    result = readme_quality_check.check_module(path)
    checks = {c["name"]: c["passed"] for c in result["checks"]}
    assert checks["stranger_accessible"] is True


# ============================================================
# Invoke match — correct branch
# ============================================================

INVOKE_MATCH = """# mybranch

Does things.

## Invoke

```
drone @mybranch command
```

## Quick Start

```
drone @mybranch start
```
"""


def test_invoke_matches_branch(tmp_path):
    path = _branch_with_readme(tmp_path, INVOKE_MATCH, branch_name="mybranch")
    result = readme_quality_check.check_module(path)
    checks = {c["name"]: c["passed"] for c in result["checks"]}
    assert checks["invoke_match"] is True


# ============================================================
# Invoke match — wrong branch
# ============================================================

INVOKE_MISMATCH = """# mybranch

Does things.

## Invoke

```
drone @otherbranch command
```

## Quick Start

```
drone @mybranch start
```
"""


def test_invoke_wrong_branch_fails(tmp_path):
    path = _branch_with_readme(tmp_path, INVOKE_MISMATCH, branch_name="mybranch")
    result = readme_quality_check.check_module(path)
    checks = {c["name"]: c["passed"] for c in result["checks"]}
    assert checks["invoke_match"] is False


# ============================================================
# No invoke section — skipped (passes)
# ============================================================

NO_INVOKE = """# mybranch

Does things.

## Quick Start

```
drone @mybranch command
```
"""


def test_no_invoke_section_skipped(tmp_path):
    path = _branch_with_readme(tmp_path, NO_INVOKE, branch_name="mybranch")
    result = readme_quality_check.check_module(path)
    checks = {c["name"]: c for c in result["checks"]}
    assert checks["invoke_match"]["passed"] is True
    assert "skipped" in checks["invoke_match"]["message"].lower()


# ============================================================
# What description — present
# ============================================================


def test_description_in_first_10_lines(tmp_path):
    readme = "# Branch\n\nThis tool processes data and generates comprehensive reports.\n"
    path = _branch_with_readme(tmp_path, readme)
    result = readme_quality_check.check_module(path)
    checks = {c["name"]: c["passed"] for c in result["checks"]}
    assert checks["what_description"] is True


# ============================================================
# What description — missing (only short lines)
# ============================================================


def test_no_description_fails(tmp_path):
    readme = "# Branch\n\nv1.0\nTODO\n\n---\n\n## Stuff\n"
    path = _branch_with_readme(tmp_path, readme)
    result = readme_quality_check.check_module(path)
    checks = {c["name"]: c["passed"] for c in result["checks"]}
    assert checks["what_description"] is False


# ============================================================
# Bypass
# ============================================================


def test_bypass_passes(tmp_path):
    path = _branch_with_readme(tmp_path, "# Bad\n\nNo content.\n")
    bypass = [{"standard": "readme_quality", "file": Path(path).as_posix()}]
    result = readme_quality_check.check_module(path, bypass_rules=bypass)
    assert result["passed"] is True
    assert result["score"] == 100


# ============================================================
# Real entry point validation
# ============================================================


def test_seedgo_readme_passes():
    _root = Path(__file__).resolve().parents[1]
    path = str(_root / "apps" / "seedgo.py")
    result = readme_quality_check.check_module(path)
    assert result["passed"] is True, (
        f"seedgo README should pass readme_quality: {[c for c in result['checks'] if not c['passed']]}"
    )
    assert result["score"] == 100


def test_uppercase_registry_name_lowercase_path(tmp_path):
    """Regression: uppercase registry name (BACKUP) with lowercase filesystem path
    must resolve correctly — branch_name derived from directory, not registry."""
    readme = """# Backup

A tool for managing automated backups across all AIPass branches.

## Quick Start

```bash
drone @backup snapshot
drone @backup restore latest
```
"""
    path = _branch_with_readme(tmp_path, readme, branch_name="backup")
    result = readme_quality_check.check_module(path)
    assert result["passed"] is True
    assert result["score"] == 100
