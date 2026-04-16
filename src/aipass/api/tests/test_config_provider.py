# =================== AIPass ====================
# Name: test_config_provider.py
# Description: Tests for provider configuration handler
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""
Tests for config.provider — provider configuration handler.

Tests:
- merge_configs deep merge behavior
- merge_configs in-place mutation and return value
- merge_configs nested dict recursion
- merge_configs non-dict overwrite
- get_validation_rules known providers
- get_validation_rules unknown provider returns None
"""

from unittest.mock import patch


from aipass.api.apps.handlers.config import provider as config_provider


# =============================================
# merge_configs tests
# =============================================


class TestMergeConfigs:
    """Tests for config.provider.merge_configs()."""

    @patch("aipass.api.apps.handlers.config.provider.json_handler")
    def test_simple_merge_adds_new_key(self, mock_jh):
        """New key in updates should appear in base."""
        base = {"a": 1}
        updates = {"b": 2}

        result = config_provider.merge_configs(base, updates)

        assert result["a"] == 1
        assert result["b"] == 2

    @patch("aipass.api.apps.handlers.config.provider.json_handler")
    def test_simple_merge_overwrites_existing_key(self, mock_jh):
        """Existing key should be overwritten by updates."""
        base = {"a": 1}
        updates = {"a": 99}

        result = config_provider.merge_configs(base, updates)

        assert result["a"] == 99

    @patch("aipass.api.apps.handlers.config.provider.json_handler")
    def test_nested_dict_merges_recursively(self, mock_jh):
        """Nested dicts should merge recursively, preserving untouched keys."""
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        updates = {"b": {"c": 99}, "e": 4}

        result = config_provider.merge_configs(base, updates)

        assert result["a"] == 1
        assert result["b"]["c"] == 99
        assert result["b"]["d"] == 3
        assert result["e"] == 4

    @patch("aipass.api.apps.handlers.config.provider.json_handler")
    def test_modifies_base_in_place(self, mock_jh):
        """merge_configs should modify base dict in-place."""
        base = {"a": 1}
        updates = {"b": 2}

        result = config_provider.merge_configs(base, updates)

        assert result is base
        assert base["b"] == 2

    @patch("aipass.api.apps.handlers.config.provider.json_handler")
    def test_returns_same_object_as_base(self, mock_jh):
        """Return value should be the same object as the input base."""
        base = {"x": "original"}
        updates = {"y": "added"}

        result = config_provider.merge_configs(base, updates)

        assert result is base

    @patch("aipass.api.apps.handlers.config.provider.json_handler")
    def test_non_dict_value_overwrites_dict(self, mock_jh):
        """Non-dict update value should overwrite existing dict value."""
        base = {"a": {"nested": True}}
        updates = {"a": "flat_string"}

        result = config_provider.merge_configs(base, updates)

        assert result["a"] == "flat_string"

    @patch("aipass.api.apps.handlers.config.provider.json_handler")
    def test_dict_value_overwrites_non_dict(self, mock_jh):
        """Dict update value should overwrite existing non-dict value."""
        base = {"a": "flat_string"}
        updates = {"a": {"nested": True}}

        result = config_provider.merge_configs(base, updates)

        assert result["a"] == {"nested": True}

    @patch("aipass.api.apps.handlers.config.provider.json_handler")
    def test_empty_updates_leaves_base_unchanged(self, mock_jh):
        """Empty updates dict should not change base."""
        base = {"a": 1, "b": 2}
        original = base.copy()
        updates = {}

        config_provider.merge_configs(base, updates)

        assert base == original

    @patch("aipass.api.apps.handlers.config.provider.json_handler")
    def test_deeply_nested_merge(self, mock_jh):
        """Three levels of nesting should all merge correctly."""
        base = {"level1": {"level2": {"level3": "old", "keep": "yes"}}}
        updates = {"level1": {"level2": {"level3": "new"}}}

        result = config_provider.merge_configs(base, updates)

        assert result["level1"]["level2"]["level3"] == "new"
        assert result["level1"]["level2"]["keep"] == "yes"

    @patch("aipass.api.apps.handlers.config.provider.json_handler")
    def test_logs_operation_on_merge(self, mock_jh):
        """merge_configs should call json_handler.log_operation."""
        base = {"a": 1}
        updates = {"b": 2, "c": 3}

        config_provider.merge_configs(base, updates)

        mock_jh.log_operation.assert_called_once_with("config_merged", {"keys_updated": 2})


# =============================================
# get_validation_rules tests (config.provider)
# =============================================


class TestGetValidationRulesConfigProvider:
    """Tests for config.provider.get_validation_rules()."""

    @patch("aipass.api.apps.handlers.config.provider.logger")
    def test_openrouter_rules(self, mock_logger):
        """openrouter should have prefix 'sk-or-v1-' and min_length 40."""
        rules = config_provider.get_validation_rules("openrouter")

        assert rules is not None
        assert rules["prefix"] == "sk-or-v1-"
        assert rules["min_length"] == 40

    @patch("aipass.api.apps.handlers.config.provider.logger")
    def test_openai_rules(self, mock_logger):
        """openai should have prefix 'sk-' and min_length 40."""
        rules = config_provider.get_validation_rules("openai")

        assert rules is not None
        assert rules["prefix"] == "sk-"
        assert rules["min_length"] == 40

    @patch("aipass.api.apps.handlers.config.provider.logger")
    def test_unknown_provider_returns_none(self, mock_logger):
        """Unknown provider should return None (no generic fallback)."""
        rules = config_provider.get_validation_rules("unknown_provider")

        assert rules is None

    @patch("aipass.api.apps.handlers.config.provider.logger")
    def test_unknown_provider_logs_info(self, mock_logger):
        """Unknown provider should log an info message."""
        config_provider.get_validation_rules("nonexistent")

        mock_logger.info.assert_called_once()
        assert "nonexistent" in mock_logger.info.call_args[0][0]

    @patch("aipass.api.apps.handlers.config.provider.logger")
    def test_known_provider_does_not_log(self, mock_logger):
        """Known provider should not trigger the info log."""
        config_provider.get_validation_rules("openrouter")

        mock_logger.info.assert_not_called()

    @patch("aipass.api.apps.handlers.config.provider.logger")
    def test_return_type_is_dict_for_known(self, mock_logger):
        """Known providers should return a dict."""
        for name in ["openrouter", "openai"]:
            rules = config_provider.get_validation_rules(name)
            assert isinstance(rules, dict), f"Expected dict for {name}"
