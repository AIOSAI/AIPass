# =================== AIPass ====================
# Name: compass.py
# Description: Compass Module — drone command for devpulse's rated decision store
# Version: 1.0.0
# Created: 2026-06-16
# Modified: 2026-06-16
# =============================================

"""
Compass Module — command routing for devpulse's rated decision store.

Compass is the truth-store of decisions: short, *rated* choices
(``good | bad | impressive | interesting``) that devpulse consults at a fork.
The rating IS the signal — repeat the good, avoid the bad. See DPLAN-0212.

This module is the thin command layer (FPLAN P2). It parses args, calls the
``compass`` storage handler (FPLAN P1), and renders results to the console.
No business logic lives here — that's the handler's job.

Subcommands:
  add "context" "decision" --rating R [--note ..] [--tags a,b] [--source ..] [--supersedes N]
  query "question" [--rating R] [--limit N] [--include-archived]
  stats
  rate <id> <rating>
  archive <id>
  note <id> "text"
  review

Every subcommand accepts ``--db PATH`` (passed through as ``db_path=``) for
testing and power use; omitted, it uses the real store.

Auto-discovered by devpulse.py via the handle_command() convention.
"""

from typing import List, Optional

from aipass.prax import logger
from aipass.cli.apps.modules import err_console, error, warning
from aipass.devpulse.apps.handlers import compass
from aipass.devpulse.apps.handlers.compass import mark_surfaced, recall_decisions
from aipass.devpulse.apps.handlers.json import json_handler

# Public cross-branch recall API (DPLAN-0246 Track 2). Other branches import
# at the modules/ boundary ONLY (seedgo boardroom ruling):
#   from aipass.devpulse.apps.modules.compass import recall_decisions, mark_surfaced
# recall_decisions(prompt_text, limit) -> scored candidates, side-effect-free;
# mark_surfaced(ids) counts only what the caller actually injected.
__all__ = ["handle_command", "mark_surfaced", "recall_decisions"]

console = err_console

_VALID_SUBCOMMANDS = ("add", "query", "stats", "rate", "archive", "note", "review")

# Console colour per rating — the rating is the signal, so make it pop.
_RATING_STYLE = {
    "good": "bold green",
    "bad": "bold red",
    "impressive": "bold magenta",
    "interesting": "bold yellow",
}

HELP_TEXT = """\
[bold cyan]compass[/bold cyan] — devpulse rated decision store

[bold]Usage:[/bold]
  compass add "context" "decision" --rating R [opts]   Store a rated decision
  compass query "question" [--rating R] [--limit N]     Search (rating shown)
  compass stats                                         Counts by rating/status
  compass rate <id> <rating>                            Re-rate a decision
  compass archive <id>                                  Archive a decision
  compass note <id> "text"                              Set a decision's note
  compass review                                         Surface one to review
  compass --help                                        Show this help

[bold]Ratings:[/bold] good | bad | impressive | interesting
[bold]Sources:[/bold] devpulse | user

[bold]Options (add):[/bold]
  --rating R       Required. One of the ratings above.
  --note "..."     Optional human observation.
  --tags a,b,c     Optional comma-separated tags.
  --source S       Optional. devpulse (default) or user.
  --supersedes N   Optional. Archive decision #N and link this entry as its
                   correction (atomic). At add time, overlapping active
                   entries are shown as a non-blocking advisory.

[bold]Options (query):[/bold]
  --rating R           Optional exact-rating filter.
  --limit N            Optional max results (default 5).
  --include-archived   Also search archived (avoid-list) entries; archived hits
                       show their status + supersession pointer.

[bold]Options (all subcommands):[/bold]
  --db PATH        Use an alternate SQLite store (testing / power use).

[bold]Examples:[/bold]
  drone @devpulse compass add "auth fork" "chose JWT over sessions" --rating good
  drone @devpulse compass add "auth fork" "switch to sessions" --rating good --supersedes 4
  drone @devpulse compass query "auth" --rating good --limit 3
  drone @devpulse compass query "auth" --include-archived
  drone @devpulse compass stats
  drone @devpulse compass rate 4 bad
  drone @devpulse compass archive 4
  drone @devpulse compass note 4 "revisited — this held up"
  drone @devpulse compass review

See DPLAN-0212 / DPLAN-0246 (design) and the compass handler (apps/handlers/compass/).
"""


