# =================== AIPass ====================
# Name: dispatch.py
# Description: Dispatch Module
# Version: 3.0.0
# Created: 2026-02-02
# Modified: 2026-02-02
# =============================================

"""
Dispatch Module

Orchestrates dispatch commands: status tracking and daemon management.
Delegates all business logic to handlers.
"""

import sys
from pathlib import Path
from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, error
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.dispatch.status import load_dispatch_log, check_pid_status, calculate_age


def print_help() -> None:
    """Print help for dispatch commands."""
    help_text = """
Dispatch Module - Agent dispatch management

COMMANDS:
  dispatch @target "Subject" "Body"   - Send dispatch email + wake target
  dispatch status                     - Show last 5 dispatch spawns with current status
  dispatch daemon                     - Start the continuous dispatch daemon
  dispatch wake @branch               - Wake only (no email sent)

DISPATCH (send + wake):
  drone @ai_mail dispatch @branch "Subject" "Body"                    # Send + continue wake
  drone @ai_mail dispatch @branch "Subject" "Body" --fresh            # Send + fresh wake
  drone @ai_mail dispatch @branch "Subject" "Body" --model opus       # Send + wake with Opus
  drone @ai_mail dispatch @branch "Subject" "Body" --no-memory-save

WAKE ONLY:
  drone @ai_mail dispatch wake @branch                       # Wake with default inbox check
  drone @ai_mail dispatch wake @branch "custom"              # Wake with custom prompt
  drone @ai_mail dispatch wake @branch --model opus          # Wake with Opus model
  drone wake @branch                                         # Shortcut via drone

MODEL OPTIONS:
  --model sonnet   Claude Sonnet 4.6 (default — cost-effective for most tasks)
  --model opus     Claude Opus 4.6 (complex tasks needing deeper reasoning)
  --model haiku    Claude Haiku 4.5 (fastest, simplest tasks)

DAEMON:
  The daemon polls branch inboxes for --dispatch emails and spawns agents.
  Kill switch: touch <repo_root>/.aipass/autonomous_pause
  Config: safety_config.json
"""
    console.print(help_text)


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle dispatch commands.

    Args:
        command: Command name
        args: Command arguments

    Returns:
        True if command handled, False otherwise
    """
    if command != "dispatch":
        return False

    if args and args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    if not args:
        print_introspection()
        return True

    subcommand = args[0]

    json_handler.log_operation("dispatch_command", {"subcommand": subcommand})

    if subcommand == "status":
        return _orchestrate_status()
    elif subcommand == "daemon":
        return _orchestrate_daemon()
    elif subcommand == "wake":
        return _orchestrate_wake(args[1:])
    elif subcommand.startswith("@") or subcommand.startswith("/"):
        return _orchestrate_dispatch_send(args)
    else:
        error(f"Unknown dispatch subcommand: {subcommand}")
        print_help()
        return False


def _orchestrate_status() -> bool:
    """Orchestrate dispatch status display."""
    logger.info("[dispatch] Showing dispatch status")

    dispatches = load_dispatch_log()

    if not dispatches:
        console.print("\n[dim]No dispatches recorded yet.[/dim]")
        return True

    recent = dispatches[-5:][::-1]

    console.print("\n[bold]DISPATCH STATUS[/bold]")
    console.print("─" * 50)

    active_count = 0
    for entry in recent:
        branch = entry.get("branch", "unknown")
        pid = entry.get("pid")
        timestamp = entry.get("timestamp", "")
        spawn_status = entry.get("status", "unknown")

        if spawn_status == "spawned" and pid:
            current_status = check_pid_status(pid)
        elif spawn_status == "failed":
            current_status = "FAILED"
        else:
            current_status = "UNKNOWN"

        if current_status == "RUNNING":
            active_count += 1

        age_str = calculate_age(timestamp)

        if current_status == "RUNNING":
            status_display = "[green]RUNNING[/green]"
        elif current_status == "COMPLETED":
            status_display = "[dim]COMPLETED[/dim]"
        elif current_status == "FAILED":
            status_display = "[red]FAILED[/red]"
        else:
            status_display = f"[yellow]{current_status}[/yellow]"

        pid_display = f"PID {pid}" if pid else "NO PID"
        console.print(f"  {branch:<12} {pid_display:<12} {status_display:<18} {age_str}")

    console.print("─" * 50)
    console.print(f"[dim]Active: {active_count}  |  Total: {len(recent)}[/dim]\n")

    return True


def _orchestrate_wake(args: List[str]) -> bool:
    """Orchestrate manual branch wake."""
    if not args or args[0] in ["--help", "-h", "help"]:
        console.print("\n[bold]Wake - Manual branch spawn[/bold]")
        console.print('  Usage: dispatch wake @branch ["custom message"]')
        console.print('  Or:    drone wake @branch ["custom message"]\n')
        return True

    # Parse --fresh, --sender, --model flags
    use_fresh = "--fresh" in args
    use_sender = "@devpulse"
    use_model = None
    filtered = []
    i = 0
    while i < len(args):
        if args[i] == "--fresh":
            i += 1
            continue
        if args[i] == "--sender" and i + 1 < len(args):
            use_sender = args[i + 1]
            i += 2
            continue
        if args[i] == "--model" and i + 1 < len(args):
            use_model = args[i + 1]
            i += 2
            continue
        filtered.append(args[i])
        i += 1

    if not filtered:
        error("Missing branch argument")
        return False

    branch_email = filtered[0]
    custom_message = filtered[1] if len(filtered) > 1 else None

    logger.info(f"[dispatch] Manual wake requested for {branch_email}")
    console.print(f"\n⏳ Waking {branch_email}...")

    from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

    dispatch_status, success = wake_branch(
        branch_email, custom_message, fresh=use_fresh, sender=use_sender, model=use_model
    )

    # Print step-by-step status
    console.print(dispatch_status.format())

    return success


def _orchestrate_dispatch_send(args: List[str]) -> bool:
    """Orchestrate combined dispatch: send email with --dispatch flag + wake branch."""
    # Parse flags
    use_fresh = False
    no_memory_save = False
    from_branch = None
    use_model = None
    filtered = []
    i = 0
    while i < len(args):
        if args[i] == "--fresh":
            use_fresh = True
            i += 1
            continue
        if args[i] == "--no-memory-save":
            no_memory_save = True
            i += 1
            continue
        if args[i] == "--from" and i + 1 < len(args):
            from_branch = args[i + 1]
            i += 2
            continue
        if args[i] == "--model" and i + 1 < len(args):
            use_model = args[i + 1]
            i += 2
            continue
        filtered.append(args[i])
        i += 1

    if len(filtered) < 3:
        error('Usage: dispatch @target "Subject" "Body" [--fresh] [--no-memory-save]')
        return True

    target = filtered[0]
    subject = filtered[1]
    body = filtered[2]

    logger.info(f"[dispatch] Combined dispatch: send + wake for {target}")
    json_handler.log_operation("dispatch_send_and_wake", {"target": target, "subject": subject, "fresh": use_fresh})

    # --- Step 1: Send dispatch email ---
    console.print(f"\nSending dispatch email to {target}...")

    from aipass.ai_mail.apps.handlers.email.send import resolve_sender_info, send_to_single
    from aipass.ai_mail.apps.handlers.email.create import create_email_file, load_email_file
    from aipass.ai_mail.apps.handlers.email.delivery import deliver_email_to_branch
    from aipass.ai_mail.apps.handlers.email.header import prepend_dispatch_header
    from aipass.ai_mail.apps.handlers.email.error_dispatch import dispatch_send_error, on_email_delivered
    from aipass.ai_mail.apps.handlers.email.dashboard_sync import push_dashboard_update
    from aipass.ai_mail.apps.handlers.users.user import get_current_user
    from aipass.ai_mail.apps.handlers.registry.read import get_branch_by_email

    try:
        from aipass.ai_mail.apps.handlers.central_writer import update_central
    except ImportError as e:
        logger.warning("[dispatch] central_writer import unavailable: %s", e)
        update_central = None

    _ai_mail_dir = Path(__file__).resolve().parents[2]
    _repo_root = _ai_mail_dir.parents[2]

    def _delivery_callback(branch_path, new_count, opened_count, total):
        on_email_delivered(
            branch_path,
            new_count,
            opened_count,
            total,
            push_dashboard_fn=push_dashboard_update,
            update_central_fn=update_central,
        )

    try:
        user_info = resolve_sender_info(from_branch, _repo_root, _ai_mail_dir, get_branch_by_email, get_current_user)
        message = prepend_dispatch_header(body, no_memory_save=no_memory_save)

        send_ok, send_error = send_to_single(
            target,
            subject,
            message,
            user_info,
            True,
            no_memory_save,
            None,
            target,
            create_email_file,
            load_email_file,
            deliver_email_to_branch,
            _delivery_callback,
            json_handler.log_operation,
            update_central,
        )

        if not send_ok:
            error(f"Send failed: {send_error}")
            dispatch_send_error(target, subject, send_error or "", deliver_email_to_branch)
            return False

        console.print(f"[green]Email sent to {target}[/green]")

        try:
            from aipass.trigger.apps.modules.core import trigger

            trigger.fire("email_dispatched", to=target, subject=subject)
        except Exception as e:
            logger.warning("[dispatch] trigger fire failed: %s", e)

    except Exception as e:
        logger.error(f"[dispatch] Send phase failed: {e}")
        error(f"Send failed: {e}")
        return False

    # --- Step 2: Wake the branch ---
    console.print(f"\nWaking {target}...")

    from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

    dispatch_status, wake_ok = wake_branch(
        target, fresh=use_fresh, sender=user_info.get("email_address", "@ai_mail"), model=use_model
    )
    console.print(dispatch_status.format())

    if not wake_ok:
        console.print(f"[yellow]Email sent but wake failed — retry: drone @ai_mail dispatch wake {target}[/yellow]")

    return True


def _orchestrate_daemon() -> bool:
    """Orchestrate daemon startup."""
    logger.info("[dispatch] Starting dispatch daemon")
    console.print("\n[bold]Starting dispatch daemon...[/bold]")

    from aipass.ai_mail.apps.handlers.dispatch.daemon import run_daemon

    run_daemon()
    return True


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("dispatch Module")
    console.print(
        "Orchestrates dispatch commands: combined send+wake, status tracking, daemon management, and manual wake."
    )
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/dispatch/")
    console.print("    - status.py (load_dispatch_log — load dispatch log entries)")
    console.print("    - status.py (check_pid_status — check if a spawned process is still running)")
    console.print("    - status.py (calculate_age — calculate age string from timestamp)")
    console.print("    - wake.py (wake_branch — manually wake a branch by spawning an agent)")
    console.print("    - daemon.py (run_daemon — start the continuous dispatch daemon)")
    console.print("  handlers/email/ (used by combined dispatch)")
    console.print("    - send.py (resolve_sender_info, send_to_single — send email pipeline)")
    console.print("    - create.py (create_email_file, load_email_file — email file creation)")
    console.print("    - delivery.py (deliver_email_to_branch — inbox delivery)")
    console.print("    - header.py (prepend_dispatch_header — dispatch header injection)")
    console.print()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print_help()
        sys.exit(0)

    if sys.argv[1] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    command = sys.argv[1]
    remaining_args = sys.argv[2:] if len(sys.argv) > 2 else []

    if handle_command(command, remaining_args):
        sys.exit(0)
    else:
        sys.exit(1)
