# =================== AIPass ====================
# Name: test_json_dir_seam.py
# Description: The json_handler test seam resolves at call time
# Version: 1.0.0
# Created: 2026-08-30
# =============================================

"""drone's own json_handler must honour AIPASS_TEST_LOG_DIR.

@prax's contract ruling (2026-08-30): AIPASS_TEST_LOG_DIR is the seam, in
@trigger's form, adopted by each branch in its OWN json_handler. Not a sixth
mocking technique — five already existed and every one of them reaches nothing.

Measured on this tree before any of this was written: the env var was set to
/tmp/aipass_test_logs_xiwxoz8x and JSON_DIR still resolved to the live
drone_json/. That is why the resolution lives behind a function. A value
captured at import cannot be redirected by a conftest that runs afterwards, and
a seam that has to win an import race is not a seam.

4189 of this branch's 7652 audit-tests hygiene records are these writes.
"""

from pathlib import Path

import pytest

from aipass.drone.apps.handlers.json import json_handler


class TestTheSeamResolvesAtCallTime:
    """The use site, not just the resolver — @prax's third detail.

    A mutation reverting the path builder to read the import-time constant
    survived every other test they had written.
    """

    def test_get_json_path_follows_the_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        resolved = json_handler.get_json_path("probe", "log")

        assert tmp_path in resolved.parents, resolved

    def test_the_live_tree_is_not_touched_when_the_var_is_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        resolved = json_handler.get_json_path("probe", "log")

        assert "src/aipass/drone/drone_json" not in str(resolved)

    def test_a_write_lands_in_the_redirected_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        json_handler.ensure_json_exists("seamprobe", "log")

        assert list(tmp_path.rglob("seamprobe_log.json")), sorted(tmp_path.rglob("*"))


class TestAbsenceAndOverride:
    def test_an_empty_value_is_absence_not_a_redirect(self, monkeypatch):
        """Path('') / 'x' is RELATIVE and scatters state wherever we stand."""
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", "")

        resolved = json_handler.get_json_path("probe", "log")

        assert resolved.is_absolute()
        assert resolved.parent == json_handler._IMPORT_TIME_JSON_DIR

    def test_no_var_at_all_resolves_to_the_real_tree(self, monkeypatch):
        monkeypatch.delenv("AIPASS_TEST_LOG_DIR", raising=False)

        resolved = json_handler.get_json_path("probe", "log")

        assert resolved.parent == json_handler._IMPORT_TIME_JSON_DIR

    def test_an_explicit_patch_still_wins_over_the_env_var(self, tmp_path, monkeypatch):
        """~20 tests across this suite redirect by setattr. They must keep working."""
        elsewhere = tmp_path / "explicit"
        elsewhere.mkdir()
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "env"))
        monkeypatch.setattr(json_handler, "JSON_DIR", elsewhere)

        resolved = json_handler.get_json_path("probe", "log")

        assert resolved.parent == elsewhere

    def test_a_patch_given_as_a_string_still_wins(self, tmp_path, monkeypatch):
        """Several branches' shared tests patch it as a str, not a Path."""
        elsewhere = tmp_path / "explicit"
        elsewhere.mkdir()
        monkeypatch.setattr(json_handler, "JSON_DIR", str(elsewhere))

        assert json_handler.get_json_path("probe", "log").parent == elsewhere


