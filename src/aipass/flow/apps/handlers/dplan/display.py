# =================== AIPass ====================
# Name: display.py
# Description: Plan display handler
# Version: 2.0.0
# Created: 2025-12-02
# Modified: 2025-12-02
# =============================================

"""
Display Handler - D-PLAN Help and Introspection

Provides help text and introspection information.
"""

# INFRASTRUCTURE IMPORT PATTERN
import sys
from pathlib import Path

# NOTE: Handlers do NOT import Prax logger (per 3-tier standard)

# =============================================================================
# CONFIGURATION
# =============================================================================

# display.py → dplan/ → handlers/ → apps/ → flow/
FLOW_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_FILE = FLOW_ROOT / "templates" / "dplan_default.md"

HELP_TEXT = """
[bold]USAGE:[/bold]
  drone @flow plan <subcommand> [options]

[bold]SUBCOMMANDS:[/bold]
  create "topic" [options]                 - Create new plan document
  list [--type type] [--tag tag] [--status status] - List plans (with filters)
  status [--type type]                     - Quick overview of plan counts
  close <number>                           - Close plan and archive
  close --all                              - Close all open plans
  sync                                     - Refresh registry from filesystem

[bold]PLAN TYPES:[/bold]
  dplan  - Development plans (default)
  bplan  - Business plans

[bold]EXAMPLES:[/bold]
  drone @flow plan create "new feature design"
  drone @flow plan create "API upgrade" --tag upgrade
  drone @flow plan create "revenue model" --type bplan
  drone @flow plan create "vera improvements" --type dplan @vera
  drone @flow plan list
  drone @flow plan list --type bplan
  drone @flow plan list --tag idea
  drone @flow plan list --status planning
  drone @flow plan status
  drone @flow plan status --type dplan
  drone @flow plan close 3
  drone @flow plan close --all

[bold]@ RESOLUTION:[/bold]
  Append @branch to create plans in another branch's dev_planning/:
    plan create "topic" @vera        → creates in vera/dev_planning/
    plan create "topic" @team_1      → creates in team_1/dev_planning/

[bold]TAGS:[/bold]
  idea, upgrade, proposal, bug, research, seed, infrastructure

[bold]STATUS VALUES:[/bold]
  📋 Planning      - Initial state
  🔄 In Progress   - Actively working on design
  ✅ Ready         - Ready for execution (send to Flow)
  ✓  Complete      - Design work done
  ❌ Abandoned     - No longer pursuing

[bold]OPTIONS:[/bold]
  --help         - Show this help message
  --type <type>  - Plan type: dplan (default), bplan
  --tag <tag>    - Filter by tag (list) or set tag (create)
  --status <s>   - Filter by status (list only)
  --dir <name>   - Create in dev_planning/<name>/ subdirectory
  @<branch>      - Target branch for plan creation
"""


# =============================================================================
# HANDLER FUNCTIONS
# =============================================================================

def get_help_text() -> str:
    """
    Get help information text

    Returns:
        Formatted help text string (Rich markup)
    """
    return HELP_TEXT


def show_help() -> str:
    """
    Get formatted help content for display

    Returns:
        Help text string (caller should use CLI header + print)
    """
    return get_help_text()


def get_introspection_data() -> dict:
    """
    Get module introspection data

    Returns:
        Dictionary with configuration info
    """
    return {
        "name": "D-PLAN Management Module",
        "description": "Manages numbered planning documents in dev_planning/",
        "template_file": str(TEMPLATE_FILE)
    }


def print_introspection() -> str:
    """
    Get introspection display text

    Returns:
        Formatted introspection text (caller handles output)
    """
    data = get_introspection_data()

    lines = [
        "",
        "[bold cyan]D-PLAN Management Module[/bold cyan]",
        "",
        f"[dim]{data['description']}[/dim]",
        "",
        "[yellow]Configuration:[/yellow]",
        f"  [dim]Template:[/dim] {data['template_file']}",
        "",
        "[dim]Run 'drone @flow plan --help' for usage[/dim]",
        ""
    ]

    return "\n".join(lines)
