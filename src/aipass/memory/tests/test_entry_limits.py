# =================== AIPass ====================
# Name: test_entry_limits.py
# Description: entry_limits config reader and the apps/modules/limits.py gateway over it
# Version: 1.2.0
# Created: 2026-06-13
# Modified: 2026-10-23
# Category: memory/tests
# =============================================

"""Tests for apps/handlers/json/entry_limits.py and its gateway apps/modules/limits.py."""

# entry_limits reads through config_loader, so tests patch config_loader._CONFIG_PATH.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — classify_entries(), is_near_cap(): tests/test_changed_entries.py
# seedgo: no-test-needed(covered_elsewhere) — check_fields() per field, pinned in tests/test_unified_schema.py
# seedgo: no-test-needed(covered_elsewhere) — resolve_entry_types() merge, pinned in tests/test_trinity_standard.py

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aipass.cli.apps.modules import reset_command_state, resolve_exit
from aipass.memory.apps.handlers.json import entry_limits as _entry_limits
from aipass.memory.apps.modules import limits as _limits


@pytest.fixture(autouse=True)
def _recorded_config_logger(monkeypatch):
    """The prax logger is the edge: a recorder per test, so a test reads what config_loader logged."""
    monkeypatch.setattr(_entry_limits.config_loader, "logger", MagicMock())


def _get_modules():
    """Return (entry_limits, config_loader) — the config_loader entry_limits reads through."""
    return _entry_limits, _entry_limits.config_loader


def _write_config(tmp_path: Path, data: dict) -> Path:
    """Write a memory.config.json into tmp_path/config/ and return its path."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "memory.config.json"
    config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return config_path


def _full_config(**entry_limits_overrides) -> dict:
    """Return a minimal memory.config.json dict; keyword args merge into its entry_limits section."""
    section = {
        "enabled": True,
        "enforce": False,
        "entry_types": {
            "key_learnings": {
                "file": "local.json",
                "container": "key_learnings",
                "kind": "dict",
                "field": "value",
                "max_chars": 200,
            },
            "sessions": {
                "file": "local.json",
                "container": "sessions",
                "kind": "list",
                "field": "summary",
                "max_chars": 300,
            },
            "todos": {
                "file": "local.json",
                "container": "todos",
                "kind": "list",
                "field": "task",
                "max_chars": 200,
            },
            "observations": {
                "file": "observations.json",
                "container": "observations",
                "kind": "list",
                "field": "note",
                "max_chars": 600,
            },
        },
        "per_branch": {},
    }
    section.update(entry_limits_overrides)
    return {"entry_limits": section}


class TestNormalConfig:
    """Reader returns the four default caps with a normal config."""

    def test_returns_four_entry_types(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = _write_config(tmp_path, _full_config())
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("some_branch")

        assert "entry_types" in result
        assert len(result["entry_types"]) == 4
        assert set(result["entry_types"].keys()) == {"key_learnings", "sessions", "todos", "observations"}

    def test_enabled_is_true(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = _write_config(tmp_path, _full_config())
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("any")

        assert result["enabled"] is True

    def test_enforce_false_on_disk_overrides_the_code_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The file is the authority: code seeds enforce=True, but False in the file means warn-only."""
        config_path = _write_config(tmp_path, _full_config())
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("any")

        assert result["enforce"] is False

    def test_default_max_chars_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = _write_config(tmp_path, _full_config())
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("any")
        types = result["entry_types"]

        assert types["key_learnings"]["max_chars"] == 200
        assert types["sessions"]["max_chars"] == 300
        assert types["todos"]["max_chars"] == 200
        assert types["observations"]["max_chars"] == 600


