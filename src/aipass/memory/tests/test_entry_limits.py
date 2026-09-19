# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_entry_limits.py
# Date: 2026-06-13
# Version: 1.1.0
# Category: memory/tests
# =============================================

"""
Tests for the entry_limits config reader (Phase 1 of FPLAN-0270).

Covers:
  - Normal config read returns four default entry types.
  - per_branch override changes a cap.
  - per_branch adds a new entry type.
  - Missing config file returns safe defaults (no crash).
  - Malformed JSON returns safe defaults + error logged (no crash).

Note: entry_limits delegates config reading to config_loader, so tests
patch config_loader._CONFIG_PATH rather than a removed entry_limits attr.
"""

import importlib
import json
import sys
from pathlib import Path
import pytest


# ---------------------------------------------------------------------------
# Helpers: fresh-import the module under test with mocks already in place
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_entry_limits(monkeypatch):
    """Drop cached module so each test gets a fresh import.

    Conftest's stand-in for aipass.memory.apps.handlers.json now carries the
    real package's __path__, so sub-module discovery works with it in place --
    the eviction here is only about getting FRESH modules per test, and
    config_loader in particular so its _CONFIG_PATH can be re-patched.

    Evicted with ``monkeypatch.delitem``, not a bare ``sys.modules.pop``: a
    bare pop is one-way and the eviction outlives the test, which is how two
    receipt tests went red on a single xdist worker on a single run.
    """
    for name in (
        "aipass.memory.apps.handlers.json",
        "aipass.memory.apps.handlers.json.json_handler",
        "aipass.memory.apps.handlers.json.config_loader",
        "aipass.memory.apps.handlers.json.entry_limits",
        # The public gateway binds the handler's function OBJECTS at import
        # time. Left cached, it would hand back the PREVIOUS test's entry_limits
        # and the identity pins below would compare two different modules.
        "aipass.memory.apps.modules.limits",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)
    yield