_NOTE_HELP_TEXT = """\
[bold]compass note[/bold] — set (replace) a decision's note

Usage:
  compass note <id> "text"        Set the note on decision #<id>
  compass note --help             Show this help

The note is re-indexed for search immediately — the FTS5 mirror stays in sync,
so the new note text is findable by 'compass query' right away.
"""


def print_introspection() -> None:
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]compass Module[/bold cyan]")
    console.print("[dim]Devpulse rated decision store. The truth-store of choices —[/dim]")
    console.print("[dim]each decision rated; the rating is the signal at a fork.[/dim]")
    console.print()
    console.print("[yellow]Subcommands:[/yellow] [cyan]add, query, stats, rate, archive, note, review[/cyan]")
    console.print("[dim]Run 'compass --help' for full usage.[/dim]")
    console.print()


def _wants_help(args: List[str]) -> bool:
    """Help flag anywhere in args = explain, never execute (DPLAN-0291 rule E).

    Bare word 'help' counts only at position 0 — later positions may be free text
    (a compass note can legitimately contain the word).
    """
    return bool(args) and (args[0] in ("--help", "-h", "help") or any(a in ("--help", "-h") for a in args))


def handle_command(command: str, args: List[str]) -> bool:
    """Route compass subcommands to the storage handler.

    Auto-discovered by devpulse.py module loader.

    Args:
        command: The primary command string.
        args: Additional arguments after the command.

    Returns:
        True if the command was handled, False otherwise.
    """
    if command != "compass":
        return False

    if not args:
        print_introspection()
        return True

    if _wants_help(args):
        console.print(HELP_TEXT)
        return True

    subcommand = args[0]
    sub_args = args[1:]

    if subcommand not in _VALID_SUBCOMMANDS:
        error(f"Unknown compass subcommand: {subcommand}", suggestion="Use 'compass --help' for usage")
        return True

    logger.info("[compass] subcommand=%s args=%s", subcommand, sub_args)
    json_handler.log_operation("compass_command", {"subcommand": subcommand})

    if subcommand == "add":
        return _handle_add(sub_args)
    if subcommand == "query":
        return _handle_query(sub_args)
    if subcommand == "stats":
        return _handle_stats(sub_args)
    if subcommand == "rate":
        return _handle_rate(sub_args)
    if subcommand == "archive":
        return _handle_archive(sub_args)
    if subcommand == "note":
        return _handle_note(sub_args)
    if subcommand == "review":
        return _handle_review(sub_args)

    return True


# =============================================================================
# ARG PARSING HELPERS
# =============================================================================


def _extract_flag(args: List[str], flag: str) -> tuple[List[str], Optional[str]]:
    """Pull a single ``--flag VALUE`` pair out of args.

    Returns the remaining args (flag + value removed) and the value (or None
    if the flag was absent). Raises ValueError if the flag is given without a
    following value — errors must fail loud, never silent.
    """
    value: Optional[str] = None
    remaining: List[str] = []
    i = 0
    while i < len(args):
        if args[i] == flag:
            if i + 1 >= len(args):
                raise ValueError(f"{flag} requires a value")
            value = args[i + 1]
            i += 2
            continue
        remaining.append(args[i])
        i += 1
    return remaining, value


def _extract_db_path(args: List[str]) -> tuple[List[str], Optional[str]]:
    """Pull the optional ``--db PATH`` flag out of args."""
    return _extract_flag(args, "--db")


def _extract_bool_flag(args: List[str], flag: str) -> tuple[List[str], bool]:
    """Pull a valueless boolean ``--flag`` out of args.

    Returns the remaining args (every occurrence of the flag removed) and True
    if the flag was present, else False. Unlike ``_extract_flag`` this consumes
    no following value.
    """
    if flag in args:
        return [a for a in args if a != flag], True
    return args, False


