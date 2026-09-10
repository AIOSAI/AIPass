# =================== AIPass ====================
# Name: release_notify.py
# Description: Release Notify Module — release mail fan-out to project managers
# Version: 1.0.0
# Created: 2026-09-09
# Modified: 2026-09-09
# =============================================

"""
Release Notify Module — release mail fan-out to project managers (release-notify).

Auto-discovered by devpulse.py via handle_command(). One merge-train step
(DPLAN-0335 leg 1): enumerate the managers, mail each one, post one commons
thread, stamp the version so a second run sends nothing.
"""

from rich.table import Table

from aipass.devpulse.apps.handlers.release_notify.managers import (
    aipass_root,
    discover_managers,
)
from aipass.devpulse.apps.handlers.release_notify.compose import (
    CHANGELOG_FILENAME,
    changelog_headline,
    compose_body,
    compose_subject,
    normalize_version,
)
from aipass.devpulse.apps.handlers.release_notify.deliver import (
    COMMONS_ROOM,
    already_notified,
    load_state,
    post_commons,
    record_notified,
    send_email,
    state_path,
)

from aipass.prax import logger
from aipass.cli.apps.modules import console as stdout_console, err_console, error, warning
from aipass.devpulse.apps.handlers.json import json_handler

# Progress and refusals are chatter and belong on stderr; the preview and the
# summary are this command's PRODUCT and go to stdout, where a redirect
# captures them. Help is documentation, so it goes to stdout too (feedback.py
# carries the measurement that settled this: help on stderr wrote an empty
# file).
console = err_console

COMMAND_NAMES = ("release-notify", "release_notify")

HELP_TEXT = """\
[bold cyan]release-notify[/bold cyan] — tell every project manager a release shipped

[bold]Usage:[/bold]
  release-notify v<version>              Mail every manager + post one commons thread
  release-notify v<version> --dry-run    Show recipients and the body, send nothing
  release-notify v<version> --force      Send again for a version already stamped
  release-notify --help                  Show this help

[bold]Who gets it:[/bold]
  Every passport with citizen_class manager under an active root in
  AIPASS_ROOTS.json, plus every project under projects/. The AIPass source
  repo is skipped — it has no scaffold of its own to update.

[bold]What they get:[/bold]
  The version, the GitHub release URL, the top of the CHANGELOG, and the
  preview-first ritual: doctor, init update --dry-run, ask for a go, apply,
  doctor again.

[bold]Idempotent:[/bold]
  One send per version. The stamp lives in .devpulse/release_notify.json;
  a second run says so and sends nothing unless --force.
"""

_DRY_RUN_FLAG = "--dry-run"
_FORCE_FLAG = "--force"
_KNOWN_FLAGS = (_DRY_RUN_FLAG, _FORCE_FLAG)


def print_introspection() -> None:
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]release_notify Module[/bold cyan]")
    console.print("[dim]Release mail fan-out to project managers — one mail per[/dim]")
    console.print("[dim]manager, one commons thread, one stamp per version.[/dim]")
    console.print()
    console.print("[yellow]Usage:[/yellow] [cyan]release-notify v<version> \\[--dry-run] \\[--force][/cyan]")
    console.print()


def _wants_help(args: list[str]) -> bool:
    """Help flag anywhere in args = explain, never execute (DPLAN-0291 rule E).

    Bare word 'help' counts only at position 0 — later positions may be values.

    Args:
        args: Arguments after the command word.

    Returns:
        True when the caller asked to be told, not to be obeyed.
    """
    return bool(args) and (args[0] in ("--help", "-h", "help") or any(a in ("--help", "-h") for a in args))


def _parse_args(args: list[str]) -> tuple[str, bool, bool] | None:
    """Read the version token and the two flags, refusing anything else BY NAME.

    Args:
        args: Arguments after the command word.

    Returns:
        tuple: (raw version token, dry_run, force), or None when the line was
        refused — the refusal is already printed.
    """
    flags = [arg for arg in args if arg.startswith("-")]
    positionals = [arg for arg in args if not arg.startswith("-")]

    unknown = [flag for flag in flags if flag not in _KNOWN_FLAGS]
    if unknown:
        error(
            f"Unknown flag: {unknown[0]}",
            suggestion=f"release-notify takes {' and '.join(_KNOWN_FLAGS)} — nothing else.",
        )
        return None

    if len(positionals) > 1:
        error(
            f"Unexpected argument: {positionals[1]}",
            suggestion=f"One version per run — already reading {positionals[0]}.",
        )
        return None

    if not positionals:
        error(
            "release-notify needs the version that shipped",
            suggestion="drone @devpulse release-notify v2.8.4 [--dry-run]",
        )
        return None

    return positionals[0], _DRY_RUN_FLAG in flags, _FORCE_FLAG in flags


def _print_lines(lines: list[str]) -> None:
    """Print plain text on stdout with Rich told to leave it alone.

    A CHANGELOG line carries square brackets and a path may carry anything;
    Rich reads [...] as markup and raises on an unknown style. soft_wrap keeps
    a passport path on ONE line — the default 80-column wrap folded every path
    in the first preview, which is unreadable and unpasteable.

    Args:
        lines: The lines to print verbatim.
    """
    for line in lines:
        stdout_console.print(line, markup=False, highlight=False, soft_wrap=True)


