# =================== AIPass ====================
# Name: support_edit_gate_trinity.py
# Description: Helpers shared by the edit_gate .trinity test files: cap tables, hook data, the import seam routers
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Helpers for the edit_gate .trinity tests (no test_ prefix: never collected)."""

# Shared by test_edit_gate_trinity.py and its _write, _edit, _tripwire and
# _refusals siblings, all of apps/handlers/security/edit_gate.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import importlib
from unittest.mock import MagicMock, patch

from aipass.hooks.apps.handlers.security import edit_gate
from aipass.memory.apps.modules import door_entry_limits as memory_entry_limits


_TEST_LIMITS_WARN = {
    "enabled": True,
    "enforce": False,
    "entry_types": {
        "key_learnings": {
            "file": "local.json",
            "container": "key_learnings",
            "kind": "dict",
            "field": "value",
            "max_chars": 200,
        },
        "sessions": {
            "file": "local.json",
            "container": "sessions",
            "kind": "list",
            "field": "summary",
            "max_chars": 300,
        },
        "todos": {
            "file": "local.json",
            "container": "todos",
            "kind": "list",
            "field": "task",
            "max_chars": 200,
        },
        "observations": {
            "file": "observations.json",
            "container": "observations",
            "kind": "list",
            "field": "note",
            "max_chars": 600,
        },
    },
}

_TEST_LIMITS_ENFORCE = {**_TEST_LIMITS_WARN, "enforce": True}

_TEST_LIMITS_DISABLED = {**_TEST_LIMITS_WARN, "enabled": False}


def _make_trinity_path(tmp_path, branch="hooks", filename="local.json"):
    """Build a .trinity file path with proper src/aipass/<branch>/.trinity/ structure."""
    trinity_dir = tmp_path / "src" / "aipass" / branch / ".trinity"
    trinity_dir.mkdir(parents=True, exist_ok=True)
    return str(trinity_dir / filename)


def _hook_data(file_path, content=None, tool_name="Write", cwd=None, **extra_input):
    """Build a hook_data dict for edit_gate.handle()."""
    tool_input = {"file_path": file_path}
    if content is not None:
        tool_input["content"] = content
    tool_input.update(extra_input)
    data = {
        "tool_name": tool_name,
        "tool_input": tool_input,
    }
    if cwd:
        data["cwd"] = cwd
    return data


def _mock_entry_limits(limits):
    """Create a mock module with controlled limits and real changed_entries."""
    el = memory_entry_limits
    mock_module = MagicMock()
    mock_module.load_entry_limits.return_value = limits
    mock_module.changed_entries = el.changed_entries
    return mock_module


_ROLLOVER_CONFIG_10 = {
    "rollover": {
        "defaults": {
            "local": {
                "sessions": {"count": 20},
                "key_learnings": {"count": 25},
                "todos": {"count": 10},
            },
            "observations": {
                "observations": {"count": 15},
            },
        },
        "per_branch": {},
    },
}


# The real importer the routers below fall through to. While the tests patched
# importlib.import_module itself, a call by name there re-entered the patch and
# recursed; the routers now stand at the gate's seam, so importlib stays real.
_REAL_IMPORT_MODULE = importlib.import_module


def _imports_via_seam(side_effect):
    """Route the gate's call-time imports through its own seam, edit_gate._import_module.

    Patching importlib.import_module replaced it process-wide: every module the
    handler reached (and pytest itself) drew the mock. The seam is the gate's alone.
    """
    return patch.object(edit_gate, "_import_module", side_effect=side_effect)


_OWNERSHIP_MODULE = "aipass.hooks.apps.modules.write_ownership"


def _fence_real(mock):
    """Answer *mock* for every import except the ownership fence, which stays real.

    These patches answered one mock for EVERY call-time import. That was harmless
    while the Edit lane made no other import before the caps; since 2026-09-18 the
    ownership fence is reached that way first, and a mocked fence is no fence.
    """
    return lambda name: _REAL_IMPORT_MODULE(name) if name == _OWNERSHIP_MODULE else mock


def _mock_importlib_modules(limits, rollover_cfg=None):
    """Return a side_effect for importlib.import_module supporting both modules."""
    el_real = _REAL_IMPORT_MODULE("aipass.memory.apps.modules.door_entry_limits")

    entry_limits_mock = MagicMock()
    entry_limits_mock.load_entry_limits.return_value = limits
    entry_limits_mock.changed_entries = el_real.changed_entries
    # The shape reader and the file budgets stay REAL. A MagicMock answers an
    # empty iterator for both, which reads as "measures clean" — the one answer
    # a size gate must never invent (FPLAN-0593: the passport row is measured
    # against @memory's published 6,000/600, not against a stand-in).
    entry_limits_mock.fields_for = el_real.fields_for
    entry_limits_mock.check_file_budget = el_real.check_file_budget

    config_loader_mock = MagicMock()
    cfg = rollover_cfg if rollover_cfg is not None else _ROLLOVER_CONFIG_10
    config_loader_mock.load.return_value = cfg
    config_loader_mock.section.side_effect = lambda name: cfg.get(name, {})
    # memory's real resolver over the test's rollover section: no I/O when the
    # section is passed, so the pad count is exactly what memory's roll applies.
    cl_real = _REAL_IMPORT_MODULE("aipass.memory.apps.modules.door_config_loader")
    config_loader_mock.get_todos_count.side_effect = lambda branch: cl_real.get_todos_count(
        branch, cfg.get("rollover", {})
    )

    def side_effect(name):
        if "entry_limits" in name:
            return entry_limits_mock
        if "config_loader" in name:
            return config_loader_mock
        return _REAL_IMPORT_MODULE(name)

    return side_effect
