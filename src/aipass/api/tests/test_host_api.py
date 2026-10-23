# =================== AIPass ====================
# Name: test_host_api.py
# Description: Tests for the Stage 0 host API's commands — routing, tokens, serve/status/stop, config, the door
# Version: 1.3.1
# Created: 2026-08-14
# Modified: 2026-10-22
# =============================================

"""Tests for the host-api commands in apps/modules/host_api.py, host_serve.py and host_config_cli.py."""

# Config and token tests live in test_host_api_config.py, the app and routes in
# test_host_api_routes.py; helpers in support_host_api.py, the store fixture in conftest.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — hashlib.sha256 and secrets.token_urlsafe themselves, behind issue_token()
# seedgo: no-test-needed(constant) — print_help() and print_introspection() display text beyond the names asserted
# seedgo: no-test-needed(windows_compat) — the 0o600 token file mode on Windows; the POSIX tests carry a skipif
# seedgo: no-test-needed(duplicate_test) — the face lane in depth, covered by tests/test_host_face.py
# seedgo: no-test-needed(duplicate_test) — the lifetime and fleet lanes in depth, tests/test_host_lifetime.py

import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from aipass.api.apps.modules.host_api import handle_command
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import face as host_face
from aipass.api.apps.handlers.host import lifetime as host_lifetime
from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.api.apps import api as api_entry
from aipass.api.apps.modules import host_api as host_api_module
from aipass.api.apps.modules import host_config_cli as host_config_cli_module
from aipass.api.apps.modules import host_pair_cli as host_pair_cli_module
from aipass.api.apps.modules import host_serve as host_serve_module
from aipass.api.tests.support_host_api import TAILNET_SHAPED, UNHELD_ADDRESS, _baud_binary, _face_bundle


# Never opened; under the platform temp dir, not /tmp, so it reads the same on Windows.
STANDIN_LOG = Path(tempfile.gettempdir()) / "host_api_serve.log"


PATCH_CONFIG_LOGGER = "aipass.api.apps.handlers.host.config.logger"

PATCH_MOD_CONSOLE = "aipass.api.apps.modules.host_api.console"
PATCH_MOD_HEADER = "aipass.api.apps.modules.host_api.header"
PATCH_MOD_ERROR = "aipass.api.apps.modules.host_api.error"
PATCH_MOD_SUCCESS = "aipass.api.apps.modules.host_api.success"
PATCH_MOD_WARNING = "aipass.api.apps.modules.host_api.warning"
PATCH_MOD_JSON = "aipass.api.apps.modules.host_api.json_handler"
PATCH_MOD_HELP = "aipass.api.apps.modules.host_api.print_help"

# host_serve.py and host_config_cli.py import console and friends by NAME, so each
# module is patched on its own or its assertions read an untouched mock.
PATCH_SRV_CONSOLE = "aipass.api.apps.modules.host_serve.console"
PATCH_SRV_HEADER = "aipass.api.apps.modules.host_serve.header"
PATCH_SRV_ERROR = "aipass.api.apps.modules.host_serve.error"
PATCH_SRV_SUCCESS = "aipass.api.apps.modules.host_serve.success"
PATCH_SRV_WARNING = "aipass.api.apps.modules.host_serve.warning"
PATCH_SRV_JSON = "aipass.api.apps.modules.host_serve.json_handler"

PATCH_CFG_CONSOLE = "aipass.api.apps.modules.host_config_cli.console"
PATCH_CFG_HEADER = "aipass.api.apps.modules.host_config_cli.header"
PATCH_CFG_ERROR = "aipass.api.apps.modules.host_config_cli.error"
PATCH_CFG_SUCCESS = "aipass.api.apps.modules.host_config_cli.success"
PATCH_CFG_WARNING = "aipass.api.apps.modules.host_config_cli.warning"
PATCH_CFG_JSON = "aipass.api.apps.modules.host_config_cli.json_handler"


def _printed(*mocks: Any) -> str:
    """
    What the mocked output calls were given, as one plain string.

    Never the calls' repr: it doubles backslashes, so a Windows path is never found.
    """
    given = (value for mock in mocks for call in mock.call_args_list for value in (*call.args, *call.kwargs.values()))
    return " ".join(str(value) for value in given)


@pytest.fixture
def quiet_module():
    """Silence the module's console output during CLI tests."""
    with (
        patch(PATCH_MOD_CONSOLE) as mock_console,
        patch(PATCH_MOD_HEADER),
        patch(PATCH_MOD_ERROR) as mock_error,
        patch(PATCH_MOD_SUCCESS) as mock_success,
        patch(PATCH_MOD_WARNING) as mock_warning,
        patch(PATCH_MOD_JSON),
        patch(PATCH_SRV_CONSOLE, new=mock_console),
        patch(PATCH_SRV_HEADER),
        patch(PATCH_SRV_ERROR, new=mock_error),
        patch(PATCH_SRV_SUCCESS, new=mock_success),
        patch(PATCH_SRV_WARNING, new=mock_warning),
        patch(PATCH_SRV_JSON),
        patch(PATCH_CFG_CONSOLE, new=mock_console),
        patch(PATCH_CFG_HEADER),
        patch(PATCH_CFG_ERROR, new=mock_error),
        patch(PATCH_CFG_SUCCESS, new=mock_success),
        patch(PATCH_CFG_WARNING, new=mock_warning),
        patch(PATCH_CFG_JSON),
    ):
        yield {
            "error": mock_error,
            "success": mock_success,
            "warning": mock_warning,
            "console": mock_console,
        }


