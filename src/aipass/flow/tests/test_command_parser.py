"""Tests for flow command argument parser.

Covers parse_create_plan_args, parse_close_command_args, and
parse_restore_command_args from apps/handlers/plan/command_parser.py.
"""

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Default type map returned by the mocked get_type_map
# ---------------------------------------------------------------------------
DEFAULT_TYPE_MAP = {
    "default": "flow_plans",
    "fplan": "flow_plans",
    "dplan": "dev_plans",
}

# The registered set these tests parse against.
#
# WHY THIS IS PINNED RATHER THAN READ. --exclude-type validates against the
# live template registry, which is runtime state: a fresh checkout ships no
# registry at all. Asserting that APLAN is accepted therefore asserted that
# THIS MACHINE had audit_plans registered, and CI -- which is always a fresh
# checkout -- red on exactly that (PR 739, linux 3.10). What these tests are
# for is the parser: does it collect the value, upper-case it, repeat, refuse
# an unknown one. None of that is a claim about which types happen to exist.
# The one test that IS a claim about the live registry stays live and is
# marked as such; TestRegisteredPrefixesContract keeps this constant honest.
FAKE_REGISTERED = ["APLAN", "DPLAN", "FPLAN", "PPLAN"]


@pytest.fixture
def registered(request):
    """Pin the parser's registered-type source for the duration of a test."""
    prefixes = getattr(request, "param", FAKE_REGISTERED)
    with patch(
        "aipass.flow.apps.handlers.plan.command_parser._registered_prefixes",
        return_value=list(prefixes),
    ) as mocked:
        yield mocked