def _rating_tag(rating: str) -> str:
    """Render a coloured ``[RATING]`` tag for query/review output."""
    style = _RATING_STYLE.get(rating, "bold white")
    return f"[{style}]\\[{(rating or '?').upper()}][/{style}]"


# =============================================================================
# SUBCOMMAND HANDLERS
# =============================================================================


def _handle_add(sub_args: List[str]) -> bool:
    """Parse and dispatch ``compass add "context" "decision" --rating R [opts]``."""
    try:
        rest, db_path = _extract_db_path(sub_args)
        rest, rating = _extract_flag(rest, "--rating")
        rest, note = _extract_flag(rest, "--note")
        rest, tags = _extract_flag(rest, "--tags")
        rest, source = _extract_flag(rest, "--source")
        rest, supersedes_raw = _extract_flag(rest, "--supersedes")
    except ValueError as exc:
        logger.warning("[compass] add arg-parse error: %s", exc)
        error(str(exc), suggestion="Use 'compass --help' for usage")
        return True

    if len(rest) < 2:
        error(
            'Usage: compass add "context" "decision" --rating R [--note ..] [--tags a,b] [--source ..] [--supersedes N]'
        )
        return True
    if rating is None:
        error("compass add requires --rating", suggestion="One of: good | bad | impressive | interesting")
        return True

    context = rest[0]
    decision = rest[1]

    supersedes: Optional[int] = None
    if supersedes_raw is not None:
        try:
            supersedes = int(supersedes_raw)
        except ValueError as exc:
            logger.warning("[compass] add bad --supersedes %r: %s", supersedes_raw, exc)
            error(f"--supersedes must be an integer, got {supersedes_raw!r}")
            return True

    # Write-time conflict check — a NON-BLOCKING advisory (DPLAN-0246). Skipped
    # when the writer already chose to supersede, and never allowed to block or
    # crash the add. Only shown when NOT already superseding.
    if supersedes is None:
        try:
            conflicts = compass.find_conflicts(context, decision, db_path=db_path)
        except Exception as exc:  # advisory must never break a write
            logger.warning("[compass] conflict-check failed (non-blocking): %s", exc)
            conflicts = []
        for c in conflicts:
            cid = c.get("id")
            excerpt = (c.get("context") or "").strip()
            if len(excerpt) > 80:
                excerpt = excerpt[:77] + "..."
            console.print(
                f"[yellow]possible conflict with #{cid}[/yellow]: {excerpt} "
                f"[dim]— supersede? (--supersedes {cid})[/dim]"
            )

    try:
        new_id = compass.add_decision(
            context,
            decision,
            rating,
            note=note,
            tags=tags,
            source=source if source is not None else "devpulse",
            db_path=db_path,
            supersedes=supersedes,
        )
    except ValueError as exc:
        logger.warning("[compass] add rejected: %s", exc)
        error(str(exc))
        return True

    console.print(f"[green]Added decision[/green] {_rating_tag(rating)} [bold]#{new_id}[/bold]")
    console.print(f"  [cyan]context:[/cyan] {context}")
    console.print(f"  [cyan]decision:[/cyan] {decision}")
    if note:
        console.print(f"  [cyan]note:[/cyan] {note}")
    if tags:
        console.print(f"  [cyan]tags:[/cyan] {tags}")
    if supersedes is not None:
        console.print(f"  [magenta]supersedes #{supersedes}[/magenta] [dim](archived)[/dim]")
    return True


def _handle_query(sub_args: List[str]) -> bool:
    """Parse and dispatch ``compass query "question" [--rating R] [--limit N]``."""
    try:
        rest, db_path = _extract_db_path(sub_args)
        rest, include_archived = _extract_bool_flag(rest, "--include-archived")
        rest, rating = _extract_flag(rest, "--rating")
        rest, limit_raw = _extract_flag(rest, "--limit")
    except ValueError as exc:
        logger.warning("[compass] query arg-parse error: %s", exc)
        error(str(exc), suggestion="Use 'compass --help' for usage")
        return True

    if not rest:
        error('Usage: compass query "question" [--rating R] [--limit N] [--include-archived]')
        return True

    query_text = rest[0]

    limit = 5
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except ValueError as exc:
            logger.warning("[compass] query bad --limit %r: %s", limit_raw, exc)
            error(f"--limit must be an integer, got {limit_raw!r}")
            return True

    try:
        results = compass.query_decisions(
            query_text,
            rating=rating,
            limit=limit,
            include_archived=include_archived,
            db_path=db_path,
        )
    except ValueError as exc:
        logger.warning("[compass] query rejected: %s", exc)
        error(str(exc))
        return True

    _render_query_results(query_text, rating, results)
    return True