class TestCommandRouting:
    """Routing, and the help gate this branch has now been burned by twice."""

    def test_no_args_prints_introspection(self, store: Path, quiet_module: dict) -> None:
        """Bare command shows the module's self-map (seedgo no-args gate)."""
        with patch("aipass.api.apps.modules.host_api.print_introspection") as mock_intro:
            assert handle_command("host-api", []) is True

        mock_intro.assert_called_once()

    def test_foreign_command_passes_through(self, quiet_module: dict) -> None:
        """Another module's command must not be claimed by this one."""
        assert handle_command("validate", ["google"]) is False

    def test_foreign_command_with_no_args_passes_through(self, quiet_module: dict) -> None:
        """The no-args gate must not swallow other modules' bare commands."""
        assert handle_command("stats", []) is False

    @pytest.mark.parametrize(
        "args",
        [
            ["--help"],
            ["-h"],
            ["serve", "--help"],
            ["serve", "-h"],
            ["revoke-token", "abc123", "--help"],
            ["issue-token", "pixel-8", "--scope", "operate", "--help"],
        ],
    )
    def test_help_flag_anywhere_explains_never_runs(self, args: list, quiet_module: dict) -> None:
        """A help flag in ANY position explains. Checking only args[0] is what let
        'cleanup 30 --help' run a real cleanup (S58) and leaked key material (S59)."""
        with (
            patch(PATCH_MOD_HELP) as mock_help,
            patch.object(host_serve_module, "cmd_serve") as mock_serve,
            patch.object(host_api_module, "_cmd_revoke_token") as mock_revoke,
            patch.object(host_api_module, "_cmd_issue_token") as mock_issue,
        ):
            assert handle_command("host-api", args) is True

        mock_help.assert_called_once()
        mock_serve.assert_not_called()
        mock_revoke.assert_not_called()
        mock_issue.assert_not_called()

    def test_unknown_subcommand_reports_and_returns_handled(self, quiet_module: dict) -> None:
        """An unknown subcommand of a command we own is our error to report."""
        assert handle_command("host-api", ["frobnicate"]) is True
        quiet_module["error"].assert_called_once()


class TestTheSpellingOurOwnSelfMapAdvertises:
    """
    `drone @api` bare lists MODULE names, so it prints 'host_api' — while the
    command is 'host-api'.
    """

    def test_the_underscore_spelling_is_accepted(self, quiet_module: dict) -> None:
        """The exact string the module list prints."""
        with patch.object(host_api_module, "_cmd_list_tokens") as listed:
            assert handle_command("host_api", ["list-tokens"]) is True

        listed.assert_called_once()

    def test_the_underscore_spelling_shows_the_same_self_map(self, quiet_module: dict) -> None:
        """Bare, it must not fall through to 'unknown command' either."""
        with patch("aipass.api.apps.modules.host_api.print_introspection") as intro:
            assert handle_command("host_api", []) is True

        intro.assert_called_once()

    def test_the_help_gate_still_covers_the_alias(self, quiet_module: dict) -> None:
        """A second spelling must not become a second, ungated door."""
        with patch(PATCH_MOD_HELP) as helped, patch.object(host_serve_module, "cmd_serve") as served:
            assert handle_command("host_api", ["serve", "--help"]) is True

        helped.assert_called_once()
        served.assert_not_called()


class TestTheHelpsNameOnlyRealVerbs:
    """`drone @api --help` named a `tokens` verb nobody routes; `host-api --help` printed only pair."""

    def test_every_verb_either_help_names_resolves_to_a_routed_command(self, capsys: Any, monkeypatch: Any) -> None:
        reached = []
        for module, name in (
            (host_serve_module, "cmd_serve"),
            (host_serve_module, "cmd_status"),
            (host_serve_module, "cmd_stop"),
            (host_serve_module, "cmd_autostart"),
            (host_config_cli_module, "_cmd_config"),
            (host_config_cli_module, "_cmd_set_config"),
            (host_pair_cli_module, "_cmd_pair"),
            (host_api_module, "_cmd_issue_token"),
            (host_api_module, "_cmd_list_tokens"),
            (host_api_module, "_cmd_revoke_token"),
        ):
            monkeypatch.setattr(module, name, lambda *_, _name=name: reached.append(_name))
        api_entry.print_help()
        host_api_module.print_help()
        shown = capsys.readouterr().out
        row = next(line for line in shown.splitlines() if "The phone's server:" in line)
        named = {verb.strip(" │|") for verb in row.split("The phone's server:")[1].split(",")}
        named |= set(re.findall(r"host-api ([a-z][a-z-]*)", shown))

        for verb in sorted(named):
            handle_command("host-api", [verb])

        assert "Unknown host-api subcommand" not in capsys.readouterr().err
        assert len(reached) == len(named)

    def test_host_api_help_lists_every_verb_whatever_order_the_modules_load_in(
        self, store: Path, capsys: Any, monkeypatch: Any
    ) -> None:
        found = [host_pair_cli_module, host_serve_module, host_config_cli_module, host_api_module]
        monkeypatch.setattr(api_entry, "discover_modules", lambda: found)
        monkeypatch.setattr(sys, "argv", ["api", "host-api", "--help"])

        api_entry.main()

        out = capsys.readouterr().out
        assert "revoke-token <id>" in out
        assert "set-config" in out
        assert "a phone signs in by its camera" not in out


class TestRevokeTokenCommandRefuses:
    """A revoke that revoked nothing is a refusal, not a note."""

    def test_an_unknown_id_refuses_through_the_error_channel(self, store: Path, quiet_module: dict) -> None:
        """error() is what carries the failure to the exit seam; warning() does not."""
        handle_command("host-api", ["revoke-token", "no-such-id"])

        quiet_module["error"].assert_called_once()
        quiet_module["warning"].assert_not_called()
        quiet_module["success"].assert_not_called()

    def test_the_refusal_names_the_id_it_could_not_find(self, store: Path, quiet_module: dict) -> None:
        """A refusal that does not name the token sends the reader to the store to guess."""
        handle_command("host-api", ["revoke-token", "no-such-id"])

        assert "no-such-id" in quiet_module["error"].call_args.args[0]

    def test_a_real_revocation_still_succeeds_silently(self, store: Path, quiet_module: dict) -> None:
        """The refusal channel must not fire on the path that actually revokes."""
        record, _raw = host_tokens.issue_token("pixel-8", scope="read")

        handle_command("host-api", ["revoke-token", record["id"]])

        quiet_module["error"].assert_not_called()
        quiet_module["success"].assert_called_once()


