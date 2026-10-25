# =================== AIPass ====================
# Name: dispatch.py
# Description: Dispatch Module
# Version: 3.5.0
# Created: 2026-02-02
# Modified: 2026-10-25
# =============================================

"""
Dispatch Module

Orchestrates dispatch commands; all business logic lives in handlers.
"""

import os
import sys
from pathlib import Path
from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, error, warning
from aipass.ai_mail.apps.handlers.cli.help_flags import wants_help
from aipass.ai_mail.apps.handlers.json import json_handler

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
  dispatch register                   - Show outstanding dispatches and which are overdue
  dispatch wake @branch               - Wake only (no email sent)

DISPATCH (send + wake):
  drone @ai_mail dispatch @branch "Subject" "Body"                    # Send + wake
  drone @ai_mail dispatch @branch "Subject" "Body" --fresh            # Send + fresh wake
  drone @ai_mail dispatch @branch "Subject" "Body" --model opus       # Send + wake with Opus
  drone @ai_mail dispatch @branch "Subject" "Body" --provider codex --model gpt-6.1-sol  # Wake on Codex
  drone @ai_mail dispatch @branch "Subject" "Body" --no-memory-save

WAKE ONLY:
  drone @ai_mail dispatch wake @branch                       # Wake with default inbox check
  drone @ai_mail dispatch wake @branch "custom"              # Wake with custom prompt
  drone @ai_mail dispatch wake @branch --model opus          # Wake with Opus model
  drone wake @branch                                         # Shortcut via drone

WAKE-BACK:
  Library callers such as @daemon's scheduled nudges may pass wake_back=False to
  wake_branch(); the dispatch and dispatch wake verbs always arm the wake-back.

MODEL OPTIONS:
  --model opus     Claude Opus 4.6 (default — full reasoning for all tasks)
  --model sonnet   Claude Sonnet 4.6 (cost-effective for lighter tasks)
  --model haiku    Claude Haiku 4.5 (fastest, simplest tasks)

PROVIDER OPTIONS:
  --provider claude   Claude Code (default)
  --provider codex    Codex CLI; --model is passed verbatim as -m, absent means ~/.codex/config.toml.
                      Managers stay Claude-only.
