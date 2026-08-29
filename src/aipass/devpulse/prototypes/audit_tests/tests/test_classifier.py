# =================== AIPass ====================
# Name: test_classifier.py - the sandbox rules, one path at a time
# Description: unit tests for the plugin's classify(), including precedence
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""The classifier, tested directly.

The end-to-end tests cannot reach every arm: this suite's own targets live under
``/tmp/pytest-of-*``, so a hermetic test has nowhere genuinely outside the tmp
allowances to plant a write.  The out-of-tree arm is proved live instead --
daemon's ``test_timer_install.py::TestInstall::test_install_success`` creates
``~/.aipass`` on every run and the gate names it -- and proved deterministically
here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROTOTYPE_ROOT = Path(__file__).resolve().parent.parent
if str(PROTOTYPE_ROOT / "plugin") not in sys.path:
    sys.path.insert(0, str(PROTOTYPE_ROOT / "plugin"))

import audit_hygiene_plugin as plugin  # type: ignore[import-not-found]  # noqa: E402


@pytest.fixture
def state():
    """A hand-built state, so every path below is decided by the rules alone."""
    fresh = plugin._State()
    fresh.log_path = "/scratch/env/_audit/hygiene.jsonl"
    fresh.env_root = "/scratch/env"
    fresh.target_root = "/scratch/env/src/aipass/branch"
    fresh.tmp_root = "/scratch"
    fresh.pytest_basetemp = "/scratch/pytest-of-someone/pytest-1"
    fresh.pytest_tmp_prefix = "/scratch/pytest-of-"
    fresh.tmpdir_allowed = True
    return fresh


def verdict(state, path: str) -> tuple[str, str]:
    return plugin.classify(path, state)


def test_a_write_into_the_copy_is_a_violation(state):
    assert verdict(state, "/scratch/env/src/aipass/branch/logs/operations.jsonl") == (
        "violation",
        "inside_copy",
    )


def test_a_write_outside_everything_is_a_violation(state):
    assert verdict(state, "/home/someone/.aipass/registry.json") == ("violation", "outside_copy")


def test_the_copy_beats_the_tmpdir_allowance(state):
    """The precedence that makes the whole gate work.

    The scratch copy lives under TMPDIR. If the blanket tmp allowance were
    checked first it would acquit every write into the copy -- which is exactly
    the population this gate exists to convict.
    """
    assert state.env_root.startswith(state.tmp_root)
    assert verdict(state, "/scratch/env/anything.json")[0] == "violation"


def test_the_copy_beats_the_pytest_tmp_allowance(state):
    """The same precedence, for a copy made from inside another pytest run."""
    state.env_root = "/scratch/pytest-of-someone/pytest-1/outer/env"
    assert verdict(state, "/scratch/pytest-of-someone/pytest-1/outer/env/x.json") == (
        "violation",
        "inside_copy",
    )


def test_pytest_tmp_is_the_sandbox(state):
    assert verdict(state, "/scratch/pytest-of-someone/pytest-1/test_a0/data.json") == (
        "allowed",
        "pytest_tmp",
    )


def test_pytest_tmp_is_recognised_without_the_private_factory_attribute(state):
    """The allowance was dead code until a mutation of it killed nothing.

    ``config._tmp_path_factory`` does not exist yet at ``pytest_configure`` time,
    so the basetemp lookup silently returned "" and every tmp_path write was
    acquitted by the blanket TMPDIR rule instead. The prefix is what makes this
    rule real.
    """
    state.pytest_basetemp = ""
    assert verdict(state, "/scratch/pytest-of-someone/pytest-9/t/x.json") == ("allowed", "pytest_tmp")


def test_tmpdir_is_allowed_by_default_and_refusable(state):
    assert verdict(state, "/scratch/aipass_test_logs_ab/x.json") == ("allowed", "tmpdir")
    state.tmpdir_allowed = False
    assert verdict(state, "/scratch/aipass_test_logs_ab/x.json") == ("violation", "outside_copy")


def test_the_declared_allowances_acquit_by_name(state):
    assert verdict(state, "/scratch/env/pkg/__pycache__/m.cpython-312.pyc")[1] == "pycache_dir"
    assert verdict(state, "/scratch/env/.pytest_cache/v/cache/lastfailed")[1] == "pytest_cache_dir"
    assert verdict(state, "/scratch/env/pkg/m.pyc")[1] == "bytecode"
    assert verdict(state, "/scratch/env/.coverage.host.1")[1] == "coverage_data"
    assert verdict(state, "/dev/null")[1] == "devnull"
    assert verdict(state, state.log_path)[1] == "plugin_log"


def test_the_canary_is_its_own_verdict(state):
    """It must not appear in the published violations, and must still be seen."""
    state.canary_path = "/scratch/env/src/aipass/branch/.audit_tests_canary_1"
    assert verdict(state, state.canary_path) == ("canary", "canary")


def test_every_allowance_name_the_classifier_can_return_is_declared(state):
    """No silent widening: a reason the artifact never names is a hidden rule."""
    declared = {name for name, _meaning in plugin.ALLOWANCES}
    state.canary_path = "/scratch/env/c"
    reached = set()
    for path in (
        state.log_path,
        state.canary_path,
        "/scratch/env/__pycache__/m.pyc",
        "/scratch/env/.pytest_cache/x",
        "/scratch/env/m.pyc",
        "/scratch/env/.coverage",
        "/dev/null",
        "/scratch/pytest-of-someone/pytest-1/x",
        "/scratch/other/x",
    ):
        outcome, reason = plugin.classify(path, state)
        if outcome != "violation":
            reached.add(reason)
    assert reached <= declared, reached - declared
    assert reached == declared, declared - reached


def test_only_write_shaped_opens_are_recorded():
    """Reads are the overwhelming majority of open events and must cost nothing."""
    import os

    read_only = ("/x", "r", os.O_CLOEXEC)
    write_mode = ("/x", "w", os.O_CLOEXEC | os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    os_open_append = ("/x", None, os.O_CLOEXEC | os.O_WRONLY | os.O_APPEND)
    assert plugin._is_write_open(read_only) is False
    assert plugin._is_write_open(write_mode) is True
    assert plugin._is_write_open(os_open_append) is True
