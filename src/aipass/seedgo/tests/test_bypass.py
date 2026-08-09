"""Tests for the bypass handler directory (bypass_handler, ignore_handler)."""

# =================== META ====================
# Name: test_bypass.py
# Description: Unit tests for handlers/bypass/
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

import json
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for bypass handlers."""
    import sys

    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    # Force re-imports
    for mod_name in [
        "aipass.seedgo.apps.handlers.bypass.bypass_handler",
        "aipass.seedgo.apps.handlers.bypass.ignore_handler",
        "aipass.seedgo.apps.handlers.bypass.utils",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ---------------------------------------------------------------------------
# Tests -- bypass_handler.load_bypass_rules
# ---------------------------------------------------------------------------


def test_load_bypass_rules_from_file(tmp_path):
    """load_bypass_rules reads rules from .seedgo/bypass.json."""
    seedgo_dir = tmp_path / ".seedgo"
    seedgo_dir.mkdir()
    bypass_file = seedgo_dir / "bypass.json"
    bypass_data = {
        "metadata": {"version": "1.0.0", "created": "", "description": "test"},
        "bypass": [{"file": "apps/foo.py", "standard": "naming", "reason": "legacy"}],
        "notes": {},
    }
    bypass_file.write_text(json.dumps(bypass_data), encoding="utf-8")

    from aipass.seedgo.apps.handlers.bypass.bypass_handler import load_bypass_rules

    rules = load_bypass_rules(str(tmp_path))
    assert len(rules) == 1
    assert rules[0]["standard"] == "naming"


def test_load_bypass_rules_empty_when_no_rules(tmp_path):
    """load_bypass_rules returns empty list when bypass has no rules."""
    seedgo_dir = tmp_path / ".seedgo"
    seedgo_dir.mkdir()
    bypass_file = seedgo_dir / "bypass.json"
    bypass_data = {
        "metadata": {"version": "1.0.0", "created": "", "description": "test"},
        "bypass": [],
        "notes": {},
    }
    bypass_file.write_text(json.dumps(bypass_data), encoding="utf-8")

    from aipass.seedgo.apps.handlers.bypass.bypass_handler import load_bypass_rules

    rules = load_bypass_rules(str(tmp_path))
    assert rules == []


def test_load_bypass_rules_creates_config_if_missing(tmp_path):
    """load_bypass_rules creates .seedgo/bypass.json if it does not exist."""
    from aipass.seedgo.apps.handlers.bypass.bypass_handler import load_bypass_rules

    rules = load_bypass_rules(str(tmp_path))
    assert isinstance(rules, list)
    # Config should now exist
    assert (tmp_path / ".seedgo" / "bypass.json").exists()


# ---------------------------------------------------------------------------
# Tests -- bypass_handler.is_bypassed
# ---------------------------------------------------------------------------


def test_is_bypassed_matching_rule():
    """is_bypassed returns True when file and standard match a rule."""
    from aipass.seedgo.apps.handlers.bypass.bypass_handler import is_bypassed

    rules = [{"file": "apps/foo.py", "standard": "naming", "reason": "legacy"}]
    result = is_bypassed(
        file_path="/branch/apps/foo.py",
        branch_path="/branch",
        standard="naming",
        line=None,
        bypass_rules=rules,
    )
    assert result is True


def test_is_bypassed_no_match():
    """is_bypassed returns False when no rule matches."""
    from aipass.seedgo.apps.handlers.bypass.bypass_handler import is_bypassed

    rules = [{"file": "apps/foo.py", "standard": "naming", "reason": "legacy"}]
    result = is_bypassed(
        file_path="/branch/apps/bar.py",
        branch_path="/branch",
        standard="naming",
        line=None,
        bypass_rules=rules,
    )
    assert result is False


def test_is_bypassed_line_specific():
    """is_bypassed respects line-specific bypass rules."""
    from aipass.seedgo.apps.handlers.bypass.bypass_handler import is_bypassed

    rules = [{"file": "apps/foo.py", "standard": "cli", "lines": [10, 20], "reason": "circular"}]
    assert is_bypassed("/branch/apps/foo.py", "/branch", "cli", 10, rules) is True
    assert is_bypassed("/branch/apps/foo.py", "/branch", "cli", 99, rules) is False


def test_is_bypassed_empty_rules():
    """is_bypassed returns False with empty rules list."""
    from aipass.seedgo.apps.handlers.bypass.bypass_handler import is_bypassed

    assert is_bypassed("/branch/apps/foo.py", "/branch", "naming", None, []) is False


# ---------------------------------------------------------------------------
# Tests -- bypass_handler.ensure_seedgo_config
# ---------------------------------------------------------------------------


def test_ensure_seedgo_config_creates_dir(tmp_path):
    """ensure_seedgo_config creates .seedgo directory and bypass.json."""
    from aipass.seedgo.apps.handlers.bypass.bypass_handler import ensure_seedgo_config

    result = ensure_seedgo_config(str(tmp_path))
    assert result == tmp_path / ".seedgo" / "bypass.json"
    assert result.exists()


def test_ensure_seedgo_config_idempotent(tmp_path):
    """Calling ensure_seedgo_config twice does not corrupt the file."""
    from aipass.seedgo.apps.handlers.bypass.bypass_handler import ensure_seedgo_config

    ensure_seedgo_config(str(tmp_path))
    ensure_seedgo_config(str(tmp_path))
    bypass_file = tmp_path / ".seedgo" / "bypass.json"
    data = json.loads(bypass_file.read_text(encoding="utf-8"))
    assert "bypass" in data


# ---------------------------------------------------------------------------
# Tests -- ignore_handler
# ---------------------------------------------------------------------------


def test_get_audit_ignore_patterns_returns_list():
    """get_audit_ignore_patterns returns a list of strings."""
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import get_audit_ignore_patterns

    patterns = get_audit_ignore_patterns()
    assert isinstance(patterns, list)
    assert all(isinstance(p, str) for p in patterns)


def test_get_template_ignore_patterns_returns_copy():
    """get_template_ignore_patterns returns a copy (not the original list)."""
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import get_template_ignore_patterns

    a = get_template_ignore_patterns()
    b = get_template_ignore_patterns()
    assert a == b
    a.append("extra")
    assert a != get_template_ignore_patterns()


def test_template_ignore_excludes_test_scaffold():
    """test_scaffold.py is in TEMPLATE_IGNORE_PATTERNS so branches don't require it."""
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import get_template_ignore_patterns

    patterns = get_template_ignore_patterns()
    assert "test_scaffold.py" in patterns


