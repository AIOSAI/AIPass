# =================== AIPass ====================
# Name: test_refusals.py - the two ways the lane declines to publish
# Description: canary not caught, and a target with no pytest files
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""Refusal is the feature.

Law T10: every negative instrument needs a proof that it can fire.  The canary is
that proof, and if it does not fire the run must publish nothing -- because a
gate reporting zero because it is switched off is indistinguishable from a clean
suite, and this fleet has already shipped one kill switch that was silently off
the code path for 508 sends.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROTOTYPE_ROOT = Path(__file__).resolve().parent.parent
if str(PROTOTYPE_ROOT) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE_ROOT))

from conftest import CLEAN_TEST, DIRTY_TEST  # type: ignore[import-not-found]  # noqa: E402

CLI = PROTOTYPE_ROOT / "audit_tests.py"


def test_a_disabled_hook_refuses_the_whole_run(make_target, audit):
    """The gate cannot catch its own canary, so it publishes nothing at all."""
    target = make_target("nohook", DIRTY_TEST)
    document = audit(target, disable_hook=True)

    assert document["status"] == "refused"
    assert "canary" in document["refusal"]["reason"]
    assert document["harness"]["canary_caught"] is False


def test_a_refused_run_publishes_no_group_and_no_score(make_target, audit):
    """Refusal, never a silent zero: every group carries the reason instead."""
    target = make_target("nohook2", DIRTY_TEST)
    document = audit(target, disable_hook=True)

    for name, group in document["groups"].items():
        assert group["status"] == "refused", name
        assert group["reason"], name
        assert "score" not in group, name


def test_the_canary_is_caught_and_cleaned_up_on_a_normal_run(make_target, audit):
    """The positive control for the control: it fires, and it leaves nothing behind."""
    target = make_target("withhook", CLEAN_TEST)
    document = audit(target, keep_copy=True)

    canary = document["harness"]["canary"]
    assert canary["attempted"] is True
    assert canary["caught"] is True
    # keep_copy is load-bearing: without it the scratch env is deleted and the
    # sentinel is gone whether or not the plugin cleaned up after itself. A
    # mutation removing the unlink survived this test until the copy was kept.
    assert Path(canary["path"]).parent.is_dir()
    assert not Path(canary["path"]).exists()
    assert not any("canary" in v["path"] for v in document["groups"]["hygiene"]["violations"])


def test_a_target_with_no_pytest_files_is_refused(tmp_path):
    """The any-directory promise stops at directories with nothing to measure."""
    empty = tmp_path / "not_a_suite"
    empty.mkdir()
    (empty / "readme.md").write_text("no tests here")

    result = subprocess.run(
        [sys.executable, str(CLI), str(empty)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 3
    assert "REFUSES" in result.stderr
    assert "no pytest test files" in result.stderr


def test_the_cli_exit_code_separates_a_failed_gate_from_a_refusal(make_target, tmp_path):
    """0 clean, 1 convicted, 2 refused - three outcomes, three codes."""
    clean = make_target("cli_clean", CLEAN_TEST)
    dirty = make_target("cli_dirty", DIRTY_TEST)

    def run(target: Path, *extra: str) -> int:
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                str(target),
                "--env-root",
                str(tmp_path / f"env_{target.name}"),
                "--timeout",
                "300",
                *extra,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        ).returncode

    assert run(clean) == 0
    assert run(dirty) == 1
    assert run(dirty, "--disable-hook") == 2
