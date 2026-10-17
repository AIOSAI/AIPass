# =================== AIPass ====================
# Name: support_config_verbs.py
# Description: Shared helpers for the test_config_verbs files - the minted verbs world and the run/read helpers
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Helpers for tests/test_config_verbs*.py (no test_ prefix: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import importlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aipass.cli.apps.modules import display

# The registry is MINTED per test: the live one is gitignored and absent on a fresh clone.
# Mixed casing is deliberate: case-insensitive branch matching is under test.
_REGISTRY_BRANCHES = [
    {"name": "memory", "path": "src/aipass/memory", "status": "active"},
    {"name": "DEVPULSE", "path": "src/aipass/devpulse", "status": "active"},
    {"name": "DAEMON", "path": "src/aipass/daemon", "status": "active"},
]

# Wide enough that no sentence in this file can reach it. See _pin_console_width.
_CONSOLE_WIDTH = 300

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_HANDLER_MODULES = (
    "aipass.memory.apps.handlers.json",
    "aipass.memory.apps.handlers.json.json_handler",
    "aipass.memory.apps.handlers.json.config_loader",
)

_ROLLOVER_MODULE = "aipass.memory.apps.modules.rollover"
_ROLLOVER_CONFIG_MODULE = "aipass.memory.apps.modules.rollover_config"


def _pin_console_width(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin both shared consoles' `_width` (the setter would restore as 80) so a tmp path never folds."""
    for console_obj in (display.CONSOLE, display.err_console):
        monkeypatch.setattr(console_obj, "_width", _CONSOLE_WIDTH)


def _evict(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Drop *name* from the import cache, recorded first so teardown puts back exactly what stood there."""
    monkeypatch.setitem(sys.modules, name, None)
    del sys.modules[name]
    parent_name, _, leaf = name.rpartition(".")
    parent = sys.modules.get(parent_name)
    if parent is not None:
        monkeypatch.setattr(parent, leaf, None, raising=False)
        delattr(parent, leaf)


def _real_verbs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Real config_loader + rollover module wired to a MINTED config and registry.

    Config and per_branch come from the real writers; BOTH registry doors are shut; conftest's mocks are evicted.
    """
    for name in _HANDLER_MODULES:
        _evict(monkeypatch, name)
    config_loader = importlib.import_module("aipass.memory.apps.handlers.json.config_loader")

    # Captured BEFORE the repoint: TestOperatorConfigIsolation needs the real file's path.
    operator_config_path = config_loader._CONFIG_PATH

    config_path = tmp_path / "custom_config" / "memory.config.json"
    config_path.parent.mkdir(parents=True)
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", config_path)
    monkeypatch.setattr(config_loader, "json_handler", MagicMock())

    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps({"branches": _REGISTRY_BRANCHES}, indent=2), encoding="utf-8")
    monkeypatch.setattr(config_loader, "_find_repo_root", lambda: tmp_path)

    detector = importlib.import_module("aipass.memory.apps.handlers.monitor.detector")
    monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])
    monkeypatch.setattr(detector, "config_loader", config_loader)

    config_loader.load()
    pushed = config_loader.push_defaults_to_per_branch()
    assert pushed["success"], f"fixture could not write its own config: {pushed}"

    _evict(monkeypatch, _ROLLOVER_MODULE)
    rollover = importlib.import_module(_ROLLOVER_MODULE)
    monkeypatch.setattr(rollover, "json_handler", MagicMock())

    # rollover_config reads `json_handler` from its own globals and is not evicted: patch it too,
    # or config verbs log through the real service.
    rollover_config = importlib.import_module(_ROLLOVER_CONFIG_MODULE)
    monkeypatch.setattr(rollover_config, "json_handler", MagicMock())

    _pin_console_width(monkeypatch)

    return SimpleNamespace(
        rollover=rollover,
        loader=config_loader,
        detector=detector,
        path=config_path,
        operator_path=operator_config_path,
    )


def _run(verbs: SimpleNamespace, *args: str) -> bool:
    """Invoke `config <args>` exactly as the entry point routes it."""
    return verbs.rollover.handle_command("config", list(args))


def _streams(capsys: pytest.CaptureFixture) -> str:
    """Both streams joined and ANSI-stripped (FORCE_COLOR leaks attributes into captured streams)."""
    captured = capsys.readouterr()
    return _ANSI.sub("", captured.out + captured.err)


def _unwrapped(text: str) -> str:
    """All whitespace removed -- the only comparison that survives ANY wrap (Rich folds mid-token)."""
    return "".join(text.split())


def _run_rollover(verbs: SimpleNamespace, *args: str) -> bool:
    """Invoke `rollover <args>` exactly as the entry point routes it."""
    return verbs.rollover.handle_command("rollover", list(args))


def _rollover_section(verbs: SimpleNamespace) -> dict:
    """Read the rollover section straight off the throwaway file."""
    return json.loads(verbs.path.read_text(encoding="utf-8"))["rollover"]


def _raw_stdout(verbs: SimpleNamespace, capsys: pytest.CaptureFixture, *args: str) -> str:
    """Run `config <args>` and return stdout EXACTLY as it reached the pipe."""
    capsys.readouterr()
    _run(verbs, *args)
    return capsys.readouterr().out


def _payload(verbs: SimpleNamespace, capsys: pytest.CaptureFixture, *args: str) -> dict:
    """Run `config <args>` and parse the WHOLE of stdout as one document (@api pipes it into a parser)."""
    return json.loads(_raw_stdout(verbs, capsys, *args))