def _render_query_results(query_text: str, rating: Optional[str], results: List[dict]) -> None:
    """Render query results — rating shown prominently, most relevant first."""
    filt = f" [dim](rating={rating})[/dim]" if rating else ""
    console.print(f"[bold]Compass[/bold] — {len(results)} result(s) for [cyan]{query_text!r}[/cyan]{filt}")

    if not results:
        console.print("[dim]No matching decisions.[/dim]")
        return

    console.print()
    for r in results:
        tag = _rating_tag(r.get("rating", "?"))
        console.print(f"{tag} [bold]#{r.get('id', '?')}[/bold]  [dim]{r.get('created', '?')}[/dim]")
        console.print(f"    [cyan]context:[/cyan]  {r.get('context', '')}")
        console.print(f"    [cyan]decision:[/cyan] {r.get('decision', '')}")
        if r.get("note"):
            console.print(f"    [cyan]note:[/cyan]     {r['note']}")
        if r.get("tags"):
            console.print(f"    [cyan]tags:[/cyan]     {r['tags']}")
        # Supersession pointers — an archived hit must never masquerade as
        # current truth, so flag its status + who replaced it (DPLAN-0246).
        if r.get("status") == "archived":
            superseded_by = r.get("superseded_by")
            if superseded_by:
                console.print(f"    [bold yellow]ARCHIVED[/bold yellow] — superseded by #{superseded_by}")
            else:
                console.print("    [bold yellow]ARCHIVED[/bold yellow] (avoid-list)")
        if r.get("supersedes"):
            console.print(f"    [magenta]supersedes #{r['supersedes']}[/magenta]")
        meta = f"source={r.get('source', '?')} status={r.get('status', '?')} surfaced={r.get('times_surfaced', 0)}"
        console.print(f"    [dim]{meta}[/dim]")
        console.print()


def _handle_stats(sub_args: List[str]) -> bool:
    """Dispatch ``compass stats`` and render readable counts."""
    try:
        rest, db_path = _extract_db_path(sub_args)
    except ValueError as exc:
        logger.warning("[compass] stats arg-parse error: %s", exc)
        error(str(exc))
        return True
    if rest:
        error(f"compass stats takes no positional args, got: {' '.join(rest)}")
        return True

    data = compass.stats(db_path=db_path)

    console.print("[bold]Compass Stats[/bold]")
    console.print(f"  Total decisions: [bold]{data.get('total', 0)}[/bold]")
    console.print("  [yellow]By rating:[/yellow]")
    for rating, count in (data.get("by_rating") or {}).items():
        console.print(f"    {_rating_tag(rating)} {count}")
    console.print("  [yellow]By status:[/yellow]")
    for status, count in (data.get("by_status") or {}).items():
        console.print(f"    [cyan]{status:<10}[/cyan] {count}")
    return True


def _handle_rate(sub_args: List[str]) -> bool:
    """Dispatch ``compass rate <id> <rating>``."""
    try:
        rest, db_path = _extract_db_path(sub_args)
    except ValueError as exc:
        logger.warning("[compass] rate arg-parse error: %s", exc)
        error(str(exc))
        return True

    if len(rest) < 2:
        error("Usage: compass rate <id> <rating>")
        return True

    try:
        decision_id = int(rest[0])
    except ValueError as exc:
        logger.warning("[compass] rate bad id %r: %s", rest[0], exc)
        error(f"<id> must be an integer, got {rest[0]!r}")
        return True

    rating = rest[1]
    try:
        changed = compass.rate(decision_id, rating, db_path=db_path)
    except ValueError as exc:
        logger.warning("[compass] rate rejected: %s", exc)
        error(str(exc))
        return True

    if changed:
        console.print(f"[green]Re-rated[/green] [bold]#{decision_id}[/bold] -> {_rating_tag(rating)}")
    else:
        warning(f"No decision with id {decision_id} — nothing changed.")
    return True