def test_get_deprecated_patterns_returns_dict():
    """get_deprecated_patterns returns a dict of string keys and string values."""
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import get_deprecated_patterns

    patterns = get_deprecated_patterns()
    assert isinstance(patterns, dict)
    for key, value in patterns.items():
        assert isinstance(key, str)
        assert isinstance(value, str)


# ---------------------------------------------------------------------------
# Tests -- .seedgoignore engine (load_ignore_entries / is_seedgo_ignored)
# ---------------------------------------------------------------------------


def test_global_default_ignores_tools_dir_with_no_dotfile(tmp_path):
    """Global default (tools/) applies branch-wide even with zero .seedgoignore files."""
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import is_seedgo_ignored

    tools_file = tmp_path / "apps" / "tools" / "scratch.py"
    tools_file.parent.mkdir(parents=True)
    tools_file.write_text("pass", encoding="utf-8")
    normal_file = tmp_path / "apps" / "modules" / "real.py"
    normal_file.parent.mkdir(parents=True)
    normal_file.write_text("pass", encoding="utf-8")

    assert is_seedgo_ignored(str(tools_file), tmp_path) is True
    assert is_seedgo_ignored(str(normal_file), tmp_path) is False


def test_seedgo_ignore_dotfile_scoped_to_its_own_directory(tmp_path):
    """A .seedgoignore dropped in a subdir only affects that subdir's subtree, not siblings."""
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import is_seedgo_ignored

    scratch_dir = tmp_path / "apps" / "handlers" / "experiment"
    scratch_dir.mkdir(parents=True)
    (scratch_dir / ".seedgoignore").write_text("*.draft.py\n", encoding="utf-8")
    (scratch_dir / "wip.draft.py").write_text("pass", encoding="utf-8")

    sibling_dir = tmp_path / "apps" / "handlers" / "other"
    sibling_dir.mkdir(parents=True)
    (sibling_dir / "wip.draft.py").write_text("pass", encoding="utf-8")

    assert is_seedgo_ignored(str(scratch_dir / "wip.draft.py"), tmp_path) is True
    assert is_seedgo_ignored(str(sibling_dir / "wip.draft.py"), tmp_path) is False