class TestNoDirectoryIsCreatedInTheLiveTree:
    """A mkdir into the real tree is a write, and writes are what we are killing.

    ``ensure_json_exists`` creates the directory and then the file. Reverting
    ONLY the mkdir still produced a correct file — something downstream made the
    redirected parent — so the file-exists assertion above could not see it. The
    audit hook can: os.mkdir on the live drone_json/ is a recorded violation
    whether or not the directory was already there.
    """

    def test_the_mkdir_targets_the_redirected_dir_not_the_live_one(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        targets = []
        real_mkdir = Path.mkdir

        def _spy(self, *args, **kwargs):
            targets.append(Path(self))
            return real_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", _spy)
        json_handler.ensure_json_exists("mkdirprobe", "log")

        assert targets, "ensure_json_exists stopped creating its directory"
        assert json_handler._IMPORT_TIME_JSON_DIR not in targets, f"a directory was created in the live tree: {targets}"


class TestNoModuleWritesAtImportTime:
    """A write bound to an import is a write no fixture can gate.

    Measured while re-verifying @prax's seam: after AIPASS_TEST_LOG_DIR was
    adopted, ONE live-tree file still changed on every run —
    ``drone_json/exceptions_log.json``. The cause was not the seam. It was a
    module-level ``log_operation`` call in ``apps/handlers/exceptions.py``,
    which runs during COLLECTION: before any fixture exists, and therefore
    outside the repo-root conftest's autouse guard that protects every other
    branch's shared JSON. The seam resolves at call time correctly; this call
    simply happened before there was a test to gate it.
    """

    def test_importing_the_exception_hierarchy_writes_nothing(self):
        import importlib

        from aipass.drone.apps.handlers.json import json_handler as jh

        calls = []
        real = jh.log_operation
        jh.log_operation = lambda *a, **kw: calls.append((a, kw)) or True
        try:
            importlib.reload(importlib.import_module("aipass.drone.apps.handlers.exceptions"))
        finally:
            jh.log_operation = real

        assert calls == [], f"import wrote a JSON record no fixture can intercept: {calls}"


class TestAnIdenticalValueIsNotAPatch:
    """``JSON_DIR`` rebound to the import-time VALUE is not a redirect.

    The first cut of this seam asked ``JSON_DIR is not _IMPORT_TIME_JSON_DIR``.
    Identity is the wrong question, and the full suite proved it: a test patches
    JSON_DIR to tmp_path, reloads the module — which rebinds BOTH names to fresh
    objects — and monkeypatch's undo then restores the pre-reload Path. Equal
    value, different object. From that point every later test in the process
    took the explicit-patch branch and wrote into the live drone_json: 3757
    resolutions per run, measured, from ordinary tests that never touched
    JSON_DIR at all.

    A caller who sets JSON_DIR to exactly where it already pointed has redirected
    nothing, so the env var still governs.
    """

    def test_rebinding_to_an_equal_path_still_honours_the_env_var(self, monkeypatch, tmp_path):
        from aipass.drone.apps.handlers.json import json_handler as jh

        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        monkeypatch.setattr(jh, "JSON_DIR", Path(str(jh._IMPORT_TIME_JSON_DIR)))

        resolved = jh._current_json_dir()

        assert tmp_path in resolved.parents, f"a same-value rebind hijacked the seam: {resolved}"

    def test_a_real_redirect_is_still_obeyed_over_the_env_var(self, monkeypatch, tmp_path):
        """Value comparison must not weaken the explicit patch it exists to honour."""
        from aipass.drone.apps.handlers.json import json_handler as jh

        target = tmp_path / "explicit"
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "env"))
        monkeypatch.setattr(jh, "JSON_DIR", target)

        assert jh._current_json_dir() == target


class TestTheRedirectSurvivesAReloadInEitherOrder:
    """@prax's corrected contract, pinned against BOTH reload orderings.

    A test that calls ``importlib.reload`` while a monkeypatch is live has its
    teardown write the PRE-reload Path object onto the POST-reload module. The
    override test must not mistake that for a deliberate patch — in either
    order: env set before the import, or the import first and the env after.

    Run in a subprocess deliberately. Reloading json_handler in-process is the
    very thing that broke the seam, and a pin that damages the session it runs
    in is not a pin.
    """

    SCRIPT = """
import pytest
import importlib, os, sys, tempfile

MOD = "aipass.drone.apps.handlers.json.json_handler"
order = sys.argv[1]
tmp = tempfile.mkdtemp(prefix="ord_")

if order == "env-first":
    os.environ["AIPASS_TEST_LOG_DIR"] = tmp
    jh = importlib.reload(importlib.import_module(MOD))
    pre = jh.JSON_DIR
    jh = importlib.reload(importlib.import_module(MOD))
else:
    os.environ.pop("AIPASS_TEST_LOG_DIR", None)
    jh = importlib.reload(importlib.import_module(MOD))
    pre = jh.JSON_DIR
    os.environ["AIPASS_TEST_LOG_DIR"] = tmp
    jh = importlib.reload(importlib.import_module(MOD))

jh.JSON_DIR = pre  # what monkeypatch teardown actually does
print(jh._current_json_dir())
sys.exit(0 if str(jh._current_json_dir()).startswith(tmp) else 1)
"""

    @pytest.mark.parametrize("order", ["env-first", "import-first"])
    def test_the_redirect_is_still_alive_after_the_reload(self, order):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-c", self.SCRIPT, order],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, (
            f"the redirect died on the {order} ordering — resolved to {result.stdout.strip()}\n{result.stderr}"
        )


