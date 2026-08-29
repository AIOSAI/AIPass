# =================== AIPass ====================
# Name: conftest.py - fixtures for the audit-tests prototype's own suite
# Description: builds throwaway pytest targets under tmp_path; nothing else
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""Fixtures for the prototype's own tests.

Every target these build lives under ``tmp_path`` and every run puts its scratch
env under ``tmp_path`` too, so this suite must pass its own hygiene gate.  A
checker whose own tests forge state would be the joke that writes itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROTOTYPE_ROOT = Path(__file__).resolve().parent.parent
if str(PROTOTYPE_ROOT) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE_ROOT))

from audit_tests_lib import runner  # type: ignore[import-not-found]  # noqa: E402

CLEAN_TEST = '''
def test_writes_only_into_tmp_path(tmp_path):
    """A well-behaved test: everything it writes lands in its own sandbox."""
    (tmp_path / "scratch.txt").write_text("fine")
    assert (tmp_path / "scratch.txt").read_text() == "fine"


def test_pure_assertion():
    assert 2 + 2 == 4
'''

DIRTY_TEST = '''
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def test_forges_a_log_in_its_own_tree():
    """The AUDIT-FORGERY shape: an append into the tree under test."""
    with open(HERE / "operations.jsonl", "a", encoding="utf-8") as handle:
        handle.write("forged\\n")
    assert (HERE / "operations.jsonl").exists()


def test_stays_clean(tmp_path):
    (tmp_path / "ok.txt").write_text("ok")
    assert (tmp_path / "ok.txt").exists()
'''


def _make_target(root: Path, name: str, test_source: str, extra: dict[str, str] | None = None) -> Path:
    target = root / name
    (target / "tests").mkdir(parents=True)
    (target / "__init__.py").write_text("")
    (target / "tests" / "test_sample.py").write_text(test_source)
    for relative, content in (extra or {}).items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return target


@pytest.fixture
def make_target(tmp_path: Path):
    """Build a throwaway pytest target under tmp_path."""

    def factory(name: str, test_source: str, extra: dict[str, str] | None = None) -> Path:
        return _make_target(tmp_path / "targets", name, test_source, extra)

    return factory


@pytest.fixture
def audit(tmp_path: Path):
    """Run the lane against a target and hand back the artifact document."""
    counter = {"n": 0}

    def run(target: Path, **overrides) -> dict:
        counter["n"] += 1
        options = runner.Options(
            target=target,
            out=tmp_path / f"artifact_{counter['n']}.json",
            env_root=tmp_path / f"env_{counter['n']}",
            timeout=300,
            **overrides,
        )
        document, _text = runner.execute(options)
        return document

    return run