def _preview(version: str, subject: str, body: str, discovery: dict) -> None:
    """Print the recipients, what was skipped and why, and the whole body.

    Args:
        version: The bare version being announced.
        subject: The subject line.
        body: The composed body.
        discovery: The result of discover_managers().
    """
    managers = discovery["managers"]
    skipped = discovery["skipped"]

    lines = [f"DRY RUN — v{version}: nothing sent, nothing written", ""]
    lines.append(f"Roots searched ({len(discovery['roots'])}):")
    lines.extend(f"  {root}" for root in discovery["roots"])
    lines.append("")
    lines.append(f"Recipients ({len(managers)}):")
    lines.extend(f"  {entry['address']:<16} {entry['passport']}" for entry in managers)
    lines.append("")
    lines.append(f"Skipped ({len(skipped)}):")
    lines.extend(f"  {entry['reason']:<52} {entry['path']}" for entry in skipped)
    lines.append("")
    lines.append(f"Commons thread: {COMMONS_ROOM} (one post, type announcement)")
    lines.append("")
    lines.append(f"Subject: {subject}")
    lines.append("")
    lines.append("--- body ---")
    lines.extend(body.splitlines())
    lines.append("--- end body ---")
    _print_lines(lines)


def _summary(rows: list[tuple[str, str, str]], commons: str) -> None:
    """Print the per-recipient outcome table on stdout.

    Args:
        rows: (address, manager name, outcome) per recipient.
        commons: The commons post outcome.
    """
    table = Table(title="release-notify", show_lines=False)
    table.add_column("Recipient", style="cyan", width=18)
    table.add_column("Manager", style="green", width=16)
    table.add_column("Result", style="white", min_width=20)
    for address, name, outcome in rows:
        table.add_row(address, name, outcome)
    table.add_row("commons", COMMONS_ROOM, commons)
    stdout_console.print(table)


def _fan_out(subject: str, body: str, managers: list[dict]) -> tuple[list[str], list[str], list[tuple[str, str, str]]]:
    """Mail every manager, keeping going past any single failure.

    Args:
        subject: The subject line.
        body: The composed body.
        managers: Manager entries from discover_managers().

    Returns:
        tuple: (addresses sent, addresses failed, table rows).
    """
    sent: list[str] = []
    failed: list[str] = []
    rows: list[tuple[str, str, str]] = []

    for entry in managers:
        address = entry["address"]
        console.print(f"[dim]sending to {address}…[/dim]")
        ok, reason = send_email(address, subject, body)
        if ok:
            sent.append(address)
            rows.append((address, entry["name"], "sent"))
        else:
            failed.append(address)
            rows.append((address, entry["name"], f"FAILED — {reason}"))

    return sent, failed, rows


def _notify(version: str, dry_run: bool, force: bool) -> bool:
    """Run the fan-out for one version.

    Args:
        version: The bare version being announced.
        dry_run: Preview only — no sends, no stamp.
        force: Send again even though this version is stamped.

    Returns:
        bool: Always True — the command was handled. Failures are reported
        through error(), which is what sets the non-zero exit.
    """
    discovery = discover_managers()
    managers = discovery["managers"]
    headline = changelog_headline(aipass_root() / CHANGELOG_FILENAME, version)
    subject = compose_subject(version)
    body = compose_body(version, headline)

    if dry_run:
        _preview(version, subject, body, discovery)
        return True

    state = load_state()
    if state.get("unreadable"):
        warning(
            f"The stamp file at {state_path()} could not be read",
            details="Treating it as empty — this run may repeat a mail rather than skip one.",
        )

    record = already_notified(state, version)
    if record and not force:
        recipients = ", ".join(record.get("recipients", [])) or "(none recorded)"
        console.print(f"[yellow]already notified[/yellow] — v{version} went out {record.get('sent_at', '?')}")
        console.print(f"[dim]recipients: {recipients}[/dim]")
        console.print(f"[dim]Send it again with: drone @devpulse release-notify v{version} --force[/dim]")
        return True

    if not managers:
        error(
            f"No project managers found for v{version} — nothing was sent",
            suggestion="Check AIPASS_ROOTS.json (drone @memory roots list) and projects/. Preview with --dry-run.",
        )
        return True

    sent, failed, rows = _fan_out(subject, body, managers)

    posted, reason = post_commons(subject, body)
    commons = "posted" if posted else f"FAILED — {reason}"

    stamp = record_notified(version, sent, failed, commons)
    _summary(rows, commons)
    console.print(f"[dim]stamped in {stamp}[/dim]")

    if failed or not posted:
        error(
            f"v{version}: {len(sent)} of {len(managers)} mails sent, commons {commons.split(' — ')[0].lower()}",
            suggestion=f"Failed: {', '.join(failed) or 'none'}. Re-run with --force once the reason is fixed.",
        )
    else:
        console.print(f"[green]v{version} announced to {len(sent)} managers[/green]")
    return True


def handle_command(command: str, args: list[str]) -> bool:
    """Route release-notify to the fan-out.

    Auto-discovered by devpulse.py's module loader.

    Args:
        command: The primary command string.
        args: Additional arguments after the command.

    Returns:
        bool: True if the command was handled, False otherwise.
    """
    if command not in COMMAND_NAMES:
        return False

    if _wants_help(args):
        stdout_console.print(HELP_TEXT)
        return True

    if not args:
        print_introspection()
        error(
            "release-notify needs the version that shipped",
            suggestion="drone @devpulse release-notify v2.8.4 [--dry-run]",
        )
        return True

    parsed = _parse_args(args)
    if parsed is None:
        return True

    version_token, dry_run, force = parsed
    version = normalize_version(version_token)
    if not version:
        error(
            f"Not a version: {version_token}",
            suggestion="Spell it like the tag: v2.8.4 (or 2.8.4).",
        )
        return True

    json_handler.log_operation("release_notify_command", {"version": version, "dry_run": dry_run, "force": force})
    logger.info(f"[release_notify] v{version} dry_run={dry_run} force={force}")
    return _notify(version, dry_run, force)
