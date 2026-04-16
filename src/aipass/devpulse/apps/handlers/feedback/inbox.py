# META
# module: devpulse.feedback
# description: Inbox operations — list, view, clear feedback messages
# END META

"""
Feedback Inbox — reading and managing feedback messages.

Provides list, view, clear, and summary operations for
devpulse's personal feedback mailbox.
"""

from rich.console import Console
from rich.table import Table

from aipass.devpulse.apps.handlers.feedback.storage import load_inbox, save_inbox

console = Console(stderr=True)


def list_messages() -> None:
    """Display a Rich table of all feedback messages.

    Shows id, from, subject, date, and read status for each message.
    """
    data = load_inbox()
    messages = data.get("messages", [])

    if not messages:
        console.print("[dim]No feedback messages.[/dim]")
        return

    table = Table(title="Feedback Inbox", show_lines=False)
    table.add_column("ID", style="cyan", width=10)
    table.add_column("From", style="green", width=14)
    table.add_column("Subject", style="white", min_width=20)
    table.add_column("Date", style="dim", width=19)
    table.add_column("Status", width=8)

    for msg in messages:
        status = "[dim]read[/dim]" if msg.get("read") else "[bold yellow]NEW[/bold yellow]"
        table.add_row(
            msg.get("id", "?"),
            msg.get("from", "?"),
            msg.get("subject", "(no subject)"),
            msg.get("timestamp", "?"),
            status,
        )

    console.print(table)


def view_message(msg_id: str) -> None:
    """Display a message and its thread, marking it as read.

    Args:
        msg_id: The 8-char hex message ID to view.
    """
    data = load_inbox()
    messages = data.get("messages", [])

    msg = _find_message(messages, msg_id)
    if msg is None:
        console.print(f"[red]Message {msg_id} not found.[/red]")
        return

    # Mark as read
    if not msg.get("read"):
        msg["read"] = True
        data["unread_count"] = max(0, data.get("unread_count", 1) - 1)
        save_inbox(data)

    # Display message
    console.print(f"\n[bold cyan]From:[/bold cyan] {msg.get('from', '?')}")
    console.print(f"[bold cyan]Subject:[/bold cyan] {msg.get('subject', '(no subject)')}")
    console.print(f"[bold cyan]Date:[/bold cyan] {msg.get('timestamp', '?')}")
    console.print(f"[bold cyan]ID:[/bold cyan] {msg.get('id', '?')}")
    console.print(f"\n{msg.get('body', '')}")

    # Display thread
    thread = msg.get("thread", [])
    if thread:
        console.print(f"\n[bold]Thread ({len(thread)} replies):[/bold]")
        for reply in thread:
            console.print(f"\n  [dim]{reply.get('timestamp', '?')}[/dim] [green]{reply.get('from', '?')}[/green]:")
            console.print(f"  {reply.get('body', '')}")

    console.print()


def clear_message(msg_id: str) -> None:
    """Remove a single message from the inbox.

    Args:
        msg_id: The 8-char hex message ID to remove.
    """
    data = load_inbox()
    messages = data.get("messages", [])

    msg = _find_message(messages, msg_id)
    if msg is None:
        console.print(f"[red]Message {msg_id} not found.[/red]")
        return

    was_unread = not msg.get("read")
    data["messages"] = [m for m in messages if m.get("id") != msg_id]
    data["total_messages"] = len(data["messages"])
    if was_unread:
        data["unread_count"] = max(0, data.get("unread_count", 1) - 1)

    save_inbox(data)
    console.print(f"[green]Cleared message {msg_id}.[/green]")


def clear_all_read() -> None:
    """Remove all read messages from the inbox."""
    data = load_inbox()
    messages = data.get("messages", [])

    before_count = len(messages)
    data["messages"] = [m for m in messages if not m.get("read")]
    after_count = len(data["messages"])
    removed = before_count - after_count

    data["total_messages"] = after_count

    save_inbox(data)

    if removed == 0:
        console.print("[dim]No read messages to clear.[/dim]")
    else:
        console.print(f"[green]Cleared {removed} read message(s).[/green]")


def get_summary() -> str:
    """Return a summary string of inbox status.

    Returns:
        str: Summary like "3 messages, 2 unread" or "No feedback messages."
    """
    data = load_inbox()
    total = data.get("total_messages", 0)
    unread = data.get("unread_count", 0)

    if total == 0:
        return "No feedback messages."

    return f"{total} message{'s' if total != 1 else ''}, {unread} unread"


def _find_message(messages: list, msg_id: str) -> dict | None:
    """Find a message by ID in the messages list.

    Args:
        messages: List of message dicts.
        msg_id: The message ID to find.

    Returns:
        The message dict if found, None otherwise.
    """
    for msg in messages:
        if msg.get("id") == msg_id:
            return msg
    return None
