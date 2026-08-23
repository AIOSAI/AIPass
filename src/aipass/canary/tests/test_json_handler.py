# =================== AIPass ====================
# Name: test_json_handler.py
# Description: Tests for canary's JSON handler shim and its shared contracts
# Version: 1.0.0
# Created: 2026-08-22
# Modified: 2026-08-22
# =============================================

"""Tests for canary's JSON handler.

Two things are under test and they are different things:
  1. The shim wiring — that canary's singleton points at canary_json/ and
     re-exports the shared API.
  2. The contracts canary relies on — defaults, validation, raises-on-invalid,
     and what happens to a missing/corrupt/empty file.

Behavioural tests use their own JsonHandler over a tmp dir rather than the
singleton, so a failure names the contract, not the branch's wiring.
"""

import json
from pathlib import Path

import pytest

from aipass.aipass.shared.json_handler import JsonHandler
from aipass.canary.apps.handlers.json import json_handler


# =============================================================================
# SHIM WIRING
# =============================================================================


def test_get_path_returns_path_under_branch_json_dir(mock_infrastructure):
    """get_json_path returns a Path, and it lands in the redirected sandbox."""
    result = json_handler.get_json_path("probe", "config")

    assert isinstance(result, Path)
    assert result.parent == mock_infrastructure
    assert result.name == "probe_config.json"


def test_shim_reexports_every_documented_function():
    """The shim must expose the full shared surface, not a subset."""
    expected = (
        "read_json",
        "write_json",
        "validate_json_structure",
        "get_json_path",
        "ensure_json_exists",
        "ensure_module_jsons",
        "load_json",
        "save_json",
        "log_operation",
        "_create_default",
    )
    missing = [name for name in expected if not hasattr(json_handler, name)]

    assert missing == [], f"shim is missing re-exports: {missing}"


# =============================================================================
# PROVISIONING
# =============================================================================


def test_ensure_exists_creates_file_and_returns_true(mock_json_handler):
    """ensure_json_exists provisions a missing file and reports True."""
    result = mock_json_handler.ensure_json_exists("widget", "config")

    assert result is True
    assert mock_json_handler.get_json_path("widget", "config").exists()


def test_ensure_exists_auto_creates_missing_dir(tmp_path):
    """The handler mkdir's its json_dir rather than failing on a missing dir."""
    nonexistent = tmp_path / "not_a_dir_yet" / "deeper"
    handler = JsonHandler(json_dir=nonexistent)

    assert handler.ensure_json_exists("widget", "data") is True
    assert nonexistent.exists()


def test_ensure_exists_does_not_overwrite_valid_content(mock_json_handler):
    """A file that already_exists and validates is left alone."""
    mock_json_handler.ensure_json_exists("widget", "config")
    path = mock_json_handler.get_json_path("widget", "config")
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["config"]["marker"] = "do-not-clobber"
    path.write_text(json.dumps(stored), encoding="utf-8")

    mock_json_handler.ensure_json_exists("widget", "config")

    reread = json.loads(path.read_text(encoding="utf-8"))
    assert reread["config"]["marker"] == "do-not-clobber"


def test_ensure_module_provisions_all_three_types(mock_json_handler):
    """ensure_module_jsons creates config, data and log together."""
    result = mock_json_handler.ensure_module_jsons("widget")

    assert result is True
    for json_type in ("config", "data", "log"):
        assert mock_json_handler.get_json_path("widget", json_type).exists()


# =============================================================================
# DEFAULT FACTORY AND DATA STRUCTURE CONTRACTS
# =============================================================================


def test_default_factory_config_carries_module_name():
    """A default config document names its module and declares config_keys."""
    result = JsonHandler._create_default("config", "widget")

    assert isinstance(result, dict)
    assert result["module_name"] == "widget"
    assert "config" in result


def test_default_factory_data_carries_last_updated():
    """A default data document carries the data_keys the validator requires."""
    result = JsonHandler._create_default("data", "widget")

    assert isinstance(result, dict)
    assert "created" in result
    assert "last_updated" in result


def test_default_factory_log_is_a_list():
    """A default log document is a list, not a dict."""
    assert JsonHandler._create_default("log", "widget") == []


def test_create_default_raises_on_invalid_type():
    """_create_default refuses an unknown json_type rather than guessing."""
    with pytest.raises(ValueError):
        JsonHandler._create_default("invalid_type", "widget")


# =============================================================================
# VALIDATION
# =============================================================================