class TestPerBranchOverride:
    """per_branch override changes a cap for the specified branch."""

    def test_override_max_chars(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _full_config(per_branch={"devpulse": {"sessions": {"max_chars": 400}}})
        config_path = _write_config(tmp_path, cfg)
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("devpulse")

        assert result["entry_types"]["sessions"]["max_chars"] == 400
        assert result["entry_types"]["sessions"]["file"] == "local.json"
        assert result["entry_types"]["sessions"]["container"] == "sessions"

    def test_override_does_not_affect_other_branches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _full_config(per_branch={"devpulse": {"sessions": {"max_chars": 400}}})
        config_path = _write_config(tmp_path, cfg)
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("memory")

        assert result["entry_types"]["sessions"]["max_chars"] == 300

    def test_override_does_not_affect_other_types(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _full_config(per_branch={"devpulse": {"sessions": {"max_chars": 400}}})
        config_path = _write_config(tmp_path, cfg)
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("devpulse")

        assert result["entry_types"]["key_learnings"]["max_chars"] == 200
        assert result["entry_types"]["observations"]["max_chars"] == 600


class TestPerBranchNewType:
    """per_branch adds a new entry type and the reader includes it."""

    def test_new_type_added(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        new_type = {
            "file": "local.json",
            "container": "custom_notes",
            "kind": "list",
            "field": "text",
            "max_chars": 500,
        }
        cfg = _full_config(per_branch={"special": {"custom_notes": new_type}})
        config_path = _write_config(tmp_path, cfg)
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("special")

        assert "custom_notes" in result["entry_types"]
        assert result["entry_types"]["custom_notes"]["max_chars"] == 500
        assert result["entry_types"]["custom_notes"]["container"] == "custom_notes"
        assert len(result["entry_types"]) == 5

    def test_new_type_not_present_for_other_branch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        new_type = {
            "file": "local.json",
            "container": "custom_notes",
            "kind": "list",
            "field": "text",
            "max_chars": 500,
        }
        cfg = _full_config(per_branch={"special": {"custom_notes": new_type}})
        config_path = _write_config(tmp_path, cfg)
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("other_branch")

        assert "custom_notes" not in result["entry_types"]
        assert len(result["entry_types"]) == 4


class TestMissingConfig:
    """Missing config file returns safe defaults without crashing."""

    def test_missing_config_returns_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        missing_path = tmp_path / "nonexistent" / "memory.config.json"
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", missing_path)

        result = mod.load_entry_limits("any_branch")

        assert result["enabled"] is True
        # Seed mirrors what the fleet actually operates, not a warn-only stand-in
        assert result["enforce"] is True
        assert len(result["entry_types"]) == 4
        assert result["entry_types"]["sessions"]["max_chars"] == 300

    def test_missing_config_logs_info_and_regenerates_the_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """config_loader serves defaults at INFO level and restores the file the operator edits."""
        missing_path = tmp_path / "nonexistent" / "memory.config.json"
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", missing_path)

        mock_logger = loader.logger
        mod.load_entry_limits("any_branch")

        mock_logger.info.assert_called()
        info_msg = mock_logger.info.call_args[0][0]
        assert "config" in info_msg.lower()
        assert missing_path.exists()
        assert json.loads(missing_path.read_text(encoding="utf-8"))["entry_limits"]["enforce"] is True


class TestMalformedJson:
    """Malformed JSON returns safe defaults and logs an error."""

    def test_malformed_json_returns_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        bad_config = config_dir / "memory.config.json"
        original = "{this is not valid json!!!"
        bad_config.write_text(original, encoding="utf-8")

        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", bad_config)

        result = mod.load_entry_limits("any_branch")

        assert result["enabled"] is True
        assert result["enforce"] is True
        assert len(result["entry_types"]) == 4
        # Defaults are served in memory only — the operator's file is theirs
        assert bad_config.read_text(encoding="utf-8") == original

    def test_malformed_json_logs_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """config_loader logs malformed JSON at ERROR level (not warning)."""
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        bad_config = config_dir / "memory.config.json"
        bad_config.write_text("{broken json", encoding="utf-8")

        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", bad_config)

        mock_logger = loader.logger
        mod.load_entry_limits("any_branch")

        mock_logger.error.assert_called()
        error_msg = mock_logger.error.call_args[0][0]
        # The whole sentence: tag, verdict, path and the parser's reason — an `or` over words passed a pathless message.
        assert error_msg.startswith("[config_loader] Malformed JSON in ")
        assert str(bad_config) in error_msg
        assert error_msg.endswith("Expecting property name enclosed in double quotes: line 1 column 2 (char 1)")

    def test_missing_entry_limits_section_returns_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Config file exists but has no entry_limits section."""
        config_path = _write_config(tmp_path, {"rollover": {"defaults": {"max_lines": 500}}})
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("any_branch")

        assert result["enabled"] is True
        assert result["enforce"] is True
        assert len(result["entry_types"]) == 4


class TestTheDraftPercentComesFromTheConfig:
    """The number an agent drafts to has one source, the config key draft_percent.

    These pins measure the property, not the number: a test asserting 80 would pass against a hardcoded constant.
    """

    def test_the_published_percent_is_the_config_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = _write_config(tmp_path, _full_config(draft_percent=65))
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        assert mod.draft_percent() == 65

    def test_the_draft_target_moves_with_the_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The whole point: one key, every cap's target derived from it."""
        config_path = _write_config(tmp_path, _full_config(draft_percent=50))
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        assert mod.draft_target(300) == 150
        assert mod.draft_target(200) == 100
        assert mod.draft_target(100) == 50

    def test_the_target_is_floored_never_rounded_up(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A target ABOVE the cap would invite the write the cap refuses."""
        config_path = _write_config(tmp_path, _full_config(draft_percent=99))
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        assert mod.draft_target(101) == 99
        assert mod.draft_target(101) < 101

    def test_the_old_module_constant_is_gone(self) -> None:
        """Named explicitly: a surviving DRAFT_PERCENT constant is a second source of truth."""
        mod, _ = _get_modules()

        assert not hasattr(mod, "DRAFT_PERCENT"), "DRAFT_PERCENT is back — the config key is no longer the only source"

    @pytest.mark.parametrize("bad", [0, -5, 101, "80", True, None, [80]])
    def test_an_unusable_percent_serves_the_seed_rather_than_removing_the_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: object
    ) -> None:
        """Narrow the draft target, never delete it: a bad config still leaves a line below the cap."""
        config_path = _write_config(tmp_path, _full_config(draft_percent=bad))
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        assert mod.draft_percent() == 80

    def test_a_config_with_no_draft_percent_at_all_still_answers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Configs written before the key existed lack it and still get the seed."""
        config_path = _write_config(tmp_path, _full_config())
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        assert mod.draft_percent() == 80
        assert mod.draft_target(300) == 240


def _gate_hits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: dict, session: dict) -> list:
    """Run one authored session through the gate's own route: the door's load_entry_limits + changed_entries."""
    monkeypatch.setattr(_entry_limits.config_loader, "_CONFIG_PATH", _write_config(tmp_path, config))
    limits = _limits.load_entry_limits("any")
    entry = {"number": 1, "date": "2026-10-23", "summary": "ok", "status": "done", **session}
    return _limits.changed_entries({}, {"sessions": [entry]}, limits)


def _banded_config(**overrides) -> dict:
    """_full_config with a closed session shape, so a non-canonical field cap is measured too."""
    config = _full_config(**overrides)
    config["entry_limits"]["entry_types"]["sessions"]["fields"] = {
        "summary": {"type": "str", "required": True, "max_chars": 300},
        "status": {"type": "str", "required": False, "max_chars": 40},
    }
    return config


class TestTheGateAllowsATenPercentBand:
    """The writer aims at the cap; the gate refuses only past cap * (100 + tolerance_percent) // 100."""

    def test_an_entry_at_cap_plus_ten_percent_is_allowed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        hits = _gate_hits(tmp_path, monkeypatch, _banded_config(tolerance_percent=10), {"summary": "x" * 330})

        assert hits == []

    def test_one_char_past_the_band_is_refused_naming_the_plain_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hits = _gate_hits(tmp_path, monkeypatch, _banded_config(tolerance_percent=10), {"summary": "x" * 331})

        assert [(h["length"], h["cap"], h["over_by"]) for h in hits] == [(331, 300, 31)]

    def test_the_band_rounds_down_to_whole_characters(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config = _banded_config(tolerance_percent=10)
        config["entry_limits"]["entry_types"]["sessions"]["max_chars"] = 205

        assert _gate_hits(tmp_path, monkeypatch, config, {"summary": "x" * 225}) == []
        assert [h["length"] for h in _gate_hits(tmp_path, monkeypatch, config, {"summary": "x" * 226})] == [226]

    def test_a_non_canonical_field_cap_carries_the_same_band(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _banded_config(tolerance_percent=10)

        assert _gate_hits(tmp_path, monkeypatch, config, {"status": "s" * 44}) == []
        refused = _gate_hits(tmp_path, monkeypatch, config, {"status": "s" * 45})
        assert [(h["field"], h["reason"], h["cap"]) for h in refused] == [("status", "field_over_cap", 40)]

    def test_a_tag_list_s_joined_cap_carries_the_same_band(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _banded_config(tolerance_percent=10)

        assert _gate_hits(tmp_path, monkeypatch, config, {"tags": ["a" * 66, "b" * 66]}) == []
        refused = _gate_hits(tmp_path, monkeypatch, config, {"tags": ["a" * 66, "b" * 67]})
        assert [(h["field"], h["length"], h["cap"]) for h in refused] == [("tags", 133, 120)]

    def test_the_band_is_the_config_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        hits = _gate_hits(tmp_path, monkeypatch, _banded_config(tolerance_percent=0), {"summary": "x" * 301})

        assert [h["length"] for h in hits] == [301]

    @pytest.mark.parametrize("bad", [-1, 101, "10", True, [10], "absent"])
    def test_an_unusable_or_missing_tolerance_serves_the_seed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: object
    ) -> None:
        config = _banded_config() if bad == "absent" else _banded_config(tolerance_percent=bad)

        assert _gate_hits(tmp_path, monkeypatch, config, {"summary": "x" * 330}) == []
        assert [h["length"] for h in _gate_hits(tmp_path, monkeypatch, config, {"summary": "x" * 331})] == [331]


_GATEWAY_CONTRACT = (
    "load_entry_limits",
    "load_file_budgets",
    "fields_for",
    "changed_entries",
    "check_file_budget",
    "draft_percent",
    "draft_target",
    "REASON_UNKNOWN_FIELD",
    "REASON_FIELD_OVER_CAP",
    "REASON_FILE_OVER_BUDGET",
)

_GATEWAY_INTERNAL = ("_field_violation", "_check_list_field", "_walk_strings", "_type_matches", "config_loader")


def _get_gateway():
    """Return (limits gateway, entry_limits) — both imported once, same generation."""
    return _limits, _entry_limits


class TestTheLimitsGatewayIsADoorNotACopy:
    """``apps/handlers/`` is private implementation; ``apps/modules/`` is the door other branches use."""

    @pytest.mark.parametrize("name", _GATEWAY_CONTRACT)
    def test_every_contract_name_is_the_same_object_as_the_handler_s(self, name: str) -> None:
        """Identity, not equality. A wrapper that merely AGREES today is the defect this ends."""
        limits, entry_limits = _get_gateway()

        assert getattr(limits, name) is getattr(entry_limits, name)

    def test_dunder_all_is_exactly_the_contract(self) -> None:
        limits, _ = _get_gateway()

        assert tuple(limits.__all__) == _GATEWAY_CONTRACT

    @pytest.mark.parametrize("name", _GATEWAY_INTERNAL)
    def test_the_internals_stay_behind_the_door(self, name: str) -> None:
        """Named one by one: a later re-export would silently widen what I must not break."""
        limits, _ = _get_gateway()

        assert not hasattr(limits, name), f"{name} is internal and must not be part of the public gateway"

    def test_it_answers_only_its_own_command(self) -> None:
        """A module that claims a command it does not own swallows another module's work."""
        limits, _ = _get_gateway()

        assert limits.handle_command("rollover", []) is False
        assert limits.handle_command("lint", ["fields"]) is False

    @pytest.mark.parametrize("args", [[], ["--help"], ["-h"], ["help"]])
    def test_the_bare_command_and_every_help_spelling_introspect(
        self, capsys: pytest.CaptureFixture, args: list
    ) -> None:
        limits, _ = _get_gateway()

        assert limits.handle_command("limits", args) is True
        assert "limits Module" in capsys.readouterr().out

    def test_an_unknown_subcommand_is_named_and_exits_nonzero(self, capsys: pytest.CaptureFixture) -> None:
        """Claimed and REPORTED with a nonzero exit — never a silent no-op that looks like success."""
        limits, _ = _get_gateway()
        reset_command_state()

        assert limits.handle_command("limits", ["nonsense"]) is True
        assert resolve_exit(True) == 2, "an unknown subcommand refused but would exit 0"
        captured = capsys.readouterr()
        assert "nonsense" in captured.out + captured.err

    def test_the_command_surface_reads_but_never_writes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The pin that keeps this a door: changing a cap is ``config set``, never this CLI."""
        limits, entry_limits = _get_gateway()
        writes: list = []
        for name in ("set_branch_limit", "set_default_limit", "save", "push_defaults_to_per_branch"):
            if hasattr(entry_limits.config_loader, name):
                monkeypatch.setattr(entry_limits.config_loader, name, lambda *a, _n=name, **k: writes.append(_n) or {})

        limits.handle_command("limits", [])

        assert writes == [], f"the gateway's CLI wrote config: {writes}"
