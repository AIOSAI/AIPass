# =================== AIPass ====================
# Name: test_module_root.py
# Description: Pins the guarded __file__ resolver
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""module_file() must return the RIGHT file when resolve() cannot be asked.

test_import_dead_cwd.py proves the imports survive. That is a weaker claim
than it looks: a fallback returning Path(".") would also let every import
succeed, and every caller would then walk up from the wrong place. These pins
are about the VALUE, not the survival.

The denial is scoped to ONE path rather than to Path.resolve as a whole. The
first draft patched the method globally, which was green under the branch
pytest.ini and RecursionError under the repo-root conftest: that conftest's
write guard resolves a path inside log_operation, so a blanket denial sent
_record_unresolved back through it forever. A global patch of a stdlib method
is a claim about every caller in the process, and this test only has a claim
about one file.
"""

from pathlib import Path

import pytest

from aipass.commons.apps.handlers import module_root

_DEAD_CWD = FileNotFoundError(2, "cwd deleted", "")


def _deny_resolve_for(monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    """Make resolve() raise for exactly one path; everything else is untouched."""
    real_resolve = Path.resolve

    def _maybe_denied(self, *args, **kwargs):
        if str(self) == target:
            raise _DEAD_CWD
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _maybe_denied)


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
    """
    The fallback is the module's own absolute path, not the cwd and not '.'.

    __file__ has been absolute since Python 3.9, so the fallback names the
    same file resolve() would have named - just spelled through any symlink
    rather than past it.
    """
    _deny_resolve_for(monkeypatch, __file__)

    result = module_root.module_file(__file__)

    assert result == Path(__file__)
    assert result.is_absolute(), "the fallback returned a relative path — every caller would walk from the cwd"
    assert result.name == "test_module_root.py"
    assert [c[0] for c in silent_audit] == ["module_file_unresolved"], "the fallback was taken but never recorded"


def test_the_denial_instrument_denies_one_path_and_only_that_path(monkeypatch: pytest.MonkeyPatch):
    """
    CONTROL — a monkeypatch that silently failed to bind would make the pin
    above green for the wrong reason (module_file would simply have resolved
    normally, and Path(__file__) == Path(__file__).resolve() on a machine with
    no symlink in the path).

    The second half is the control ON the control: the denial must be narrow,
    or it is patching the whole process again.
    """
    _deny_resolve_for(monkeypatch, __file__)

    with pytest.raises(FileNotFoundError):
        Path(__file__).resolve()

    sibling = Path(__file__).parent / "conftest.py"
    assert sibling.resolve() == Path(sibling).absolute(), "the denial leaked past its one target path"


def test_a_failing_audit_write_never_escapes(monkeypatch: pytest.MonkeyPatch):
    """
    _record_unresolved runs at module import time on every caller. If it could
    raise, the diagnostic would become the import crash module_file exists to
    prevent.
    """

    def _exploding_log(*args, **kwargs):
        raise RuntimeError("the audit lane is down")

    _deny_resolve_for(monkeypatch, __file__)
    monkeypatch.setattr(
        "aipass.commons.apps.handlers.json.json_handler.log_operation",
        _exploding_log,
    )

    assert module_root.module_file(__file__) == Path(__file__)