class TestTheSavePathCreatesItsOwnDirectory:
    """A redirect points at a directory that does not exist yet.

    @daemon's second defect, checked here rather than assumed: their save_json
    went straight into the atomic write, whose tempfile raises FileNotFoundError
    before a byte is written, and it had worked for years only because the live
    daemon_json/ is committed and therefore always present. Drone already
    mkdirs in _atomic_write_json, so this passed on the first run — pinned so
    that stays true, because nothing else would notice it going away until a
    redirect or a clean checkout hit it.
    """

    def test_writing_into_a_directory_that_does_not_exist_yet_succeeds(self, tmp_path, monkeypatch):
        target = tmp_path / "never" / "created"
        monkeypatch.setattr(json_handler, "JSON_DIR", target)

        assert json_handler.save_json("probe", "log", []) is True
        assert (target / "probe_log.json").is_file()


class TestTheAnchorIsEnvIndependent:
    """The precondition this seam rests on, pinned instead of asserted in prose.

    ``_current_json_dir`` treats "differs from BOTH fixed points" as proof of a
    deliberate override. That reasoning is only sound while ``real`` really is
    the real tree — and ``real`` is ``_IMPORT_TIME_JSON_DIR``, captured once at
    import. If that anchor were seeded from ``AIPASS_TEST_LOG_DIR``, then any
    run where the variable is already exported at import time makes the ANCHOR a
    redirect. A later test pointing the variable somewhere else leaves the stale
    anchor differing from both fixed points, which reads as an explicit patch,
    and the seam dies for the rest of the process.

    That is not hypothetical and it is not drone's: @prax shipped the contract
    and then violated this precondition in their own implementation, took two CI
    reds for it (deterministic from the repo root, green from the branch dir),
    and named my docstring's "load-bearing" line as the bug report. Their
    mechanism needs NO ``importlib.reload`` — an env var already exported at
    import is enough, which makes it a wider hole than the reload write-back
    @daemon and I both hit.

    Drone is immune BY CONSTRUCTION — the anchor is ``_BRANCH_ROOT /
    "drone_json"`` and reads no environment. But "immune by construction" was
    exactly the shape of two guards this week that turned out to be unobservable,
    so it is a test now.

    IT MUST BE A SUBPROCESS. In-process the property is unfalsifiable: the import
    already happened, so setting the variable now proves nothing about what the
    anchor was seeded from. @prax's form, adopted.
    """

    def test_importing_with_the_env_var_already_set_leaves_the_anchor_on_the_real_tree(self, tmp_path):
        import subprocess
        import sys
        import textwrap

        probe = textwrap.dedent(
            """
            import os, sys
            os.environ["AIPASS_TEST_LOG_DIR"] = sys.argv[1]
            from aipass.drone.apps.handlers.json import json_handler as jh
            print("ANCHOR", jh._IMPORT_TIME_JSON_DIR)
            print("REDIRECT", jh._current_json_dir())
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", probe, str(tmp_path)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        anchor = next(line.split(" ", 1)[1] for line in result.stdout.splitlines() if line.startswith("ANCHOR"))
        redirect = next(line.split(" ", 1)[1] for line in result.stdout.splitlines() if line.startswith("REDIRECT"))

        assert anchor.endswith("drone/drone_json"), f"the anchor was seeded from the environment: {anchor}"
        assert str(tmp_path) not in anchor, f"the anchor IS the redirect — the seam has no fixed point: {anchor}"
        assert str(tmp_path) in redirect, f"the env var was exported before import and ignored: {redirect}"
