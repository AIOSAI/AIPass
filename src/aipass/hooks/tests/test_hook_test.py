# =================== AIPass ====================
# Name: test_hook_test.py
# Version: 1.4.0
# Description: Tests for the portable hook test runner
# Branch: hooks
# Layer: tests
# Created: 2026-07-10
# Modified: 2026-10-28
# =============================================

"""Tests for apps/modules/hook_test.py and the parity and smoke handlers it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — MOCK_EVENTS' sample payloads and HELP_COMMANDS' display strings
# seedgo: no-test-needed(stdlib) — tempfile.gettempdir() choosing where the synthetic file lands
# seedgo: no-test-needed(ruff) — that modules/hook_test.py parses and imports the engine it drives

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.config import diagnostics
from aipass.hooks.apps.handlers.parity import runner, smoke
from aipass.hooks.apps.handlers.prompt import temporal
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


_ALL_FOUR_REFUSE = [("PreToolUse", h, 2) for h in ("pre_edit_gate", "git_gate", "rm_gate", "testwrite_gate")]


class FakeClis:
    """Stands where claude, codex and opencode run: records each launch and writes its session's engine lines.

    An OpenCode model in *limited* answers the free tier's 429 after the plugin's hooks have run."""

    def __init__(self, monkeypatch, tmp_path, lines: dict[str, list[tuple[str, str, int]]]) -> None:
        self.calls: list[dict] = []
        self.lines = lines
        self.ids = {"claude": "claude-sess", "codex": "codex-thread", "opencode": "ses_oc"}
        self.limited: set[str] = set()
        self.log = tmp_path / "engine.jsonl"
        monkeypatch.setattr(diagnostics, "LOG_FILE", self.log)
        monkeypatch.setattr(runner.subprocess, "run", self._run)

    def _run(self, argv, **kwargs):
        self.calls.append({"argv": argv, **kwargs})
        provider = Path(argv[0]).name
        if provider not in self.ids:
            return subprocess.CompletedProcess(argv, 0, "sent", "")
        session = self.ids[provider]
        with self.log.open("a", encoding="utf-8") as handle:
            for event, hook, code in self.lines.get(provider, []):
                entry = {"event": event, "hook": hook, "exit_code": code, "stdout_len": 0, "session_id": session}
                handle.write(json.dumps(entry) + "\n")
        if provider == "opencode" and argv[argv.index("-m") + 1] in self.limited:
            refusal = {"type": "error", "sessionID": session, "error": {"type": "provider.free-limit", "status": 429}}
            start = json.dumps({"type": "step_start", "sessionID": session})
            return subprocess.CompletedProcess(argv, 1, start + "\n" + json.dumps(refusal), "")
        if provider == "claude":
            stdout = json.dumps({"type": "result", "session_id": session})
        elif provider == "opencode":
            stdout = json.dumps({"type": "step_start", "sessionID": session}) + "\n" + json.dumps({"type": "text"})
        else:
            stdout = json.dumps({"type": "thread.started", "thread_id": session})
        return subprocess.CompletedProcess(argv, 0, stdout if session else "", "")


def _table(err: str) -> dict[str, list[str]]:
    """The printed parity table, row label -> [lane, one cell per provider run, verdict]."""
    cells = [[c.strip() for c in line.strip("│").split("│")] for line in err.splitlines() if line.startswith("│")]
    return {row[1]: [row[0], *row[2:]] for row in cells if row[0] != "Lane"}


def _parity(tmp_path, *flags: str) -> None:
    branch = tmp_path / "canary"
    branch.mkdir(exist_ok=True)
    hook_test.handle_command("parity", ["--branch", str(branch), *flags])


class TestParity:
    def test_the_same_refusals_on_both_providers_read_same_and_exit_clean(self, monkeypatch, tmp_path, capsys):
        FakeClis(monkeypatch, tmp_path, {"claude": _ALL_FOUR_REFUSE, "codex": _ALL_FOUR_REFUSE})
        _parity(tmp_path, "--lane", "C")
        table = _table(capsys.readouterr().err)
        assert {label: row[1:] for label, row in table.items()} == {
            label: ["refused", "refused", "same"]
            for label in ("cross-branch write", "raw git status", "raw rm", "new test file")
        }

    def test_a_gate_refusing_on_one_provider_only_is_different_and_exits_1(self, monkeypatch, tmp_path, capsys):
        codex = [line if line[1] != "rm_gate" else ("PreToolUse", "rm_gate", 0) for line in _ALL_FOUR_REFUSE]
        FakeClis(monkeypatch, tmp_path, {"claude": _ALL_FOUR_REFUSE, "codex": codex})
        with pytest.raises(SystemExit) as exit_info:
            _parity(tmp_path, "--lane", "C")
        assert exit_info.value.code == 1
        table = _table(capsys.readouterr().err)
        assert table["raw rm"][1:] == ["refused", "not refused", "DIFFERENT"]
        assert table["raw git status"][3] == "same"

    def test_an_accepted_difference_is_marked_with_its_reason_and_does_not_fail(self, monkeypatch, tmp_path, capsys):
        starts = [("SessionStart", h, 0) for h in ("cadence_reset", "release_notice", "session_pointer")]
        FakeClis(monkeypatch, tmp_path, {"claude": starts, "codex": [*starts, ("SessionStart", "culture", 0)]})
        _parity(tmp_path, "--lane", "B")
        culture = _table(capsys.readouterr().err)["start: culture"]
        assert culture[1:3] == ["not reached", "ran"]
        assert culture[3].startswith("accepted (native on Claude")

    def test_a_session_that_prints_no_id_is_no_data_and_exits_1(self, monkeypatch, tmp_path, capsys):
        fake = FakeClis(monkeypatch, tmp_path, {"codex": _ALL_FOUR_REFUSE})
        fake.ids["claude"] = ""
        with pytest.raises(SystemExit) as exit_info:
            _parity(tmp_path, "--lane", "C")
        assert exit_info.value.code == 1
        table = _table(capsys.readouterr().err)
        assert [row[1] for row in table.values()] == ["no data"] * 4
        assert [row[3] for row in table.values()] == ["no data"] * 4

    def test_both_providers_get_the_same_prompt_on_stdin_headless_from_the_branch(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "outer-seat")
        fake = FakeClis(monkeypatch, tmp_path, {"claude": _ALL_FOUR_REFUSE, "codex": _ALL_FOUR_REFUSE})
        _parity(tmp_path, "--lane", "C")
        claude, codex = fake.calls
        assert claude["argv"][:2] == ["claude", "-p"] and "bypassPermissions" in claude["argv"]
        assert codex["argv"] == ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "--json", "-"]
        assert claude["input"] == codex["input"] and "git status" in claude["input"]
        assert claude["cwd"] == codex["cwd"] == str(tmp_path / "canary")
        assert claude["env"]["AIPASS_SESSION_TYPE"] == "dispatched"
        assert not [key for key in claude["env"] if key.startswith("CLAUDE")]

    def test_lane_a_sends_one_probe_mail_to_the_branch_before_the_sessions(self, monkeypatch, tmp_path):
        fake = FakeClis(monkeypatch, tmp_path, {})
        with pytest.raises(SystemExit):
            _parity(tmp_path, "--lane", "A")
        assert [c["argv"][0] for c in fake.calls] == ["drone", "claude", "codex"]
        assert fake.calls[0]["argv"][:4] == ["drone", "@ai_mail", "email", "@canary"]

    def test_json_writes_the_report_into_a_reports_folder_it_creates(self, monkeypatch, tmp_path):
        FakeClis(monkeypatch, tmp_path, {"claude": _ALL_FOUR_REFUSE, "codex": _ALL_FOUR_REFUSE})
        monkeypatch.setattr(hook_test, "REPORTS_DIR", tmp_path / "artifacts" / "reports")
        _parity(tmp_path, "--lane", "C", "--json")
        (report,) = (tmp_path / "artifacts" / "reports").glob("parity_*.json")
        written = json.loads(report.read_text(encoding="utf-8"))
        assert written["ok"] is True
        assert [row["verdict"] for row in written["rows"]] == ["same"] * 4

    def test_one_provider_launches_only_that_cli_and_compares_nothing(self, monkeypatch, tmp_path, capsys):
        fake = FakeClis(monkeypatch, tmp_path, {"claude": _ALL_FOUR_REFUSE})
        _parity(tmp_path, "--lane", "C", "--provider", "claude")
        assert [c["argv"][0] for c in fake.calls] == ["claude"]
        table = _table(capsys.readouterr().err)
        assert [row[1:] for row in table.values()] == [["refused", "not compared"]] * 4

    def test_opencode_runs_headless_beside_the_others_and_its_session_is_read_off_the_stream(
        self, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.setenv("OPENCODE_SESSION_ID", "outer-seat")
        monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(tmp_path / "ocdir"))
        monkeypatch.setenv("PWD", str(tmp_path))
        lines = {p: _ALL_FOUR_REFUSE for p in ("claude", "codex", "opencode")}
        fake = FakeClis(monkeypatch, tmp_path, lines)
        _parity(tmp_path, "--lane", "C", "--provider", "claude,codex,opencode")
        table = _table(capsys.readouterr().err)
        assert [row[1:] for row in table.values()] == [["refused", "refused", "refused", "same"]] * 4
        opencode = fake.calls[2]
        assert opencode["argv"][1:] == [
            "run",
            "--standalone",
            "--format",
            "json",
            "--auto",
            "-m",
            runner.OPENCODE_MODELS[0],
        ]
        assert opencode["input"] == fake.calls[0]["input"] and opencode["cwd"] == str(tmp_path / "canary")
        # OpenCode seats itself at $PWD before its real cwd: an inherited PWD runs the lane as the caller.
        assert opencode["env"]["PWD"] == opencode["cwd"]
        assert "OPENCODE_SESSION_ID" not in opencode["env"]
        assert opencode["env"]["OPENCODE_CONFIG_DIR"] == str(tmp_path / "ocdir")

    def test_a_free_limit_reruns_once_on_the_fallback_model(self, monkeypatch, tmp_path, capsys):
        fake = FakeClis(monkeypatch, tmp_path, {"opencode": _ALL_FOUR_REFUSE, "claude": _ALL_FOUR_REFUSE})
        fake.limited.add(runner.OPENCODE_MODELS[0])
        _parity(tmp_path, "--lane", "C", "--provider", "claude,opencode")
        models = [c["argv"][-1] for c in fake.calls if Path(c["argv"][0]).name == "opencode"]
        assert models == list(runner.OPENCODE_MODELS)
        assert [row[1:] for row in _table(capsys.readouterr().err).values()] == [["refused", "refused", "same"]] * 4

    def test_every_model_limited_is_no_data_after_one_run_each(self, monkeypatch, tmp_path, capsys):
        fake = FakeClis(monkeypatch, tmp_path, {"claude": _ALL_FOUR_REFUSE, "opencode": _ALL_FOUR_REFUSE})
        fake.limited.update(runner.OPENCODE_MODELS)
        with pytest.raises(SystemExit) as exit_info:
            _parity(tmp_path, "--lane", "C", "--provider", "claude,opencode")
        assert exit_info.value.code == 1
        assert len([c for c in fake.calls if Path(c["argv"][0]).name == "opencode"]) == len(runner.OPENCODE_MODELS)
        assert [row[2:] for row in _table(capsys.readouterr().err).values()] == [["no data", "no data"]] * 4


class FakeSmokeClis:
    """Stands where the three CLIs run a smoke turn: the real temporal hook answers the prompt, and its
    output lands where each provider records hook context (unless *hook_ran* is off)."""

    def __init__(self, monkeypatch, tmp_path) -> None:
        self.home = tmp_path / "home"
        self.calls: list[dict] = []
        self.hook_ran = True
        self.stderr = ""
        self.session = True
        self.limited: set[str] = set()
        self.during = None
        # Path.home() reads HOME on POSIX and USERPROFILE on Windows.
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("USERPROFILE", str(self.home))
        monkeypatch.delenv("OPENCODE_DB", raising=False)
        monkeypatch.delenv("OPENCODE_CONFIG_DIR", raising=False)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        plugin = tmp_path / "config" / "opencode" / "plugins" / "aipass.ts"
        plugin.parent.mkdir(parents=True)
        plugin.write_text("// plugin", encoding="utf-8")
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        for name in runner.PROVIDERS:
            self.install(name)
        monkeypatch.setenv("PATH", str(self.bin))
        monkeypatch.setattr(smoke.subprocess, "run", self._run)

    def install(self, name: str) -> None:
        """A stub on PATH; Windows' which wants a PATHEXT suffix, POSIX's the execute bit."""
        for stub in (self.bin / name, self.bin / f"{name}.cmd"):
            stub.write_text("", encoding="utf-8")
            stub.chmod(0o755)

    def _run(self, argv, **kwargs):
        self.calls.append({"argv": argv, **kwargs})
        provider = Path(argv[0]).stem
        if self.during:
            self.during(Path(kwargs["cwd"]))
        if not self.session:
            return subprocess.CompletedProcess(argv, 1, "", self.stderr)
        hook = temporal.handle({"prompt": kwargs["input"]})["stdout"] if self.hook_ran else "Temporal: no hook"
        # The model's reply carries the ack even when no hook ran: only the hook's own row may count.
        reply = "ok smoke-ack:" + temporal.SMOKE_NONCE.search(kwargs["input"]).group(1)
        getattr(self, f"_{provider}")(hook, reply, kwargs["input"])
        if provider == "opencode" and argv[argv.index("-m") + 1] in self.limited:
            refusal = {"type": "error", "sessionID": "ses_oc", "error": {"type": "provider.free-limit"}}
            return subprocess.CompletedProcess(argv, 1, json.dumps(refusal), "")
        stdout = {
            "claude": {"type": "result", "session_id": "claude-sess"},
            "codex": {"type": "thread.started", "thread_id": "codex-thread"},
            "opencode": {"type": "step_start", "sessionID": "ses_oc"},
        }[provider]
        return subprocess.CompletedProcess(argv, 0, json.dumps(stdout), "")

    def _jsonl(self, path: Path, records: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

    def _claude(self, hook: str, reply: str, prompt: str) -> None:
        attachment = {"type": "hook_success", "hookEvent": "UserPromptSubmit", "content": hook}
        self._jsonl(
            self.home / ".claude" / "projects" / "-branch" / "claude-sess.jsonl",
            [
                {"type": "user", "message": {"content": prompt}},
                {"type": "attachment", "attachment": attachment},
                {"type": "assistant", "message": {"content": reply}},
            ],
        )

    def _codex(self, hook: str, reply: str, prompt: str) -> None:
        def message(role: str, text: str) -> dict:
            return {"type": "response_item", "payload": {"type": "message", "role": role, "content": [{"text": text}]}}

        self._jsonl(
            self.home / ".codex" / "sessions" / "2026" / "10" / "28" / "rollout-2026-10-28T13-00-00-codex-thread.jsonl",
            [message("developer", hook), message("user", prompt), message("assistant", reply)],
        )

    def _opencode(self, hook: str, reply: str, prompt: str) -> None:
        db = Path(os.environ["XDG_DATA_HOME"]) / "opencode" / "opencode.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS session_message (session_id text, type text, data text)")
            conn.execute("INSERT INTO session_message VALUES ('ses_oc', 'user', ?)", (json.dumps(prompt + hook),))
            conn.execute("INSERT INTO session_message VALUES ('ses_oc', 'assistant', ?)", (json.dumps(reply),))
        conn.close()


def _smoke(tmp_path, *flags: str) -> None:
    branch = tmp_path / "canary"
    branch.mkdir(exist_ok=True)
    hook_test.handle_command("smoke", ["--branch", str(branch), *flags])


class TestSmoke:
    def test_each_provider_passes_on_the_hook_ack_in_its_own_record_and_exits_clean(
        self, monkeypatch, tmp_path, capsys
    ):
        fake = FakeSmokeClis(monkeypatch, tmp_path)
        _smoke(tmp_path)
        out = capsys.readouterr().out
        assert out.startswith("smoke: claude pass (")
        assert ", claude-sess) · codex pass (" in out and ", codex-thread) · opencode pass (" in out
        assert [Path(c["argv"][0]).stem for c in fake.calls] == ["claude", "codex", "opencode"]
        assert all(
            "aipass-smoke:" in c["input"] and c["env"]["AIPASS_SESSION_TYPE"] == "dispatched" for c in fake.calls
        )
        # Unset, the turn's auto_process hook starts @memory's archive of the branch's .trinity.
        assert all(c["env"]["AIPASS_HOOK_PROBE"] == "1" for c in fake.calls)

    def test_the_ack_in_the_model_reply_alone_is_a_fail_and_exits_1(self, monkeypatch, tmp_path, capsys):
        fake = FakeSmokeClis(monkeypatch, tmp_path)
        fake.hook_ran = False
        with pytest.raises(SystemExit) as exit_info:
            _smoke(tmp_path, "--provider", "claude,codex")
        assert exit_info.value.code == 1
        assert capsys.readouterr().out.count("fail (the session ran but its record carries no hook nonce ack)") == 2

    def test_opencode_with_no_hook_ack_in_the_user_message_fails(self, monkeypatch, tmp_path, capsys):
        FakeSmokeClis(monkeypatch, tmp_path).hook_ran = False
        with pytest.raises(SystemExit):
            _smoke(tmp_path, "--provider", "opencode")
        assert "opencode fail (" in capsys.readouterr().out

    def test_a_cli_not_installed_is_a_skip_with_no_launch(self, monkeypatch, tmp_path, capsys):
        fake = FakeSmokeClis(monkeypatch, tmp_path)
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        _smoke(tmp_path, "--provider", "codex")
        assert capsys.readouterr().out.strip() == "smoke: codex skip (codex is not installed)"
        assert fake.calls == []

    def test_opencode_without_the_plugin_is_a_skip_with_no_launch(self, monkeypatch, tmp_path, capsys):
        fake = FakeSmokeClis(monkeypatch, tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "elsewhere"))
        _smoke(tmp_path, "--provider", "opencode")
        assert "opencode skip (the AIPass plugin is not installed for OpenCode)" in capsys.readouterr().out
        assert fake.calls == []

    def test_no_login_is_a_skip_whose_why_carries_none_of_the_cli_output(self, monkeypatch, tmp_path, capsys):
        fake = FakeSmokeClis(monkeypatch, tmp_path)
        fake.session = False
        fake.stderr = "Not logged in. token sk-secret-123"
        _smoke(tmp_path, "--provider", "claude")
        out = capsys.readouterr().out
        assert "claude skip (not logged in, or no provider for the model)" in out
        assert "sk-secret" not in out

    def test_an_unknown_launch_error_with_no_session_is_a_fail(self, monkeypatch, tmp_path, capsys):
        FakeSmokeClis(monkeypatch, tmp_path).session = False
        with pytest.raises(SystemExit):
            _smoke(tmp_path, "--provider", "claude")
        assert "claude fail (no session id (exit 1))" in capsys.readouterr().out

    def test_free_limit_on_every_opencode_model_is_a_skip_after_one_run_each(self, monkeypatch, tmp_path, capsys):
        fake = FakeSmokeClis(monkeypatch, tmp_path)
        fake.limited.update(runner.OPENCODE_MODELS)
        _smoke(tmp_path, "--provider", "opencode")
        assert "opencode skip (free limit reached on every free model)" in capsys.readouterr().out
        assert [c["argv"][-1] for c in fake.calls] == list(runner.OPENCODE_MODELS)

    def test_a_named_model_runs_once_on_that_model_for_that_provider_only(self, monkeypatch, tmp_path, capsys):
        fake = FakeSmokeClis(monkeypatch, tmp_path)
        _smoke(tmp_path, "--provider", "opencode,codex", "--model", "opencode=openai/gpt-6.1-sol")
        assert fake.calls[0]["argv"][-1] == "openai/gpt-6.1-sol"
        assert "-m" not in fake.calls[1]["argv"]
        assert "opencode pass (" in capsys.readouterr().out

    def test_a_session_with_no_record_on_disk_is_a_skip_no_readback(self, monkeypatch, tmp_path, capsys):
        fake = FakeSmokeClis(monkeypatch, tmp_path)
        monkeypatch.setattr(fake, "_claude", lambda *_: None)
        _smoke(tmp_path, "--provider", "claude")
        assert "claude skip (no readback: the provider's record of the session is not found)" in capsys.readouterr().out

    def test_the_branch_files_a_turn_writes_are_restored_byte_for_byte(self, monkeypatch, tmp_path):
        mail = tmp_path / "canary" / ".ai_mail.local"
        mail.mkdir(parents=True)
        (mail / "session.json").write_text('{"before": 1}', encoding="utf-8")
        fake = FakeSmokeClis(monkeypatch, tmp_path)

        def turn_writes(branch: Path) -> None:
            (branch / ".ai_mail.local" / "session.json").write_text('{"after": 2}', encoding="utf-8")
            (branch / ".ai_mail.local" / "grounding.json").write_text("{}", encoding="utf-8")

        fake.during = turn_writes
        _smoke(tmp_path, "--provider", "claude")
        assert (mail / "session.json").read_text(encoding="utf-8") == '{"before": 1}'
        assert not (mail / "grounding.json").exists()

    def test_json_prints_one_array_of_results_on_stdout(self, monkeypatch, tmp_path, capsys):
        FakeSmokeClis(monkeypatch, tmp_path)
        _smoke(tmp_path, "--provider", "claude,opencode", "--json")
        results = json.loads(capsys.readouterr().out)
        assert [(r["provider"], r["status"], r["session_id"]) for r in results] == [
            ("claude", "pass", "claude-sess"),
            ("opencode", "pass", "ses_oc"),
        ]
        assert set(results[0]) == {"provider", "status", "why", "session_id", "elapsed_ms"}
