# =================== AIPass ====================
# Name: feedback.py
# Description: Feedback Module — command routing for devpulse feedback mailbox
# Version: 1.2.0
# Created: 2026-04-11
# Modified: 2026-10-22
# =============================================

"""
Feedback Module — command routing for devpulse's personal feedback mailbox.
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
from aipass.cli.apps.modules import console as stdout_console, err_console, error
from aipass.devpulse.apps.handlers.json import json_handler

# Mailbox chatter goes to stderr so it never pollutes a pipeline; help is documentation and goes to stdout.
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

    ``error``, not ``warning``: warning skips mark_command_failed, so a chained next step would run.
    """
    from aipass.devpulse.apps.handlers.owner.guard import guard_owner_caller, owner_address

    if guard_owner_caller("feedback"):
        return True
    owner = owner_address()
    whose = f"it belongs to {owner}" if owner else "no owner is sealed or readable for this project"
    error(
        "feedback mailbox management is owner-only and this seat is not the owner",
        suggestion=(
            f"{whose} — ownership is the entry marked owner: true in the project's sealed registry. "
            "'feedback send' and 'feedback --help' are open to every seat."
        ),
    )
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
    """Help flag anywhere in args = explain, never execute; bare 'help' only first, later positions are values."""
    return bool(args) and (args[0] in ("--help", "-h", "help") or any(a in ("--help", "-h") for a in args))


def handle_command(command: str, args: list[str]) -> bool:
    """Route feedback commands to handler functions."""
    if command != "feedback":
        return False

    # Help and `send` stay open: send is the inbound channel any agent uses. Every other verb is owner-only.
    if _wants_help(args):
        stdout_console.print(HELP_TEXT)
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
    """Handle the send subcommand. The sender is the drone rail, never an argument: a body of several
    tokens once read as sender + subject + body, and the reply went nowhere."""
    if len(args) < 2:
        error('Usage: feedback send "subject" "body"')
        return True

    from_branch, ai_mail_path = _resolve_sender()
    send_feedback(from_branch, args[0], " ".join(args[1:]), ai_mail_path)
    return True