class TestIssueTokenCommand:
    """The CLI's issuance discipline."""

    def test_no_out_flag_lands_the_receipt_in_the_secrets_store(self, store: Path, quiet_module: dict) -> None:
        """--out is OPTIONAL, and the default is where secrets already live."""
        handle_command("host-api", ["issue-token", "pixel-8"])

        quiet_module["error"].assert_not_called()

        receipt = store / "host_api" / "pixel-8.token"
        assert receipt.is_file(), "no receipt was written and nothing said so"
        assert host_tokens.verify_token(receipt.read_text(encoding="utf-8")) is not None

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
    def test_the_default_receipt_is_still_0600(self, store: Path, quiet_module: dict) -> None:
        """The mode is the point of the file, not a property of --out."""
        handle_command("host-api", ["issue-token", "pixel-8"])

        receipt = store / "host_api" / "pixel-8.token"

        assert stat.S_IMODE(os.stat(receipt).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(receipt.parent).st_mode) == 0o700

    def test_the_raw_value_is_still_never_printed(self, store: Path, quiet_module: dict) -> None:
        """S49, checked against the console rather than assumed from the shape."""
        handle_command("host-api", ["issue-token", "pixel-8"])

        raw = (store / "host_api" / "pixel-8.token").read_text(encoding="utf-8")
        printed = _printed(quiet_module["console"].print)
        printed += _printed(quiet_module["success"])

        assert raw not in printed, "the raw token reached the console"

    def test_an_existing_receipt_is_never_overwritten(self, store: Path, quiet_module: dict) -> None:
        """Its token is still LIVE — truncating the file orphans a credential."""
        handle_command("host-api", ["issue-token", "pixel-8"])
        receipt = store / "host_api" / "pixel-8.token"
        first = receipt.read_text(encoding="utf-8")

        handle_command("host-api", ["issue-token", "pixel-8"])

        quiet_module["error"].assert_called_once()
        assert receipt.read_text(encoding="utf-8") == first, "the first receipt was overwritten"
        assert len(host_tokens.list_tokens()) == 1, "a second token was minted for a receipt that could not be written"

    def test_an_existing_explicit_out_file_is_never_overwritten_either(
        self,
        store: Path,
        tmp_path: Path,
        quiet_module: dict,
    ) -> None:
        """Same rule when the caller names the path — the loss is identical."""
        out = tmp_path / "device.token"
        out.write_text("an-older-receipt", encoding="utf-8")

        handle_command("host-api", ["issue-token", "pixel-8", "--out", str(out)])

        quiet_module["error"].assert_called_once()
        assert out.read_text(encoding="utf-8") == "an-older-receipt"
        assert host_tokens.list_tokens() == [], "a token was minted that its caller can never read"

    def test_a_label_that_is_a_path_is_refused_before_anything_is_minted(
        self,
        store: Path,
        quiet_module: dict,
    ) -> None:
        """The label becomes a FILENAME now, so it needs the name fence."""
        handle_command("host-api", ["issue-token", "../escaped"])

        quiet_module["error"].assert_called_once()
        assert host_tokens.list_tokens() == [], "a token was minted for a label that could not be written"
        assert not (store.parent / "escaped.token").exists()

    def test_a_receipt_appearing_mid_mint_is_not_truncated(
        self,
        store: Path,
        tmp_path: Path,
        quiet_module: dict,
    ) -> None:
        """The existence check is a good sentence; O_EXCL is the guarantee.

        The file appears DURING the mint, past exists(); the minted token must be revoked.
        """
        out = tmp_path / "device.token"
        real_issue = host_tokens.issue_token

        def _someone_else_gets_there_first(label: str, scope: str = "read") -> Any:
            out.write_text("a receipt that arrived first", encoding="utf-8")
            return real_issue(label, scope)

        with patch.object(host_tokens, "issue_token", side_effect=_someone_else_gets_there_first):
            handle_command("host-api", ["issue-token", "pixel-8", "--out", str(out)])

        assert out.read_text(encoding="utf-8") == "a receipt that arrived first", (
            "a receipt created inside the window was truncated"
        )
        quiet_module["error"].assert_called_once()
        told = str(quiet_module["error"].call_args)
        assert "revoke" in told.lower(), f"the token was minted and the operator was not told to revoke it: {told}"

    def test_missing_label_refused(self, store: Path, quiet_module: dict, tmp_path: Path) -> None:
        """A label is required before anything is minted."""
        handle_command("host-api", ["issue-token", "--out", str(tmp_path / "x.token")])

        quiet_module["error"].assert_called_once()
        assert host_tokens.list_tokens() == []

    def test_writes_raw_value_to_0600_file(self, store: Path, tmp_path: Path, quiet_module: dict) -> None:
        """The raw value leaves through a file the operator owns, at 0600."""
        out = tmp_path / "device.token"

        handle_command("host-api", ["issue-token", "pixel-8", "--out", str(out)])

        raw = out.read_text(encoding="utf-8")
        assert host_tokens.verify_token(raw) is not None
        if sys.platform != "win32":
            assert stat.S_IMODE(os.stat(out).st_mode) == 0o600

    def test_scope_flag_is_honoured(self, store: Path, tmp_path: Path, quiet_module: dict) -> None:
        """--scope operate mints an operate token, not a read one."""
        out = tmp_path / "ops.token"

        handle_command("host-api", ["issue-token", "ops-phone", "--scope", "operate", "--out", str(out)])

        assert host_tokens.list_tokens()[0]["scope"] == "operate"


