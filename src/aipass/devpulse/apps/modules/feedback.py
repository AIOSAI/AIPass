# =================== AIPass ====================
# Name: feedback.py
# Description: Feedback Module — command routing for devpulse feedback mailbox
# Version: 1.0.0
# Created: 2026-04-11
# Modified: 2026-05-15
# =============================================

"""
Feedback Module — command routing for devpulse's personal feedback mailbox.

Auto-discovered by devpulse.py via handle_command() convention.
Routes feedback subcommands to the appropriate handler functions.
"""

from aipass.devpulse.apps.handlers.feedback.inbox import (
    list_messages,
    view_message,
    clear_message,
    clear_all_read,
    get_summary,
)
from aipass.devpulse.apps.handlers.feedback.compose import (
    send_feedback,
    reply_to,
    _resolve_sender,
)

from aipass.prax import logger
from aipass.cli.apps.modules import err_console, error, warning
from aipass.devpulse.apps.handlers.json import json_handler

console = err_console

HELP_TEXT = """\
[bold cyan]feedback[/bold cyan] — DevPulse personal feedback mailbox

[bold]Usage:[/bold]
  feedback                        Inbox summary (count, unread)
  feedback inbox                  List all messages
  feedback view <id>              Read message + thread
  feedback reply <id> "message"   Reply to sender
  feedback send "subject" "body"  Receive feedback from agent
  feedback clear <id>             Remove a message
  feedback clear --all            Remove all read messages
  feedback --help                 Show this help
"""


def _guard_caller() -> bool:
    """Owner-only gate for mailbox reads/management (see handlers.owner.guard).

    The mailbox belongs to the project owner. `send` and `--help` stay open
    (send is the inbound channel any agent uses to drop feedback here); every
    other verb reads or mutates the owner's mail and is owner-gated. #681.
    """
    from aipass.devpulse.apps.handlers.owner.guard import guard_owner_caller

    if guard_owner_caller("feedback"):
        return True
    warning("feedback mailbox management is owner-only — refusing non-owner call")
    return False


def print_introspection() -> None:
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]feedback Module[/bold cyan]")
    console.print("[dim]DevPulse personal feedback mailbox. Receives cross-project[/dim]")
    console.print("[dim]feedback messages from any agent via drone routing.[/dim]")
    console.print()
    console.print("[yellow]Subcommands:[/yellow] [cyan]inbox, view, reply, send, clear[/cyan]")
    console.print()


def _wants_help(args: list[str]) -> bool:
    """Help flag anywhere in args = explain, never execute (DPLAN-0291 rule E).

    Bare word 'help' counts only at position 0 — later positions may be values.
    """
    return bool(args) and (args[0] in ("--help", "-h", "help") or any(a in ("--help", "-h") for a in args))


def handle_command(command: str, args: list[str]) -> bool:
    """Route feedback commands to handler functions.

    Auto-discovered by devpulse.py module loader.

    Args:
        command: The primary command string.
        args: Additional arguments after the command.

    Returns:
        bool: True if the command was handled, False otherwise.
    """
    if command != "feedback":
        return False

    # Open verbs (no owner gate): help + `send`. `send` is the inbound channel
    # any agent uses to drop feedback into the owner's mailbox. Everything else
    # reads or manages that mailbox -> owner-only (#681).
    if _wants_help(args):
        console.print(HELP_TEXT)
        return True

    if args and args[0] == "send":
        json_handler.log_operation("feedback_command", {"subcommand": "send"})
        return _handle_send(args[1:])

    if not _guard_caller():
        return True

    if not args:
        print_introspection()
        summary = get_summary()
        console.print(f"[bold cyan]Feedback:[/bold cyan] {summary}")
        return True

    subcommand = args[0]
    sub_args = args[1:]
    json_handler.log_operation("feedback_command", {"subcommand": subcommand})

    if subcommand == "inbox":
        list_messages()
        return True

    if subcommand == "view":
        if not sub_args:
            error("Usage: feedback view <id>")
            return True
        view_message(sub_args[0])
        return True

    if subcommand == "reply":
        if len(sub_args) < 2:
            error('Usage: feedback reply <id> "message"')
            return True
        msg_id = sub_args[0]
        body = " ".join(sub_args[1:])
        reply_to(msg_id, body)
        return True

    if subcommand == "clear":
        if not sub_args:
            error("Usage: feedback clear <id> | feedback clear --all")
            return True
        if sub_args[0] == "--all":
            clear_all_read()
        else:
            clear_message(sub_args[0])
        return True

    logger.warning("[feedback] unknown subcommand: %s", subcommand)
    error(f"Unknown feedback subcommand: {subcommand}", suggestion="Use 'feedback --help' for usage")
    return True


def _handle_send(args: list[str]) -> bool:
    """Handle the send subcommand, parsing from_branch, subject, and body.

    Expected format: send "subject" "body"
    The from_branch is extracted from the first arg or defaults to 'unknown'.

    Args:
        args: Arguments after 'send'.

    Returns:
        bool: Always True (command was handled).
    """
    if len(args) < 2:
        error('Usage: feedback send "subject" "body"')
        console.print("[dim]Tip: from_branch is auto-detected or pass as first arg.[/dim]")
        return True

    # Auto-detect sender from drone env vars, fall back to arg parsing
    auto_branch, auto_path = _resolve_sender()

    if len(args) >= 3 and not args[0].startswith('"'):
        # Explicit from_branch provided as first arg
        from_branch = args[0]
        subject = args[1]
        body = " ".join(args[2:])
        ai_mail_path = auto_path if from_branch == auto_branch else ""
    else:
        from_branch = auto_branch
        subject = args[0]
        body = " ".join(args[1:])
        ai_mail_path = auto_path

    send_feedback(from_branch, subject, body, ai_mail_path)
    return True