def test_seedgo_ignore_supports_gitignore_style_patterns(tmp_path):
    """Comments, blank lines, and negation follow standard gitignore semantics."""
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import is_seedgo_ignored

    (tmp_path / ".seedgoignore").write_text(
        "\n".join(["# comment", "", "scratch/", "!scratch/keep_me.py"]),
        encoding="utf-8",
    )
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    (scratch_dir / "throwaway.py").write_text("pass", encoding="utf-8")
    (scratch_dir / "keep_me.py").write_text("pass", encoding="utf-8")

    assert is_seedgo_ignored(str(scratch_dir / "throwaway.py"), tmp_path) is True
    assert is_seedgo_ignored(str(scratch_dir / "keep_me.py"), tmp_path) is False


def test_seedgo_ignore_nested_scopes_both_apply(tmp_path):
    """A nested .seedgoignore adds to (not replaces) any ancestor .seedgoignore scopes."""
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import is_seedgo_ignored

    (tmp_path / ".seedgoignore").write_text("*.rootskip\n", encoding="utf-8")
    child_dir = tmp_path / "apps" / "child"
    child_dir.mkdir(parents=True)
    (child_dir / ".seedgoignore").write_text("*.childskip\n", encoding="utf-8")
    (child_dir / "a.rootskip").write_text("pass", encoding="utf-8")
    (child_dir / "b.childskip").write_text("pass", encoding="utf-8")
    (child_dir / "c.py").write_text("pass", encoding="utf-8")

    assert is_seedgo_ignored(str(child_dir / "a.rootskip"), tmp_path) is True
    assert is_seedgo_ignored(str(child_dir / "b.childskip"), tmp_path) is True
    assert is_seedgo_ignored(str(child_dir / "c.py"), tmp_path) is False


def test_is_seedgo_ignored_path_outside_branch_root_returns_false(tmp_path):
    """A file outside branch_root cannot be resolved to a relative path — treated as not ignored."""
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import is_seedgo_ignored

    branch_root = tmp_path / "branch"
    branch_root.mkdir()
    outside_file = tmp_path / "elsewhere" / "file.py"
    outside_file.parent.mkdir()
    outside_file.write_text("pass", encoding="utf-8")

    assert is_seedgo_ignored(str(outside_file), branch_root) is False


def test_load_ignore_entries_default_only_when_no_dotfiles(tmp_path):
    """With no .seedgoignore files present, only the global default scope is returned."""
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import load_ignore_entries

    entries = load_ignore_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0][0] == ""


def test_is_seedgo_ignored_accepts_precomputed_entries(tmp_path):
    """Passing pre-loaded entries skips the internal reload — same result as omitting it."""
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import is_seedgo_ignored, load_ignore_entries

    tools_file = tmp_path / "tools" / "scratch.py"
    tools_file.parent.mkdir(parents=True)
    tools_file.write_text("pass", encoding="utf-8")

    entries = load_ignore_entries(tmp_path)
    assert is_seedgo_ignored(str(tools_file), tmp_path, entries) is True


# ---------------------------------------------------------------------------
# Tests -- utils.is_bypassed name-scoped bypass
# ---------------------------------------------------------------------------


def test_utils_name_match_suppresses_regardless_of_line():
    """Name-scoped bypass matches by function name, ignoring line number."""
    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

    rules = [
        {
            "file": "apps/ops.py",
            "standard": "unused_function",
            "functions": ["update_command"],
            "reason": "public API",
        }
    ]
    assert (
        is_bypassed(
            "/branch/apps/ops.py",
            "unused_function",
            line=999,
            bypass_rules=rules,
            name="update_command",
        )
        is True
    )