# ---------------------------------------------------------------------------
# parse_create_plan_args
# ---------------------------------------------------------------------------
class TestParseCreatePlanArgs:
    """Tests for parse_create_plan_args."""

    @patch(
        "aipass.flow.apps.handlers.template.registry_ops.get_type_map",
        return_value=DEFAULT_TYPE_MAP,
    )
    def test_empty_args_returns_defaults(self, _mock_type_map):
        from aipass.flow.apps.handlers.plan.command_parser import parse_create_plan_args

        location, subject, plan_type_key = parse_create_plan_args([])
        assert location is None
        assert subject == ""
        assert plan_type_key == "flow_plans"

    @patch(
        "aipass.flow.apps.handlers.template.registry_ops.get_type_map",
        return_value=DEFAULT_TYPE_MAP,
    )
    def test_single_arg_sets_location(self, _mock_type_map):
        from aipass.flow.apps.handlers.plan.command_parser import parse_create_plan_args

        location, subject, plan_type_key = parse_create_plan_args(["@flow"])
        assert location == "@flow"
        assert subject == ""
        assert plan_type_key == "flow_plans"

    @patch(
        "aipass.flow.apps.handlers.template.registry_ops.get_type_map",
        return_value=DEFAULT_TYPE_MAP,
    )
    def test_two_args_sets_location_and_subject(self, _mock_type_map):
        from aipass.flow.apps.handlers.plan.command_parser import parse_create_plan_args

        location, subject, plan_type_key = parse_create_plan_args(["@flow", "My task"])
        assert location == "@flow"
        assert subject == "My task"
        assert plan_type_key == "flow_plans"

    @patch(
        "aipass.flow.apps.handlers.template.registry_ops.get_type_map",
        return_value=DEFAULT_TYPE_MAP,
    )
    def test_dplan_type_resolves_to_dev_plans(self, _mock_type_map):
        from aipass.flow.apps.handlers.plan.command_parser import parse_create_plan_args

        location, subject, plan_type_key = parse_create_plan_args(["@flow", "Dev work", "dplan"])
        assert location == "@flow"
        assert subject == "Dev work"
        assert plan_type_key == "dev_plans"

    @patch(
        "aipass.flow.apps.handlers.template.registry_ops.get_type_map",
        return_value={**DEFAULT_TYPE_MAP, "master": "master"},
    )
    def test_master_type_resolves_to_master(self, _mock_type_map):
        from aipass.flow.apps.handlers.plan.command_parser import parse_create_plan_args

        _, _, plan_type_key = parse_create_plan_args(["@flow", "Important task", "master"])
        assert plan_type_key == "master"

    @patch(
        "aipass.flow.apps.handlers.template.registry_ops.get_type_map",
        return_value=DEFAULT_TYPE_MAP,
    )
    def test_unknown_type_passed_through(self, _mock_type_map):
        from aipass.flow.apps.handlers.plan.command_parser import parse_create_plan_args

        _, _, plan_type_key = parse_create_plan_args(["@flow", "Experiment", "custom_thing"])
        # Not in the type map, so the raw value is returned as-is
        assert plan_type_key == "custom_thing"

    @patch(
        "aipass.flow.apps.handlers.template.registry_ops.get_type_map",
        return_value=DEFAULT_TYPE_MAP,
    )
    def test_type_resolution_is_case_insensitive(self, _mock_type_map):
        from aipass.flow.apps.handlers.plan.command_parser import parse_create_plan_args

        _, _, plan_type_key = parse_create_plan_args(["@flow", "Subject", "DPLAN"])
        assert plan_type_key == "dev_plans"

    @patch(
        "aipass.flow.apps.handlers.template.registry_ops.get_type_map",
        return_value=DEFAULT_TYPE_MAP,
    )
    def test_default_keyword_resolves_to_flow_plans(self, _mock_type_map):
        from aipass.flow.apps.handlers.plan.command_parser import parse_create_plan_args

        _, _, plan_type_key = parse_create_plan_args(["@flow", "Subject", "default"])
        assert plan_type_key == "flow_plans"

    @patch(
        "aipass.flow.apps.handlers.template.registry_ops.get_type_map",
        side_effect=Exception("registry broken"),
    )
    def test_fallback_type_map_on_registry_error(self, _mock_type_map):
        from aipass.flow.apps.handlers.plan.command_parser import parse_create_plan_args

        location, subject, plan_type_key = parse_create_plan_args(["@flow", "Fallback test", "dplan"])
        assert location == "@flow"
        assert subject == "Fallback test"
        assert plan_type_key == "dev_plans"

    @patch(
        "aipass.flow.apps.handlers.template.registry_ops.get_type_map",
        side_effect=Exception("registry broken"),
    )
    def test_fallback_defaults_for_no_type_arg(self, _mock_type_map):
        from aipass.flow.apps.handlers.plan.command_parser import parse_create_plan_args

        _, _, plan_type_key = parse_create_plan_args([])
        assert plan_type_key == "flow_plans"

    @patch(
        "aipass.flow.apps.handlers.template.registry_ops.get_type_map",
        return_value=DEFAULT_TYPE_MAP,
    )
    def test_return_types(self, _mock_type_map):
        from aipass.flow.apps.handlers.plan.command_parser import parse_create_plan_args

        result = parse_create_plan_args(["@flow", "subject", "dplan"])
        assert isinstance(result, tuple)
        assert len(result) == 3
        location, subject, plan_type_key = result
        assert isinstance(location, str)  # Only for this specific test case where args are provided
        assert isinstance(subject, str)
        assert isinstance(plan_type_key, str)

    @patch(
        "aipass.flow.apps.handlers.template.registry_ops.get_type_map",
        return_value=DEFAULT_TYPE_MAP,
    )
    def test_location_type_union(self, _mock_type_map):
        """Location can be None or str -- verify both paths."""
        from aipass.flow.apps.handlers.plan.command_parser import parse_create_plan_args

        # None case
        loc1, _, _ = parse_create_plan_args([])
        assert loc1 is None
        # String case
        loc2, _, _ = parse_create_plan_args(["@flow"])
        assert isinstance(loc2, str)

    @patch(
        "aipass.flow.apps.handlers.template.registry_ops.get_type_map",
        return_value=DEFAULT_TYPE_MAP,
    )
    def test_empty_args_location_is_none(self, _mock_type_map):
        from aipass.flow.apps.handlers.plan.command_parser import parse_create_plan_args

        result = parse_create_plan_args([])
        assert result[0] is None


