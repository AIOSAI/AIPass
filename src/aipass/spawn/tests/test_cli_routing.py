# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: Tests for CLI routing and help output
# Version: 1.0.3
# Created: 2026-03-27
# Modified: 2026-09-29
# =============================================

"""Tests for apps/spawn.py's CLI routing, help output, and introspection."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/spawn.py parses and imports
# seedgo: no-test-needed(documentation) — docstrings on print_help, print_introspection, and handle_create

import logging
from unittest.mock import patch

import pytest

from aipass.spawn.apps.handlers import update_ops
from aipass.spawn.apps.handlers.seed_ops import canonical_text, seed_path_for
from aipass.spawn.apps.modules.export_seeds import handle_export_seeds
from aipass.spawn.apps.modules.sync_registry import handle_sync_registry
from aipass.spawn.apps.modules.update import handle_update
from aipass.spawn.apps.spawn import handle_create, main, print_help, print_introspection
from aipass.spawn.tests.conftest import make_passport


class TestCliRouting:
    """Tests for spawn.py main() CLI routing."""

    def test_no_args_triggers_introspection(self):
        """main() with no args calls print_introspection."""

        with patch("sys.argv", ["spawn"]):
            with patch("aipass.spawn.apps.spawn.print_introspection") as mock_intro:
                result = main()
        assert result == 0
        mock_intro.assert_called_once()

    def test_help_flag(self):
        """main() with --help calls print_help."""

        with patch("sys.argv", ["spawn", "--help"]):
            with patch("aipass.spawn.apps.spawn.print_help") as mock_help:
                result = main()
        assert result == 0
        mock_help.assert_called_once()

    def test_short_help(self):
        """main() with -h calls print_help."""

        with patch("sys.argv", ["spawn", "-h"]):
            with patch("aipass.spawn.apps.spawn.print_help") as mock_help:
                result = main()
        assert result == 0
        mock_help.assert_called_once()

    def test_help_word(self):
        """main() with 'help' command calls print_help."""

        with patch("sys.argv", ["spawn", "help"]):
            with patch("aipass.spawn.apps.spawn.print_help") as mock_help:
                result = main()
        assert result == 0
        mock_help.assert_called_once()

    def test_unknown_command(self):
        """main() with unknown command returns 1."""

        with patch("sys.argv", ["spawn", "nonexistent_command"]):
            with patch("aipass.spawn.apps.spawn.error") as mock_error:
                result = main()
        assert result == 1
        mock_error.assert_called_once()

    def test_command_returns_int(self):
        """main() with no argv prints introspection and exits 0 - the value, not just the type.

        Measured 2026-09-08: exactly 0. A bare invocation is not a refusal, so
        this is the one door in the file that is SUPPOSED to exit zero, and the
        number is pinned rather than its type.
        """

        with patch("sys.argv", ["spawn"]):
            with patch("aipass.spawn.apps.spawn.print_introspection") as mock_introspection:
                result = main()
        assert isinstance(result, int)
        assert result == 0, result
        mock_introspection.assert_called_once()


class TestCreateHelp:
    """Tests for create --help interception."""

    def test_create_help_flag(self):
        """create --help shows help instead of argparse error."""

        with patch("aipass.spawn.apps.spawn.print_help") as mock_help:
            result = handle_create(["--help"])
        assert result == 0
        mock_help.assert_called_once()

    def test_create_short_help(self):
        """create -h shows help."""

        with patch("aipass.spawn.apps.spawn.print_help") as mock_help:
            result = handle_create(["-h"])
        assert result == 0
        mock_help.assert_called_once()

    def test_create_help_with_class(self):
        """create specialist --help shows help."""

        with patch("aipass.spawn.apps.spawn.print_help") as mock_help:
            result = handle_create(["specialist", "--help"])
        assert result == 0
        mock_help.assert_called_once()

    def test_create_help_beats_a_retired_class(self):
        """--help is answered before the retired-name refusal — asking for help
        is never the thing that gets refused."""

        with patch("aipass.spawn.apps.spawn.print_help") as mock_help:
            result = handle_create(["aipass_framework", "--help"])
        assert result == 0
        mock_help.assert_called_once()


class TestCreateDryRun:
    """Tests for create --dry-run preview."""

    def test_dry_run_returns_zero(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """--dry-run returns 0 for valid target.

        Mutant: the preview drops its 'DRY RUN' header -> red.
        """

        target = str(tmp_path / "drytest")
        result = handle_create([target, "--dry-run"])
        assert result == 0
        out = capsys.readouterr().out
        assert "DRY RUN" in out
        assert "DRYTEST" in out

    def test_dry_run_creates_no_files(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """--dry-run creates nothing on disk."""

        target = tmp_path / "drytest"
        handle_create([str(target), "--dry-run"])
        assert not target.exists()
        assert "No files were created" in capsys.readouterr().out

    def test_dry_run_existing_target_returns_error(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """--dry-run returns 1 if target already exists.

        Mutant: the refusal no longer names 'Target already exists' -> red.
        """

        target = tmp_path / "existing"
        target.mkdir()
        result = handle_create([str(target), "--dry-run"])
        assert result == 1
        captured = capsys.readouterr()
        assert "Target already exists" in captured.out + captured.err


class TestTemplateFlag:
    """Tests for --template flag as class selector."""

    def test_template_flag_unknown_treated_as_path(self, tmp_path):
        """--template with unknown value is treated as path (backward compat)."""

        target = str(tmp_path / "path_test")
        with patch("aipass.spawn.apps.spawn.error") as mock_error:
            result = handle_create([target, "--template", "/nonexistent/path"])
        assert result == 1
        mock_error.assert_called_once()


class TestCreateUnknownClassRefusal:
    """`create <bare-token>` refuses when the lone positional is neither a
    registered class nor path-shaped, instead of silently reading it as the
    target path (APLAN-0007 open item 1; devpulse: general refusal in front
    of the parser, not another special case)."""

    def test_bare_unrecognized_token_refuses_no_branch_created(self, tmp_path, monkeypatch):
        """`create wizard` (no path arg) must refuse — not silently create a
        branch named WIZARD in ./wizard."""

        monkeypatch.chdir(tmp_path)
        registry = tmp_path / "AIPASS_REGISTRY.json"

        with patch("aipass.spawn.apps.spawn.error") as mock_error:
            result = handle_create(["wizard", "--registry", str(registry)])

        assert result == 1
        mock_error.assert_called_once()
        message = str(mock_error.call_args).lower()
        assert "wizard" in message
        # The refusal names the classes that DO exist. Both, since DPLAN-0319 R4
        # collapsed the roster to manager|specialist — a caller who mistyped needs
        # the live names, not the retired ones.
        assert "manager" in message
        assert "specialist" in message
        assert not (tmp_path / "wizard").exists()
        assert not registry.exists()

    def test_path_like_single_positional_still_creates(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """A token carrying a path marker is unaffected — still creates via the
        default class exactly as before (legitimate `create <path>` usage).

        Mutant: the success report drops 'Agent created:' -> red.
        """

        target = tmp_path / "legit_agent"
        registry = tmp_path / "AIPASS_REGISTRY.json"
        result = handle_create([str(target), "--registry", str(registry)])

        assert result == 0
        assert "Agent created: LEGIT_AGENT" in capsys.readouterr().out
        assert target.exists()
        assert (target / ".trinity" / "passport.json").exists()

    @pytest.mark.parametrize("citizen_class", ["manager", "specialist"])
    def test_explicit_class_and_path_still_works(self, tmp_path, citizen_class, capsys: pytest.CaptureFixture[str]):
        """`create <class> <path>` — the two-positional form — is untouched.

        Rewritten for DPLAN-0319 R4: this used to drive "aipass_framework", a
        name that is now retired and refused (see the sibling test below). Both
        LIVE classes must still create, and the class the caller typed must be
        the class the passport ends up claiming — a create that accepted the
        word and wrote something else would be the exact drift the rework ends.
        """
        import json

        target = tmp_path / f"legit_{citizen_class}"
        registry = tmp_path / "AIPASS_REGISTRY.json"
        result = handle_create([citizen_class, str(target), "--registry", str(registry)])

        assert result == 0
        assert f"Class: {citizen_class}" in capsys.readouterr().out
        assert target.exists()
        passport = json.loads((target / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert passport["identity"]["citizen_class"] == citizen_class

    def test_retired_class_and_path_refuses_by_name(self, tmp_path):
        """`create aipass_framework <path>` is REFUSED, not silently remapped.

        Was green as a create; the contract inverted with DPLAN-0319 R4. It also
        must not die as a bare argparse SystemExit(2) — the caller has to be told
        the name retired and what replaced it.
        """

        target = tmp_path / "legacy_agent"
        registry = tmp_path / "AIPASS_REGISTRY.json"
        with patch("aipass.spawn.apps.spawn.error") as mock_error:
            result = handle_create(["aipass_framework", str(target), "--registry", str(registry)])

        assert result == 1
        mock_error.assert_called_once()
        message = str(mock_error.call_args)
        assert "aipass_framework" in message
        assert "specialist" in message
        assert not target.exists()
        assert not registry.exists()

    def test_relative_dot_prefixed_token_still_creates(self, tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """An explicit relative-path marker ('./name') disambiguates and still creates."""

        monkeypatch.chdir(tmp_path)
        registry = tmp_path / "AIPASS_REGISTRY.json"
        result = handle_create(["./dotted_agent", "--registry", str(registry)])

        assert result == 0
        assert "Agent created: DOTTED_AGENT" in capsys.readouterr().out
        assert (tmp_path / "dotted_agent").exists()


class TestPrintHelp:
    """Tests for print_help output."""

    def test_print_help_runs(self, capsys: pytest.CaptureFixture[str]):
        """print_help executes without error.

        Mutant: the help header text changed -> red.
        """

        print_help()
        out = capsys.readouterr().out
        assert "SPAWN - Branch Lifecycle Manager" in out
        assert "drone @spawn create" in out


class TestPrintIntrospection:
    """Tests for print_introspection output."""

    def test_print_introspection_runs(self, capsys: pytest.CaptureFixture[str]):
        """print_introspection executes without error.

        Mutant: the 'spawn Entry Point' title dropped -> red.
        """

        print_introspection()
        assert "spawn Entry Point" in capsys.readouterr().out

    def test_output_capture(self, capsys: pytest.CaptureFixture[str]):
        """Verify print_introspection mentions connected modules.

        Mutant: the core.py line dropped from the listing -> red.
        """

        print_introspection()
        assert "core.py" in capsys.readouterr().out


class TestSyncRegistryCheckFlags:
    """sync-registry --check and --json, each passed through handle_sync_registry."""

    def test_check_reports_and_json_changes_the_shape(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """--check runs the read-only owner/identity check on a tmp_path registry; --json turns
        the report into a JSON document. Neither reaches sync_registry's write path.

        Mutant: --json ignored (json_output=False) -> red.
        """
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text('{"metadata": {}, "branches": []}', encoding="utf-8")
        before = registry.read_bytes()

        assert handle_sync_registry([str(tmp_path), "--check"]) == 1
        plain = capsys.readouterr()
        assert "No branch entry has owner:true" in plain.out
        assert "Owner/identity check: 2 issue(s)" in plain.err
        assert '"clean"' not in plain.out

        assert handle_sync_registry([str(tmp_path), "--check", "--json"]) == 1
        as_json = capsys.readouterr().out
        assert '"clean": false' in as_json
        assert '"no_owner"' in as_json
        assert registry.read_bytes() == before, "--check is read-only"


class TestUpdateTraceFlag:
    """update --trace, passed through handle_update against a tmp_path registry."""

    def test_trace_logs_the_resolved_branch(self, tmp_path, monkeypatch, caplog: pytest.LogCaptureFixture):
        """--trace logs where the branch resolved; without it nothing is said. Dry run is the
        default and the branch has no passport, so the update stops before any write.

        Mutant: --trace ignored (trace = False) -> red.
        """
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text('{"metadata": {}, "branches": [{"name": "PROBE", "path": "probe"}]}', encoding="utf-8")
        (tmp_path / "probe").mkdir()
        asked: list = []
        monkeypatch.setattr(update_ops, "find_registry", lambda *a, **k: asked.append(k) or registry)

        with caplog.at_level(logging.INFO):
            assert handle_update(["@probe"]) == 1
        assert "[update] Resolved" not in caplog.text
        caplog.clear()

        with caplog.at_level(logging.INFO):
            assert handle_update(["@probe", "--trace"]) == 1
        assert "[update] Resolved probe" in caplog.text
        assert len(asked) == 2
        assert not (tmp_path / "probe" / ".trinity").exists()


class TestExportSeedsOnlyFlag:
    """export-seeds --only, passed through handle_export_seeds in a tmp_path world."""

    def test_only_restricts_the_written_seeds_to_the_named_branch(self, tmp_path, monkeypatch):
        """--only decides which seed is written; the other branch is left untouched.

        The world is tmp_path: --root points discovery there, the cwd is there,
        and spawn's operations log goes there through conftest's
        AIPASS_TEST_LOG_DIR. export_seeds takes no registry, so there is no
        find_registry to point.

        Mutant: --only dropped on its way to export_seeds (only=None) -> red.
        """
        for branch in ("wanderer", "stranger"):
            trinity = tmp_path / "src" / "aipass" / branch / ".trinity"
            trinity.mkdir(parents=True)
            (trinity / "passport.json").write_text(canonical_text(make_passport(branch)), encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        assert handle_export_seeds(["--root", str(tmp_path), "--only", "@wanderer", "--confirm"]) == 0

        assert seed_path_for(tmp_path / "src" / "aipass" / "wanderer").is_file()
        assert not seed_path_for(tmp_path / "src" / "aipass" / "stranger").exists()


def test_output_capture(capsys: pytest.CaptureFixture[str]):
    """Verify print_introspection mentions connected modules."""

    print_introspection()
    output = capsys.readouterr().out
    assert "core.py" in output
