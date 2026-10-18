# =================== AIPass ====================
# Name: db.py
# Description: The Commons SQLite connection manager
# Version: 1.2.0
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""The Commons - SQLite Connection Manager"""

import os
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional, TypeVar, Callable

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.commons.apps.handlers.json import json_handler
from aipass.commons.apps.handlers.module_root import module_file


def find_branch_root(start_path: Optional[Path] = None) -> Optional[Path]:
    """Walk up from a starting path to find the commons branch root."""
    # .aipass/ is git-tracked (.trinity/ is not): it is what resolves a fresh clone.
    # module_file(), not .resolve(): DB_PATH calls this at import, where Windows resolve reads cwd.
    current = start_path if start_path is not None else module_file(__file__).parent
    for _ in range(10):
        if (current / ".trinity").is_dir() or (current / ".aipass").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def resolve_db_path() -> Optional[Path]:
    """Resolve the database file path; None means callers must not guess a location."""
    branch_root = find_branch_root()
    if branch_root:
        return branch_root / "commons.db"

    aipass_root = os.environ.get("AIPASS_ROOT", "")
    if aipass_root:
        return Path(aipass_root) / "src" / "aipass" / "commons" / "commons.db"

    return None


DB_PATH = resolve_db_path()


class CommonsRootNotFound(RuntimeError):
    """Raised by get_db() at use-time, never at import, when the branch root cannot be resolved."""


SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_RETRY_DELAYS = (0.1, 0.5, 2.0)

T = TypeVar("T")


def retry_on_locked(fn: Callable[..., T], *args, **kwargs) -> T:
    """Retry wrapper for database operations that may hit "database is locked"."""
    last_err: Optional[sqlite3.OperationalError] = None
    for delay in (*_RETRY_DELAYS, None):
        try:
            return fn(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc):
                raise
            logger.warning(f"[db] Database locked, retrying: {exc}")
            last_err = exc
            if delay is None:
                break
            time.sleep(delay)
    raise last_err  # type: ignore[misc]


def get_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a connection to the Commons database; CommonsRootNotFound if no path resolves."""
    path = db_path or DB_PATH
    if path is None:
        raise CommonsRootNotFound(
            "Could not resolve the commons database path: walked up from "
            f"{module_file(__file__).parent} looking for a '.trinity/' or "
            "'.aipass/' directory and found neither. Set the AIPASS_ROOT "
            "environment variable to the repo root, or run from inside a "
            "checked-out AIPass branch."
        )
    path.parent.mkdir(parents=True, exist_ok=True)

    def _connect() -> sqlite3.Connection:
        conn = sqlite3.connect(str(path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    return retry_on_locked(_connect)


def close_db(conn: sqlite3.Connection) -> None:
    """Close a database connection safely."""
    if conn:
        conn.close()


def init_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Create tables from schema.sql (CREATE IF NOT EXISTS, no migrations) and seed rooms and agents."""
    resolved_path = db_path or DB_PATH
    conn = get_db(db_path)

    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)

    _seed_default_rooms(conn)

    _seed_room_personalities(conn)

    _seed_secret_rooms(conn)

    _register_branches(conn)

    logger.info("[commons.db] Database initialized successfully")
    json_handler.log_operation("db_init", {"db_path": str(resolved_path), "success": True})
    return conn


def _seed_default_rooms(conn: sqlite3.Connection) -> None:
    """Create default rooms if they don't exist."""
    default_rooms = [
        ("general", "General", "Main gathering space for all branches", "SYSTEM"),
        ("dev", "Dev", "Development discussions, code reviews, technical topics", "SYSTEM"),
        ("watercooler", "Watercooler", "Casual chat, random thoughts, off-topic", "SYSTEM"),
        ("announcements", "Announcements", "System-wide announcements and updates", "SYSTEM"),
        ("ideas", "Ideas", "Brainstorming, proposals, and feature requests", "SYSTEM"),
    ]

    # rooms.created_by references agents: SYSTEM must exist first.
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name, description) VALUES (?, ?, ?)",
        ("SYSTEM", "System", "The Commons system account"),
    )

    for name, display_name, description, created_by in default_rooms:
        conn.execute(
            "INSERT OR IGNORE INTO rooms (name, display_name, description, created_by) VALUES (?, ?, ?, ?)",
            (name, display_name, description, created_by),
        )

    conn.commit()