def test_utils_name_not_in_functions_list():
    """Name-scoped bypass rejects function not in the functions list."""
    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

    rules = [
        {
            "file": "apps/ops.py",
            "standard": "unused_function",
            "functions": ["update_command"],
            "reason": "public API",
        }
    ]
    assert (
        is_bypassed(
            "/branch/apps/ops.py",
            "unused_function",
            line=232,
            bypass_rules=rules,
            name="delete_command",
        )
        is False
    )


def test_utils_line_drift_no_longer_breaks_name_scoped():
    """Line drift doesn't affect name-scoped bypass — name is stable."""
    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

    rules = [
        {
            "file": "apps/ops.py",
            "standard": "unused_function",
            "functions": ["get_skill", "get_skill_names"],
            "reason": "public API",
        }
    ]
    assert (
        is_bypassed(
            "/branch/apps/ops.py",
            "unused_function",
            line=52,
            bypass_rules=rules,
            name="get_skill",
        )
        is True
    )
    assert (
        is_bypassed(
            "/branch/apps/ops.py",
            "unused_function",
            line=9999,
            bypass_rules=rules,
            name="get_skill",
        )
        is True
    )


def test_utils_functions_present_name_none_falls_back_to_lines():
    """When functions is set but name=None (other checker), fall back to line matching."""
    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

    rules = [
        {
            "file": "apps/ops.py",
            "standard": "unused_function",
            "functions": ["update_command"],
            "lines": [10],
            "reason": "test",
        }
    ]
    assert (
        is_bypassed(
            "/branch/apps/ops.py",
            "unused_function",
            line=10,
            bypass_rules=rules,
            name=None,
        )
        is True
    )


def test_utils_existing_lines_only_rules_still_work():
    """Existing line-only rules (no functions field) still match by line."""
    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

    rules = [
        {
            "file": "apps/foo.py",
            "standard": "cli",
            "lines": [10, 20],
            "reason": "circular",
        }
    ]
    assert (
        is_bypassed(
            "/branch/apps/foo.py",
            "cli",
            line=10,
            bypass_rules=rules,
        )
        is True
    )
    assert (
        is_bypassed(
            "/branch/apps/foo.py",
            "cli",
            line=99,
            bypass_rules=rules,
        )
        is False
    )


def test_utils_file_only_bypass_still_matches():
    """File-level bypass (no lines, no functions) still works."""
    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

    rules = [
        {
            "file": "apps/foo.py",
            "standard": "unused_function",
            "reason": "whole file bypassed",
        }
    ]
    assert (
        is_bypassed(
            "/branch/apps/foo.py",
            "unused_function",
            line=50,
            bypass_rules=rules,
            name="anything",
        )
        is True
    )


def test_utils_multiple_functions_in_one_rule():
    """A single rule can list multiple function names."""
    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

    rules = [
        {
            "file": "apps/registry.py",
            "standard": "unused_function",
            "functions": ["get_skill", "get_skill_names"],
            "reason": "public API",
        }
    ]
    assert (
        is_bypassed(
            "/branch/apps/registry.py",
            "unused_function",
            line=1,
            bypass_rules=rules,
            name="get_skill",
        )
        is True
    )
    assert (
        is_bypassed(
            "/branch/apps/registry.py",
            "unused_function",
            line=1,
            bypass_rules=rules,
            name="get_skill_names",
        )
        is True
    )
    assert (
        is_bypassed(
            "/branch/apps/registry.py",
            "unused_function",
            line=1,
            bypass_rules=rules,
            name="other_func",
        )
        is False
    )


# ---------------------------------------------------------------------------
# utils.is_bypassed -- scope must be SUPPLIED, not just declared (FPLAN-0382)
# ---------------------------------------------------------------------------


def test_utils_lines_rule_does_not_match_when_no_line_supplied():
    """A lines rule is inert for a caller that passes no line -- never file-wide.

    This is the whole defect: every checker's top-of-check_module gate calls
    is_bypassed(path, standard) with no line, so a rule reading "lines": [37, 66]
    used to suppress the entire file for that standard.
    """
    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

    rules = [{"file": "apps/ops.py", "standard": "silent_catch", "lines": [37, 66], "reason": "test"}]

    assert is_bypassed("/branch/apps/ops.py", "silent_catch", bypass_rules=rules) is False
    assert is_bypassed("/branch/apps/ops.py", "silent_catch", line=37, bypass_rules=rules) is True
    assert is_bypassed("/branch/apps/ops.py", "silent_catch", line=99, bypass_rules=rules) is False


