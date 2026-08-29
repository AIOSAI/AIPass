# =================== AIPass ====================
# Name: test_static_self_skip.py - the SELF-SKIP nominator
# Description: fires on a subject-reading predicate, silent on a machine-reading one
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""Both sides of the SELF-SKIP rule.

A nominator that only ever fires is a nominator nobody will read, so the silent
cases are tested as hard as the loud ones: ``TAXONOMY`` §6 -- a checker that flags
nothing in table A is not measuring, one that flags anything in table B is not
shippable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROTOTYPE_ROOT = Path(__file__).resolve().parent.parent
if str(PROTOTYPE_ROOT) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE_ROOT))

from audit_tests_lib import static_skip  # type: ignore[import-not-found]  # noqa: E402
from audit_tests_lib.astutil import SubjectIndex  # type: ignore[import-not-found]  # noqa: E402
from audit_tests_lib.modmap import build_module_map  # type: ignore[import-not-found]  # noqa: E402

HANDLER_SOURCE = """
JSON_DIR = "/somewhere"


def load_json(name):
    return {}
"""


@pytest.fixture
def branch(tmp_path: Path):
    """A miniature branch with one handler module and a tests directory."""
    src = tmp_path / "src"
    module_dir = src / "mybranch" / "apps"
    module_dir.mkdir(parents=True)
    (src / "mybranch" / "__init__.py").write_text("")
    (module_dir / "__init__.py").write_text("")
    (module_dir / "json_handler.py").write_text(HANDLER_SOURCE)
    tests = src / "mybranch" / "tests"
    tests.mkdir()

    def write_test(name: str, source: str) -> Path:
        path = tests / name
        path.write_text(source)
        return path

    modules = build_module_map(src)
    index = SubjectIndex(modules, src / "mybranch")
    return write_test, index, src / "mybranch"


def test_skipif_on_a_subject_attribute_is_nominated(branch):
    """The plain case: the predicate asks the code under test if it still works."""
    write_test, index, root = branch
    path = write_test(
        "test_bad.py",
        """
import pytest

from mybranch.apps import json_handler


@pytest.mark.skipif(not hasattr(json_handler, "JSON_DIR"), reason="no dir")
def test_something():
    assert True
""",
    )
    result = static_skip.run([path], index, root)
    assert result["nominations"], result
    assert result["nominations"][0]["species"] == "SELF-SKIP"
    assert "JSON_DIR" in result["nominations"][0]["predicate"]


def test_a_platform_predicate_is_acquitted(branch):
    """T7's other half: reading the machine is exactly what a skip is for."""
    write_test, index, root = branch
    path = write_test(
        "test_good.py",
        """
import shutil
import sys

import pytest

from mybranch.apps import json_handler


@pytest.mark.skipif(sys.platform == "win32", reason="posix only")
def test_something():
    assert json_handler.load_json("x") == {}


@pytest.mark.skipif(shutil.which("rsync") is None, reason="needs rsync")
def test_something_else():
    assert True
""",
    )
    result = static_skip.run([path], index, root)
    assert result["nominations"] == []
    assert result["counters"]["acquitted_machine"] == 2


def test_the_indirect_drift_guard_is_nominated_through_the_taint(branch):
    """The fleet's flagship shape, and no direct read appears in the predicate.

    ``_ATTR`` is assigned inside an ``if hasattr(subject, ...)`` and the skip then
    tests ``_ATTR is None``.  Renaming the constant makes the whole module vanish
    from the run, which is the SKIP-ON-DRIFT the templates ship fleet-wide.
    """
    write_test, index, root = branch
    path = write_test(
        "test_drift.py",
        """
import pytest

from mybranch.apps import json_handler

_ATTR = None
for _candidate in ("JSON_DIR", "BRANCH_JSON_DIR"):
    if hasattr(json_handler, _candidate):
        _ATTR = _candidate
        break

if _ATTR is None:
    pytest.skip("cannot find the dir attribute", allow_module_level=True)


def test_something():
    assert True
""",
    )
    result = static_skip.run([path], index, root)
    assert result["nominations"], result
    assert result["nominations"][0]["species"] == "SKIP-ON-DRIFT"


def test_importorskip_on_the_subject_is_nominated_and_on_a_dependency_is_not(branch):
    """Skipping because numpy is absent is a fact about the box, not the branch."""
    write_test, index, root = branch
    subject = write_test(
        "test_selfimport.py",
        """
import pytest

json_handler = pytest.importorskip("mybranch.apps.json_handler")


def test_something():
    assert True
""",
    )
    dependency = write_test(
        "test_depimport.py",
        """
import pytest

numpy = pytest.importorskip("numpy")


def test_something():
    assert True
""",
    )
    assert len(static_skip.run([subject], index, root)["nominations"]) == 1
    assert static_skip.run([dependency], index, root)["nominations"] == []


def test_a_file_that_does_not_parse_is_counted_not_crashed(branch):
    """Templates and half-written files exist; the nominator survives them."""
    write_test, index, root = branch
    path = write_test("test_broken.py", "def test_x(:\n    pass\n")
    result = static_skip.run([path], index, root)
    assert result["counters"]["parse_errors"] == 1
    assert result["nominations"] == []