def _seed_room_personalities(conn: sqlite3.Connection) -> None:
    """Set default personality data for built-in rooms, leaving customized rooms alone."""
    personalities = {
        "general": {
            "mood": "welcoming",
            "flavor_text": "The main hall. Everyone passes through here.",
            "entrance_message": "You step into the general hall. The bulletin boards are full.",
        },
        "dev": {
            "mood": "focused",
            "flavor_text": "Whiteboards covered in diagrams. The smell of fresh code.",
            "entrance_message": "You enter the dev room. Terminal screens glow softly.",
        },
        "watercooler": {
            "mood": "relaxed",
            "flavor_text": "Dim lights. A half-finished diagram on the wall. Someone left coffee.",
            "entrance_message": "You push through the saloon doors into the watercooler. It's cozy.",
        },
        "announcements": {
            "mood": "formal",
            "flavor_text": "A podium stands at the center. The room echoes.",
            "entrance_message": "You enter the announcements hall. Important notices line the walls.",
        },
        "ideas": {
            "mood": "creative",
            "flavor_text": "Sticky notes cover every surface. A spark of inspiration hangs in the air.",
            "entrance_message": "You step into the ideas lab. Possibilities are everywhere.",
        },
    }

    for room_name, personality in personalities.items():
        row = conn.execute("SELECT mood FROM rooms WHERE name = ?", (room_name,)).fetchone()

        if row and (not row["mood"] or row["mood"] == "neutral"):
            conn.execute(
                "UPDATE rooms SET mood = ?, flavor_text = ?, entrance_message = ? WHERE name = ?",
                (personality["mood"], personality["flavor_text"], personality["entrance_message"], room_name),
            )

    conn.commit()


def _seed_secret_rooms(conn: sqlite3.Connection) -> None:
    """Seed secret (hidden) rooms, found only through 'explore', if they don't already exist."""
    secret_rooms = [
        ("the-void", "The Void", "Where deleted thoughts echo", "Look beyond what's listed", "SYSTEM"),
        ("glitch-garden", "Glitch Garden", "Where beautiful failures bloom", "Errors have their own beauty", "SYSTEM"),
        (
            "time-capsule-vault",
            "Time Capsule Vault",
            "Sealed messages await their moment",
            "Some things need patience",
            "SYSTEM",
        ),
    ]

    for name, display_name, description, hint, created_by in secret_rooms:
        existing = conn.execute("SELECT name FROM rooms WHERE name = ?", (name,)).fetchone()

        if not existing:
            conn.execute(
                "INSERT INTO rooms (name, display_name, description, created_by, hidden, discovery_hint) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (name, display_name, description, created_by, hint),
            )

    conn.commit()


def _register_branches(conn: sqlite3.Connection) -> None:
    """Auto-register missing branches from AIPASS_REGISTRY.json as agents."""
    registry_path = _find_branch_registry()
    if not registry_path:
        return

    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("[db] Failed to read branch registry JSON")
        return

    branches = registry.get("branches", [])
    for branch in branches:
        # Registry casing is mixed; lowercase to match identity_ops.get_caller_branch().
        name = branch.get("name", "").lower()
        if not name:
            continue

        description = branch.get("description", "")
        display_name = name.replace("_", " ").title()

        conn.execute(
            "INSERT OR IGNORE INTO agents (branch_name, display_name, description) VALUES (?, ?, ?)",
            (name, display_name, description),
        )

    conn.commit()


def _find_branch_registry() -> Optional[Path]:
    """Locate AIPASS_REGISTRY.json by searching standard paths."""
    search_paths = []

    aipass_root = os.environ.get("AIPASS_ROOT", "")
    if aipass_root:
        search_paths.append(Path(aipass_root) / "AIPASS_REGISTRY.json")

    # module_file(): with an unreadable cwd a bare resolve raises OSError.
    current = module_file(__file__).parent
    for _ in range(10):
        candidate = current / "AIPASS_REGISTRY.json"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent

    search_paths.extend(
        [
            Path.home() / ".aipass" / "AIPASS_REGISTRY.json",
            Path.home() / "AIPASS_REGISTRY.json",
        ]
    )

    for path in search_paths:
        if path.exists():
            return path

    return None


if __name__ == "__main__":
    print("Initializing The Commons database...")
    connection = init_db()
    cursor = connection.execute("SELECT COUNT(*) FROM agents")
    agent_count = cursor.fetchone()[0]
    cursor = connection.execute("SELECT COUNT(*) FROM rooms")
    room_count = cursor.fetchone()[0]
    print(f"Database ready at: {DB_PATH}")
    print(f"  Agents registered: {agent_count}")
    print(f"  Rooms created: {room_count}")
    close_db(connection)