def test_utils_functions_rule_does_not_match_when_no_name_supplied():
    """Same contract for name-scoped rules: no name supplied means no match."""
    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

    rules = [{"file": "apps/ops.py", "standard": "unused_function", "functions": ["foo"], "reason": "test"}]

    assert is_bypassed("/branch/apps/ops.py", "unused_function", bypass_rules=rules) is False
    assert is_bypassed("/branch/apps/ops.py", "unused_function", name="foo", bypass_rules=rules) is True
    assert is_bypassed("/branch/apps/ops.py", "unused_function", name="bar", bypass_rules=rules) is False


def test_utils_declared_scope_that_is_supplied_must_match():
    """With both keys declared, a supplied scope that disagrees blocks the match.

    A rule for update_command does not cover some other symbol that happens to
    sit on the same line.
    """
    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

    rules = [
        {
            "file": "apps/ops.py",
            "standard": "unused_function",
            "functions": ["update_command"],
            "lines": [10],
            "reason": "test",
        }
    ]

    assert is_bypassed("/branch/apps/ops.py", "unused_function", line=10, name="other", bypass_rules=rules) is False
    assert is_bypassed("/branch/apps/ops.py", "unused_function", line=10, name="update_command", bypass_rules=rules)


def test_utils_unscoped_rule_is_still_file_wide():
    """A rule with neither lines nor functions keeps matching everything in its file."""
    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

    rules = [{"file": "apps/ops.py", "standard": "silent_catch", "reason": "test"}]

    assert is_bypassed("/branch/apps/ops.py", "silent_catch", bypass_rules=rules) is True
    assert is_bypassed("/branch/apps/ops.py", "silent_catch", line=12345, bypass_rules=rules) is True


# inert.py -- a rule whose scope the checker can never evaluate must ANNOUNCE itself (FPLAN-0382 ruling a)


def test_inert_scope_support_is_derived_not_hardcoded():
    """The map comes from the checker sources, so it cannot drift from them."""
    from aipass.seedgo.apps.handlers.bypass import inert

    support = inert.scope_support()

    # cli threads line= into is_bypassed; handlers gates once at the top of check_module.
    assert "lines" in support["cli"]
    assert support["handlers"] == set()


def test_inert_lines_rule_on_line_blind_standard_is_reported():
    from aipass.seedgo.apps.handlers.bypass import inert

    assert inert.inert_scopes({"file": "a.py", "standard": "handlers", "lines": [10]}) == ("lines",)


def test_inert_lines_rule_on_line_passing_standard_is_not_reported():
    from aipass.seedgo.apps.handlers.bypass import inert

    assert inert.inert_scopes({"file": "a.py", "standard": "cli", "lines": [10]}) == ()


def test_inert_unscoped_rule_is_never_reported():
    """File-wide rules are the recommended form -- they must not be nagged about."""
    from aipass.seedgo.apps.handlers.bypass import inert

    assert inert.inert_scopes({"file": "a.py", "standard": "handlers"}) == ()


def test_inert_unknown_standard_is_left_alone():
    """A rule naming no known standard is a different defect; this channel reports scope only."""
    from aipass.seedgo.apps.handlers.bypass import inert

    assert inert.inert_scopes({"file": "a.py", "standard": "nope", "lines": [1]}) == ()


def test_inert_branch_info_names_the_file_and_standard(tmp_path):
    import json

    from aipass.seedgo.apps.handlers.bypass import inert

    (tmp_path / ".seedgo").mkdir()
    (tmp_path / ".seedgo" / "bypass.json").write_text(
        json.dumps({"bypass": [{"file": "apps/x.py", "standard": "handlers", "lines": [7]}]}), encoding="utf-8"
    )

    lines = inert.check_branch_info(str(tmp_path))

    assert len(lines) == 1
    assert "apps/x.py" in lines[0] and "handlers" in lines[0] and "inert" in lines[0]


def test_inert_branch_info_empty_without_a_bypass_file(tmp_path):
    from aipass.seedgo.apps.handlers.bypass import inert

    assert inert.check_branch_info(str(tmp_path)) == []
