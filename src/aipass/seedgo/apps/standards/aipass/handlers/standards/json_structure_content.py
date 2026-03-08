"""
JSON Structure Standards Content Handler

Provides formatted JSON structure standards content.
Module orchestrates, handler implements.
"""

# =================== AIPass ====================
# Name: json_structure_content.py
# Description: JSON Structure Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================


def get_json_structure_standards() -> str:
    """Return formatted JSON structure standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]THREE-JSON PATTERN:[/bold cyan]",
        "",
        "[bold]Every module gets 3 auto-created files:[/bold]",
        "  • [yellow]module_config.json[/yellow] - Settings, limits (small, stable)",
        "  • [yellow]module_data.json[/yellow]   - Metrics, state (medium, periodic)",
        "  • [yellow]module_log.json[/yellow]    - Operations history (auto-rotating)",
        "",
        "[yellow]RULE:[/yellow] Auto-created on first use - NEVER create manually",
        "",
        "[bold cyan]USAGE (AUTO-DETECTION):[/bold cyan]",
        "  [dim]from aipass.seedgo.apps.handlers.json import json_handler[/dim]",
        "",
        "  [dim]# Handler auto-detects calling module name:[/dim]",
        "  [dim]json_handler.log_operation(\"operation_name\", {\"key\": \"value\"})[/dim]",
        "",
        "  [dim]# Creates module_config.json, module_data.json, module_log.json[/dim]",
        "  [dim]# Based on templates in apps/json_templates/default/[/dim]",
        "",
        "[bold cyan]LOG ROTATION (CRITICAL):[/bold cyan]",
        "  Set in config.json:",
        "  [dim]{[/dim]",
        "    [dim]\"config\": { \"max_log_entries\": 100 }[/dim]",
        "  [dim]}[/dim]",
        "",
        "  • Handler auto-rotates when limit reached",
        "  • Keeps most recent N entries (FIFO)",
        "  • [yellow]⚠️  Prevents log explosion (drone logs hit 171KB/7001 entries)[/yellow]",
        "",
        "[bold cyan]LOG STRUCTURE:[/bold cyan]",
        "  Array of entries (NOT object with \"entries\" key):",
        "  [dim][[/dim]",
        "    [dim]{ \"timestamp\": \"...\", \"operation\": \"...\", \"data\": {...} }[/dim]",
        "  [dim]][/dim]",
        "",
        "[bold cyan]LOCATIONS:[/bold cyan]",
        "  • Package JSON: [dim]src/aipass/{module}/aipass_json/[/dim]",
        "  • Per-module: [dim]src/aipass/{module}/{module}_json/[/dim]",
        "",
        "[bold red]SETUP json_handler.py (MANDATORY):[/bold red]",
        "  [red]✗ DO NOT copy seedgo's handler without changing paths![/red]",
        "",
        "  [green]✓ Update BRANCH_ROOT:[/green]",
        "    [dim]{BRANCH}_ROOT = Path(__file__).resolve().parents[N][/dim]",
        "",
        "  [green]✓ Update JSON_DIR:[/green]",
        "    [dim]{BRANCH}_JSON_DIR = {BRANCH}_ROOT / \"{branch}_json\"[/dim]",
        "",
        "  [green]✓ Update TEMPLATES_DIR:[/green]",
        "    [dim]JSON_TEMPLATES_DIR = {BRANCH}_ROOT / \"apps\" / \"json_templates\"[/dim]",
        "",
        "  [yellow]Validate:[/yellow] Run standards checker on json_handler.py",
        "  [dim]Expected: 100/100 on JSON STRUCTURE standard[/dim]",
        "",
        "[bold cyan]SPECIAL JSONS:[/bold cyan]",
        "  • [bold]Registries:[/bold] Collections (AIPASS_REGISTRY.json)",
        "  • [bold]Custom:[/bold] Module-specific needs (no limit)",
        "  • [dim]Not part of three-JSON pattern[/dim]",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (json_structure)[/dim]",
        "  [dim]See: src/aipass/seedgo/apps/standards/aipass/handlers/json/json_handler.py[/dim]",
    ]

    return "\n".join(lines)
