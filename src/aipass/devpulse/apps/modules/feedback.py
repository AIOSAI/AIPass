# META
# module: devpulse.feedback
# description: Command routing module for feedback mailbox
# END META

"""
Feedback Module — command routing for devpulse's personal feedback mailbox.

Auto-discovered by devpulse.py via handle_command() convention.
Routes feedback subcommands to the appropriate handler functions.
"""

from rich.console import Console

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

console = Console(stderr=True)

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

    # No subcommand — show summary
    if not args:
        summary = get_summary()
        console.print(f"[bold cyan]Feedback:[/bold cyan] {summary}")
        return True

    subcommand = args[0]
    sub_args = args[1:]

    if subcommand in ("--help", "-h", "help"):
        console.print(HELP_TEXT)
        return True

    if subcommand == "inbox":
        list_messages()
        return True

    if subcommand == "view":
        if not sub_args:
            console.print("[red]Usage: feedback view <id>[/red]")
            return True
        view_message(sub_args[0])
        return True

    if subcommand == "reply":
        if len(sub_args) < 2:
            console.print('[red]Usage: feedback reply <id> "message"[/red]')
            return True
        msg_id = sub_args[0]
        body = " ".join(sub_args[1:])
        reply_to(msg_id, body)
        return True

    if subcommand == "send":
        return _handle_send(sub_args)

    if subcommand == "clear":
        if not sub_args:
            console.print("[red]Usage: feedback clear <id> | feedback clear --all[/red]")
            return True
        if sub_args[0] == "--all":
            clear_all_read()
        else:
            clear_message(sub_args[0])
        return True

    console.print(f"[red]Unknown feedback subcommand: {subcommand}[/red]")
    console.print("Use [bold]feedback --help[/bold] for usage.")
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
        console.print('[red]Usage: feedback send "subject" "body"[/red]')
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
