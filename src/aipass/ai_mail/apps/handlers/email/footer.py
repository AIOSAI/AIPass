# =================== AIPass ====================
# Name: footer.py
# Description: Email Footer Handler
# Version: 1.2.5
# Created: 2026-01-29
# Modified: 2026-11-26
# =============================================

"""
Email Footer Handler
"""

from aipass.ai_mail.apps.handlers.json import json_handler

STANDARD_FOOTER = """
---
▶ BUILD/EDIT task? First: drone @trigger medic mute @<your-branch> — auto-expires 4h, re-arms mid-build, no unmute.

⚠️ TASK CHECKLIST (before marking complete):
□ STANDARDS CHECK → drone @sentry audit @branch (80%+)
□ UPDATE DOCS → Your README and every docs/ page that describes what you changed
□ UPDATE MEMORIES → Your .trinity/local.json records this work
□ CLOSE YOUR PLAN → drone @flow close <your_plan_id> — any type, once finished; a master once all its phases are.
□ EMAIL SENDER → drone @ai_mail email @<sender> "Subject" "Summary"

Memories = Presence. No update = No learning.
---"""


def get_footer() -> str:
    """Get the standard email footer."""
    return STANDARD_FOOTER


def append_footer(message: str) -> str:
    """Append standard footer to email message."""
    json_handler.log_operation("append_footer", {"message_length": len(message)})
    return message + get_footer()


if __name__ == "__main__":
    from aipass.cli import console

    console.print("\n" + "=" * 70)
    console.print("EMAIL FOOTER HANDLER")
    console.print("=" * 70)
    console.print("\nPURPOSE:")
    console.print("  Generates standard footer for all outgoing emails")
    console.print()
    console.print("[bold cyan]FUNCTIONS PROVIDED:[/bold cyan]")
    console.print("[dim]  the calls other modules import[/dim]")
    console.print("  - get_footer() -> str")
    console.print("  - append_footer(message) -> str")
    console.print()
    console.print("[bold cyan]FOOTER CONTENT:[/bold cyan]")
    console.print(STANDARD_FOOTER, markup=False, highlight=False)
    console.print()
    console.print("[bold cyan]HANDLER CHARACTERISTICS:[/bold cyan]")
    console.print("[dim]  the layering rules this handler keeps[/dim]")
    console.print("  [green]+[/green] Independent - no module dependencies")
    console.print("  [green]+[/green] Can import prax (service provider)")
    console.print("  [green]+[/green] Pure business logic")
    console.print("  [dim]-[/dim] CANNOT import parent modules")
    console.print()
    console.print("[bold cyan]USAGE FROM MODULES:[/bold cyan]")
    console.print("[dim]  how a module imports it[/dim]")
    console.print("  from ai_mail.apps.handlers.email.footer import append_footer")
    console.print("  from ai_mail.apps.handlers.email.footer import get_footer")
    console.print()
    console.print("=" * 70 + "\n")