# ---------------------------------------------------------------------------
# parse_close_command_args
# ---------------------------------------------------------------------------
class TestParseCloseCommandArgs:
    """Tests for parse_close_command_args."""

    def test_empty_args_returns_error(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        plan_num, confirm, all_plans, dry_run, _excl, error = parse_close_command_args([])
        assert plan_num is None
        assert confirm is False
        assert all_plans is False
        assert dry_run is False
        assert error == "Plan number or --all required"

    def test_plan_number_only(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        plan_num, confirm, all_plans, dry_run, _excl, error = parse_close_command_args(["42"])
        assert plan_num == "42"
        assert confirm is False
        assert all_plans is False
        assert dry_run is False
        assert error is None

    def test_all_flag(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        plan_num, confirm, all_plans, dry_run, _excl, error = parse_close_command_args(["--all"])
        assert plan_num is None
        assert confirm is False
        assert all_plans is True
        assert dry_run is False
        assert error is None

    def test_confirm_flag(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        plan_num, confirm, all_plans, dry_run, _excl, error = parse_close_command_args(["42", "--confirm"])
        assert plan_num == "42"
        assert confirm is True
        assert all_plans is False
        assert dry_run is False
        assert error is None

    def test_interactive_flag_sets_confirm(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        _, confirm, _, _, _excl, error = parse_close_command_args(["42", "--interactive"])
        assert confirm is True
        assert error is None

    def test_dry_run_flag(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        plan_num, confirm, all_plans, dry_run, _excl, error = parse_close_command_args(["42", "--dry-run"])
        assert plan_num == "42"
        assert confirm is False
        assert all_plans is False
        assert dry_run is True
        assert error is None

    def test_preview_flag_sets_dry_run(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        _, _, _, dry_run, _excl, error = parse_close_command_args(["42", "--preview"])
        assert dry_run is True
        assert error is None

    def test_all_with_confirm(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        plan_num, confirm, all_plans, dry_run, _excl, error = parse_close_command_args(["--all", "--confirm"])
        assert plan_num is None
        assert confirm is True
        assert all_plans is True
        assert dry_run is False
        assert error is None

    def test_all_with_dry_run(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        plan_num, confirm, all_plans, dry_run, _excl, error = parse_close_command_args(["--all", "--dry-run"])
        assert plan_num is None
        assert confirm is False
        assert all_plans is True
        assert dry_run is True
        assert error is None

    def test_all_with_preview(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        _, _, all_plans, dry_run, _excl, error = parse_close_command_args(["--all", "--preview"])
        assert all_plans is True
        assert dry_run is True
        assert error is None

    def test_all_confirm_dry_run_combined(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        plan_num, confirm, all_plans, dry_run, _excl, error = parse_close_command_args(
            ["--all", "--confirm", "--dry-run"]
        )
        assert plan_num is None
        assert confirm is True
        assert all_plans is True
        assert dry_run is True
        assert error is None

    def test_yes_flag_is_redundant(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        plan_num, confirm, all_plans, dry_run, _excl, error = parse_close_command_args(["42", "--yes"])
        assert plan_num == "42"
        # --yes does NOT set confirm (it's for backward compat, auto-confirm is default)
        assert confirm is False
        assert error is None

    def test_y_flag_is_redundant(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        plan_num, confirm, _, _, _excl, error = parse_close_command_args(["42", "-y"])
        assert plan_num == "42"
        assert confirm is False
        assert error is None

    def test_plan_number_with_all_flags(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        plan_num, confirm, all_plans, dry_run, _excl, error = parse_close_command_args(["7", "--confirm", "--dry-run"])
        assert plan_num == "7"
        assert confirm is True
        assert all_plans is False
        assert dry_run is True
        assert error is None

    def test_return_types(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        result = parse_close_command_args(["42"])
        assert isinstance(result, tuple)
        assert len(result) == 6
        plan_num, confirm, all_plans, dry_run, exclude_types, error = result
        assert isinstance(exclude_types, list)
        assert isinstance(plan_num, str)
        assert isinstance(confirm, bool)
        assert isinstance(all_plans, bool)
        assert isinstance(dry_run, bool)
        assert error is None

    def test_error_return_types(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        result = parse_close_command_args([])
        plan_num, confirm, all_plans, dry_run, _excl, error = result
        assert plan_num is None
        assert isinstance(error, str)

    def test_only_flags_no_plan_number_without_all(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        _, _, all_plans, _, _excl, error = parse_close_command_args(["--confirm", "--dry-run"])
        assert all_plans is False
        assert error == "Plan number or --all required"

    def test_plan_number_string_preserved(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        plan_num, _, _, _, _excl, _ = parse_close_command_args(["0042"])
        assert plan_num == "0042"

    def test_flag_order_does_not_matter(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        r1 = parse_close_command_args(["--all", "--confirm", "--dry-run"])
        r2 = parse_close_command_args(["--dry-run", "--all", "--confirm"])
        r3 = parse_close_command_args(["--confirm", "--dry-run", "--all"])
        assert r1 == r2 == r3

    def test_help_flag_not_treated_as_plan_number(self):
        """--help starts with -- so it's filtered from non-flag args."""
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        plan_num, confirm, all_plans, dry_run, _excl, error = parse_close_command_args(["--help"])
        # --help starts with -- so no non-flag args remain
        assert error is not None  # "Plan number or --all required"

    # ---- the silent flag drop ----
    # `--exclude APLAN` used to be byte-identical to passing nothing: the
    # argument vanished and the bulk close ran anyway. Red first — every one
    # of these returned error=None before the fix.

    def test_unknown_flag_refuses(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        plan_num, _, all_plans, _, _excl, error = parse_close_command_args(["--all", "--exclude", "APLAN"])
        assert error is not None
        assert "--exclude" in error
        # REFUSES the run: nothing survives the parse to be acted on.
        assert plan_num is None
        assert all_plans is False or error  # the caller must not proceed on an error

    def test_typo_in_the_flag_name_refuses(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        _, _, _, _, _excl, error = parse_close_command_args(["--all", "--exclude-typo", "APLAN"])
        assert error is not None
        assert "--exclude-typo" in error

    def test_unknown_flag_on_single_close_refuses(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        _, _, _, _, _excl, error = parse_close_command_args(["FPLAN-0042", "--force"])
        assert error is not None
        assert "--force" in error

    def test_stray_positional_refuses(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        _, _, _, _, _excl, error = parse_close_command_args(["FPLAN-0042", "FPLAN-0043"])
        assert error is not None

    def test_plan_number_with_all_refuses(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        _, _, _, _, _excl, error = parse_close_command_args(["--all", "42"])
        assert error is not None

    # ---- --exclude-type ----

    def test_exclude_type_collected(self, registered):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        _, _, all_plans, _, exclude_types, error = parse_close_command_args(["--all", "--exclude-type", "APLAN"])
        assert error is None
        assert all_plans is True
        assert exclude_types == ["APLAN"]

    def test_exclude_type_is_repeatable(self, registered):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        _, _, _, _, exclude_types, error = parse_close_command_args(
            ["--all", "--exclude-type", "APLAN", "--exclude-type", "PPLAN"]
        )
        assert error is None
        assert exclude_types == ["APLAN", "PPLAN"]

    def test_exclude_type_accepts_equals_form_and_lowercase(self, registered):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        _, _, _, _, exclude_types, error = parse_close_command_args(["--all", "--exclude-type=aplan"])
        assert error is None
        assert exclude_types == ["APLAN"]

    def test_unknown_plan_type_refuses_and_names_the_valid_ones(self, registered):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        _, _, _, _, _excl, error = parse_close_command_args(["--all", "--exclude-type", "APLNA"])
        assert error is not None
        assert "APLNA" in error
        # The operator must be able to act on the refusal, so every registered
        # type is named -- whatever the registered set happens to be.
        for prefix in FAKE_REGISTERED:
            assert prefix in error

    def test_exclude_type_validated_against_the_live_registry(self):
        """Not a literal list -- the valid set comes from the registered templates.

        Deliberately NOT mocked: this is the one test that must touch the real
        registry, because what it pins is that the parser and `drone @flow
        templates` read the same source. It is hermetic by construction rather
        than by isolation -- the input is derived from the same call the parser
        validates against, so it holds on a fresh checkout with two types and
        on this machine with seven.
        """
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args
        from aipass.flow.apps.handlers.template.registry_ops import get_prefix_map

        live = {p.upper() for p in get_prefix_map().values() if p}
        assert live, "the registry must always answer with at least the protected types"
        for prefix in sorted(live):
            _, _, _, _, exclude_types, error = parse_close_command_args(["--all", "--exclude-type", prefix])
            assert error is None, f"{prefix} is registered but was refused"
            assert exclude_types == [prefix]

    def test_a_bare_registry_still_accepts_the_protected_types(self):
        """What a fresh checkout is GUARANTEED to have, tracked tree alone.

        flow_json/ is not tracked, so CI starts with no registry and seeds
        _DEFAULT_TYPES. FPLAN and DPLAN are also _PROTECTED_TYPES and cannot be
        removed, so they are the only prefixes any checkout can promise. This
        test is the floor the CI failure exposed.
        """
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        for prefix in ("FPLAN", "DPLAN"):
            _, _, _, _, exclude_types, error = parse_close_command_args(["--all", "--exclude-type", prefix])
            assert error is None, f"{prefix} is protected but was refused"
            assert exclude_types == [prefix]

    def test_exclude_type_without_a_value_refuses(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        _, _, _, _, _excl, error = parse_close_command_args(["--all", "--exclude-type"])
        assert error is not None

    def test_exclude_type_without_all_refuses(self, registered):
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        _, _, _, _, _excl, error = parse_close_command_args(["FPLAN-0042", "--exclude-type", "APLAN"])
        assert error is not None
        assert "--all" in error

    def test_dry_run_with_error(self):
        """--dry-run alone without plan number should error but preserve dry_run."""
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        plan_num, confirm, all_plans, dry_run, _excl, error = parse_close_command_args(["--dry-run"])
        assert dry_run is True
        assert error is not None


# ---------------------------------------------------------------------------
# parse_restore_command_args
# ---------------------------------------------------------------------------
class TestParseRestoreCommandArgs:
    """Tests for parse_restore_command_args."""

    def test_empty_args_returns_error(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_restore_command_args

        plan_num, error = parse_restore_command_args([])
        assert plan_num is None
        assert error == "Plan number required"

    def test_plan_number_returned(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_restore_command_args

        plan_num, error = parse_restore_command_args(["42"])
        assert plan_num == "42"
        assert error is None

    def test_string_plan_number_preserved(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_restore_command_args

        plan_num, error = parse_restore_command_args(["0034"])
        assert plan_num == "0034"
        assert error is None

    def test_return_types_on_success(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_restore_command_args

        result = parse_restore_command_args(["1"])
        assert isinstance(result, tuple)
        assert len(result) == 2
        plan_num, error = result
        assert isinstance(plan_num, str)
        assert error is None

    def test_return_types_on_error(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_restore_command_args

        result = parse_restore_command_args([])
        plan_num, error = result
        assert plan_num is None
        assert isinstance(error, str)

    def test_extra_args_ignored(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_restore_command_args

        plan_num, error = parse_restore_command_args(["5", "extra", "stuff"])
        assert plan_num == "5"
        assert error is None

    def test_single_digit_plan_number(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_restore_command_args

        plan_num, error = parse_restore_command_args(["1"])
        assert plan_num == "1"
        assert error is None

    def test_large_plan_number(self):
        from aipass.flow.apps.handlers.plan.command_parser import parse_restore_command_args

        plan_num, error = parse_restore_command_args(["9999"])
        assert plan_num == "9999"
        assert error is None

    def test_empty_string_plan_number(self):
        """Empty string should still be returned (validation happens elsewhere)."""
        from aipass.flow.apps.handlers.plan.command_parser import parse_restore_command_args

        plan_num, error = parse_restore_command_args([""])
        assert plan_num == ""
        assert error is None

    def test_whitespace_plan_number(self):
        """Whitespace plan number is passed through (validation elsewhere)."""
        from aipass.flow.apps.handlers.plan.command_parser import parse_restore_command_args

        plan_num, error = parse_restore_command_args(["  "])
        assert plan_num == "  "
        assert error is None


# ---------------------------------------------------------------------------
# The mock's contract with production
# ---------------------------------------------------------------------------
class TestRegisteredPrefixesContract:
    """Proves FAKE_REGISTERED is shaped like what production actually returns.

    A mock is only worth what its shape agreement is worth. The exclude-type
    tests above run against FAKE_REGISTERED; if _registered_prefixes() ever
    starts returning something else -- a dict, lower-case, dir names instead of
    prefixes -- those tests would keep passing against a fiction. These do not.
    """

    @staticmethod
    def _is_prefix_list(value) -> bool:
        return (
            isinstance(value, list)
            and all(isinstance(p, str) and p and p == p.upper() and p == p.strip() for p in value)
            and value == sorted(value)
        )

    def test_production_returns_a_sorted_list_of_upper_case_prefixes(self):
        from aipass.flow.apps.handlers.plan.command_parser import _registered_prefixes

        live = _registered_prefixes()
        assert self._is_prefix_list(live), live
        assert len(set(live)) == len(live), "prefixes must be unique"

    def test_the_fake_satisfies_the_same_contract(self):
        assert self._is_prefix_list(FAKE_REGISTERED)

    def test_the_protected_types_are_present_on_any_checkout(self):
        """_PROTECTED_TYPES cannot be unregistered, so these always hold."""
        from aipass.flow.apps.handlers.plan.command_parser import _registered_prefixes

        live = _registered_prefixes()
        assert {"FPLAN", "DPLAN"} <= set(live)
        assert {"FPLAN", "DPLAN"} <= set(FAKE_REGISTERED)

    def test_the_fixture_actually_replaces_the_production_source(self, registered):
        """REACH assertion: without this the mocked tests prove nothing."""
        from aipass.flow.apps.handlers.plan.command_parser import parse_close_command_args

        parse_close_command_args(["--all", "--exclude-type", "APLAN"])
        assert registered.called, "the parser never consulted the registered-type source"
