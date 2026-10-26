# =================== AIPass ====================
# Name: test_hook_test.py
# Version: 1.1.0
# Description: Tests for the portable hook test runner
# Branch: hooks
# Layer: tests
# Created: 2026-07-10
# Modified: 2026-10-25
# =============================================

"""Tests for apps/modules/hook_test.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — MOCK_EVENTS' sample payloads and HELP_COMMANDS' display strings
# seedgo: no-test-needed(stdlib) — tempfile.gettempdir() choosing where the synthetic file lands
# seedgo: no-test-needed(ruff) — that modules/hook_test.py parses and imports the engine it drives

import json
import os
from pathlib import Path
from unittest.mock import patch

from aipass.hooks.apps.modules import hook_test

_MOD = "aipass.hooks.apps.modules.hook_test"


class TestRunTest:
    def test_no_config_returns_error(self):
        with (
            patch(f"{_MOD}.find_project_config", return_value=None),
            patch(
                f"{_MOD}.config_unavailable_reason",
                return_value="No .aipass/hooks.json found — run from an AIPass project directory.",
            ),
        ):
            result = hook_test.run_test()
        assert "error" in result
        assert "hooks.json" in result["error"]

    def test_no_config_error_reports_the_real_refusal(self):
        """Not-enrolled must not be reported as file-not-found — the CLI echoes
        whatever the loader says refused it, verbatim."""
        truth = "/proj/.aipass/hooks.json exists, but this project is not enrolled...\nFix: aipass trust /proj"
        with (
            patch(f"{_MOD}.find_project_config", return_value=None),
            patch(f"{_MOD}.config_unavailable_reason", return_value=truth),
        ):
            result = hook_test.run_test()
        assert result["error"] == truth
        assert "No .aipass/hooks.json found" not in result["error"]

    def test_hooks_disabled_returns_error(self):
        with patch(f"{_MOD}.find_project_config", return_value={"hooks_enabled": False}):
            result = hook_test.run_test()
        assert "error" in result
        assert "hooks_enabled" in result["error"]

    def test_fires_enabled_hooks(self):
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "test_hook": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.security.git_gate.handle",
                    "matcher": "Bash|Edit",
                },
            },
        }
        with patch(f"{_MOD}.find_project_config", return_value=config):
            result = hook_test.run_test()
        assert "PreToolUse" in result
        assert len(result["PreToolUse"]) == 1
        assert result["PreToolUse"][0]["hook"] == "test_hook"

    def test_skips_non_dict_entries(self):
        config = {
            "hooks_enabled": True,
            "_comment": "template config",
        }
        with patch(f"{_MOD}.find_project_config", return_value=config):
            result = hook_test.run_test()
        assert result == {}

    def test_skips_hooks_without_handler(self):
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "empty_hook": {"enabled": True},
            },
        }
        with patch(f"{_MOD}.find_project_config", return_value=config):
            result = hook_test.run_test()
        assert result == {}

    def test_reports_crashed_hooks(self):
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "bad_hook": {
                    "enabled": True,
                    "handler": "nonexistent.module.handle",
                    "matcher": "",
                },
            },
        }
        with patch(f"{_MOD}.find_project_config", return_value=config):
            result = hook_test.run_test()
        assert "PreToolUse" in result
        bad = result["PreToolUse"][0]
        assert bad["status"] == "crashed"
        assert "nonexistent" in bad["error"]
        assert bad["exit_code"] == 0


class TestPrintResults:
    def test_error_result_prints(self):
        with patch.object(hook_test.CONSOLE, "print") as mock_print:
            hook_test.print_results({"error": "No config found"})
        mock_print.assert_called_once_with("[red]No config found[/red]")

    def test_normal_results_print_summary(self):
        results = {
            "PreToolUse": [
                {"hook": "git_gate", "status": "fired", "elapsed_ms": 5.0},
                {"hook": "rm_gate", "status": "blocked", "elapsed_ms": 3.0},
            ],
        }
        calls = []
        with patch.object(hook_test.CONSOLE, "print", side_effect=lambda x="": calls.append(x)):
            hook_test.print_results(results)
        summary = [c for c in calls if "Summary" in str(c)]
        assert len(summary) == 1
        assert "1 fired" in summary[0]
        assert "1 blocked" in summary[0]


class TestHandleCommand:
    def test_rejects_non_test_command(self):
        assert hook_test.handle_command("status", []) is False

    def test_no_args_shows_introspection(self):
        with patch.object(hook_test, "print_introspection") as mock_intro:
            result = hook_test.handle_command("test", [])
        assert result is True
        mock_intro.assert_called_once()

    def test_runs_test_with_run_arg(self):
        with (
            patch.object(hook_test, "run_test", return_value={}) as mock_run,
            patch.object(hook_test, "print_results") as mock_results,
            patch.object(hook_test.CONSOLE, "print") as mock_print,
        ):
            result = hook_test.handle_command("test", ["run"])
        assert result is True
        mock_run.assert_called_once_with(verbose=False)
        mock_results.assert_called_once_with({}, verbose=False)
        mock_print.assert_any_call("[bold cyan]HOOKS Test Runner[/bold cyan]")


class TestProbeIsolation:
    """The probe must not write the branch it is probing (DPLAN-0323 tie-up).

    Before the fix, run_test() fired the REAL PreCompact handlers against the
    real cwd, so pre_compact_prep stamped a genuine AUTO-COMPACT session into
    hooks' live .trinity/local.json — a probe indistinguishable from a real
    compaction afterwards.
    """

    def _prep_config(self):
        return {
            "hooks_enabled": True,
            "PreCompact": {
                "pre_compact_prep": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.lifecycle.pre_compact_prep.handle",
                },
            },
        }

    def test_live_trinity_is_not_written(self, tmp_path, monkeypatch):
        """The whole point: fire the real stamping handler, real memory untouched."""
        branch = tmp_path / "hooks"
        (branch / ".trinity").mkdir(parents=True)
        local = branch / ".trinity" / "local.json"
        local.write_text('{"sessions": [], "key_learnings": [], "todos": []}\n', encoding="utf-8")
        before = local.read_text(encoding="utf-8")

        monkeypatch.chdir(branch)
        with patch(f"{_MOD}.find_project_config", return_value=self._prep_config()):
            result = hook_test.run_test()

        assert result["PreCompact"][0]["status"].startswith("fired")
        assert local.read_text(encoding="utf-8") == before

    def test_handler_still_ran_against_the_skeleton(self, tmp_path, monkeypatch):
        """VACUITY GUARD: 'nothing was written' must not mean 'nothing ran'."""
        branch = tmp_path / "hooks"
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "local.json").write_text(
            '{"sessions": [], "key_learnings": [], "todos": []}\n', encoding="utf-8"
        )
        monkeypatch.chdir(branch)

        seen = {}
        real_stamp = hook_test.dispatch

        def spy(event_type, stdin_data, config):
            seen["cwd"] = json.loads(stdin_data).get("cwd")
            return real_stamp(event_type, stdin_data, config)

        with (
            patch(f"{_MOD}.find_project_config", return_value=self._prep_config()),
            patch(f"{_MOD}.dispatch", side_effect=spy),
        ):
            hook_test.run_test()

        assert seen["cwd"] is not None
        assert seen["cwd"] != str(branch)

    def test_cwd_and_env_are_restored(self, tmp_path, monkeypatch):
        """A probe that leaves the caller in a deleted tempdir is its own defect."""
        branch = tmp_path / "hooks"
        (branch / ".trinity").mkdir(parents=True)
        monkeypatch.chdir(branch)
        sentinel_home = str(tmp_path / "sentinel" / "home")
        monkeypatch.setenv("AIPASS_HOME", sentinel_home)
        monkeypatch.delenv(hook_test.PROBE_ENV_VAR, raising=False)

        with patch(f"{_MOD}.find_project_config", return_value=self._prep_config()):
            hook_test.run_test()

        assert Path.cwd() == branch
        assert os.environ["AIPASS_HOME"] == sentinel_home
        assert hook_test.PROBE_ENV_VAR not in os.environ

    def test_workspace_is_removed(self, tmp_path, monkeypatch):
        branch = tmp_path / "hooks"
        (branch / ".trinity").mkdir(parents=True)
        monkeypatch.chdir(branch)

        seen = {}

        def spy(event_type, stdin_data, config):
            # The workspace is the skeleton's parent; the hooks are told the skeleton as their cwd.
            seen["workspace"] = Path(json.loads(stdin_data)["cwd"]).parent
            seen["existed"] = seen["workspace"].is_dir()
            return ("", 0)

        with (
            patch(f"{_MOD}.find_project_config", return_value=self._prep_config()),
            patch(f"{_MOD}.dispatch", side_effect=spy),
        ):
            hook_test.run_test()

        assert seen["existed"] is True
        assert not seen["workspace"].exists()

    def test_probe_flag_is_set_while_hooks_run(self, tmp_path, monkeypatch):
        """The flag the two mutation refusals read — proven live, not assumed."""
        branch = tmp_path / "hooks"
        (branch / ".trinity").mkdir(parents=True)
        monkeypatch.chdir(branch)

        seen = {}

        def spy(event_type, stdin_data, config):
            seen["flag"] = os.environ.get(hook_test.PROBE_ENV_VAR)
            return ("", 0)

        with (
            patch(f"{_MOD}.find_project_config", return_value=self._prep_config()),
            patch(f"{_MOD}.dispatch", side_effect=spy),
        ):
            hook_test.run_test()

        assert seen["flag"] == "1"


_MEMORY_FILES = ("local.json", "observations.json", "passport.json")  # the skeleton's contract


def _skeleton_at_dispatch(branch: Path, monkeypatch, look) -> dict:
    """Run run_test() from `branch` and hand `look` the skeleton as the hooks are told it, mid-run."""
    monkeypatch.chdir(branch)
    seen: dict = {}

    def spy(event_type, stdin_data, config):
        seen.update(look(Path(json.loads(stdin_data)["cwd"])))
        return ("", 0)

    config = {"hooks_enabled": True, "PreCompact": {"p": {"enabled": True, "handler": "x.y.handle"}}}
    with (
        patch(f"{_MOD}.find_project_config", return_value=config),
        patch(f"{_MOD}.dispatch", side_effect=spy),
    ):
        hook_test.run_test()
    return seen


class TestBuildSkeleton:
    """The skeleton is read as the hooks see it, through run_test (fleet green leg 9)."""

    def test_copies_the_memory_files(self, tmp_path, monkeypatch):
        # The floor, and the point of the test: the skeleton exists so no run
        # touches real memory, so a skeleton missing a file means a hook reads
        # nothing where the real branch has memory.
        real = tmp_path / "hooks"
        (real / ".trinity").mkdir(parents=True)
        for name in _MEMORY_FILES:
            (real / ".trinity" / name).write_text(f'{{"{name}": 1}}', encoding="utf-8")

        def look(skeleton: Path) -> dict:
            return {name: (skeleton / ".trinity" / name).read_text(encoding="utf-8") for name in _MEMORY_FILES}

        seen = _skeleton_at_dispatch(real, monkeypatch, look)
        assert seen == {name: f'{{"{name}": 1}}' for name in _MEMORY_FILES}

    def test_tolerates_a_branch_with_no_memory_files(self, tmp_path, monkeypatch):
        real = tmp_path / "bare"
        real.mkdir()

        def look(skeleton: Path) -> dict:
            return {"trinity": (skeleton / ".trinity").is_dir(), "name": skeleton.name}

        assert _skeleton_at_dispatch(real, monkeypatch, look) == {"trinity": True, "name": "bare"}

    def test_skeleton_carries_no_registry(self, tmp_path, monkeypatch):
        """A temp repo root would not confine @memory's subprocess — see the module docstring."""
        real = tmp_path / "hooks"
        (real / ".trinity").mkdir(parents=True)

        def look(skeleton: Path) -> dict:
            return {
                "in_branch": (skeleton / "AIPASS_REGISTRY.json").exists(),
                "beside": (skeleton.parent / "AIPASS_REGISTRY.json").exists(),
                "trinity": (skeleton / ".trinity").is_dir(),
            }

        assert _skeleton_at_dispatch(real, monkeypatch, look) == {"in_branch": False, "beside": False, "trinity": True}


# _restore_env is read through run_test: test_cwd_and_env_are_restored pins the unset var
# staying unset (PROBE_ENV_VAR) and the prior value put back (AIPASS_HOME); its direct pins
# are retired (fleet green leg 9, ruling b).
