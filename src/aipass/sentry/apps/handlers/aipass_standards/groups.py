# =================== AIPass ====================
# Name: groups.py
# Description: The aipass pack's checker registry: every scored row and the one group it prints under
# Version: 1.0.0
# Created: 2026-11-26
# Modified: 2026-11-26
# =============================================

"""
The aipass pack's checker registry.

Every ``*_check.py`` in this directory is registered here under exactly one group, and so is
every scored row the audit adds beside the checkers (diagnostics, pack_registry). The audit grid
prints by these groups and the standards doc carries one section per group, in this order.
The pack_registry row fails a checker file missing from GROUPS, a name here with no file, and a
file that does not load as a checker.
"""

from typing import Dict, List

GROUPS: Dict[str, List[str]] = {
    "architecture": [
        "architecture",
        "encapsulation",
        "front_door",
        "gateway_boundary",
        "handlers",
        "imports",
        "module_scope_side_effect",
        "modules",
        "stdlib_only",
        "trigger",
    ],
    "cli": [
        "cli",
        "cli_flags",
        "cli_ux",
        "help_flag_safety",
        "help_text",
        "introspection",
        "output_routing",
        "rich_markup",
        "stderr_routing",
        "subcommand_help",
    ],
    "code": ["accepted_and_never_used_parameter", "dead_code", "deep_nesting", "unused_function"],
    "docs": ["documentation", "docs_page", "readme", "readme_quality", "template", "todo", "trinity"],
    "errors": ["error_handling", "exception_text_in_response", "fallback", "silent_catch"],
    "header": ["lowercase_name", "meta", "naming", "shebang"],
    "json": ["json_handler", "json_structure"],
    "logging": [
        "commented_logger",
        "debug_print",
        "log_handler",
        "log_level",
        "log_structure",
        "log_visibility",
        "logged_fallback",
        "one_logger",
    ],
    "paths": [
        "caller_file_depth",
        "developer_home",
        "fixed_depth_path",
        "hardcoded_path",
        "host_portability",
        "os_walk_onerror",
    ],
    "security": ["clear_text_secret_logging", "hardcoded_key", "permission_flags"],
    "tests": [
        "calendar_bound",
        "conftest_fixtures",
        "constant_predicate",
        "declared_pass_contradiction",
        "declared_pass_symbol_resolves",
        "discarded_patch",
        "duplicate_test",
        "file_top",
        "flag_never_passed",
        "host_coupled_oracle",
        "import_site",
        "literal_path",
        "mock_console",
        "named_encoding",
        "no_product_call",
        "oversize_test_file",
        "rendered_path_oracle",
        "retired_token_docstring",
        "router_assert",
        "self_set_assert",
        "sleep_in_test",
        "stale_header_date",
        "state_leak",
        "stdlib_patch",
        "subprocess_text_true",
        "through_the_command",
        "uncalled_public_function",
        "unconsumed_side_effect",
        "unused_conftest_fixture",
        "weak_oracle",
    ],
    "tooling": ["diagnostics", "pack_registry", "ruff"],
}

# Scored rows the audit itself adds; registered above, but no *_check.py backs them.
AUDIT_ROWS = frozenset({"diagnostics", "pack_registry"})