class TestDetachStatusAndStop:
    """The CLI half of the serve-flap fix."""

    @pytest.fixture
    def detachable(self):
        """The lifetime handler, stubbed — this is about the CLI's wiring."""
        with patch.object(host_serve_module, "host_lifetime") as lifetime:
            lifetime.LifetimeError = host_lifetime.LifetimeError
            yield lifetime

    def test_serve_without_detach_still_runs_in_this_process(
        self,
        store: Path,
        quiet_module: dict,
        extra_present: None,
        detachable,
    ) -> None:
        """Detaching is opt-in. Every existing caller keeps what it had."""
        with patch.object(host_server, "serve") as served:
            handle_command("host-api", ["serve"])

        served.assert_called_once()
        detachable.serve_detached.assert_not_called()

    def test_detach_never_runs_the_server_in_this_process(
        self,
        store: Path,
        quiet_module: dict,
        extra_present: None,
        detachable,
    ) -> None:
        """The point of the flag: drone times a launcher, not a server."""
        detachable.serve_detached.return_value = {"pid": 42, "host": "127.0.0.1", "port": 8790, "log": "/x.log"}

        with patch.object(host_server, "serve") as served:
            handle_command("host-api", ["serve", "--detach"])

        served.assert_not_called()
        detachable.serve_detached.assert_called_once()

    def test_detach_passes_the_parsed_bind_through(
        self,
        store: Path,
        quiet_module: dict,
        extra_present: None,
        detachable,
    ) -> None:
        """--host and --port must reach the child, not be silently dropped."""
        detachable.serve_detached.return_value = {"pid": 42, "host": "127.0.0.1", "port": 9001, "log": "/x.log"}

        handle_command("host-api", ["serve", "--detach", "--host", "127.0.0.1", "--port", "9001"])

        assert detachable.serve_detached.call_args.kwargs == {"host": "127.0.0.1", "port": 9001}

    def test_a_bad_port_is_refused_before_anything_detaches(
        self,
        store: Path,
        quiet_module: dict,
        extra_present: None,
        detachable,
    ) -> None:
        """The existing gate must not be skipped by the new path."""
        handle_command("host-api", ["serve", "--detach", "--port", "eighty"])

        detachable.serve_detached.assert_not_called()
        quiet_module["error"].assert_called_once()

    def test_a_refused_bind_is_reported_by_the_command_that_was_told_no(
        self,
        store: Path,
        quiet_module: dict,
        extra_present: None,
        detachable,
    ) -> None:
        """D1 across the detach seam.

        It surfaces here, not in the child's log, and leaves non-zero like the foreground.
        """
        detachable.serve_detached.side_effect = host_config.BindRefused("wildcards are refused")

        with pytest.raises(SystemExit) as exit_info:
            handle_command("host-api", ["serve", "--detach"])

        assert exit_info.value.code == 1
        quiet_module["error"].assert_called_once()

    def test_an_unknown_subcommand_still_reaches_the_error(
        self,
        store: Path,
        quiet_module: dict,
    ) -> None:
        """The delegation must not swallow anything.

        host_api offers every host-api call to host_serve first; it must decline the rest.
        """
        handle_command("host-api", ["serv"])

        quiet_module["error"].assert_called_once_with(
            "Unknown host-api subcommand: serv", suggestion="Run 'drone @api host-api --help' for available subcommands"
        )

    def test_host_serve_declines_commands_that_are_not_host_api(self) -> None:
        """It answers for `host-api` subcommands and nothing else."""
        assert host_serve_module.handle_command("issue-token", ["serve"]) is False
        assert host_serve_module.handle_command("host-api", ["list-tokens"]) is False

    def test_a_help_flag_anywhere_explains_rather_than_serves(self, quiet_module: dict) -> None:
        """`serve --help` must never start a server.

        host_api's gate catches it first today; this router must not rely on its caller.
        """
        with patch.object(host_serve_module, "cmd_serve") as served:
            assert host_serve_module.handle_command("host-api", ["serve", "--help"]) is True

        served.assert_not_called()

    def test_status_says_where_to_read_a_server_that_is_not_running(
        self,
        store: Path,
        quiet_module: dict,
        detachable,
    ) -> None:
        """A dead server stays dead and SAYS SO — no restart, and no silence."""
        detachable.server_state.return_value = {"state": "none", "record": None, "reason": ""}
        detachable.log_path.return_value = STANDIN_LOG

        handle_command("host-api", ["status"])

        printed = _printed(quiet_module["console"].print)

        assert "host_api_serve.log" in printed
        quiet_module["error"].assert_not_called()

    def test_status_reports_a_running_server(self, store: Path, quiet_module: dict, detachable) -> None:
        """pid, bind and log — the three things an operator asks for next."""
        detachable.server_state.return_value = {
            "state": "running",
            "reason": "",
            "record": {
                "pid": 4242,
                "host": "127.0.0.1",
                "port": 8790,
                "log": str(STANDIN_LOG),
                "started": "2026-08-19 18:00:00",
            },
        }

        handle_command("host-api", ["status"])

        printed = _printed(quiet_module["console"].print)
        printed += _printed(quiet_module["success"])

        assert "4242" in printed
        assert "8790" in printed

    def test_status_says_it_cannot_tell_rather_than_inventing_an_absence(
        self, store: Path, quiet_module: dict, detachable
    ) -> None:
        """Status prints that it cannot tell when the supervisor is silent, never "No server is running"."""
        detachable.server_state.return_value = {
            "state": "unknown",
            "record": None,
            "reason": "systemctl is here but did not answer",
        }
        detachable.log_path.return_value = STANDIN_LOG

        handle_command("host-api", ["status"])

        printed = _printed(quiet_module["console"].print)
        printed += _printed(quiet_module["error"])

        assert [c.args for c in quiet_module["error"].call_args_list] == [
            ("Cannot tell — the supervisor did not answer",)
        ]
        assert "did not answer" in printed
        assert "No server is running" not in printed

    def test_stopping_nothing_is_not_an_error(self, store: Path, quiet_module: dict, detachable) -> None:
        """Running `stop` twice must be safe — the second has nothing to do."""
        detachable.stop.return_value = None

        handle_command("host-api", ["stop"])

        quiet_module["error"].assert_not_called()

    def test_a_server_that_will_not_stop_is_reported_not_swallowed(
        self,
        store: Path,
        quiet_module: dict,
        detachable,
    ) -> None:
        """Never silently escalated, never silently given up on."""
        detachable.stop.side_effect = host_lifetime.LifetimeError("did not exit within 10.0s")

        handle_command("host-api", ["stop"])

        quiet_module["error"].assert_called_once_with("did not exit within 10.0s")


