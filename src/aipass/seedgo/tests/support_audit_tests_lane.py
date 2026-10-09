# =================== AIPass ====================
# Name: support_audit_tests_lane.py
# Description: Shared builders for the audit-tests lane test files (split from test_audit_tests_lane.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Shared helpers for the tests of apps/handlers/audit_tests/ and the pytest pack (not test_: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

from pathlib import Path

from aipass.seedgo.apps.handlers.tests_pytest_standards import envcopy


def _records(*, hook=True, canary_caught=True, violations=0, order=None):
    """A synthetic run's records, shaped exactly as the payload writes them."""
    records = [{"rec": "header", "hook_installed": hook, "allowances": [], "observed_events": ["open"]}]
    records.append({"rec": "copy_check", "verified_live": True, "resolved_to": "/env/pkg/__init__.py"})
    for index in range(violations):
        records.append(
            {
                "rec": "violation",
                "nodeid": f"tests/test_x.py::test_{index}",
                "phase": "call",
                "event": "open",
                "path": f"/real/state_{index}.json",
                "count": 1,
                "where": "outside_copy",
            }
        )
    records.append(
        {
            "rec": "summary",
            "canary": {"attempted": True, "caught": canary_caught, "path": "/env/c", "error": ""},
            "executed_order": list(order or []),
            "child_processes_spawned": 0,
            "sqlite3_connections": {"file_backed": 0, "memory": 0, "read_only": 0},
        }
    )
    return records


def _spec_for(env_root: Path) -> envcopy.EnvSpec:
    """A minimal EnvSpec pointing at a scratch root."""
    return envcopy.EnvSpec(
        layout="plain",
        env_root=env_root,
        run_cwd=env_root,
        target_copy=env_root / "t",
        target_module="",
        test_arg="t",
        python=Path("/usr/bin/python3"),
        pythonpath=str(env_root),
        plugin_dir=env_root / "_audit_plugin",
        log_path=env_root / "_audit" / "hygiene.jsonl",
    )
