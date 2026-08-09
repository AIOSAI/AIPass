# =================== AIPass ====================
# Name: test_trigger_config_loader.py
# Description: Tests for the trigger operator config loader
# Version: 1.0.0
# Created: 2026-08-08
# Modified: 2026-08-08
# =============================================

"""Tests for handlers/json/config_loader.py — regenerate when missing, never clobber what the operator wrote."""

import json
from pathlib import Path
from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def loader(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """The real loader, pointed at a config file under tmp_path.

    Real reads and real writes — the loader's whole job is what it does to a
    file on disk, so a mocked filesystem would test nothing.
    """
    from aipass.trigger.apps.handlers.json import config_loader

    monkeypatch.setattr(config_loader, "CONFIG_PATH", tmp_path / "custom_config" / "trigger.config.json")
    monkeypatch.setattr(config_loader, "_LOADER_LOG", tmp_path / "config_loader.jsonl")
    return config_loader


def _write_config(loader, payload: Any) -> bytes:
    """Write an operator config file verbatim, returning the exact bytes on disk."""
    loader.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    loader.CONFIG_PATH.write_text(text, encoding="utf-8")
    return loader.CONFIG_PATH.read_bytes()


# ---------------------------------------------------------------------------
# Missing file -- regeneration
# ---------------------------------------------------------------------------


class TestMissingFile:
    """A genuinely missing file is regenerated in full — that is why code carries defaults."""

    def test_load_writes_the_file(self, loader) -> None:
        """The operator ends up with a real file to edit, not just in-memory defaults."""
        loader.load()

        assert loader.CONFIG_PATH.exists()

    def test_regenerated_file_holds_the_full_defaults(self, loader) -> None:
        """Regeneration is complete: every shipped key lands on disk, not a stub."""
        loader.load()

        on_disk = json.loads(loader.CONFIG_PATH.read_text(encoding="utf-8"))
        assert on_disk == loader.DEFAULT_CONFIG

    def test_load_returns_the_defaults(self, loader) -> None:
        """The caller gets a usable config on the same call that regenerates."""
        assert loader.load() == loader.DEFAULT_CONFIG

    def test_regenerated_file_is_human_editable(self, loader) -> None:
        """Indented and newline-terminated — an operator has to be able to edit this."""
        loader.load()

        text = loader.CONFIG_PATH.read_text(encoding="utf-8")
        assert "\n  " in text
        assert text.endswith("\n")

    def test_no_temp_file_is_left_behind(self, loader) -> None:
        """The atomic write cleans up after itself."""
        loader.load()

        assert [p.name for p in loader.CONFIG_PATH.parent.iterdir()] == ["trigger.config.json"]

    def test_a_second_load_reads_the_regenerated_file(self, loader) -> None:
        """Once written, the file is the authority — a value edited into it wins."""
        loader.load()
        on_disk = json.loads(loader.CONFIG_PATH.read_text(encoding="utf-8"))
        on_disk["escalation"]["warning_threshold"] = 42
        loader.CONFIG_PATH.write_text(json.dumps(on_disk), encoding="utf-8")

        assert loader.load()["escalation"]["warning_threshold"] == 42

    def test_returned_config_is_a_copy(self, loader) -> None:
        """A caller mutating what it got back cannot poison the regeneration seed."""
        config = loader.load()
        config["escalation"]["warning_threshold"] = 999

        assert loader.DEFAULT_CONFIG["escalation"]["warning_threshold"] != 999
        assert loader.load()["escalation"]["warning_threshold"] != 999


# ---------------------------------------------------------------------------
# Unreadable file -- never clobbered
# ---------------------------------------------------------------------------


class TestUnreadableFileIsNeverClobbered:
    """A file that exists but will not parse may be one stray comma from correct.

    It carries hand-tuned operator values, so the loader serves defaults in
    memory and leaves the bytes alone (DPLAN-0206).
    """

    def test_malformed_json_serves_defaults(self, loader) -> None:
        """A trailing comma does not take the lane down with it."""
        _write_config(loader, '{"escalation": {"warning_threshold": 3,}}')

        assert loader.load() == loader.DEFAULT_CONFIG

    def test_malformed_json_leaves_the_bytes_untouched(self, loader) -> None:
        """The operator's file must be exactly as they left it, byte for byte."""
        original = _write_config(loader, '{"escalation": {"warning_threshold": 3,}}')

        loader.load()

        assert loader.CONFIG_PATH.read_bytes() == original

    def test_a_json_list_serves_defaults(self, loader) -> None:
        """Valid JSON, wrong shape: deep_merge would raise on it."""
        _write_config(loader, [{"escalation": {}}])

        assert loader.load() == loader.DEFAULT_CONFIG

    def test_a_json_list_leaves_the_bytes_untouched(self, loader) -> None:
        """Wrong shape takes the same no-clobber path as malformed."""
        original = _write_config(loader, [{"escalation": {}}])

        loader.load()

        assert loader.CONFIG_PATH.read_bytes() == original

    def test_a_bare_json_string_serves_defaults(self, loader) -> None:
        """Any non-object at the top level is the wrong shape."""
        original = _write_config(loader, '"escalation"')

        assert loader.load() == loader.DEFAULT_CONFIG
        assert loader.CONFIG_PATH.read_bytes() == original

    def test_an_empty_file_serves_defaults(self, loader) -> None:
        """A truncated write is unreadable, not an invitation to overwrite."""
        original = _write_config(loader, "")

        assert loader.load() == loader.DEFAULT_CONFIG
        assert loader.CONFIG_PATH.read_bytes() == original

    def test_section_still_works_over_a_broken_file(self, loader) -> None:
        """Consumers keep running on defaults while the operator fixes their file."""
        _write_config(loader, "{ not json")

        assert loader.section("escalation") == loader.DEFAULT_CONFIG["escalation"]

    def test_repairing_the_file_takes_effect(self, loader) -> None:
        """Positive control: once the file parses, it is authoritative again."""
        _write_config(loader, "{ not json")
        assert loader.load() == loader.DEFAULT_CONFIG

        _write_config(loader, {"escalation": {"warning_threshold": 3}})

        assert loader.load()["escalation"]["warning_threshold"] == 3


# ---------------------------------------------------------------------------
# Operator overrides
# ---------------------------------------------------------------------------


class TestOperatorOverridesWin:
    """The file on disk is the runtime authority; defaults only fill the gaps."""

    def test_a_single_override_wins(self, loader) -> None:
        """One edited key changes that key."""
        _write_config(loader, {"escalation": {"warning_threshold": 3}})

        assert loader.load()["escalation"]["warning_threshold"] == 3

    def test_untouched_keys_keep_their_defaults(self, loader) -> None:
        """A partial file is not a truncated config — the rest is filled in."""
        _write_config(loader, {"escalation": {"warning_threshold": 3}})

        escalation = loader.load()["escalation"]
        assert escalation["digest_recipient"] == "@devpulse"
        assert escalation["cooldown_minutes"] == 360
        assert set(escalation) == set(loader.DEFAULT_CONFIG["escalation"])

    def test_a_falsey_override_wins(self, loader) -> None:
        """enabled=false is an operator decision, not a missing value."""
        _write_config(loader, {"escalation": {"enabled": False, "ignore_branches": []}})

        escalation = loader.load()["escalation"]
        assert escalation["enabled"] is False
        assert escalation["ignore_branches"] == []

    def test_a_list_override_replaces_rather_than_extends(self, loader) -> None:
        """Lists are values, not merge targets — what the operator listed is the list."""
        _write_config(loader, {"escalation": {"ignore_branches": ["flow", "memory"]}})

        assert loader.load()["escalation"]["ignore_branches"] == ["flow", "memory"]

    def test_unknown_keys_survive(self, loader) -> None:
        """A key the code does not know yet is still the operator's — it is kept."""
        _write_config(loader, {"escalation": {"experimental_knob": 7}, "future_section": {"a": 1}})

        config = loader.load()
        assert config["escalation"]["experimental_knob"] == 7
        assert config["future_section"] == {"a": 1}

    def test_defaults_are_not_mutated_by_a_load(self, loader) -> None:
        """Reading an operator file must not rewrite the regeneration seed in memory."""
        _write_config(loader, {"escalation": {"warning_threshold": 3}})
        loader.load()

        assert loader.DEFAULT_CONFIG["escalation"]["warning_threshold"] == 10

    def test_an_empty_object_serves_pure_defaults(self, loader) -> None:
        """`{}` is a readable file, so it merges — to exactly the defaults."""
        _write_config(loader, {})

        assert loader.load() == loader.DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# deep_merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    """Merging is recursive and non-destructive."""

    def test_nested_dicts_merge_key_by_key(self, loader) -> None:
        """An override reaching one nested key leaves its siblings alone."""
        merged = loader.deep_merge({"a": {"x": 1, "y": 2}}, {"a": {"y": 9}})

        assert merged == {"a": {"x": 1, "y": 9}}

    def test_inputs_are_not_mutated(self, loader) -> None:
        """Neither argument is touched — the caller's defaults stay pristine."""
        base: Dict[str, Any] = {"a": {"x": 1}}
        overrides: Dict[str, Any] = {"a": {"y": 2}}

        loader.deep_merge(base, overrides)

        assert base == {"a": {"x": 1}}
        assert overrides == {"a": {"y": 2}}

    def test_nested_values_are_deep_copied(self, loader) -> None:
        """Mutating the result cannot reach back into the base."""
        base: Dict[str, Any] = {"a": {"x": [1, 2]}}

        merged = loader.deep_merge(base, {})
        merged["a"]["x"].append(3)

        assert base["a"]["x"] == [1, 2]

    def test_a_dict_can_replace_a_scalar(self, loader) -> None:
        """Type changes take the override wholesale rather than raising."""
        assert loader.deep_merge({"a": 1}, {"a": {"x": 2}}) == {"a": {"x": 2}}

    def test_a_scalar_can_replace_a_dict(self, loader) -> None:
        """The reverse type change is just as safe."""
        assert loader.deep_merge({"a": {"x": 2}}, {"a": 1}) == {"a": 1}


# ---------------------------------------------------------------------------
# section()
# ---------------------------------------------------------------------------


class TestSection:
    """Consumers ask for one section and must always get a usable dict."""

    def test_known_section_is_returned(self, loader) -> None:
        """The escalation section comes back merged."""
        _write_config(loader, {"escalation": {"warning_threshold": 3}})

        section = loader.section("escalation")
        assert section["warning_threshold"] == 3
        assert section["digest_recipient"] == "@devpulse"

    def test_unknown_section_is_an_empty_dict(self, loader) -> None:
        """A section nobody has shipped yet reads as empty, never None."""
        assert loader.section("does_not_exist") == {}

    def test_a_non_dict_section_is_an_empty_dict(self, loader) -> None:
        """An operator typo that makes a section a list cannot crash its consumer."""
        _write_config(loader, {"escalation": ["oops"]})

        assert loader.section("escalation") == {}

    def test_meta_section_is_readable(self, loader) -> None:
        """_meta ships with the file so an operator can see who consumes what."""
        assert "escalation" in loader.section("_meta")


# ---------------------------------------------------------------------------
# Write failures
# ---------------------------------------------------------------------------


class TestWriteFailure:
    """A config that cannot be written still has to serve a working config."""

    def test_unwritable_path_still_serves_defaults(self, monkeypatch, loader, tmp_path: Path) -> None:
        """Parent is a file, so the regen write fails — the caller still gets defaults."""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        monkeypatch.setattr(loader, "CONFIG_PATH", blocker / "trigger.config.json")

        assert loader.load() == loader.DEFAULT_CONFIG

    def test_section_survives_an_unwritable_path(self, monkeypatch, loader, tmp_path: Path) -> None:
        """Consumers keep their settings even when regeneration is impossible."""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        monkeypatch.setattr(loader, "CONFIG_PATH", blocker / "trigger.config.json")

        assert loader.section("escalation")["digest_recipient"] == "@devpulse"


# ---------------------------------------------------------------------------
# Shipped defaults
# ---------------------------------------------------------------------------


class TestShippedDefaults:
    """What a fresh install finds in the file after a regen."""

    def test_escalation_defaults_are_complete(self, loader) -> None:
        """Every knob the lane reads is present, so no consumer falls back blindly."""
        escalation = loader.DEFAULT_CONFIG["escalation"]

        for key in (
            "enabled",
            "digest_recipient",
            "warning_threshold",
            "error_threshold",
            "window_minutes",
            "cooldown_minutes",
            "sample_lines",
            "max_signatures",
            "escalate_suppressed",
            "watch_branch_log_warnings",
            "ignore_branches",
        ):
            assert key in escalation

    def test_defaults_are_json_serializable(self, loader) -> None:
        """The seed has to survive the round trip it is written through."""
        assert json.loads(json.dumps(loader.DEFAULT_CONFIG)) == loader.DEFAULT_CONFIG

    def test_suppressed_errors_stay_silent_by_default(self, loader) -> None:
        """Compass #219: a human silenced it, so the lane ships silent too."""
        assert loader.DEFAULT_CONFIG["escalation"]["escalate_suppressed"] is False
