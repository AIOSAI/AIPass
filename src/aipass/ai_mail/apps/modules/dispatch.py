# =================== AIPass ====================
# Name: dispatch.py
# Description: Dispatch Module
# Version: 3.1.0
# Created: 2026-02-02
# Modified: 2026-08-12
# =============================================

"""
Dispatch Module

Orchestrates dispatch commands: status tracking and daemon management.
Delegates all business logic to handlers.
"""

import os
import sys
from pathlib import Path
from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, error
from aipass.ai_mail.apps.handlers.cli.help_flags import wants_help
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.dispatch.status import load_dispatch_log, check_pid_status, calculate_age

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")


def print_help() -> None:
    """Print help for dispatch commands."""
    help_text = """
Dispatch Module - Agent dispatch management

COMMANDS:
  dispatch @target "Subject" "Body"   - Send dispatch email + wake target
  dispatch status                     - Show last 5 dispatch spawns with current status
  dispatch register                   - Show outstanding dispatches and which are overdue
  dispatch daemon                     - Start the continuous dispatch daemon
  dispatch wake @branch               - Wake only (no email sent)

DISPATCH (send + wake):
  drone @ai_mail dispatch @branch "Subject" "Body"                    # Send + wake
  drone @ai_mail dispatch @branch "Subject" "Body" --fresh            # Send + fresh wake
  drone @ai_mail dispatch @branch "Subject" "Body" --model opus       # Send + wake with Opus
  drone @ai_mail dispatch @branch "Subject" "Body" --no-memory-save

WAKE ONLY:
  drone @ai_mail dispatch wake @branch                       # Wake with default inbox check
  drone @ai_mail dispatch wake @branch "custom"              # Wake with custom prompt
  drone @ai_mail dispatch wake @branch --model opus          # Wake with Opus model
  drone wake @branch                                         # Shortcut via drone

MODEL OPTIONS:
  --model opus     Claude Opus 4.6 (default — full reasoning for all tasks)
  --model sonnet   Claude Sonnet 4.6 (cost-effective for lighter tasks)
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
        True if command handled, False otherwise.

        "Handled" means recognised and run — not "it worked". A failed send or
        wake reports itself through error(), which sets the process failure flag
        main() maps to exit 2. Returning False for a failure sent the router on
        to the next module, which re-ran the send and then printed
        "Unknown command: dispatch" over a dispatch it had just attempted.
    """
    if command != "dispatch":
        return False

    # Whole-sequence, before anything routes: a trailing --help on a dispatch
    # would otherwise land in the subcommand slot and SEND the mail and WAKE
    # the branch it was asked to describe.
    if wants_help(args):
        print_help()
        return True

    if not args:
        print_introspection()
        return True

    subcommand = args[0]

    json_handler.log_operation("dispatch_command", {"subcommand": subcommand})

    # A verb table rather than an if/elif chain. Adding `register` made the chain
    # deep enough to trip the nesting limit; a table stays flat however many
    # verbs land, and the address forms below stay separate because they match on
    # a PREFIX rather than on the whole word.
    verbs = {
        "status": lambda: _orchestrate_status(),
        "register": lambda: _orchestrate_register(),
        "daemon": lambda: _orchestrate_daemon(),
        "wake": lambda: _orchestrate_wake(args[1:]),
    }

    run_verb = verbs.get(subcommand)
    if run_verb is not None:
        return run_verb()

    if subcommand.startswith("@") or subcommand.startswith("/"):
        return _orchestrate_dispatch_send(args)

    error(f"Unknown dispatch subcommand: {subcommand}")
    print_help()
    return True