@pytest.fixture
def extra_present():
    """
    Pin the [host] extra as installed.

    `_cmd_serve` returns early without it, so a gate test would pass without running.
    """
    with patch.object(host_server, "is_available", return_value=True):
        yield


class TestServeCommand:
    """Serving is gated on the bind rule."""

    def test_bind_refusal_is_reported_and_server_never_starts(
        self,
        store: Path,
        quiet_module: dict,
        extra_present: None,
    ) -> None:
        """A refused bind must surface as an error, not a traceback, and above
        all must not reach a listener."""
        with patch.object(host_server, "serve", side_effect=host_config.BindRefused("nope")) as mock_serve:
            with pytest.raises(SystemExit):
                handle_command("host-api", ["serve", "--host", "0.0.0.0"])

        mock_serve.assert_called_once()
        quiet_module["error"].assert_called_once()

    def test_a_refused_bind_exits_non_zero_so_systemd_can_retry(
        self,
        store: Path,
        quiet_module: dict,
        extra_present: None,
    ) -> None:
        """
        The exit CODE, not just the message — this one is load-bearing.

        At boot the tailnet address can arrive after the server; exit 0 disarms Restart=on-failure.
        """
        with patch.object(host_server, "serve", side_effect=host_config.BindRefused("nope")):
            with pytest.raises(SystemExit) as exit_info:
                handle_command("host-api", ["serve", "--host", "0.0.0.0"])

        assert exit_info.value.code == 1, "a refused bind must exit non-zero or Restart=on-failure never fires"

    def test_non_numeric_port_refused_before_serving(
        self,
        store: Path,
        quiet_module: dict,
        extra_present: None,
    ) -> None:
        """A bad --port is caught in the CLI, never handed to the server."""
        with patch.object(host_server, "serve") as mock_serve:
            handle_command("host-api", ["serve", "--port", "eighty"])

        mock_serve.assert_not_called()
        quiet_module["error"].assert_called_once()

    def test_port_check_is_what_refuses_it_not_the_install_gate(
        self,
        store: Path,
        quiet_module: dict,
        extra_present: None,
    ) -> None:
        """
        The regression guard for the false pass above.

        A valid --port must REACH serve, or 'refused before serving' proves nothing.
        """
        with patch.object(host_server, "serve") as mock_serve:
            handle_command("host-api", ["serve", "--port", "8790"])

        mock_serve.assert_called_once()
        quiet_module["error"].assert_not_called()

    def test_missing_extra_reports_install_hint(self, store: Path, quiet_module: dict) -> None:
        """Without the extra, the operator gets instructions, not an ImportError."""
        with patch.object(host_server, "is_available", return_value=False):
            handle_command("host-api", ["serve"])

        quiet_module["error"].assert_called_once_with(
            "Server libraries not installed", suggestion=host_server.INSTALL_HINT
        )


