# =================== AIPass ====================
# Name: test_quality_content.py
# Description: Test Quality Standards Content Handler
# Version: 3.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
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
        "  Every branch should have tests covering 10 standard categories.",
        "  The checker scans ALL test files in tests/ (including conftest.py) —",
        "  no specific filenames required. Quality = coverage breadth.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Branch-level static analysis (does NOT run pytest):",
        "",
        "  [yellow]1. Test file discovery:[/yellow]",
        "  Scans [dim]tests/[/dim] for ALL [dim]test_*.py[/dim] files + [dim]conftest.py[/dim]",
        "  No naming requirements — any test file counts",
        "",
        "  [yellow]2. Category coverage:[/yellow]",
        "  For each of 10 categories, checks if test files reference",
        "  the expected patterns. Reports per-category: X/N covered",
        "",
        "[bold cyan]THE 10 CATEGORIES (48 items total):[/bold cyan]",
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
        "[bold cyan]SCORING MODEL:[/bold cyan]",
        "",
        "  Score = (items_covered / 48) * 100",
        "",
        "  Overall pass threshold: [yellow]75%[/yellow] (36+ of 48 items)",
        "",
        "  [dim]No test files = 0%. All 48 items covered = 100%.[/dim]",
        "",
        "[bold cyan]EXAMPLE OUTPUT:[/bold cyan]",
        "",
        "  [dim]json_handler: 8/8 covered[/dim]",
        "  [dim]cli_routing: 7/9 covered (missing: help_word, output_capture)[/dim]",
        "  [dim]conftest_fixtures: 4/6 covered (missing: mock_infrastructure, mock_logger)[/dim]",
        "  [dim]error_resilience: 0/4 covered (...)[/dim]",
        "  [dim]Overall: 23/48 items covered across 10 categories (47%)[/dim]",
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
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "test_quality"})
    return "\n".join(lines)