def _orchestrate_register() -> bool:
    """Show what the register says is still outstanding, and what is overdue.

    The reader door for Patrick's rule 1. Crash detection is supposed to be
    "visible to any reader" with nothing running to discover it — this is a
    reader, and it proves the claim rather than leaving it as an assertion in
    a docstring. Reading the register costs one file read and no process.
    """
    from aipass.ai_mail.apps.handlers.dispatch import register

    entries = register.outstanding()
    if not entries:
        console.print("No dispatches outstanding.")
        return True

    console.print(f"\n[bold]Outstanding dispatches ({len(entries)})[/bold]\n")
    for entry in entries:
        flag = "[red]OVERDUE[/red]" if entry.get("overdue") else "[green]running[/green]"
        console.print(
            f"  {flag}  {entry.get('sender', '?')} -> {entry.get('target', '?')}"
            f"  [dim]{entry.get('dispatch_id', '')[:8]}[/dim]"
        )
        console.print(f"           {entry.get('subject') or '(no subject)'}")
        console.print(
            f"           [dim]sent {entry.get('ts', '?')} · expected by {entry.get('expected_by', '?')}[/dim]"
        )

    overdue = sum(1 for e in entries if e.get("overdue"))
    if overdue:
        console.print(
            f"\n[yellow]{overdue} past its expected-by with no completion record — "
            f"the monitor for it is not running.[/yellow]"
        )
    return True


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
        return True

    branch_email = filtered[0]
    custom_message = filtered[1] if len(filtered) > 1 else None

    from aipass.ai_mail.apps.handlers.dispatch.wake import is_wake_blocked

    if is_wake_blocked(branch_email):
        error(
            f"target {branch_email} is protected from manual wake. "
            f'Use \'drone @ai_mail dispatch {branch_email} "Subject" "Body"\' to send work instead.'
        )
        return True

    # --sender is a CLI string and reaches wake_branch's privilege-bearing
    # `sender` param, exactly like --from does on the dispatch-send path.
    from aipass.ai_mail.apps.handlers.users.verified_caller import resolve_wake_sender, sender_claim_refusal

    refusal = sender_claim_refusal(use_sender)
    if refusal:
        error(f"Wake refused: {refusal}")
        return True

    logger.info(f"[dispatch] Manual wake requested for {branch_email}")
    console.print(f"\n⏳ Waking {branch_email}...")

    from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

    dispatch_status, success = wake_branch(
        branch_email, custom_message, fresh=use_fresh, sender=resolve_wake_sender(use_sender), model=use_model
    )

    # Print step-by-step status
    console.print(dispatch_status.format())

    if not success:
        # The status block shows which step failed but never marks the command
        # failed, so a dead wake exited 0. Say it once, out loud.
        error(f"Wake failed for {branch_email} — see the step status above")

    return True


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
        if args[i] == "--no-watchdog":
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

    # --from is an unauthenticated string. It may author the mail, but it must
    # not buy a wake lane: refused BEFORE the send, so a spoof attempt leaves
    # no delivered dispatch email behind claiming to be from someone it isn't.
    from aipass.ai_mail.apps.handlers.users import verified_caller

    refusal = verified_caller.sender_claim_refusal(from_branch)
    if refusal:
        error(f"Dispatch to {target} refused: {refusal}")
        return True

    # Admin lane (FPLAN-0401): the 5-leg grant check runs HERE because this is
    # where the caller env still lives — wake_branch only ever receives the
    # verdict. The rail pre-check is noise control, not security: only the
    # grant holder can pass leg 1 anyway, so anyone else skips the file reads
    # and the lane-dark report they could do nothing about. A verifier that
    # raises must not take the mail down with it — no grant, dispatch proceeds.
    is_admin = False
    if verified_caller.resolve_verified_caller() == verified_caller.ADMIN_HOLDER:
        try:
            is_admin, admin_reason = verified_caller.verify_admin_caller()
        except Exception as exc:
            logger.warning("[dispatch] admin verification failed unexpectedly: %s", exc)
            is_admin, admin_reason = False, f"admin verification error: {exc}"
        if not is_admin:
            console.print(f"[dim]Admin lane closed: {admin_reason}[/dim]")

    logger.info(f"[dispatch] Combined dispatch: send + wake for {target}")
    json_handler.log_operation("dispatch_send_and_wake", {"target": target, "subject": subject, "fresh": use_fresh})

    # --- Step 1: Send dispatch email ---
    # No "Sending..." announcement before the fact. Progress goes to stdout and
    # failures to stderr, and drone captures each stream whole and replays
    # stdout first — so a pre-send progress line always surfaced BELOW the
    # refusal it preceded, reading as "it failed, and then it sent". The send is
    # sub-second: announce the outcome, not the intent.

    from aipass.ai_mail.apps.handlers.email.send import resolve_sender_info, send_to_single
    from aipass.ai_mail.apps.handlers.email.create import create_email_file, load_email_file
    from aipass.ai_mail.apps.handlers.email.delivery import deliver_email_to_branch
    from aipass.ai_mail.apps.handlers.email.header import prepend_dispatch_header
    from aipass.ai_mail.apps.handlers.email.error_dispatch import dispatch_send_error, on_email_delivered
    from aipass.ai_mail.apps.handlers.users.user import get_current_user
    from aipass.ai_mail.apps.handlers.registry.read import get_branch_by_email
    from aipass.ai_mail.apps.handlers.paths import find_repo_root

    try:
        from aipass.ai_mail.apps.handlers.central_writer import update_central
    except ImportError as e:
        logger.warning("[dispatch] central_writer import unavailable: %s", e)
        update_central = None

    _ai_mail_dir = Path(__file__).resolve().parents[2]
    _repo_root = find_repo_root()

    def _delivery_callback(branch_path, new_count, opened_count, total):
        on_email_delivered(update_central_fn=update_central)

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
            error(f"Dispatch to {target} not sent: {send_error}")
            dispatch_send_error(target, subject, send_error or "", deliver_email_to_branch)
            return True

        console.print(f"[green]Email sent to {target}[/green]")

        try:
            from aipass.trigger.apps.modules.core import trigger

            trigger.fire("email_dispatched", to=target, subject=subject)
        except Exception as e:
            logger.warning("[dispatch] trigger fire failed: %s", e)

    except Exception as e:
        logger.error(f"[dispatch] Send phase failed: {e}")
        error(f"Dispatch to {target} not sent: {e}")
        return True

    # --- Step 2: Wake the branch ---
    console.print(f"\nWaking {target}...")

    from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

    # The wake is attributed to the VERIFIED caller, not to the mail's author:
    # --from moves who the email is from, never who the wake came from.
    dispatch_status, wake_ok = wake_branch(
        target,
        fresh=use_fresh,
        sender=verified_caller.resolve_wake_sender(user_info.get("email_address", "@ai_mail")),
        model=use_model,
        admin=is_admin,
        subject=subject,
    )
    console.print(dispatch_status.format())

    if not wake_ok:
        logger.warning("[dispatch] Wake failed for %s — email was sent", target)
        error(f"Email sent but wake failed — retry: drone @ai_mail dispatch wake {target}")
    else:
        _announce_wake_back(target, verified_caller.resolve_wake_sender(user_info.get("email_address", "@ai_mail")))

    return True


