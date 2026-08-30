# =================== AIPass ====================
# Name: commons_feed.py
# Description: Commons Live Social Feed (read-only monitor view)
# Version: 1.1.0
# Created: 2026-07-21
# Modified: 2026-08-29
# =============================================

"""
PRAX Monitor — Commons Live Feed

`drone @prax monitor run commons` streams The Commons' social chatter
(posts, comments, votes, reactions) room-tagged, monitor-style, instead of
tailing commons' technical prax logs (still reachable via `--logs`).

Read-only by construction: connects to commons.db via a `mode=ro` URI, so
the feed can never write — commons stays the only writer. Polls with per-table
id cursors, showing only genuinely new rows each cycle.
"""

import os
import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rich.markup import escape as rich_escape

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, header, error, warning
from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.monitoring.event_queue import MonitoringEvent
from aipass.prax.apps.handlers.monitoring.telegram_relay import (
    init_relay,
    relay_event,
    stop_relay,
    is_relay_enabled_by_env,
)

# =============================================================================
# CONFIGURATION
# =============================================================================

POLL_INTERVAL = 1.5
BACKFILL_LIMIT = 10

_PRAX_ROOT = Path(__file__).resolve().parents[3]  # monitoring/ -> handlers/ -> apps/ -> prax/
_ECOSYSTEM_ROOT = _PRAX_ROOT.parent

CURSOR_TABLES = ("posts", "comments", "votes", "reactions")

_CURSOR_TABLE_FOR_KIND = {
    "post": "posts",
    "comment": "comments",
    "vote": "votes",
    "reaction": "reactions",
}

MOOD_COLORS = {
    "welcoming": "green",
    "focused": "cyan",
    "relaxed": "yellow",
    "formal": "blue",
    "creative": "magenta",
    "neutral": "white",
}
DEFAULT_ROOM_COLOR = "white"
ROOM_LABEL_WIDTH = 18

_stop_event = threading.Event()

# =============================================================================
# DB ACCESS (read-only)
# =============================================================================


def _get_commons_db_path() -> Path:
    """Resolve commons.db — sibling branch under the same ecosystem root.

    AIPASS_COMMONS_DB_PATH overrides for tests, mirroring AIPASS_TEST_LOG_DIR.
    """
    override = os.environ.get("AIPASS_COMMONS_DB_PATH")
    if override:
        return Path(override)
    return _ECOSYSTEM_ROOT / "commons" / "commons.db"


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open commons.db strictly read-only via a mode=ro URI — writes always fail."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _load_room_moods(conn: sqlite3.Connection) -> Dict[str, str]:
    """Load room name -> mood, for cheap color tagging."""
    rows = conn.execute("SELECT name, mood FROM rooms").fetchall()
    return {row["name"]: row["mood"] for row in rows}


def initial_cursors(conn: sqlite3.Connection) -> Dict[str, int]:
    """Snapshot the current max id per event table — the poll starting line."""
    cursors = {}
    for table in CURSOR_TABLES:
        row = conn.execute(f"SELECT COALESCE(MAX(id), 0) AS m FROM {table}").fetchone()
        cursors[table] = row["m"]
    return cursors


