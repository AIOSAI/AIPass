# =================== AIPass ====================
# Name: test_static_mock_drift.py - the MOCK-DRIFT nominator
# Description: both arms fire; a target that resolves stays silent
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""Both arms of MOCK-DRIFT, and the silence in between."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROTOTYPE_ROOT = Path(__file__).resolve().parent.parent
if str(PROTOTYPE_ROOT) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE_ROOT))

from audit_tests_lib import static_mock  # type: ignore[import-not-found]  # noqa: E402
from audit_tests_lib.modmap import build_module_map  # type: ignore[import-not-found]  # noqa: E402

ENGINE_SOURCE = """
DEFAULT_LIMIT = 10


def run_snapshot(path):
    return path


class Engine:
    pass
"""


@pytest.fixture
def branch(tmp_path: Path):
    """A branch with one real module, so a patch target can be checked against it."""
    src = tmp_path / "src"
    package = src / "mybranch" / "apps"
    package.mkdir(parents=True)
    (src / "mybranch" / "__init__.py").write_text("")
    (package / "__init__.py").write_text("")
    (package / "engine.py").write_text(ENGINE_SOURCE)
    tests = src / "mybranch" / "tests"
    tests.mkdir()

    def write_test(name: str, source: str) -> Path:
        path = tests / name
        path.write_text(source)
        return path

    return write_test, build_module_map(src), src / "mybranch"


def test_a_target_that_does_not_exist_is_nominated(branch):
    """Arm one: the function was renamed and the patch kept pointing at the old name."""
    write_test, modules, root = branch
    path = write_test(
        "test_gone.py",
        """
from unittest.mock import patch


def test_something():
    with patch("mybranch.apps.engine.run_snapshot_v2"):
        assert True
""",
    )
    result = static_mock.run([path], modules, root)
    assert len(result["nominations"]) == 1
    assert result["nominations"][0]["arm"] == "unresolved"
    assert result["nominations"][0]["target"] == "mybranch.apps.engine.run_snapshot_v2"
    assert result["nominations"][0]["line"] == 6


def test_patching_a_whole_module_is_nominated(branch):
    """Arm two: replace the module and every name reached through it is a mock."""
    write_test, modules, root = branch
    path = write_test(
        "test_module.py",
        """
from unittest.mock import patch


def test_something():
    with patch("mybranch.apps.engine"):
        assert True
""",
    )
    result = static_mock.run([path], modules, root)
    assert len(result["nominations"]) == 1
    assert result["nominations"][0]["arm"] == "whole_module"


def test_a_resolving_target_is_left_alone(branch):
    """The silence that makes the noise worth reading."""
    write_test, modules, root = branch
    path = write_test(
        "test_fine.py",
        """
from unittest.mock import patch


def test_function():
    with patch("mybranch.apps.engine.run_snapshot"):
        assert True


def test_constant():
    with patch("mybranch.apps.engine.DEFAULT_LIMIT", 5):
        assert True


def test_class():
    with patch("mybranch.apps.engine.Engine"):
        assert True
""",
    )
    result = static_mock.run([path], modules, root)
    assert result["nominations"] == []
    assert result["counters"]["resolved_ok"] == 3


def test_autospec_acquits_both_arms(branch):
    """`spec=` / `autospec=True` is the documented exemption, and it is honoured."""
    write_test, modules, root = branch
    path = write_test(
        "test_specced.py",
        """
from unittest.mock import patch


def test_module_with_autospec():
    with patch("mybranch.apps.engine", autospec=True):
        assert True


def test_missing_with_spec():
    with patch("mybranch.apps.engine.gone", spec=True):
        assert True
""",
    )
    result = static_mock.run([path], modules, root)
    assert result["nominations"] == []
    assert result["counters"]["acquitted_by_spec"] == 2


def test_a_third_party_target_is_out_of_scope_not_a_suspect(branch):
    """Resolution is import-free, so anything outside the copy is counted, not accused."""
    write_test, modules, root = branch
    path = write_test(
        "test_external.py",
        """
from unittest.mock import patch


def test_something():
    with patch("requests.get"):
        assert True
""",
    )
    result = static_mock.run([path], modules, root)
    assert result["nominations"] == []
    assert result["counters"]["out_of_tree"] == 1