def _get_modules():
    """Import and return (entry_limits, config_loader) modules."""
    config_loader = importlib.import_module("aipass.memory.apps.handlers.json.config_loader")
    entry_limits = importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")
    return entry_limits, config_loader


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, data: dict) -> Path:
    """Write a memory.config.json into tmp_path/config/ and return its path."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "memory.config.json"
    config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return config_path


def _full_config(**entry_limits_overrides) -> dict:
    """Return a minimal memory.config.json dict with an entry_limits section.

    Any keyword args are merged into the entry_limits section.
    """
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


# ===========================================================================
# 1. Normal config returns four default entry types
# ===========================================================================


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
        """The file is the authority: code seeds enforce=True, but an operator
        who sets False in the file gets warn-only.
        """
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


# ===========================================================================
# 2. per_branch override changes a cap
# ===========================================================================


class TestPerBranchOverride:
    """per_branch override changes a cap for the specified branch."""

    def test_override_max_chars(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _full_config(per_branch={"devpulse": {"sessions": {"max_chars": 400}}})
        config_path = _write_config(tmp_path, cfg)
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("devpulse")

        assert result["entry_types"]["sessions"]["max_chars"] == 400
        # Other fields on sessions should be preserved from base
        assert result["entry_types"]["sessions"]["file"] == "local.json"
        assert result["entry_types"]["sessions"]["container"] == "sessions"

    def test_override_does_not_affect_other_branches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _full_config(per_branch={"devpulse": {"sessions": {"max_chars": 400}}})
        config_path = _write_config(tmp_path, cfg)
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("memory")

        # memory branch should get the default, not devpulse's override
        assert result["entry_types"]["sessions"]["max_chars"] == 300

    def test_override_does_not_affect_other_types(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _full_config(per_branch={"devpulse": {"sessions": {"max_chars": 400}}})
        config_path = _write_config(tmp_path, cfg)
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("devpulse")

        # Other types should be unchanged
        assert result["entry_types"]["key_learnings"]["max_chars"] == 200
        assert result["entry_types"]["observations"]["max_chars"] == 600


# ===========================================================================
# 3. per_branch adds a NEW entry type
# ===========================================================================


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
        # Original four types still present
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


# ===========================================================================
# 4. Missing config file returns safe defaults (no crash)
# ===========================================================================


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
        """config_loader serves defaults at INFO level and restores the file.

        The caps an operator edits live in that file, so a caller reaching
        limits through a missing config must leave a real file behind to edit.
        """
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


# ===========================================================================
# 5. Malformed JSON returns safe defaults + error logged (no crash)
# ===========================================================================


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
        # The whole sentence: the tag that routes it, the verdict, the offending
        # path and the parser's own reason. An `or` over two words passed on any
        # message carrying either, including one that named no file at all.
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


# ===========================================================================
# 6. draft_percent is a CONFIG KEY, not a module constant (FPLAN-0593 Phase 5)
# ===========================================================================


class TestTheDraftPercentComesFromTheConfig:
    """The number an agent drafts to has one source, and it is the config.

    It was ``entry_limits.DRAFT_PERCENT = 80`` until FPLAN-0593 Phase 5. Because
    a module constant is not readable as configuration, @seedgo mirrored it as
    ``_DRAFT_PERCENT = 80`` in ``trinity_groups.py`` and pinned the mirror
    against @memory's ``draft_target()`` — which is a copy that happens to be
    tested, not a source. Publishing the key is what lets that mirror retire.

    These pins measure the property, not the number: move the key and the target
    moves with it. A test asserting 80 would pass just as happily against a
    hardcoded constant, which is the exact thing being ended.
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
        """Named explicitly: a surviving constant is a second source of truth.

        @seedgo's retirement note points at this name. If it comes back, the
        mirror it is meant to replace becomes correct again by accident.
        """
        mod, _ = _get_modules()

        assert not hasattr(mod, "DRAFT_PERCENT"), "DRAFT_PERCENT is back — the config key is no longer the only source"

    @pytest.mark.parametrize("bad", [0, -5, 101, "80", True, None, [80]])
    def test_an_unusable_percent_serves_the_seed_rather_than_removing_the_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: object
    ) -> None:
        """Narrow the draft target, never delete it.

        A truncated or hand-edited config must not leave the fleet with no
        target to aim at — that would be a cap with nothing below it, which is
        how an agent finds the wall instead of the line.
        """
        config_path = _write_config(tmp_path, _full_config(draft_percent=bad))
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        assert mod.draft_percent() == 80

    def test_a_config_with_no_draft_percent_at_all_still_answers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The key is new; every config written before Phase 5 lacks it."""
        config_path = _write_config(tmp_path, _full_config())
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        assert mod.draft_percent() == 80
        assert mod.draft_target(300) == 240


# ===========================================================================
# 7. The public gateway: apps/modules/limits.py is a door, not a copy
# ===========================================================================


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
    """Import and return (limits gateway, entry_limits) — both fresh, same generation."""
    entry_limits = importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")
    limits = importlib.import_module("aipass.memory.apps.modules.limits")
    return limits, entry_limits


class TestTheLimitsGatewayIsADoorNotACopy:
    """``apps/handlers/`` is private implementation; ``apps/modules/`` is the door.

    @seedgo's ``check_handler_independence`` sends cross-branch callers to a
    branch's ``modules`` package. Today @hooks reaches past that into
    ``handlers/json/entry_limits.py`` by dotted path and @seedgo guard-imports
    ``draft_target`` from it — not because they went around the rule, but
    because no door existed to reach for. ``apps/modules/fleet.py`` is the same
    pattern for the same reason.
    """

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
        """Claimed and REPORTED — never a silent no-op that looks like success.

        Both streams are read: the refusal routes to stderr under @seedgo's
        output-routing standard, and the exit code is what tells a caller the
        difference between "described the contract" and "did not understand you".
        """
        from aipass.cli.apps.modules import reset_command_state, resolve_exit

        limits, _ = _get_gateway()
        reset_command_state()

        assert limits.handle_command("limits", ["nonsense"]) is True
        assert resolve_exit(True) == 2, "an unknown subcommand refused but would exit 0"
        captured = capsys.readouterr()
        assert "nonsense" in captured.out + captured.err

    def test_the_command_surface_reads_but_never_writes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The pin that keeps this a door: changing a cap is ``config set``, not this.

        Introspection prints the live ``draft_percent()``, so this does not
        claim the CLI computes nothing — it claims the CLI never writes. A
        gateway that could move a cap would be a second write surface for the
        numbers the whole fleet is measured against.
        """
        limits, entry_limits = _get_gateway()
        writes: list = []
        for name in ("set_branch_limit", "set_default_limit", "save", "push_defaults_to_per_branch"):
            if hasattr(entry_limits.config_loader, name):
                monkeypatch.setattr(entry_limits.config_loader, name, lambda *a, _n=name, **k: writes.append(_n) or {})

        limits.handle_command("limits", [])

        assert not writes, f"the gateway's CLI wrote config: {writes}"
