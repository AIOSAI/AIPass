# =================== AIPass ====================
# Name: test_validator.py
# Description: Unit tests for skills validator
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-11-17
# Category: skills/tests
# =============================================

"""Tests for apps/handlers/validator.py, the requires-block check, and apps/modules/validator.py, the validate verb."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(stdlib) — how shutil.which() and importlib.util.find_spec() search

from aipass.skills.apps.handlers import switch_handler
from aipass.skills.apps.handlers.validator import validate_skill
from aipass.skills.apps.modules import validator as validate_verb

_OFF = "Skill 'marked_probe' is switched OFF. Turn it back on with: drone @skills on marked_probe"


class TestValidateOnAnOffSkill:
    def test_off_validate_imports_nothing_and_neither_passes_nor_fails_the_skill(self, marked_probe, capsys):
        switch_handler.set_enabled("marked_probe", False)

        assert validate_verb.handle_command("validate", ["marked_probe"]) is False

        out, err = capsys.readouterr()
        assert not (marked_probe / "IMPORTED").exists()
        assert _OFF in err and "not validated" in err
        assert "requirements met" not in out and "NOT met" not in out

    def test_on_validate_imports_the_handler_and_validates_as_before(self, marked_probe, capsys):
        assert validate_verb.handle_command("validate", ["marked_probe"]) is True

        out, _ = capsys.readouterr()
        assert (marked_probe / "IMPORTED").exists()
        assert "Skill 'marked_probe' - all requirements met." in out

    def test_an_unreadable_switch_state_refuses_validate(self, marked_probe, capsys):
        switch_handler.get_state_path().write_text("{not json", encoding="utf-8")

        assert validate_verb.handle_command("validate", ["marked_probe"]) is False

        _, err = capsys.readouterr()
        assert not (marked_probe / "IMPORTED").exists()
        assert "switch_state.json" in err and "not validated" in err


class TestValidateSkill:
    def test_null_requirement_lists_mean_no_requirements(self):
        # A YAML `pip:` with nothing under it loads as None, not [].
        # Mutant killed 2026-09-27: the `or []` dropped from the pip line.
        result = validate_skill({"requires": {"pip": None, "bins": None, "config": None}})
        assert result["valid"] is True
        assert result["missing_pip"] == []
        assert result["missing_bins"] == []
        assert result["missing_config"] == []

    def test_an_empty_requires_block_means_no_requirements(self):
        # Pins a shipped defect: YAML `requires:` with nothing under it is None, and .get() raised.
        result = validate_skill({"requires": None})
        assert (result["valid"], result["missing_pip"]) == (True, [])

    def test_a_requires_list_is_malformed_never_met(self):
        result = validate_skill({"requires": ["psutil"]})
        assert result["valid"] is False
        assert result["malformed"] == "requires must map pip/bins/config to lists, not a list"

    def test_empty_requirements(self):
        result = validate_skill({"requires": {"pip": [], "bins": [], "config": []}})
        assert result["valid"] is True

    def test_installed_pip_package(self):
        # sys is always available
        result = validate_skill({"requires": {"pip": ["sys"]}})
        assert result["valid"] is True
        assert result["missing_pip"] == []

    def test_missing_pip_package(self):
        result = validate_skill({"requires": {"pip": ["nonexistent_pkg_xyz_123"]}})
        assert result["valid"] is False
        assert "nonexistent_pkg_xyz_123" in result["missing_pip"]

    def test_a_package_whose_parent_is_missing_is_reported_missing(self):
        # Mutant killed 2026-11-17: asking find_spec for the dotted name raises ModuleNotFoundError.
        result = validate_skill({"requires": {"pip": ["nonexistent_pkg_xyz_123.sub"]}})
        assert (result["valid"], result["missing_pip"]) == (False, ["nonexistent_pkg_xyz_123.sub"])

    def test_an_installed_dotted_package_is_not_missing(self):
        result = validate_skill({"requires": {"pip": ["xml.etree"]}})
        assert (result["valid"], result["missing_pip"]) == (True, [])

    def test_available_binary(self):
        # python3 should be on PATH
        result = validate_skill({"requires": {"bins": ["python3"]}})
        assert result["valid"] is True
        assert result["missing_bins"] == []

    def test_missing_binary(self):
        result = validate_skill({"requires": {"bins": ["nonexistent_bin_xyz"]}})
        assert result["valid"] is False
        assert "nonexistent_bin_xyz" in result["missing_bins"]

    def test_missing_config(self):
        result = validate_skill({"requires": {"config": ["NONEXISTENT_VAR_XYZ"]}})
        assert result["valid"] is False
        assert "NONEXISTENT_VAR_XYZ" in result["missing_config"]

    def test_set_config(self, monkeypatch):
        monkeypatch.setenv("_TEST_SKILLS_VAR", "value")
        result = validate_skill({"requires": {"config": ["_TEST_SKILLS_VAR"]}})
        assert result["valid"] is True
        assert result["missing_config"] == []

    def test_mixed_pass_fail(self):
        result = validate_skill(
            {
                "requires": {
                    "pip": ["sys"],
                    "bins": ["nonexistent_bin_xyz"],
                    "config": [],
                }
            }
        )
        assert result["valid"] is False
        assert result["missing_pip"] == []
        assert "nonexistent_bin_xyz" in result["missing_bins"]

    def test_return_structure(self):
        result = validate_skill({})
        assert "valid" in result
        assert "missing_pip" in result
        assert "missing_bins" in result
        assert "missing_config" in result
        # Verify actual values, not just key existence
        assert result["valid"] is True
        assert result["missing_pip"] == []
        assert result["missing_bins"] == []
        assert result["missing_config"] == []

    def test_return_structure_with_failures(self):
        """Verify structure contains actual failure data, not just keys."""
        result = validate_skill(
            {
                "requires": {
                    "pip": ["nonexistent_pkg_xyz_123"],
                    "bins": ["nonexistent_bin_xyz"],
                    "config": ["NONEXISTENT_VAR_XYZ"],
                }
            }
        )
        assert result["valid"] is False
        assert result["missing_pip"] == ["nonexistent_pkg_xyz_123"]
        assert result["missing_bins"] == ["nonexistent_bin_xyz"]
        assert result["missing_config"] == ["NONEXISTENT_VAR_XYZ"]
