# =================== AIPass ====================
# Name: test_provider_choice.py
# Description: Tests for the install's last step: one provider picked, installed, wired, opened
# Version: 1.0.0
# Created: 2026-11-24
# Modified: 2026-11-24
# =============================================

"""Tests for apps/handlers/provider_choice.py's ending and the aipass provider command it backs."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that every module this file imports parses and imports

import json
from unittest.mock import MagicMock, patch

import pytest

from aipass.aipass.apps.handlers import provider_choice
from aipass.aipass.apps.modules import provider
from aipass.aipass.tests.support_doctor import _home_at


class TestProviderEnding:
    """The install's last question: one provider, installed if missing, wired alone, devpulse opened in it."""

    _PC = "aipass.aipass.apps.handlers.provider_choice"

    def _end(self, tmp_path, key, *, non_interactive=False, answers=(), found=None, installer_rc=0):
        lines: list[str] = []
        found = dict(found or {})
        report = tmp_path / "src" / "aipass" / "devpulse" / "dropbox" / "install_report.json"
        report.parent.mkdir(parents=True)
        report.write_text('{"outcome": "installed"}', encoding="utf-8")

        def run(argv, **_kw):
            if argv == provider_choice.PROVIDERS.get(key or "claude").installer and installer_rc == 0:
                found[key] = f"/bin/{key}"
            return MagicMock(returncode=installer_rc if "install" in " ".join(argv) else 0)

        with (
            patch(
                f"{self._PC}.shutil.which", side_effect=lambda b: found.get(b) or ("/bin/npm" if b == "npm" else None)
            ),
            patch(f"{self._PC}.subprocess.run", side_effect=run) as ran,
            patch(f"{self._PC}.wire_provider", return_value=["wired"]) as wire,
            patch(f"{self._PC}.json_handler"),
            _home_at(tmp_path),
        ):
            rc = provider_choice.run_ending(
                key, tmp_path, "hello", non_interactive=non_interactive, dry_run=False,
                prompt=MagicMock(side_effect=list(answers)), say=lines.append,
            )  # fmt: skip
        return rc, lines, ran, wire, json.loads(report.read_text(encoding="utf-8"))

    def test_headless_without_provider_installs_and_wires_nothing(self, tmp_path) -> None:
        """A bare non-interactive run never installs a CLI unasked. Mutant: ask anyway -> red (no answers)."""
        rc, lines, ran, wire, report = self._end(tmp_path, None, non_interactive=True)
        assert rc == 0
        assert ran.call_count == 0 and wire.call_count == 0
        assert any("aipass provider codex" in line for line in lines)
        assert "provider" not in report

    def test_enter_asks_again_and_a_number_picks_wires_only_that_one_and_records_it(self, tmp_path) -> None:
        """Mutant: wire every installed CLI -> red on the single wire call."""
        rc, lines, ran, wire, report = self._end(tmp_path, None, answers=["", "2"], found={"codex": "/bin/codex"})
        assert rc == 0
        wire.assert_called_once_with("codex", tmp_path)
        assert report["provider"] == "codex"
        assert any("[2] Codex   (installed)" in line for line in lines)
        assert ran.call_args.args[0] == ["/bin/codex", "hello"]
        assert ran.call_args.kwargs["cwd"] == tmp_path / "src" / "aipass" / "devpulse"

    def test_a_missing_cli_is_installed_by_its_vendor_then_claude_opens_through_the_shim_entry(self, tmp_path) -> None:
        rc, _lines, ran, _wire, _report = self._end(tmp_path, "claude")
        assert rc == 0
        argvs = [c.args[0] for c in ran.call_args_list]
        assert argvs[0] == ["bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"]
        assert argvs[-1] == [
            str(tmp_path / ".venv" / "bin" / "python3"), "-m", "aipass.hooks.apps.handlers.lifecycle.session_boot"
        ]  # fmt: skip
        assert ran.call_args.kwargs["env"]["AIPASS_HOME"] == str(tmp_path)

    def test_an_installer_failure_names_the_page_and_leaves_the_install_complete(self, tmp_path) -> None:
        """Mutant: wire after a failed install -> red on the wire call."""
        rc, lines, _ran, wire, report = self._end(tmp_path, "opencode", installer_rc=1)
        assert rc == 1
        wire.assert_not_called()
        assert report == {"outcome": "installed"}
        assert any(
            "AIPass itself is installed" in line and "https://github.com/sst/opencode#installation" in line
            for line in lines
        )

    def test_q_skips_with_the_later_command(self, tmp_path) -> None:
        rc, lines, ran, wire, _report = self._end(tmp_path, None, answers=["q"])
        assert rc == 0 and ran.call_count == 0 and wire.call_count == 0
        assert any("aipass provider" in line for line in lines)

    def test_aipass_provider_on_an_installed_cli_rewires_and_opens_never_installs(self, tmp_path) -> None:
        """Idempotent: the CLI is found, so no vendor installer runs. Mutant: install unconditionally -> red."""
        rc, _lines, ran, wire, report = self._end(tmp_path, "claude", found={"claude": "/bin/claude"})
        assert rc == 0
        wire.assert_called_once_with("claude", tmp_path)
        assert all("install.sh" not in " ".join(c.args[0]) for c in ran.call_args_list)
        assert report["provider"] == "claude"

    def test_aipass_provider_refuses_an_unknown_name_with_2(self, capsys) -> None:
        with pytest.raises(SystemExit) as exit_info:
            provider.handle_command("provider", ["gemini"])
        assert exit_info.value.code == 2
        assert "claude, codex, opencode" in capsys.readouterr().err