@pytest.mark.parametrize(
    "json_type,data,expected",
    [
        ("config", {"module_name": "w", "version": "1.0.0", "config": {}}, True),
        ("config", {"module_name": "w"}, False),
        ("config", ["not", "a", "dict"], False),
        ("data", {"created": "2026-08-22", "last_updated": "2026-08-22"}, True),
        ("data", {"created": "2026-08-22"}, False),
        ("log", [], True),
        ("log", {"not": "a list"}, False),
        ("invalid_mode", {}, False),
    ],
)
def test_validate_json_structure_contract(json_type, data, expected):
    """validate_json_structure returns a bool matching the documented shape."""
    result = JsonHandler.validate_json_structure(data, json_type)

    assert isinstance(result, bool)
    assert result is expected


# =============================================================================
# LOAD / SAVE
# =============================================================================


def test_load_returns_dict_and_creates_when_missing(mock_json_handler):
    """load_json provisions on first read and hands back the correct type."""
    result = mock_json_handler.load_json("widget", "config")

    assert isinstance(result, dict)
    assert result["module_name"] == "widget"


def test_save_then_load_round_trips(mock_json_handler, sample_test_data):
    """A saved document reads back with its payload intact."""
    assert mock_json_handler.save_json("widget", "data", dict(sample_test_data)) is True

    reloaded = mock_json_handler.load_json("widget", "data")
    assert isinstance(reloaded, dict)
    assert reloaded["test_key"] == "test_value"


def test_save_refreshes_last_updated(mock_json_handler):
    """Saving a data document stamps last_updated rather than trusting caller."""
    stale = {"created": "2020-01-01", "last_updated": "2020-01-01"}

    mock_json_handler.save_json("widget", "data", stale)

    assert stale["last_updated"] != "2020-01-01"


def test_save_invalid_raises_value_error(mock_json_handler):
    """save_json raises on a document that fails validation — it never writes junk."""
    with pytest.raises(ValueError):
        mock_json_handler.save_json("widget", "config", {"missing": "everything"})


# =============================================================================
# LOG OPERATIONS
# =============================================================================


def test_log_operation_appends_entry_with_operation_field(mock_json_handler):
    """A log_entry records its operation and a timestamp."""
    result = mock_json_handler.log_operation("probe_ran", {"detail": "x"}, module_name="widget")

    assert result is True
    log = mock_json_handler.load_json("widget", "log")
    assert log[-1]["operation"] == "probe_ran"
    assert "timestamp" in log[-1]


def test_log_operation_rotates_at_max_entries(mock_json_handler):
    """The log is capped — old entries roll off instead of growing forever."""
    oversized = [{"timestamp": "t", "operation": f"op{i}"} for i in range(JsonHandler.MAX_LOG_ENTRIES + 5)]
    mock_json_handler.save_json("widget", "log", oversized)

    mock_json_handler.log_operation("newest", module_name="widget")

    log = mock_json_handler.load_json("widget", "log")
    assert len(log) == JsonHandler.MAX_LOG_ENTRIES
    assert log[-1]["operation"] == "newest"


# =============================================================================
# ERROR RESILIENCE
# =============================================================================


def test_read_json_returns_none_for_missing_file(tmp_path):
    """A missing_file is None, not a FileNotFoundError escaping to the caller."""
    assert JsonHandler.read_json(tmp_path / "file_not_found.json") is None


def test_read_json_returns_none_for_corrupt_json(tmp_path):
    """Malformed content surfaces as None, not a raw JSONDecodeError."""
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not valid json", encoding="utf-8")

    assert JsonHandler.read_json(corrupt) is None


def test_ensure_exists_regenerates_empty_file(mock_json_handler):
    """An empty_file is repaired in place rather than read as valid."""
    mock_json_handler.ensure_json_exists("widget", "config")
    path = mock_json_handler.get_json_path("widget", "config")
    path.write_text("", encoding="utf-8")

    assert mock_json_handler.ensure_json_exists("widget", "config") is True
    assert json.loads(path.read_text(encoding="utf-8"))["module_name"] == "widget"


def test_ensure_exists_regenerates_corrupt_file(mock_json_handler):
    """A corrupt document is replaced with a valid default."""
    mock_json_handler.ensure_json_exists("widget", "data")
    path = mock_json_handler.get_json_path("widget", "data")
    path.write_text("{malformed", encoding="utf-8")

    assert mock_json_handler.ensure_json_exists("widget", "data") is True
    assert "last_updated" in json.loads(path.read_text(encoding="utf-8"))


def test_write_json_returns_false_on_nonexistent_unwritable_target(tmp_path):
    """write_json answers False on an OS error instead of raising."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a dir", encoding="utf-8")

    result = JsonHandler.write_json(blocker / "nested" / "out.json", {"a": 1})

    assert result is False
