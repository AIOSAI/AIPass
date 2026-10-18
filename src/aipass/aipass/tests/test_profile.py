# =================== AIPass ====================
# Name: test_profile.py
# Description: Tests for aipass profile Phase 3
# Version: 1.2.6
# Created: 2026-04-16
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/profile.py and the handlers it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/modules/profile.py parses and imports
# seedgo: no-test-needed(constant) — USER_FIELDS' literal contents and the store's filename

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.aipass.apps.modules import profile as profile_mod
from aipass.aipass.apps.modules.profile import (
    USER_FIELDS,
    get_user_profile,
    handle_command,
    print_help,
    print_introspection,
    save_profile,
)


@pytest.fixture
def tmp_store(tmp_path):
    """Patch BOTH profile paths into tmp_path and yield the store path.

    An unpatched _LEGACY_LOCAL_JSON would let a defaults test read the live profile.
    """
    store = tmp_path / "aipass_json" / "user_profile.json"
    store.parent.mkdir(parents=True)
    legacy = tmp_path / ".trinity" / "local.json"
    legacy.parent.mkdir(parents=True)
    with patch("aipass.aipass.apps.modules.profile._PROFILE_JSON", store):
        with patch("aipass.aipass.apps.modules.profile._LEGACY_LOCAL_JSON", legacy):
            yield store


class _CtrlCStdin(io.StringIO):
    """A stdin the user presses Ctrl-C on: input() reads it and gets KeyboardInterrupt.

    The product's own input() runs; nothing process-wide is replaced.
    """

    def readline(self, size: int | None = -1) -> str:
        """Raise as a terminal does when Ctrl-C arrives mid-read."""
        raise KeyboardInterrupt


@pytest.fixture
def tmp_legacy(tmp_store):
    """Return the patched legacy local.json path alongside the store."""
    return tmp_store.parent.parent / ".trinity" / "local.json"


@pytest.fixture
def tmp_store_with_data(tmp_store):
    """Pre-populate the store with a full profile."""
    data = {"profile": {f: f"test_{f}" for f in USER_FIELDS}}
    tmp_store.write_text(json.dumps(data), encoding="utf-8")
    return tmp_store