class TestSetConfigCommand:
    """Writing the bind address is itself a security control."""

    def test_stores_a_valid_bind(self, store: Path, quiet_module: dict) -> None:
        """The ordinary case: a loopback bind is accepted and persisted."""
        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["set-config", "--host", "127.0.0.1", "--port", "9100"])
            config = host_config.load_config()

        assert config == {"host": "127.0.0.1", "port": 9100}

    def test_the_saved_line_names_the_entry_never_a_path(self, store: Path, quiet_module: dict) -> None:
        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["set-config", "--host", "127.0.0.1", "--port", "9100"])

        printed = " ".join(str(call.args[0]) for call in quiet_module["console"].print.call_args_list if call.args)
        assert "host_api/config" in printed
        assert str(store) not in printed

    def test_refuses_to_store_a_bind_that_would_not_start(self, store: Path, quiet_module: dict) -> None:
        """Validate before storing, so the refusal reaches the person who typed
        it rather than surfacing at 3am when the server will not come up."""
        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["set-config", "--host", "0.0.0.0"])
            config = host_config.load_config()

        quiet_module["error"].assert_called_once()
        assert config["host"] == host_config.DEFAULT_HOST

    def test_no_flags_is_an_error(self, store: Path, quiet_module: dict) -> None:
        """A set command with nothing to set is a mistake, not a no-op."""
        handle_command("host-api", ["set-config"])

        assert [c.args for c in quiet_module["error"].call_args_list] == [("Nothing to set",)]

    def test_non_numeric_port_refused(self, store: Path, quiet_module: dict) -> None:
        """A bad port never reaches the store."""
        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["set-config", "--port", "eighty"])

        quiet_module["error"].assert_called_once()
        assert host_config.load_config()["port"] == host_config.DEFAULT_PORT

    def test_face_dir_is_validated_and_stored(self, store: Path, quiet_module: dict, tmp_path: Path) -> None:
        """The CLI door @aipass's installer names when it cannot call in-process."""
        bundle = _face_bundle(tmp_path / "face")

        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["set-config", "--face-dir", str(bundle)])

        quiet_module["error"].assert_not_called()
        assert host_config.face_dir() == bundle

    def test_face_dir_default_clears_it(self, store: Path, quiet_module: dict, tmp_path: Path) -> None:
        """'default' is the spelling for 'serve the checkout build again'."""
        with patch(PATCH_CONFIG_LOGGER):
            host_config.set_face_dir(_face_bundle(tmp_path / "face"))
            handle_command("host-api", ["set-config", "--face-dir", "default"])

        quiet_module["error"].assert_not_called()
        assert host_config.face_dir() is None

    def test_a_refused_face_dir_is_an_error_that_says_why(
        self, store: Path, quiet_module: dict, tmp_path: Path
    ) -> None:
        """The refusal's own sentence reaches the operator, and nothing is stored."""
        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["set-config", "--face-dir", str(tmp_path / "never-built")])

        assert [c.args for c in quiet_module["error"].call_args_list] == [
            ("Refusing to store a face dir that would not serve",)
        ]
        assert "not a directory" in str(quiet_module["error"].call_args)
        assert host_config.face_dir() is None

    def test_a_refused_face_dir_stores_no_bind_either(self, store: Path, quiet_module: dict, tmp_path: Path) -> None:
        """One command, one outcome: half of a refused command is not stored."""
        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["set-config", "--port", "9100", "--face-dir", str(tmp_path / "never-built")])

        quiet_module["error"].assert_called_once()
        assert host_config.load_config()["port"] == host_config.DEFAULT_PORT

    def test_a_refused_bind_stores_no_face_dir_either(self, store: Path, quiet_module: dict, tmp_path: Path) -> None:
        """The other half of the same promise."""
        bundle = _face_bundle(tmp_path / "face")

        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["set-config", "--host", "0.0.0.0", "--face-dir", str(bundle)])

        assert [c.args for c in quiet_module["error"].call_args_list] == [
            ("Refusing to store a bind that would not start",)
        ]
        assert host_config.face_dir() is None

    def test_bind_and_face_dir_together_keep_both(self, store: Path, quiet_module: dict, tmp_path: Path) -> None:
        """The bind write must not overwrite the face_dir stored a moment before it."""
        bundle = _face_bundle(tmp_path / "face")

        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["set-config", "--port", "9100", "--face-dir", str(bundle)])
            config = host_config.load_config()

        quiet_module["error"].assert_not_called()
        assert config["port"] == 9100
        assert config["face_dir"] == str(bundle)

    def test_face_dir_alone_does_not_revalidate_a_stored_bind(
        self, store: Path, quiet_module: dict, tmp_path: Path
    ) -> None:
        """The installer points the face while the stored address may be down."""
        bundle = _face_bundle(tmp_path / "face")

        with patch(PATCH_CONFIG_LOGGER):
            host_config.save_config({"host": UNHELD_ADDRESS, "port": 8787})
            handle_command("host-api", ["set-config", "--face-dir", str(bundle)])

        quiet_module["error"].assert_not_called()
        assert host_config.face_dir() == bundle

    def test_a_save_is_logged_without_the_store_path(self, store: Path) -> None:
        """
        The caller gets the entry name back; the log line names the store in words.

        CodeQL follows the secret-named call's result into a log as clear-text secret data.
        """
        with patch(PATCH_CONFIG_LOGGER) as log:
            written = host_config.save_config({"host": UNHELD_ADDRESS, "port": 8787})

        assert written == "host_api/config"
        logged = " ".join(str(arg) for arg in log.info.call_args.args)
        assert "config saved to the host_api config in the secrets store" in logged
        assert written not in logged
        assert str(store) not in logged

    def test_a_home_relative_face_dir_is_expanded(
        self, store: Path, quiet_module: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A quoted ~ reaches this command unexpanded; the store only ever holds absolute paths."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        bundle = _face_bundle(tmp_path / "face")

        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["set-config", "--face-dir", "~/face"])

        quiet_module["error"].assert_not_called()
        assert host_config.face_dir() == bundle

    def test_baud_bin_is_validated_and_stored(self, store: Path, quiet_module: dict, tmp_path: Path) -> None:
        """The CLI door beside the installer's in-process one."""
        binary = _baud_binary(tmp_path / "bin" / "baud-cli")

        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["set-config", "--baud-bin", str(binary)])

        quiet_module["error"].assert_not_called()
        assert host_config.baud_bin() == binary

    def test_baud_bin_default_clears_it(self, store: Path, quiet_module: dict, tmp_path: Path) -> None:
        """'default' hands the lanes back to the automatic lookup."""
        with patch(PATCH_CONFIG_LOGGER):
            host_config.set_baud_bin(_baud_binary(tmp_path / "baud-cli"))
            handle_command("host-api", ["set-config", "--baud-bin", "default"])

        quiet_module["error"].assert_not_called()
        assert host_config.baud_bin() is None

    def test_a_refused_baud_bin_is_an_error_that_says_why(
        self, store: Path, quiet_module: dict, tmp_path: Path
    ) -> None:
        """The failing leg's own sentence reaches the operator, and nothing is stored."""
        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["set-config", "--baud-bin", str(tmp_path / "never-installed")])

        assert [c.args for c in quiet_module["error"].call_args_list] == [
            ("Refusing to store a baud binary that would not run",)
        ]
        assert "does not exist" in str(quiet_module["error"].call_args)
        assert host_config.baud_bin() is None

    def test_a_refused_baud_bin_stores_no_face_dir_either(
        self, store: Path, quiet_module: dict, tmp_path: Path
    ) -> None:
        """Every path is validated before any is stored."""
        bundle = _face_bundle(tmp_path / "face")

        with patch(PATCH_CONFIG_LOGGER):
            handle_command(
                "host-api",
                ["set-config", "--face-dir", str(bundle), "--baud-bin", str(tmp_path / "never-installed")],
            )

        assert [c.args for c in quiet_module["error"].call_args_list] == [
            ("Refusing to store a baud binary that would not run",)
        ]
        assert host_config.face_dir() is None
        assert host_config.baud_bin() is None


class TestFlagParsing:
    """The small helper every command reads its options through."""

    def test_absent_flag_returns_none(self) -> None:
        """A flag nobody passed has no value."""
        assert host_serve_module.flag_value(["serve"], "--host") is None

    def test_flag_at_end_without_value_returns_none(self) -> None:
        """A dangling flag is not a value, and must not read past the list."""
        assert host_serve_module.flag_value(["serve", "--host"], "--host") is None

    def test_flag_followed_by_another_flag_returns_none(self) -> None:
        """'--host --port 80' has no host — reading '--port' as one would bind junk."""
        assert host_serve_module.flag_value(["serve", "--host", "--port", "80"], "--host") is None

    def test_returns_the_value(self) -> None:
        """The ordinary case."""
        assert host_serve_module.flag_value(["serve", "--host", "127.0.0.1"], "--host") == "127.0.0.1"


