# =================== AIPass ====================
# Name: support_config_verbs.py
# Description: Shared helpers for the test_config_verbs files - the minted verbs world and the run/read helpers
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Helpers for tests/test_config_verbs*.py (no test_ prefix: never collected).

The minted config-and-registry world behind conftest's `verbs` fixture, and the
helpers two or more of the split config-verbs files use to run a verb and read
what it printed or wrote. Moved verbatim from test_config_verbs.py when it was
split by subject (2026-10-08).
"""

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

# The real display module, imported once at the top: nothing in the suite
# stands it in, conftest imports it the same way, and its consoles are patched
# at the edge (their width) per test.
from aipass.cli.apps.modules import display

# The registry these tests address, MINTED per test in tmp_path.
# AIPASS_REGISTRY.json is machine-managed and gitignored: on a fresh clone it
# does not exist at all, so a suite that read the live one proved only that
# THIS machine had already run AIPass. Mixed casing is deliberate -- the real
# registry carries lowercase and UPPERCASE names side by side, and
# case-insensitive branch matching is one of the things under test.
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


# ---------------------------------------------------------------------------
# Fixture: real modules, throwaway config
# ---------------------------------------------------------------------------


def _pin_console_width(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fix both shared Rich consoles at a known width.

    Rich resolves its width from the ENVIRONMENT -- a real terminal if there
    is one, else COLUMNS, else 80. These tests assert refusal sentences that
    carry a tmp path, and under an xdist worker that path is long enough that
    an 80-column console folds a newline INTO the sentence: the assertion then
    fails on output that is perfectly correct. Green on a dev machine with a
    wide terminal, red on a runner with none. @daemon paid for this twice on
    08-16 one layer along -- name the rendering explicitly, never let the shell
    decide it.

    `_width` and not the public `width` setter: these are module-global console
    objects shared with every other suite, and monkeypatch would restore
    `width` by writing back the number it read (80), leaving the console pinned
    for whoever ran next. `_width` starts as None and restores as None, and it
    is the attribute Console.size honours last.
    """
    for console_obj in (display.CONSOLE, display.err_console):
        monkeypatch.setattr(console_obj, "_width", _CONSOLE_WIDTH)


def _evict(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Drop *name* from the import cache, recorded first so teardown puts back exactly what stood there.

    The parent package's attribute goes the same way while the parent is still
    cached, because the re-import rebinds it. A bare pop left the fixture's
    re-imported json package, config_loader and rollover cached after teardown
    (seedgo module_eviction, 2026-09-15) - the species test_rollover.py's
    _import_rollover cured the same morning.
    """
    monkeypatch.setitem(sys.modules, name, None)
    del sys.modules[name]
    parent_name, _, leaf = name.rpartition(".")
    parent = sys.modules.get(parent_name)
    if parent is not None:
        monkeypatch.setattr(parent, leaf, None, raising=False)
        delattr(parent, leaf)


def _real_verbs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Real config_loader + rollover module wired to a MINTED config and registry.

    Hermetic on purpose: nothing here reads state that exists only on a machine
    someone has already run AIPass on.

      * The config is built from config_loader.DEFAULT_CONFIG -- the in-tree
        regeneration seed, kept in lockstep with the operator file by S193
        doctrine -- and written by the real writer, through load()'s
        regeneration of a missing file. A hand-formatted copy would make the
        no-op-set byte-identity test assert against this file's formatting
        instead of the writer's.
      * per_branch is filled by the real push_defaults_to_per_branch() reading the
        minted registry, so the fixture and the engine cannot disagree about
        the seeded shape.
      * BOTH registry doors are shut. detector._read_registry reads
        _REPO_ROOT/AIPASS_REGISTRY.json and then walks up from the caller's CWD
        for any other *_REGISTRY.json -- run from a checkout, that second door
        finds the fleet's own registry and the suite goes quietly non-hermetic.

    conftest replaces the handlers.json package with a MagicMock, which would
    make the lazy `from ... import config_loader` inside the module return a
    mock instead of the code under test. Evicting it forces a real import;
    :func:`_evict` records each eviction, so teardown restores what stood there.
    """
    for name in _HANDLER_MODULES:
        _evict(monkeypatch, name)
    config_loader = importlib.import_module("aipass.memory.apps.handlers.json.config_loader")

    # Captured BEFORE the repoint: the guard in TestOperatorConfigIsolation
    # needs to know where the real file would have been.
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

    # Minted through the public doors, in the order a fresh install meets them:
    # load() on a missing file regenerates DEFAULT_CONFIG, and the push fills
    # per_branch from the minted registry. Both write only the tmp path above.
    config_loader.load()
    pushed = config_loader.push_defaults_to_per_branch()
    assert pushed["success"], f"fixture could not write its own config: {pushed}"

    _evict(monkeypatch, _ROLLOVER_MODULE)
    rollover = importlib.import_module(_ROLLOVER_MODULE)
    monkeypatch.setattr(rollover, "json_handler", MagicMock())

    # The config verbs live in modules/rollover_config.py and read
    # `json_handler` from THEIR OWN module globals, so the patch above does not
    # reach them: without this second one, config get/set/set-default log
    # through the real service while the test believes it is sandboxed. That
    # module is NOT evicted with rollover -- the re-import above binds the same
    # cached object -- so patching it here is what makes the seam hold.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(verbs: SimpleNamespace, *args: str) -> bool:
    """Invoke `config <args>` exactly as the entry point routes it."""
    return verbs.rollover.handle_command("config", list(args))


def _streams(capsys: pytest.CaptureFixture) -> str:
    """Both streams joined and ANSI-stripped -- refusals to stderr, displays to stdout.

    Stripping is not cosmetic. FORCE_COLOR makes Rich emit attributes into a
    captured non-terminal stream, so `assert "[DEFAULT]" in out` passes in one
    shell and fails in the next on byte-identical code (@daemon, 08-16).
    """
    captured = capsys.readouterr()
    return _ANSI.sub("", captured.out + captured.err)


def _unwrapped(text: str) -> str:
    """All whitespace removed -- the only comparison that survives ANY wrap.

    A Rich fold can land mid-token (`custom_config` arrives as `custom_con` +
    newline + `fig`), so collapsing runs of whitespace is not enough. Used for
    the refusal sentences that carry a tmp path; the console width is pinned
    as well, and this is the belt to that pair of braces.
    """
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
    """Run `config <args>` and parse the WHOLE of stdout as one document.

    Deliberately not a substring search: a banner line, a stray trailing
    blank or a Rich-injected wrap all make json.loads fail right here --
    which is the contract, because @api pipes this straight into a parser.
    """
    return json.loads(_raw_stdout(verbs, capsys, *args))