class TestLiveStoreIsolation:
    """The suite must never write the branch's real profile store."""

    def test_store_path_is_not_the_live_branch_file(
        self, isolate_profile_store: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """conftest's autouse guard has redirected both profile paths, seen through `aipass profile`.

        The legacy read is the guard's temp file; the store write is recorded, never performed.
        """
        live_store = Path(profile_mod.__file__).parents[2] / "aipass_json" / "user_profile.json"
        (isolate_profile_store / "local.json").write_text(
            json.dumps({"user": {"name": "LegacyProbe"}}), encoding="utf-8"
        )
        with (
            patch("aipass.aipass.apps.modules.profile.json_handler.write_json", return_value=True) as mock_write,
            patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"),
        ):
            assert handle_command("profile", []) is True

        assert "LegacyProbe" in capsys.readouterr().out
        written = Path(mock_write.call_args[0][0])
        assert written == isolate_profile_store / "user_profile.json"
        assert written != live_store

    def test_unmocked_save_lands_in_the_temp_store(self, isolate_profile_store) -> None:
        """A save with no local patching writes under the guard's temp dir."""
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            save_profile({"name": "IsolationProbe"})
        written = isolate_profile_store / "user_profile.json"
        assert json.loads(written.read_text(encoding="utf-8"))["profile"]["name"] == "IsolationProbe"


class TestWriteDurability:
    """The two behaviours the hand-rolled writer carried, kept after the refactor.

    A REAL failure inside write_json, not a stub returning False: a stub would pass even if
    the save stopped being atomic.
    """

    @staticmethod
    def _fail_the_replace():
        """Patch the json service's replace step to raise, as a full disk would.

        Through prax's package path: the fence refuses a foreign import of its handlers.
        """
        return patch(
            "aipass.prax.json_handler.replace_with_retry",
            side_effect=OSError("no space left on device"),
        )

    @staticmethod
    def _assert_one_write_failed_fire(mock_trigger, store: Path) -> None:
        """The failed save fired its one bus event, with the full payload profile.py sends."""
        mock_trigger.fire.assert_called_once_with(
            "profile_write_failed",
            path=str(store),
            reason="write_failure_cleanup",
            detail="json_handler removed its own temp file; the store was left untouched",
        )

    def test_oserror_mid_write_leaves_the_store_byte_intact(self, tmp_store) -> None:
        """A failed save must not half-write or truncate the previous profile.

        Mutant: the fired path str(_PROFILE_JSON) -> str(_LEGACY_LOCAL_JSON) reddens this.
        """
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            save_profile({"name": "Original", "os": "Linux"})
        before = tmp_store.read_bytes()

        with (
            self._fail_the_replace(),
            patch("aipass.trigger.apps.modules.core.trigger") as mock_trigger,
            patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"),
        ):
            with pytest.raises(OSError):
                save_profile({"name": "Replacement", "os": "Windows"})

        assert tmp_store.read_bytes() == before
        assert get_user_profile()["name"] == "Original"
        self._assert_one_write_failed_fire(mock_trigger, tmp_store)

    def test_failed_write_leaves_no_temp_file_behind(self, tmp_store) -> None:
        """The handler unlinks its own temp file on the failure path; the bus is patched where it lives."""
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            save_profile({"name": "Original"})

        with (
            self._fail_the_replace(),
            patch("aipass.trigger.apps.modules.core.trigger") as mock_trigger,
            patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"),
        ):
            with pytest.raises(OSError):
                save_profile({"name": "Replacement"})

        leftovers = [p.name for p in tmp_store.parent.iterdir() if p.name != tmp_store.name]
        assert leftovers == []
        self._assert_one_write_failed_fire(mock_trigger, tmp_store)

    def test_write_failure_raises_instead_of_answering_false(self, tmp_store) -> None:
        """json_handler answers False; save_profile must not pass that off as success.

        The FIRST save, no store on disk yet: it raises, fires, and leaves no store behind.
        """
        assert not tmp_store.exists()
        with (
            self._fail_the_replace(),
            patch("aipass.trigger.apps.modules.core.trigger") as mock_trigger,
            patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"),
        ):
            with pytest.raises(OSError):
                save_profile({"name": "Doomed"})

        assert not tmp_store.exists()
        self._assert_one_write_failed_fire(mock_trigger, tmp_store)

    def test_trigger_fires_on_write_failure(self, tmp_store) -> None:
        """The write-failure event fires under its true name, with the payload kept.

        Never the old ``file_deleted``: that alias is trigger's to keep, not this module's to emit.
        """
        with patch("aipass.trigger.apps.modules.core.trigger") as mock_trigger:
            with self._fail_the_replace():
                with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
                    with pytest.raises(OSError):
                        save_profile({"name": "Doomed"})

        mock_trigger.fire.assert_called_once()
        event, kwargs = mock_trigger.fire.call_args[0][0], mock_trigger.fire.call_args[1]
        assert event == "profile_write_failed"
        assert event != "file_deleted"
        assert kwargs["reason"] == "write_failure_cleanup"
        assert kwargs["path"] == str(tmp_store)

    def test_successful_save_fires_nothing(self, tmp_store) -> None:
        """The counterfactual: without it the fire-test could pass on any call."""
        with patch("aipass.trigger.apps.modules.core.trigger") as mock_trigger:
            with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
                save_profile({"name": "Fine"})

        mock_trigger.fire.assert_not_called()

    def test_module_does_no_direct_file_operations(self) -> None:
        """The seedgo modules rule, pinned here so it cannot regress silently."""
        source = Path(profile_mod.__file__).read_text(encoding="utf-8")
        body = [line for line in source.splitlines() if line.strip() and not line.strip().startswith("#")]
        for forbidden in (".mkdir(", ".write_text(", ".read_text(", "json.dump(", "json.load("):
            offenders = [line.strip() for line in body if forbidden in line]
            assert offenders == [], f"{forbidden} -> {offenders}"


class TestRoundTrip:
    """A save must survive its own log_operation call."""

    def test_save_then_read_round_trips(self, tmp_store) -> None:
        """Real json_handler, no mocks: the store is not clobbered by logging.

        ensure_module_jsons regenerates <module>_data.json, so the store must not use that name.
        """
        save_profile({f: f"kept_{f}" for f in USER_FIELDS})
        assert get_user_profile()["name"] == "kept_name"
        assert json.loads(tmp_store.read_text(encoding="utf-8"))["profile"]["os"] == "kept_os"

    def test_store_name_is_outside_the_managed_triplet(self, isolate_profile_store) -> None:
        """The filename must not collide with <module>_{config,data,log}.json."""
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            save_profile({"name": "NameProbe"})
        written = {p.name for p in isolate_profile_store.iterdir() if p.is_file()}
        assert written == {"user_profile.json"}
        assert "user_profile.json" not in (
            "profile_config.json",
            "profile_data.json",
            "profile_log.json",
        )


class TestGetUserProfile:
    def test_creates_defaults_when_no_file(self, tmp_store) -> None:
        """Returns default None-filled profile when local.json absent."""
        result = get_user_profile()
        assert set(result.keys()) == set(USER_FIELDS)
        assert all(v is None for v in result.values())

    def test_reads_existing_profile(self, tmp_store_with_data) -> None:
        """Returns stored values when user section exists."""
        result = get_user_profile()
        assert result["name"] == "test_name"
        assert result["os"] == "test_os"

    def test_creates_profile_section_if_missing(self, tmp_store) -> None:
        """Writes defaults to disk when the profile key is absent."""
        tmp_store.write_text(json.dumps({"other": "data"}), encoding="utf-8")
        result = get_user_profile()
        assert all(v is None for v in result.values())
        stored = json.loads(tmp_store.read_text(encoding="utf-8"))
        assert "profile" in stored

    def test_adopts_legacy_user_section(self, tmp_store, tmp_legacy) -> None:
        """A pre-1.1.0 local.json "user" section is read when the store is absent."""
        tmp_legacy.write_text(json.dumps({"sessions": [], "user": {"name": "Bob", "os": "Linux"}}), encoding="utf-8")
        result = get_user_profile()
        assert result["name"] == "Bob"
        assert result["os"] == "Linux"
        assert result["shell"] is None
        assert json.loads(tmp_store.read_text(encoding="utf-8"))["profile"]["name"] == "Bob"

    def test_legacy_local_json_is_never_written(self, tmp_store, tmp_legacy) -> None:
        """Reading and saving leave local.json byte-identical -- .trinity is not ours."""
        original = json.dumps({"sessions": [1, 2, 3], "user": {"name": "Bob"}})
        tmp_legacy.write_text(original, encoding="utf-8")
        get_user_profile()
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            save_profile({"name": "Changed"})
        assert tmp_legacy.read_text(encoding="utf-8") == original

    def test_store_wins_over_legacy(self, tmp_store, tmp_legacy) -> None:
        """Once the store exists the legacy section is ignored, not merged."""
        tmp_store.write_text(json.dumps({"profile": {"name": "Store"}}), encoding="utf-8")
        tmp_legacy.write_text(json.dumps({"user": {"name": "Legacy"}}), encoding="utf-8")
        assert get_user_profile()["name"] == "Store"

    def test_returns_empty_dict_on_corrupt_file(self, tmp_store) -> None:
        """Corrupt JSON degrades to the full field set, every value None."""
        tmp_store.write_text("NOT JSON", encoding="utf-8")
        result = get_user_profile()
        assert isinstance(result, dict)
        assert result == {field: None for field in USER_FIELDS}

    def test_all_user_fields_present(self, tmp_store) -> None:
        """All USER_FIELDS keys are present in returned profile.

        A store predating the other fields. Mutant: stored dict returned as is (no fill-in) -> red.
        """
        tmp_store.write_text(json.dumps({"profile": {"name": "Bob"}}), encoding="utf-8")
        result = get_user_profile()
        assert result == {
            "name": "Bob",
            "os": None,
            "shell": None,
            "preferred_cli": None,
            "install_method": None,
            "first_seen": None,
        }


class TestSaveProfile:
    def test_saves_profile_to_disk(self, tmp_store) -> None:
        """Profile dict is written to user section of local.json."""
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            save_profile({"name": "user", "os": "Linux"})
        stored = json.loads(tmp_store.read_text(encoding="utf-8"))
        assert stored["profile"]["name"] == "user"

    def test_save_replaces_whole_profile(self, tmp_store) -> None:
        """The store holds only the profile -- a save is a full replace."""
        tmp_store.write_text(json.dumps({"profile": {"name": "Old", "os": "Linux"}}), encoding="utf-8")
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            save_profile({"name": "Bob"})
        stored = json.loads(tmp_store.read_text(encoding="utf-8"))
        assert stored["profile"] == {"name": "Bob"}

    def test_logs_operation(self, tmp_store) -> None:
        """json_handler.log_operation is called on save."""
        # Patch the attribute, not the shim: a MagicMock shim invents log_operation, so a
        # rename would stay green; patch() itself raises the day the name moves.
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation") as mock_log:
            save_profile({"name": "Test"})
        # Mutant: log_operation("profile_save", ...) -> ("profile_saved", ...) -> red.
        mock_log.assert_called_once_with("profile_save", {"fields": ["name"]})

    def test_creates_parent_dirs(self, tmp_path) -> None:
        """Missing aipass_json/ directory is created on write."""
        deep_path = tmp_path / "a" / "b" / "aipass_json" / "user_profile.json"
        with patch("aipass.aipass.apps.modules.profile._PROFILE_JSON", deep_path):
            with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
                save_profile({"name": "Test"})
        assert deep_path.exists()


class TestPrintIntrospection:
    def test_does_not_raise(self, tmp_store, capsys) -> None:
        """print_introspection renders through the REAL console without raising.

        The only test where Rich really renders this function: a malformed markup tag
        fails here and leaves the console-patched sibling green.
        """
        print_introspection()
        rendered = capsys.readouterr().out
        # The first line, not a substring: the set-hint carries the same three words.
        lines = [line.strip() for line in rendered.splitlines() if line.strip()]
        assert lines[0] == "aipass profile"
        for field in USER_FIELDS:
            assert field in rendered, f"{field} is missing from the rendered table"

    def test_outputs_field_names(self, tmp_store, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: set-hint line dropped -> red."""
        print_introspection()
        out, _err = capsys.readouterr()
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        assert lines[0] == "aipass profile"
        positions = [out.index(field) for field in USER_FIELDS]
        assert positions == sorted(positions)
        assert "Use 'aipass profile set <field> <value>' to update." in out


class TestPrintHelp:
    def test_prints_something(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: FIELDS line dropped from help -> red."""
        print_help()
        out, _err = capsys.readouterr()
        assert "aipass profile — user memory read/write" in out
        assert "FIELDS: " + ", ".join(USER_FIELDS) in out


class TestHandleCommand:
    def test_wrong_command_returns_false(self) -> None:
        """Non-profile commands are not handled."""
        assert handle_command("doctor", []) is False
        assert handle_command("init", ["run"]) is False

    def test_no_args_calls_introspection(self, tmp_store) -> None:
        """'profile' with no args shows the profile (runs the command)."""
        with patch("aipass.aipass.apps.modules.profile.print_introspection") as mock_pi:
            result = handle_command("profile", [])
        assert result is True
        mock_pi.assert_called_once()

    def test_info_flag_calls_introspection(self, tmp_store) -> None:
        """--info flag calls print_introspection."""
        with patch("aipass.aipass.apps.modules.profile.print_introspection") as mock_pi:
            result = handle_command("profile", ["--info"])
        assert result is True
        mock_pi.assert_called_once()

    def test_help_flag_returns_true(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: help branch skips print_help -> red."""
        assert handle_command("profile", ["--help"]) is True
        out, _err = capsys.readouterr()
        assert "user memory read/write" in out

    def test_h_flag_returns_true(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: help branch skips print_help -> red."""
        assert handle_command("profile", ["-h"]) is True
        out, _err = capsys.readouterr()
        assert "user memory read/write" in out

    def test_help_word_returns_true(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: help branch skips print_help -> red."""
        assert handle_command("profile", ["help"]) is True
        out, _err = capsys.readouterr()
        assert "user memory read/write" in out

    def test_set_valid_field(self, tmp_store) -> None:
        """'set name user' stores value and returns True."""
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            result = handle_command("profile", ["set", "name", "user"])
        assert result is True
        stored = json.loads(tmp_store.read_text(encoding="utf-8"))
        assert stored["profile"]["name"] == "user"

    def test_set_invalid_field_returns_true(self, tmp_store, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: 'Unknown field' error dropped -> red."""
        result = handle_command("profile", ["set", "INVALID_FIELD", "val"])
        assert result is True
        _out, err = capsys.readouterr()
        assert "Unknown field: INVALID_FIELD" in err

    def test_set_missing_value_returns_true(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: usage error dropped -> red."""
        result = handle_command("profile", ["set", "name"])
        assert result is True
        _out, err = capsys.readouterr()
        assert "Usage: aipass profile set <field> <value>" in err

    def test_clear_confirmed(self, tmp_store) -> None:
        """'clear' with 'aipass' confirmation resets profile."""
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            with patch("sys.stdin", io.StringIO("aipass\n")):
                result = handle_command("profile", ["clear"])
        assert result is True
        stored = json.loads(tmp_store.read_text(encoding="utf-8"))
        assert all(v is None for v in stored["profile"].values())

    def test_clear_cancelled(self, tmp_store, capsys: pytest.CaptureFixture[str]) -> None:
        """A wrong confirmation clears nothing, so it must not exit 0.

        Mutant: its Cancelled error() dropped -> red (stderr read).
        """
        before = tmp_store.read_text(encoding="utf-8") if tmp_store.exists() else None
        with patch("sys.stdin", io.StringIO("nope\n")):
            with pytest.raises(SystemExit) as exc:
                handle_command("profile", ["clear"])

        assert exc.value.code == 1
        assert (tmp_store.read_text(encoding="utf-8") if tmp_store.exists() else None) == before
        _out, err = capsys.readouterr()
        assert "confirmation was 'nope', not 'aipass'. Profile NOT cleared." in err

    def test_clear_keyboard_interrupt(self, tmp_store, capsys: pytest.CaptureFixture[str]) -> None:
        """Ctrl-C during clear leaves the profile intact and refuses non-zero.

        Mutant: its Cancelled error() dropped -> red (stderr read).
        """
        before = tmp_store.read_text(encoding="utf-8") if tmp_store.exists() else None
        with patch("sys.stdin", _CtrlCStdin()):
            with pytest.raises(SystemExit) as exc:
                handle_command("profile", ["clear"])

        assert exc.value.code == 1
        assert (tmp_store.read_text(encoding="utf-8") if tmp_store.exists() else None) == before
        _out, err = capsys.readouterr()
        assert "Cancelled — no confirmation read, profile NOT cleared." in err

    def test_clear_eof_error(self, tmp_store, capsys: pytest.CaptureFixture[str]) -> None:
        """A PIPED clear has no stdin to confirm on: refuse, never report success.

        Mutant: its Cancelled error() dropped -> red (stderr read).
        """
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            save_profile({"name": "Kept", "os": "Linux"})
        before = tmp_store.read_text(encoding="utf-8")
        with patch("sys.stdin", io.StringIO("")):
            with pytest.raises(SystemExit) as exc:
                handle_command("profile", ["clear"])

        assert exc.value.code == 1
        assert tmp_store.read_text(encoding="utf-8") == before
        _out, err = capsys.readouterr()
        assert "Cancelled — no confirmation read, profile NOT cleared." in err

    def test_clear_yes_clears_a_piped_store_without_asking(self, tmp_store) -> None:
        """The pipe's own door is `clear --yes`: the same empty stdin with the flag clears the
        store on disk without asking, so a script that means it can.
        Mutant: the skip-confirm flags `("--yes", "-y")` -> `("-y",)` -> red.
        """
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            save_profile({"name": "Kept", "os": "Linux"})
        with (
            patch("sys.stdin", io.StringIO("")),
            patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"),
        ):
            assert handle_command("profile", ["clear", "--yes"]) is True
        stored = json.loads(tmp_store.read_text(encoding="utf-8"))
        assert stored["profile"] == {f: None for f in USER_FIELDS}

    def test_clear_confirmed_still_exits_zero(self, tmp_store, capsys: pytest.CaptureFixture[str]) -> None:
        """The counterfactual: the real clear path must NOT have become a refusal.

        Mutant: confirmed clear skips its 'Profile cleared.' -> red.
        """
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            with patch("sys.stdin", io.StringIO("aipass\n")):
                assert handle_command("profile", ["clear"]) is True
        out, _err = capsys.readouterr()
        assert "Profile cleared." in out

    def test_unknown_subcommand_shows_help(self) -> None:
        """Unrecognised subcommand falls through to help (returns True)."""
        with patch("aipass.aipass.apps.modules.profile.print_help") as mock_help:
            result = handle_command("profile", ["bogus"])
        assert result is True
        mock_help.assert_called_once()