class TestIntrospection:
    """The module's self-map stays honest about the phase gate."""

    def test_introspection_names_the_serve_verb(self, store: Path) -> None:
        """Bare `drone @api host-api` prints a self-map that names its verbs."""
        with patch(PATCH_MOD_CONSOLE) as mock_console, patch(PATCH_MOD_HEADER), patch(PATCH_CONFIG_LOGGER):
            host_api_module.print_introspection()

        printed = _printed(mock_console.print)
        assert "serve" in printed

    def test_help_names_every_subcommand_it_routes(self) -> None:
        """Help output is Rich markup and must name the four verbs."""
        with patch(PATCH_MOD_CONSOLE) as mock_console:
            host_api_module.print_help()

        printed = _printed(mock_console.print)
        missing = [verb for verb in host_serve_module.SUBCOMMANDS if verb not in printed]

        assert missing == [], f"help does not name these routed verbs: {missing}"

    def test_config_command_reports_refusal_without_raising(self, store: Path, quiet_module: dict) -> None:
        """`host-api config` on a bad address warns rather than exploding."""
        with patch(PATCH_CONFIG_LOGGER):
            host_config.save_config({"host": TAILNET_SHAPED, "port": 8787})
            handle_command("host-api", ["config"])

        quiet_module["warning"].assert_called_once_with("Bind address would be REFUSED")

    def test_help_does_not_claim_loopback_only_while_the_gate_is_open(self) -> None:
        """
        It did until 2026-09-13: 'Phase 1 is loopback-only' a month after the
        gate opened. The sentence is read from LOOPBACK_ONLY now."""
        with patch(PATCH_MOD_CONSOLE) as mock_console, patch.object(host_config, "LOOPBACK_ONLY", False):
            host_api_module.print_help()

        printed = _printed(mock_console.print).lower()
        assert "loopback-only" not in printed
        assert "loopback only" not in printed

    def test_help_says_loopback_only_when_the_gate_is_closed(self) -> None:
        """The same sentence, read the other way: closing the gate changes the help too."""
        with patch(PATCH_MOD_CONSOLE) as mock_console, patch.object(host_config, "LOOPBACK_ONLY", True):
            host_api_module.print_help()

        printed = _printed(mock_console.print).lower()
        assert "loopback-only" in printed

    def test_help_names_the_face_dir_flag(self) -> None:
        """A setting the help never mentions is a setting nobody finds."""
        with patch(PATCH_MOD_CONSOLE) as mock_console:
            host_api_module.print_help()

        printed = _printed(mock_console.print)
        assert "--face-dir" in printed

    def test_config_shows_a_configured_face_dir_and_its_entry(
        self, store: Path, quiet_module: dict, tmp_path: Path
    ) -> None:
        """The effective face dir, the source that named it, and whether phone.html is there."""
        bundle = _face_bundle(tmp_path / "face")

        with patch(PATCH_CONFIG_LOGGER):
            host_config.set_face_dir(bundle)
            handle_command("host-api", ["config"])

        printed = _printed(quiet_module["console"].print)
        assert str(bundle) in printed
        assert f"({host_face.SOURCE_CONFIGURED})" in printed
        assert "present" in printed

    def test_config_says_when_the_configured_entry_is_missing(
        self, store: Path, quiet_module: dict, tmp_path: Path
    ) -> None:
        """Stored while valid, emptied since: the preview says so before a restart does."""
        bundle = _face_bundle(tmp_path / "face")

        with patch(PATCH_CONFIG_LOGGER):
            host_config.set_face_dir(bundle)
            (bundle / host_config.FACE_ENTRY).unlink()
            handle_command("host-api", ["config"])

        printed = _printed(quiet_module["console"].print)
        assert "missing" in printed
        assert "present" not in printed

    def test_config_names_the_checkout_default_when_unset(self, store: Path, quiet_module: dict) -> None:
        """Unset is not blank: the preview names the checkout build it falls to."""
        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["config"])

        printed = _printed(quiet_module["console"].print)
        assert f"({host_face.SOURCE_CHECKOUT})" in printed
        assert str(host_face.face_root()) in printed

    @pytest.fixture
    def lookups(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
        """Empty stand-ins for the home, checkout and PATH the binary lookup reads. Returns the checkout."""
        home = tmp_path / "home"
        repo = tmp_path / "repo"
        home.mkdir()
        repo.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        monkeypatch.setattr(host_fleet, "repo_root", lambda: repo)
        monkeypatch.setattr(host_fleet.shutil, "which", lambda _name: None)
        return repo

    def test_help_names_the_baud_bin_flag(self) -> None:
        """A setting the help never mentions is a setting nobody finds."""
        with patch(PATCH_MOD_CONSOLE) as mock_console:
            host_api_module.print_help()

        printed = _printed(mock_console.print)
        assert "--baud-bin" in printed

    def test_config_names_a_configured_binary_and_that_it_runs(
        self, store: Path, quiet_module: dict, tmp_path: Path, lookups: Path
    ) -> None:
        """The binary line: the path, the source word, and whether it is executable."""
        binary = _baud_binary(tmp_path / "bin" / "baud-cli")

        with patch(PATCH_CONFIG_LOGGER):
            host_config.set_baud_bin(binary)
            handle_command("host-api", ["config"])

        printed = _printed(quiet_module["console"].print)
        assert f"{binary} [dim]({host_fleet.SOURCE_CONFIGURED})" in printed
        assert "[green]yes[/green]" in printed

    def test_config_says_a_gone_configured_binary_will_be_refused(
        self, store: Path, quiet_module: dict, tmp_path: Path, lookups: Path
    ) -> None:
        """Still named as configured, marked not runnable, with the cure — before a phone finds out."""
        binary = _baud_binary(tmp_path / "bin" / "baud-cli")

        with patch(PATCH_CONFIG_LOGGER):
            host_config.set_baud_bin(binary)
            binary.unlink()
            handle_command("host-api", ["config"])

        printed = _printed(quiet_module["console"].print)
        assert f"{binary} [dim]({host_fleet.SOURCE_CONFIGURED})" in printed
        assert "[yellow]no[/yellow]" in printed
        assert "--baud-bin default" in printed

    def test_config_names_the_checkout_binary_when_nothing_is_configured(
        self, store: Path, quiet_module: dict, lookups: Path
    ) -> None:
        """Unset is not blank: the line names the step of the lookup that answers."""
        desktop = _baud_binary(lookups / host_fleet.DEFAULT_BINARY_RELATIVE)

        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["config"])

        printed = _printed(quiet_module["console"].print)
        assert f"{desktop} [dim]({host_fleet.SOURCE_CHECKOUT})" in printed

    def test_config_says_missing_and_how_to_install(self, store: Path, quiet_module: dict, lookups: Path) -> None:
        """Nothing anywhere: the source word is missing and the cure is on the next line."""
        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["config"])

        printed = _printed(quiet_module["console"].print)
        assert f"not found [dim]({host_fleet.SOURCE_MISSING})" in printed
        assert "Install it: aipass baud install." in printed


