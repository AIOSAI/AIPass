# =================== AIPass ====================
# Name: test_quality_content.py
# Description: Test Quality Standards Content Handler
# Version: 4.0.0
# Created: 2026-03-24
# Modified: 2026-03-27
# =============================================

"""
Test Quality Standards Content Handler

Provides formatted Test Quality standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_test_quality_standards() -> str:
    """Return formatted test_quality standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Every branch should have tests covering 11 standard categories.",
        "  The checker scans ALL test files in tests/ (including conftest.py) —",
        "  no specific filenames required. Quality = coverage breadth.",
        "",
        "  [dim]Consolidates the former test_coverage standard into this single[/dim]",
        "  [dim]comprehensive test checker (module coverage is category 11).[/dim]",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Branch-level static analysis (does NOT run pytest):",
        "",
        "  [yellow]1. Pattern coverage (categories 1-10):[/yellow]",
        "  Scans [dim]tests/[/dim] for ALL [dim]test_*.py[/dim] files + [dim]conftest.py[/dim]",
        "  For each of 10 categories, checks if test files reference",
        "  the expected patterns. Reports per-category: X/N covered",
        "",
        "  [yellow]2. Module coverage (category 11):[/yellow]",
        "  Discovers test files broadly (tests/ + scattered test_*.py)",
        "  Maps tested modules via import patterns",
        "  Checks: test files exist, test functions exist, module coverage >= 25%",
        "",
        "[bold cyan]THE 11 CATEGORIES (51 items total):[/bold cyan]",
        "",
        "  [bold]1. JSON Handler (8 items)[/bold]",
        "     [dim]default_factory, validate, get_path, ensure_exists,[/dim]",
        "     [dim]load, save, log_operation, ensure_module[/dim]",
        "     Template: seedgo/templates/test_json_handler_template.py",
        "",
        "  [bold]2. CLI Routing (9 items)[/bold]",
        "     [dim]help_flag (--help), short_help (-h), help_word,[/dim]",
        "     [dim]no_args, unknown_command, return_bool,[/dim]",
        "     [dim]print_help, print_introspection, output_capture[/dim]",
        "     Template: seedgo/templates/test_cli_routing_template.py",
        "",
        "  [bold]3. Conftest Fixtures (6 items)[/bold]",
        "     [dim]temp_dir, sample_data, mock_infrastructure,[/dim]",
        "     [dim]mock_logger, mock_json_handler, cleanup[/dim]",
        "     Template: seedgo/templates/test_conftest_template.py",
        "",
        "  [bold]4. Error Resilience (4 items)[/bold]",
        "     [dim]missing_file, corrupt_json, empty_file, nonexistent_dir[/dim]",
        "     Template: seedgo/templates/test_error_resilience_template.py",
        "",
        "  [bold]5. Return Type Contracts (4 items)[/bold]",
        "     [dim]command_returns_bool, paths_return_path,[/dim]",
        "     [dim]ensure_returns_bool, load_correct_type[/dim]",
        "     Template: seedgo/templates/test_contracts_template.py",
        "",
        "  [bold]6. Exception Contracts (3 items)[/bold]",
        "     [dim]create_default_raises, save_invalid_raises,[/dim]",
        "     [dim]invalid_mode_raises[/dim]",
        "     Template: seedgo/templates/test_contracts_template.py",
        "",
        "  [bold]7. Data Structure Contracts (3 items)[/bold]",
        "     [dim]config_keys, data_keys, log_entry_field[/dim]",
        "     Template: seedgo/templates/test_contracts_template.py",
        "",
        "  [bold]8. Success/Failure Paths (4 items)[/bold]",
        "     [dim]known_routes_true, unknown_returns_false,[/dim]",
        "     [dim]help_preempts, no_args_triggers[/dim]",
        "     Template: seedgo/templates/test_cli_routing_template.py",
        "",
        "  [bold]9. Init/Provisioning (4 items)[/bold]",
        "     [dim]creates_files, auto_creates_dir,[/dim]",
        "     [dim]no_overwrite, returns_dict[/dim]",
        "     Template: seedgo/templates/test_init_provisioning_template.py",
        "",
        "  [bold]10. Infrastructure Mocking (3 items)[/bold]",
        "      [dim]autouse_fixtures, sys_modules_mock, reimport_after_mock[/dim]",
        "      Template: seedgo/templates/test_conftest_template.py",
        "",
        "  [bold]11. Module Coverage (3 items)[/bold]",
        "      [dim]test_files_exist, test_functions_exist, module_coverage_25pct[/dim]",
        "      Uses import-based module mapping (from aipass.<branch>.apps...)",
        "      Threshold: 25% of modules covered via imports",
        "",
        "[bold cyan]SCORING MODEL:[/bold cyan]",
        "",
        "  Score = (items_covered / 51) * 100",
        "",
        "  Overall pass threshold: [yellow]75%[/yellow] (39+ of 51 items)",
        "",
        "  [dim]No test files = 0%. All 51 items covered = 100%.[/dim]",
        "",
        "[bold cyan]EXAMPLE OUTPUT:[/bold cyan]",
        "",
        "  [dim]json_handler: 8/8 covered[/dim]",
        "  [dim]cli_routing: 7/9 covered (missing: help_word, output_capture)[/dim]",
        "  [dim]conftest_fixtures: 4/6 covered (missing: mock_infrastructure, mock_logger)[/dim]",
        "  [dim]error_resilience: 0/4 covered (...)[/dim]",
        "  [dim]module_coverage: 3/3 covered (5/8 modules, 42 tests)[/dim]",
        "  [dim]Overall: 26/51 items covered across 11 categories (50%)[/dim]",
        "",
        "[bold cyan]HOW TO COMPLY:[/bold cyan]",
        "",
        "  Write tests that cover the 10 categories above.",
        "  Tests can be in any test_*.py file in your tests/ directory.",
        "  Conftest fixtures go in tests/conftest.py.",
        "",
        "  Reference templates are available at:",
        "  [dim]seedgo/templates/test_json_handler_template.py[/dim]",
        "  [dim]seedgo/templates/test_cli_routing_template.py[/dim]",
        "  [dim]seedgo/templates/test_conftest_template.py[/dim]",
        "  [dim]seedgo/templates/test_error_resilience_template.py[/dim]",
        "  [dim]seedgo/templates/test_contracts_template.py[/dim]",
        "  [dim]seedgo/templates/test_init_provisioning_template.py[/dim]",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Runs once per branch (not per file). Entry point: [dim]check_branch()[/dim]",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Via [dim].seedgo/bypass.json[/dim] — supports standard-level and",
        "  file-level bypass rules",
        "",
        "[bold cyan]HISTORY:[/bold cyan]",
        "  [dim]v4.0 (2026-03-27): Consolidated test_coverage into test_quality[/dim]",
        "  [dim]  Module coverage is now category 11 (3 items). Total: 51 items.[/dim]",
        "  [dim]v3.0 (2026-03-24): Expanded from 8 to 48 items across 10 categories[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "test_quality"})
    return "\n".join(lines)