"""
    console.print(help_text)


def handle_command(command: str, args: List[str]) -> bool:
    """Handle dispatch commands.

    True means recognised and run, not "it worked": failures go through error(). False on failure re-runs the send.
    """
    if command != "dispatch":
        return False

    # Whole-sequence, before routing: a trailing --help must never send and wake.
    if wants_help(args):
        print_help()
        return True

    if not args:
        print_introspection()
        return True

    subcommand = args[0]

    json_handler.log_operation("dispatch_command", {"subcommand": subcommand})

    # Address forms below stay out of the table: they match on a prefix, not the whole word.
    verbs = {
        "register": lambda: _orchestrate_register(),
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
    """Show what the register says is still outstanding, and what is overdue."""
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
            f"           [dim]sent {entry.get('ts', '?')} · expected by {entry.get('expected_by', '?')} · "
            f"monitor {_monitor_phrase(entry)}[/dim]"
        )

    overdue = sum(1 for e in entries if e.get("overdue"))
    if overdue:
        console.print(
            f"\n[yellow]{overdue} past its expected-by with no completion record — "
            f"the monitor for it is not running.[/yellow]"
        )

    # warning(), not error(): a reader must not exit non-zero for reporting what it found.
    dead = sum(1 for e in entries if e.get("monitor_alive") is False)
    if dead:
        warning(f"{dead} whose monitor process is GONE — visible now rather than at expected-by.")
    return True


def _monitor_phrase(entry: dict) -> str:
    """How this row's monitor reads to a human, including when it cannot be told.

    "unknown" covers rows that predate the pid field and systemd-scope spawns; printing them as dead would be false.
    """
    alive = entry.get("monitor_alive")
    if alive is True:
        return f"[green]alive[/green] (pid {entry.get('monitor_pid')})"
    if alive is False:
        return f"[red]GONE[/red] (pid {entry.get('monitor_pid')})"
    return "[dim]unknown — no pid recorded[/dim]"


def _provider_refusal(provider: str) -> str:
    """Why `provider` cannot be woken on, or "" when it can."""
    from aipass.ai_mail.apps.handlers.dispatch.wake import KNOWN_PROVIDERS

    if provider in KNOWN_PROVIDERS:
        return ""
    return f"unknown provider {provider!r} — known: {', '.join(KNOWN_PROVIDERS)}"


def _orchestrate_wake(args: List[str]) -> bool:
    """Orchestrate manual branch wake."""
    if not args or args[0] in ["--help", "-h", "help"]:
        console.print("\n[bold]Wake - Manual branch spawn[/bold]")
        console.print(
            '  Usage: dispatch wake @branch ["custom message"] [--fresh] [--model M] [--provider claude|codex]'
        )
        console.print('  Or:    drone wake @branch ["custom message"]\n')
        return True

    use_fresh = "--fresh" in args
    use_sender = "@devpulse"
    use_model = None
    use_provider = "claude"
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
        if args[i] == "--provider" and i + 1 < len(args):
            use_provider = args[i + 1]
            i += 2
            continue
        filtered.append(args[i])
        i += 1

    if not filtered:
        error("Missing branch argument")
        return True

    provider_refusal = _provider_refusal(use_provider)
    if provider_refusal:
        error(f"Wake refused: {provider_refusal}")
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

    # --sender is a CLI claim that reaches wake_branch's privilege-bearing `sender`, like --from.
    from aipass.ai_mail.apps.handlers.users.verified_caller import resolve_wake_sender, sender_claim_refusal

    refusal = sender_claim_refusal(use_sender)
    if refusal:
        error(f"Wake refused: {refusal}")
        return True

    # Admin lane: the same 5-leg grant as send+wake, verified here where the caller env lives.
    # A raising verifier means no grant; the wake still proceeds.
    from aipass.ai_mail.apps.handlers.users import verified_caller

    is_admin = False
    if verified_caller.resolve_verified_caller() == verified_caller.ADMIN_HOLDER:
        try:
            is_admin, admin_reason = verified_caller.verify_admin_caller()
        except Exception as exc:
            logger.warning("[dispatch] admin verification failed unexpectedly: %s", exc)
            is_admin, admin_reason = False, f"admin verification error: {exc}"
        if not is_admin:
            console.print(f"[dim]Admin lane closed: {admin_reason}[/dim]")

    logger.info(f"[dispatch] Manual wake requested for {branch_email}")
    console.print(f"\n⏳ Waking {branch_email}...")

    from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

    dispatch_status, success = wake_branch(
        branch_email,
        custom_message,
        fresh=use_fresh,
        sender=resolve_wake_sender(use_sender),
        model=use_model,
        admin=is_admin,
        provider=use_provider,
    )

    console.print(dispatch_status.format())

    if not success:
        # The status block never marks the command failed; without this a dead wake exits 0.
        error(f"Wake failed for {branch_email} — see the step status above")

    return True


def _orchestrate_dispatch_send(args: List[str]) -> bool:
    """Orchestrate combined dispatch: send email with --dispatch flag + wake branch."""
    use_fresh = False
    no_memory_save = False
    from_branch = None
    use_model = None
    use_provider = "claude"
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
        if args[i] == "--provider" and i + 1 < len(args):
            use_provider = args[i + 1]
            i += 2
            continue
        filtered.append(args[i])
        i += 1

    if len(filtered) < 3:
        error(
            'Usage: dispatch @target "Subject" "Body" [--fresh] [--no-memory-save] [--model M] [--provider claude|codex]'
        )
        return True

    target = filtered[0]

    # Before the send: a typo'd provider must not deliver mail that no agent will be woken for.
    provider_refusal = _provider_refusal(use_provider)
    if provider_refusal:
        error(f"Dispatch to {target} not sent: {provider_refusal}")
        return True
    subject = filtered[1]
    body = filtered[2]

    # --from may author the mail but not buy a wake lane; refused BEFORE the send so a spoof delivers nothing.
    from aipass.ai_mail.apps.handlers.users import verified_caller

    refusal = verified_caller.sender_claim_refusal(from_branch)
    if refusal:
        error(f"Dispatch to {target} refused: {refusal}")
        return True

    # Admin lane: verified here where the caller env lives. The rail pre-check is noise control, not security.
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

    # No pre-send progress line: drone replays stdout before stderr, so it would print after the refusal.

    # _send_direct would broadcast @all; a dispatch wakes one branch.
    if target.lower() in ("all", "@all"):
        error(f"Dispatch to {target} not sent: dispatch reaches one branch, broadcast with email @all")
        return True

    from aipass.ai_mail.apps.handlers.email.send import resolve_sender_info
    from aipass.ai_mail.apps.handlers.users.user import get_current_user
    from aipass.ai_mail.apps.handlers.registry.read import get_branch_by_email
    from aipass.ai_mail.apps.handlers.paths import find_repo_root
    from aipass.ai_mail.apps.modules.email_send import _send_direct

    try:
        ai_mail_dir = Path(__file__).resolve().parents[2]
        user_info = resolve_sender_info(
            from_branch, find_repo_root(), ai_mail_dir, get_branch_by_email, get_current_user
        )
    except Exception as e:
        logger.error(f"[dispatch] Send phase failed: {e}")
        error(f"Dispatch to {target} not sent: {e}")
        return True

    sent = _send_direct(
        target,
        subject,
        body,
        auto_execute=True,
        dispatched_to=target,
        no_memory_save=no_memory_save,
        from_branch=from_branch,
        user_info=user_info,
    )
    if not sent:
        return True

    console.print(f"\nWaking {target}...")

    from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

    # The wake is attributed to the VERIFIED caller; --from never moves who the wake came from.
    dispatch_status, wake_ok = wake_branch(
        target,
        fresh=use_fresh,
        sender=verified_caller.resolve_wake_sender(user_info.get("email_address", "@ai_mail")),
        model=use_model,
        admin=is_admin,
        subject=subject,
        provider=use_provider,
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

    Managers are never woken (deliberate blocklist); the wake-back mails them, so the promise must say mail.
    """
    from aipass.ai_mail.apps.handlers.dispatch.wake import is_manager

    if is_manager(sender):
        console.print(
            f"[dim]Wake-back enabled — {sender} is a manager and is never woken, "
            f"so you will be MAILED when {target} completes[/dim]"
        )
    else:
        console.print(f"[dim]Wake-back enabled — sender will be woken when {target} completes (if available)[/dim]")


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]dispatch Module[/bold cyan]")
    console.print(
        "[dim]Orchestrates dispatch commands: combined send+wake, the dispatch register, and manual wake.[/dim]"
    )
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/dispatch/[/cyan]")
    console.print("    - [cyan]wake.py[/cyan] [dim](wake_branch — manually wake a branch by spawning an agent)[/dim]")
    console.print("  [cyan]handlers/email/[/cyan] [dim](used by combined dispatch)[/dim]")
    console.print(
        "    - [cyan]send.py[/cyan] [dim](resolve_sender_info — the sender the mail and the wake share)[/dim]"
    )
    console.print("  [cyan]modules/email_send.py[/cyan] [dim](_send_direct — the send half of combined dispatch)[/dim]")
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