class TestCrossBranchApi:
    """The module-level functions other branches would import."""

    def test_issue_and_revoke_round_trip(self, store: Path) -> None:
        """The public surface mirrors the handler behaviour."""
        record, raw = host_api_module.issue_token("pixel-8")
        assert host_tokens.verify_token(raw) is not None

        assert host_api_module.revoke_token(record["id"]) is True
        assert host_tokens.verify_token(raw) is None

    def test_serve_delegates_to_the_handler(self) -> None:
        """The module orchestrates; the handler implements."""
        with patch.object(host_server, "serve") as mock_serve:
            host_api_module.serve(host="127.0.0.1", port=9000)

        mock_serve.assert_called_once_with(host="127.0.0.1", port=9000)

    def test_the_path_settings_door_stores_and_clears_through_the_handler(self, store: Path, tmp_path: Path) -> None:
        """@aipass sets the face dir and the baud binary through the module, not the handler."""
        bundle = _face_bundle(tmp_path / "face")
        binary = _baud_binary(tmp_path / "bin" / "baud-cli")

        with patch(PATCH_CONFIG_LOGGER):
            assert host_api_module.set_face_dir(bundle) == bundle
            assert host_api_module.set_baud_bin(binary) == binary

            assert host_api_module.face_dir() == host_config.face_dir() == bundle
            assert host_api_module.baud_bin() == host_config.baud_bin() == binary
            assert host_api_module.load_config()[host_config.BAUD_BIN_KEY] == str(binary)

            assert host_api_module.set_baud_bin(None) is None
            assert host_api_module.set_face_dir(None) is None

        assert host_config.baud_bin() is None
        assert host_config.face_dir() is None

    def test_the_door_refuses_with_the_handler_exceptions(self, store: Path, tmp_path: Path) -> None:
        """A caller catching the module's names catches exactly what the handler raises."""
        assert host_api_module.BaudBinRefused is host_config.BaudBinRefused
        assert host_api_module.FaceDirRefused is host_config.FaceDirRefused

        with patch(PATCH_CONFIG_LOGGER):
            with pytest.raises(host_api_module.BaudBinRefused, match="does not exist"):
                host_api_module.set_baud_bin(tmp_path / "no-such-baud-cli")
            with pytest.raises(host_api_module.FaceDirRefused, match="is not a directory"):
                host_api_module.set_face_dir(tmp_path / "no-such-face")

        stored = host_config.load_config()
        assert host_config.BAUD_BIN_KEY not in stored
        assert host_config.FACE_DIR_KEY not in stored

    def test_set_bind_stores_the_bind_and_reports_what_it_replaced(self, store: Path) -> None:
        """The installer writes the bind in-process, same store as set-config."""
        with patch(PATCH_CONFIG_LOGGER):
            result = host_api_module.set_bind("127.0.0.1", 9100)
            config = host_config.load_config()

        assert result == {
            "host": "127.0.0.1",
            "port": 9100,
            "changed": True,
            "previous": {"host": host_config.DEFAULT_HOST, "port": host_config.DEFAULT_PORT},
        }
        assert (config["host"], config["port"]) == ("127.0.0.1", 9100)

    def test_set_bind_refuses_a_wildcard_and_stores_nothing(self, store: Path) -> None:
        with patch(PATCH_CONFIG_LOGGER):
            with pytest.raises(host_api_module.BindRefused):
                host_api_module.set_bind("0.0.0.0", 9100)
            config = host_config.load_config()

        assert host_api_module.BindRefused is host_config.BindRefused
        assert (config["host"], config["port"]) == (host_config.DEFAULT_HOST, host_config.DEFAULT_PORT)

    def test_set_bind_keeps_a_bind_already_stored_without_writing_it_again(self, store: Path) -> None:
        """Idempotent: a second install on the same bind is a no-op, not a rewrite."""
        with patch(PATCH_CONFIG_LOGGER):
            host_api_module.set_bind("127.0.0.1", 9100)
            with patch.object(host_config, "save_config") as save:
                result = host_api_module.set_bind("127.0.0.1", 9100)

        save.assert_not_called()
        assert result["changed"] is False
        assert result["previous"] == {"host": "127.0.0.1", "port": 9100}

    def test_receipt_path_is_the_token_store_receipt(self, store: Path) -> None:
        """The installer asks for the path rather than restating it."""
        assert host_api_module.receipt_path("pixel-8") == host_tokens.receipt_path("pixel-8")
        assert host_api_module.receipt_path("pixel-8").name == "pixel-8.token"

        with pytest.raises(host_api_module.TokenError):
            host_api_module.receipt_path("..")
