# =================== AIPass ====================
# Name: testing_content.py
# Description: Testing Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Testing Standards Content Handler

Provides formatted testing standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_testing_standards() -> str:
    """Return formatted testing standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold red]TESTING STANDARDS[/bold red]",
        "",
        "[yellow]CURRENT STATE:[/yellow] Manual testing with JSON/log verification",
        "[dim]Future: pytest framework expansion once branches stabilize[/dim]",
        "",
        "─" * 70,
        "",
        "[bold cyan]THE 90% BUILD PROCESS:[/bold cyan]",
        "",
        "[bold cyan]1. Planning Phase[/bold cyan]",
        "  [green]✓[/green] Issue plan through Flow (master or default plan)",
        "  [green]✓[/green] Define structure before coding",
        "",
        "[bold cyan]2. Build to 90% (AI-Led)[/bold cyan]",
        "  [green]✓[/green] AI builds structure and implementation",
        "  [green]✓[/green] Internal verification as you go:",
        "    [dim]- Does the module turn on?[/dim]",
        "    [dim]- Do commands work?[/dim]",
        "    [dim]- Basic functionality confirmed?[/dim]",
        "",
        "[bold cyan]3. 90% Threshold (Human Review)[/bold cyan]",
        "  [green]✓[/green] Human reviews structure and implementation",
        "  [green]✓[/green] Feature tests (does it do what it should?)",
        "  [green]✓[/green] Identifies bugs and missing error handling",
        "",
        "[bold cyan]4. Debug Cycle[/bold cyan]",
        "  [yellow]CRITICAL:[/yellow] Fix error handling BEFORE fixing bugs",
        "  [dim]1. Fix error handling - make errors tell the truth[/dim]",
        "  [dim]2. Then fix the actual bug[/dim]",
        "  [dim]3. See clean pass with honest outputs[/dim]",
        "",
        "[bold cyan]5. Iterate Until Acceptable[/bold cyan]",
        "  [green]✓[/green] Test features, debug cycle, reach acceptable standard",
        "",
        "─" * 70,
        "",
        "[bold yellow]ERROR HANDLING PHILOSOPHY:[/bold yellow]",
        "",
        "[yellow]RULE:[/yellow] Errors must tell the truth",
        "",
        "[green]✓ Good error handling:[/green]",
        "  [dim]try:[/dim]",
        "    [dim]result = api_call()[/dim]",
        "    [dim]if not result:[/dim]",
        "      [dim]logger.error('API call failed - no response')[/dim]",
        "      [dim]return {'success': False, 'error': 'API returned no data'}[/dim]",
        "  [dim]except Exception as e:[/dim]",
        "    [dim]logger.error(f'API call exception: {e}', exc_info=True)[/dim]",
        "    [dim]return {'success': False, 'error': str(e)}[/dim]",
        "",
        "[red]✗ Bad error handling:[/red]",
        "  [dim]try:[/dim]",
        "    [dim]result = api_call()[/dim]",
        "    [dim]return {'success': True}  # LIES - didn't check result[/dim]",
        "  [dim]except:[/dim]",
        "    [dim]pass  # Silent failure - no truth[/dim]",
        "",
        "─" * 70,
        "",
        "[bold yellow]JSON/LOG VERIFICATION LAYER:[/bold yellow]",
        "",
        "[bold cyan]Config Verification:[/bold cyan]",
        "  [dim]cat module_name_config.json  # Settings, keys, toggles[/dim]",
        "",
        "[bold cyan]State Verification:[/bold cyan]",
        "  [dim]cat module_name_data.json   # Metrics, counts, status[/dim]",
        "",
        "[bold cyan]Operations Verification:[/bold cyan]",
        "  [dim]cat module_name_log.json    # Recent operations and results[/dim]",
        "",
        "[bold cyan]Detailed Debugging:[/bold cyan]",
        "  [dim]cat system_logs/module_name.log  # Prax file-based logging[/dim]",
        "",
        "─" * 70,
        "",
        "[bold yellow]TESTING CHECKLIST:[/bold yellow]",
        "",
        "  [green]✓[/green] Does it turn on without errors?",
        "  [green]✓[/green] Do basic commands work?",
        "  [green]✓[/green] Are errors handled and logged?",
        "  [green]✓[/green] Do outputs tell the truth?",
        "  [green]✓[/green] Check config.json - settings correct?",
        "  [green]✓[/green] Check data.json - state tracking working?",
        "  [green]✓[/green] Check log.json - operations recorded?",
        "  [green]✓[/green] Test edge cases (invalid input, missing files)",
        "  [green]✓[/green] Check Prax logs for detailed debugging",
        "  [green]✓[/green] Manual feature tests at 90% stage",
        "",
        "─" * 70,
        "",
        "[bold yellow]PYTEST INFRASTRUCTURE:[/bold yellow]",
        "",
        "[dim]pytest.ini[/dim]                    Root config",
        "[dim]tests/conftest.py[/dim]             Shared fixtures",
        "[dim]src/aipass/<branch>/tests/[/dim]    Branch-specific tests",
        "",
        "[yellow]RULE:[/yellow] Expand automated tests when:",
        "  [dim]- Modules and branches stabilize[/dim]",
        "  [dim]- System changes slow down (monthly, not weekly)[/dim]",
        "  [dim]- Maintenance cost < value of automation[/dim]",
        "",
        "[yellow]RULE:[/yellow] Selective approach:",
        "  [green]✓[/green] Test critical/stable components (API, Prax rotation)",
        "  [green]✓[/green] Skip testing rapidly changing features",
        "  [green]✓[/green] Manual testing for experimental work",
        "  [green]✓[/green] Automated tests where they add value",
        "",
        "[dim]Run: pytest, pytest src/aipass/<branch>/tests/, pytest -m unit[/dim]",
        "",
        "─" * 70,
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (testing)[/dim]",
        "  [dim]See: src/aipass/api/tests/ (working pytest examples)[/dim]",
        "  [dim]See: src/aipass/seedgo/apps/modules/test_cli_errors.py (demo module)[/dim]",
        "",
        "[bold]Status:[/bold] Draft v1 - Manual testing documented",
        "[bold]Philosophy:[/bold] Build fast, verify as you go, handle errors honestly",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "testing"})
    return "\n".join(lines)
