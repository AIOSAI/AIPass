# =================== AIPass ====================
# Name: test_module_root.py
# Description: Pins the guarded __file__ resolver
# Version: 1.2.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/module_root.py: module_file() returns the RIGHT file when resolve() cannot be asked."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — ntpath.realpath's getcwd read; resolve denied for one path here, Windows CI runs it
# seedgo: no-test-needed(constant) — MODULE_NAME and module_file's logger.debug text

import os
from pathlib import Path

import pytest

from aipass.commons.apps.handlers import module_root

_DEAD_CWD = FileNotFoundError(2, "cwd deleted", "")


def _deny_resolve_for(monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    """Make resolve() raise for exactly one path, as module_root sees it; everything else is untouched."""
    # One path, on module_root's own Path: a global Path.resolve patch recurses through the
    # repo-root conftest's write guard. type(Path()) rather than Path: Path subclasses need 3.12.

    class _DeniedResolvePath(type(Path())):
        def resolve(self, strict: bool = False):
            if str(self) == target:
                raise _DEAD_CWD
            return super().resolve(strict=strict)

    monkeypatch.setattr(module_root, "Path", _DeniedResolvePath)


@pytest.fixture
def silent_audit(monkeypatch: pytest.MonkeyPatch) -> list:
    """Capture _record_unresolved's audit line instead of writing it to disk."""
    calls: list = []

    def _capture(operation, data=None, module_name=None):
        calls.append((operation, data, module_name))
        return True

    monkeypatch.setattr(
        "aipass.commons.apps.handlers.json.json_handler.log_operation",
        _capture,
    )
    return calls


def test_module_file_resolves_normally():
    """On a healthy filesystem the answer is the resolved path."""
    assert module_root.module_file(__file__) == Path(__file__).resolve()


def test_module_file_returns_the_absolute_file_when_resolve_is_denied(
    monkeypatch: pytest.MonkeyPatch, silent_audit: list
):
    """The fallback is the module's own absolute path, not the cwd and not '.'."""
    _deny_resolve_for(monkeypatch, __file__)

    result = module_root.module_file(__file__)

    assert result == Path(__file__)
    assert result.is_absolute(), "the fallback returned a relative path — every caller would walk from the cwd"
    assert result.name == "test_module_root.py"
    assert [c[0] for c in silent_audit] == ["module_file_unresolved"], "the fallback was taken but never recorded"


def test_the_denial_instrument_denies_one_path_and_only_that_path(monkeypatch: pytest.MonkeyPatch):
    """CONTROL: the denial binds (else the pin above passes for the wrong reason) and leaks past no other path."""
    _deny_resolve_for(monkeypatch, __file__)

    with pytest.raises(FileNotFoundError):
        module_root.Path(__file__).resolve()

    sibling = Path(__file__).parent / "conftest.py"
    assert module_root.Path(sibling).resolve() == Path(sibling).resolve(), "the denial leaked past its one target path"
    assert Path(__file__).resolve() == Path(os.path.realpath(__file__)), "the denial leaked out of module_root"


def test_a_failing_audit_write_never_escapes(monkeypatch: pytest.MonkeyPatch):
    """_record_unresolved runs at import time on every caller, so a raise would become the import crash."""

    def _exploding_log(*args, **kwargs):
        raise RuntimeError("the audit lane is down")

    _deny_resolve_for(monkeypatch, __file__)
    monkeypatch.setattr(
        "aipass.commons.apps.handlers.json.json_handler.log_operation",
        _exploding_log,
    )

    assert module_root.module_file(__file__) == Path(__file__)