def _fetch_new_posts(conn: sqlite3.Connection, since_id: int) -> List[dict]:
    rows = conn.execute(
        "SELECT id, room_name, author, title, content, created_at FROM posts WHERE id > ? ORDER BY id ASC",
        (since_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_new_comments(conn: sqlite3.Connection, since_id: int) -> List[dict]:
    rows = conn.execute(
        "SELECT c.id, c.post_id, c.parent_id, c.author, c.content, c.created_at, "
        "p.room_name AS room_name, p.author AS post_author "
        "FROM comments c JOIN posts p ON c.post_id = p.id "
        "WHERE c.id > ? ORDER BY c.id ASC",
        (since_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_new_votes(conn: sqlite3.Connection, since_id: int) -> List[dict]:
    rows = conn.execute(
        "SELECT v.id, v.agent_name, v.target_id, v.target_type, v.direction, v.created_at, "
        "COALESCE(p1.room_name, p2.room_name) AS room_name "
        "FROM votes v "
        "LEFT JOIN posts p1 ON v.target_type = 'post' AND v.target_id = p1.id "
        "LEFT JOIN comments c ON v.target_type = 'comment' AND v.target_id = c.id "
        "LEFT JOIN posts p2 ON c.post_id = p2.id "
        "WHERE v.id > ? ORDER BY v.id ASC",
        (since_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_new_reactions(conn: sqlite3.Connection, since_id: int) -> List[dict]:
    rows = conn.execute(
        "SELECT r.id, r.agent_name, r.post_id, r.comment_id, r.reaction, r.created_at, "
        "COALESCE(p1.room_name, p2.room_name) AS room_name "
        "FROM reactions r "
        "LEFT JOIN posts p1 ON r.post_id = p1.id "
        "LEFT JOIN comments c ON r.comment_id = c.id "
        "LEFT JOIN posts p2 ON c.post_id = p2.id "
        "WHERE r.id > ? ORDER BY r.id ASC",
        (since_id,),
    ).fetchall()
    return [dict(r) for r in rows]


_NEW_FETCHERS = {
    "post": _fetch_new_posts,
    "comment": _fetch_new_comments,
    "vote": _fetch_new_votes,
    "reaction": _fetch_new_reactions,
}


def fetch_new_events(conn: sqlite3.Connection, cursors: Dict[str, int]) -> Tuple[List[dict], Dict[str, int]]:
    """Fetch rows newer than each cursor, tag with kind, return sorted events + advanced cursors."""
    events: List[dict] = []
    new_cursors = dict(cursors)

    for kind, table in _CURSOR_TABLE_FOR_KIND.items():
        rows = _NEW_FETCHERS[kind](conn, cursors[table])
        if rows:
            events.extend({**row, "kind": kind} for row in rows)
            new_cursors[table] = rows[-1]["id"]

    events.sort(key=lambda e: (e["created_at"], e["id"]))
    return events, new_cursors


def fetch_backfill(conn: sqlite3.Connection, cursors: Dict[str, int], limit: int = BACKFILL_LIMIT) -> List[dict]:
    """Fetch the last `limit` events at/under the given cursors — startup context."""
    events: List[dict] = []
    queries = {
        "post": "SELECT id, room_name, author, title, content, created_at FROM posts "
        "WHERE id <= ? ORDER BY id DESC LIMIT ?",
        "comment": "SELECT c.id, c.post_id, c.parent_id, c.author, c.content, c.created_at, "
        "p.room_name AS room_name, p.author AS post_author FROM comments c "
        "JOIN posts p ON c.post_id = p.id WHERE c.id <= ? ORDER BY c.id DESC LIMIT ?",
        "vote": "SELECT v.id, v.agent_name, v.target_id, v.target_type, v.direction, v.created_at, "
        "COALESCE(p1.room_name, p2.room_name) AS room_name FROM votes v "
        "LEFT JOIN posts p1 ON v.target_type = 'post' AND v.target_id = p1.id "
        "LEFT JOIN comments c ON v.target_type = 'comment' AND v.target_id = c.id "
        "LEFT JOIN posts p2 ON c.post_id = p2.id WHERE v.id <= ? ORDER BY v.id DESC LIMIT ?",
        "reaction": "SELECT r.id, r.agent_name, r.post_id, r.comment_id, r.reaction, r.created_at, "
        "COALESCE(p1.room_name, p2.room_name) AS room_name FROM reactions r "
        "LEFT JOIN posts p1 ON r.post_id = p1.id "
        "LEFT JOIN comments c ON r.comment_id = c.id "
        "LEFT JOIN posts p2 ON c.post_id = p2.id WHERE r.id <= ? ORDER BY r.id DESC LIMIT ?",
    }

    for kind, sql in queries.items():
        table = _CURSOR_TABLE_FOR_KIND[kind]
        rows = conn.execute(sql, (cursors[table], limit)).fetchall()
        events.extend({**dict(row), "kind": kind} for row in rows)

    events.sort(key=lambda e: (e["created_at"], e["id"]))
    return events[-limit:]


# =============================================================================
# DISPLAY
# =============================================================================


INLINE_BODY_MAX = 100


def _join_body(header: str, text: Optional[str], sep: str) -> str:
    """Header + body: inline when the body fits, else the FULL body on its own lines.

    The feed is where agents get read live — a long message breaks to
    multi-line instead of truncating, so nothing an agent says is lost."""
    if not text:
        return header
    collapsed = " ".join(text.split())
    if len(collapsed) <= INLINE_BODY_MAX:
        return f"{header}{sep}{collapsed}"
    lines = [line.rstrip() for line in text.strip().splitlines()]
    return header + "\n" + "\n".join(lines)


def event_room(event: dict) -> str:
    """Room name for an event, or 'commons' when it can't be resolved (orphaned row)."""
    return event.get("room_name") or "commons"


def format_event(event: dict) -> str:
    """Plain-text (no Rich markup) description of an event — shared by console + relay."""
    kind = event["kind"]

    if kind == "post":
        return _join_body(f'{event["author"]} posted: "{event["title"]}"', event["content"], " — ")
    if kind == "comment":
        target = event.get("post_author") or "?"
        return _join_body(f"{event['author']} replied to {target}:", event["content"], " ")
    if kind == "vote":
        direction = "up" if (event.get("direction") or 0) > 0 else "down"
        return f"{event['agent_name']} voted {direction} on {event['target_type']} #{event['target_id']}"
    if kind == "reaction":
        target_kind = "post" if event.get("post_id") else "comment"
        reaction = event.get("reaction") or ""
        return f"{event['agent_name']} reacted {reaction} to a {target_kind}"
    return str(event)


def _print_feed_event(room: str, message: str, mood: Optional[str]) -> None:
    """Print one feed line — room tag colored by mood, monitor-style timestamp."""
    ts = datetime.now().strftime("%H:%M:%S")
    color = MOOD_COLORS.get(mood or "", DEFAULT_ROOM_COLOR)
    label = f"[{room}]"
    # message is agent-authored text — escape it so brackets survive Rich verbatim
    console.print(f"[dim]{ts}[/dim] [{color}]{label:<{ROOM_LABEL_WIDTH}}[/{color}] {rich_escape(message)}")


def _emit(event: dict, room_moods: Dict[str, str]) -> None:
    """Render an event to the console and relay it (relay is a no-op when inactive)."""
    room = event_room(event)
    message = format_event(event)
    _print_feed_event(room, message, room_moods.get(room))

    relay_event(
        MonitoringEvent(
            priority=3,
            event_type="log",
            branch=room.upper(),
            message=message,
            level="info",
        )
    )


# =============================================================================
# FEED STATE + INTERACTIVE COMMANDS
# =============================================================================


class FeedState:
    """Tracks rooms/agents/events seen and the active room filter."""

    def __init__(self) -> None:
        self.rooms_seen: set = set()
        self.agents_seen: set = set()
        self.events_count: int = 0
        self.room_filter: Optional[set] = None

    def record(self, event: dict) -> None:
        """Count an event toward status stats — independent of the display filter."""
        self.rooms_seen.add(event_room(event))
        agent = event.get("author") or event.get("agent_name")
        if agent:
            self.agents_seen.add(agent)
        self.events_count += 1

    def visible(self, event: dict) -> bool:
        """Whether the active room filter allows this event to display."""
        if not self.room_filter:
            return True
        return event_room(event) in self.room_filter


def _feed_help_text() -> str:
    return """
Available Commands:
  filter <room>[,<room>...]  - Show only these rooms
  filter clear                - Remove the room filter
  status                      - Show feed stats (rooms/agents/events)
  help                        - Show this help
  quit/exit                   - Stop the feed
"""


def _print_feed_status(state: FeedState) -> None:
    console.print()
    console.print("[bold cyan]Commons Feed Status:[/bold cyan]")
    console.print(f"  [green]Rooms seen:[/green] {len(state.rooms_seen)}")
    console.print(f"  [green]Agents seen:[/green] {len(state.agents_seen)}")
    console.print(f"  [green]Events streamed:[/green] {state.events_count}")
    if state.room_filter:
        console.print(f"  [yellow]Filter:[/yellow] {', '.join(sorted(state.room_filter))}")
    console.print()


def _handle_feed_cmd(cmd: str, cmd_args: List[str], state: FeedState) -> None:
    """Dispatch an interactive feed command."""
    if cmd == "help":
        console.print(_feed_help_text())
        return
    if cmd == "status":
        _print_feed_status(state)
        return
    if cmd == "filter":
        if not cmd_args or cmd_args[0] in ("clear", "all"):
            state.room_filter = None
            warning("Filter cleared — showing all rooms")
            return
        rooms = {room.strip() for token in cmd_args for room in token.split(",") if room.strip()}
        state.room_filter = rooms
        warning(f"Filtering to rooms: {', '.join(sorted(rooms))}")
        return
    error(f"Unknown command: {cmd}")
    console.print("[dim]Type 'help' for available commands[/dim]")


def _interactive_feed_loop(state: FeedState) -> None:
    """Interactive command loop for the feed — mirrors the branch monitor's loop shape."""
    if not sys.stdin.isatty():
        logger.info("[commons_feed] No TTY detected - passive mode (Ctrl+C to stop)")
        try:
            while not _stop_event.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("[commons_feed] Stopped by user (passive mode)")
            console.print("\n[yellow]Stopping feed...[/yellow]")
        return

    from aipass.prax.apps.handlers.monitoring.interactive_filter import parse_command

    while not _stop_event.is_set():
        try:
            user_input = input().strip()
            if not user_input:
                continue

            cmd, cmd_args = parse_command(user_input)
            if not cmd:
                continue

            if cmd in ("quit", "exit", "q"):
                console.print("[yellow]Stopping feed...[/yellow]")
                break

            _handle_feed_cmd(cmd, cmd_args, state)

        except KeyboardInterrupt:
            logger.info("[commons_feed] Stopped by user")
            console.print("\n[yellow]Stopping feed...[/yellow]")
            break
        except EOFError:
            logger.info("[commons_feed] EOF received, stopping interactive loop")
            break


# =============================================================================
# POLL WORKER
# =============================================================================


def _poll_worker(
    conn: sqlite3.Connection, cursors: Dict[str, int], state: FeedState, room_moods: Dict[str, str]
) -> None:
    """Background thread: poll for new rows, display + relay the visible ones."""
    while not _stop_event.is_set():
        try:
            events, new_cursors = fetch_new_events(conn, cursors)
            cursors.update(new_cursors)
            for event in events:
                state.record(event)
                if state.visible(event):
                    _emit(event, room_moods)
        except sqlite3.Error as exc:
            logger.warning(
                "[commons_feed] The commons live feed could not read new messages this cycle (%s) — "
                "it will retry on the next poll; nothing in commons.db is changed or lost.",
                type(exc).__name__,
            )
        _stop_event.wait(POLL_INTERVAL)


# =============================================================================
# ENTRY POINT
# =============================================================================


def run_commons_feed(args: List[str], relay_config: Optional[dict] = None) -> bool:
    """Launch the commons live social feed — read-only, room-tagged, monitor-style.

    relay_config is loaded by monitor.py (the module layer, which owns the
    cross-branch @api secrets lookup) and passed in — this handler never
    reaches outside its own branch.
    """
    _stop_event.clear()
    json_handler.log_operation("commons_feed_started", {"args": args})

    relay_enabled = "--relay" in args or is_relay_enabled_by_env()
    init_relay(relay_enabled, relay_config if relay_enabled else None)
    if relay_enabled:
        console.print("[green]monitor → Telegram relay ON (prax_monitor)[/green]")

    db_path = _get_commons_db_path()
    if not db_path.exists():
        error(f"commons.db not found at {db_path}")
        stop_relay()
        return True

    try:
        conn = connect_readonly(db_path)
        cursors = initial_cursors(conn)
    except sqlite3.Error as exc:
        logger.warning(
            "[commons_feed] The commons live feed could not open commons.db for reading (%s) — "
            "the feed did not start. The database was not modified.",
            type(exc).__name__,
        )
        error(
            f"Cannot open the commons database for reading, so the commons live feed did not start. "
            f"The database itself was not modified. Location: {db_path}"
        )
        stop_relay()
        return True

    state = FeedState()
    room_moods = _load_room_moods(conn)

    console.print()
    header("PRAX Mission Control - Commons Live Feed")
    console.print()
    console.print("[green]Live — read-only feed of The Commons (posts, comments, votes, reactions)[/green]")
    is_tty = sys.stdin.isatty()
    console.print("[dim]Type 'help' for commands[/dim]" if is_tty else "[dim]Ctrl+C to stop[/dim]")
    console.print()

    for event in fetch_backfill(conn, cursors):
        state.record(event)
        _emit(event, room_moods)

    poll_thread = threading.Thread(target=_poll_worker, args=(conn, cursors, state, room_moods), daemon=True)
    poll_thread.start()

    try:
        _interactive_feed_loop(state)
    except KeyboardInterrupt:
        logger.info("[commons_feed] KeyboardInterrupt escaped interactive loop")
        console.print("\n[yellow]Feed stopped.[/yellow]")

    _stop_event.set()
    poll_thread.join(timeout=POLL_INTERVAL + 2.0)
    stop_relay()
    conn.close()

    # sys.exit(0) prevents drone's post-execution json_handler from running
    # after the feed exits, avoiding a json.load crash on Ctrl+C (matches monitor.py).
    sys.exit(0)