def _announce_wake_back(target: str, sender: str) -> None:
    """Print what will ACTUALLY happen when `target` finishes.

    Managers are never woken — the blocklist is deliberate and stays. Telling a
    manager "you will be woken" was a promise the lane could not keep, and the
    manager then heard nothing at all: two live cases on 2026-08-21 (@devpulse
    dispatching @ai_mail and @drone back to back). The wake-back now mails them,
    so the promise says mail.

    Args:
        target: The dispatched branch.
        sender: The address that will receive the wake-back.
    """
    from aipass.ai_mail.apps.handlers.dispatch.wake import is_manager

    if is_manager(sender):
        console.print(
            f"[dim]Wake-back enabled — {sender} is a manager and is never woken, "
            f"so you will be MAILED when {target} completes[/dim]"
        )
    else:
        console.print(f"[dim]Wake-back enabled — sender will be woken when {target} completes (if available)[/dim]")


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
    console.print("[bold cyan]dispatch Module[/bold cyan]")
    console.print(
        "[dim]Orchestrates dispatch commands: combined send+wake,"
        " status tracking, daemon management, and manual wake.[/dim]"
    )
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/dispatch/[/cyan]")
    console.print("    - [cyan]status.py[/cyan] [dim](load_dispatch_log — load dispatch log entries)[/dim]")
    console.print(
        "    - [cyan]status.py[/cyan] [dim](check_pid_status — check if a spawned process is still running)[/dim]"
    )
    console.print("    - [cyan]status.py[/cyan] [dim](calculate_age — calculate age string from timestamp)[/dim]")
    console.print("    - [cyan]wake.py[/cyan] [dim](wake_branch — manually wake a branch by spawning an agent)[/dim]")
    console.print("    - [cyan]daemon.py[/cyan] [dim](run_daemon — start the continuous dispatch daemon)[/dim]")
    console.print("  [cyan]handlers/email/[/cyan] [dim](used by combined dispatch)[/dim]")
    console.print("    - [cyan]send.py[/cyan] [dim](resolve_sender_info, send_to_single — send email pipeline)[/dim]")
    console.print("    - [cyan]create.py[/cyan] [dim](create_email_file, load_email_file — email file creation)[/dim]")
    console.print("    - [cyan]delivery.py[/cyan] [dim](deliver_email_to_branch — inbox delivery)[/dim]")
    console.print("    - [cyan]header.py[/cyan] [dim](prepend_dispatch_header — dispatch header injection)[/dim]")
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