def _handle_archive(sub_args: List[str]) -> bool:
    """Dispatch ``compass archive <id>``."""
    try:
        rest, db_path = _extract_db_path(sub_args)
    except ValueError as exc:
        logger.warning("[compass] archive arg-parse error: %s", exc)
        error(str(exc))
        return True

    if not rest:
        error("Usage: compass archive <id>")
        return True

    try:
        decision_id = int(rest[0])
    except ValueError as exc:
        logger.warning("[compass] archive bad id %r: %s", rest[0], exc)
        error(f"<id> must be an integer, got {rest[0]!r}")
        return True

    changed = compass.archive(decision_id, db_path=db_path)
    if changed:
        console.print(
            f"[green]Archived[/green] [bold]#{decision_id}[/bold] [dim](kept as avoid-list, not deleted)[/dim]"
        )
    else:
        warning(f"No decision with id {decision_id} — nothing changed.")
    return True


def _handle_note(sub_args: List[str]) -> bool:
    """Dispatch ``compass note <id> "text"`` — set a decision's note.

    Follows the subcommand-help convention: ``compass note --help`` prints the
    per-subcommand help block; malformed input shows the Usage line.
    """
    try:
        rest, db_path = _extract_db_path(sub_args)
    except ValueError as exc:
        logger.warning("[compass] note arg-parse error: %s", exc)
        error(str(exc))
        return True

    if rest and rest[0] in ("--help", "-h", "help"):
        console.print(_NOTE_HELP_TEXT)
        return True

    if len(rest) < 2:
        error('Usage: compass note <id> "text"')
        return True

    try:
        decision_id = int(rest[0])
    except ValueError as exc:
        logger.warning("[compass] note bad id %r: %s", rest[0], exc)
        error(f"<id> must be an integer, got {rest[0]!r}")
        return True

    note_text = rest[1]
    changed = compass.set_note(decision_id, note_text, db_path=db_path)
    if changed:
        console.print(f"[green]Note set[/green] on [bold]#{decision_id}[/bold]")
        console.print(f"  [cyan]note:[/cyan] {note_text}")
    else:
        warning(f"No decision with id {decision_id} — nothing changed.")
    return True


def _handle_review(sub_args: List[str]) -> bool:
    """Dispatch ``compass review`` — surface one active decision to review."""
    try:
        rest, db_path = _extract_db_path(sub_args)
    except ValueError as exc:
        logger.warning("[compass] review arg-parse error: %s", exc)
        error(str(exc))
        return True
    if rest:
        error(f"compass review takes no positional args, got: {' '.join(rest)}")
        return True

    result = compass.review(db_path=db_path)
    if result is None:
        console.print("[dim]No active decisions to review.[/dim]")
        return True

    tag = _rating_tag(result.get("rating", "?"))
    console.print(f"[bold]Compass Review[/bold] {tag} [bold]#{result.get('id', '?')}[/bold]")
    console.print(f"  [cyan]context:[/cyan]  {result.get('context', '')}")
    console.print(f"  [cyan]decision:[/cyan] {result.get('decision', '')}")
    if result.get("note"):
        console.print(f"  [cyan]note:[/cyan]     {result['note']}")
    if result.get("tags"):
        console.print(f"  [cyan]tags:[/cyan]     {result['tags']}")
    console.print(
        f"  [dim]created={result.get('created', '?')} last_reviewed={result.get('last_reviewed', '?')} "
        f"surfaced={result.get('times_surfaced', 0)}[/dim]"
    )
    console.print("[dim]Tip: re-rate with 'compass rate <id> <rating>' or retire with 'compass archive <id>'.[/dim]")
    return True
