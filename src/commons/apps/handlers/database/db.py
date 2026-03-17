# =================== AIPass ====================
# Name: db.py
# Description: The Commons SQLite connection manager
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
The Commons - SQLite Connection Manager

Handles database initialization, connection lifecycle,
and schema bootstrapping for The Commons social network.

Pure sqlite3 stdlib - no external dependencies.

Database location: {AIPASS_ROOT}/.aipass/commons.db
where AIPASS_ROOT comes from environment variable or defaults to ~/.aipass/
"""

import os
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional, TypeVar, Callable

from aipass.prax.apps.modules.logger import system_logger as logger
from commons.apps.handlers.json import json_handler

# =============================================================================
# DATABASE PATHS
# =============================================================================

def _get_db_path() -> Path:
    """
    Resolve the database file path.

    Uses AIPASS_ROOT environment variable if set, otherwise defaults
    to ~/.aipass/. Database stored at {root}/.aipass/commons.db.

    Returns:
        Path to the commons.db file.
    """
    aipass_root = os.environ.get("AIPASS_ROOT", "")
    if aipass_root:
        root = Path(aipass_root) / ".aipass"
    else:
        root = Path.home() / ".aipass"
    return root / "commons.db"


DB_PATH = _get_db_path()
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Retry configuration for locked-database scenarios
_RETRY_DELAYS = (0.1, 0.5, 2.0)  # exponential backoff: 3 retries

T = TypeVar("T")


# =============================================================================
# RETRY LOGIC
# =============================================================================

def retry_on_locked(fn: Callable[..., T], *args, **kwargs) -> T:
    """
    Retry wrapper for database operations that may hit "database is locked".

    Catches sqlite3.OperationalError with "database is locked" message and
    retries with exponential backoff (0.1s, 0.5s, 2.0s).

    Args:
        fn: The callable to execute.
        *args: Positional arguments forwarded to fn.
        **kwargs: Keyword arguments forwarded to fn.

    Returns:
        The return value of fn.

    Raises:
        sqlite3.OperationalError: If all retries are exhausted.
    """
    last_err: Optional[sqlite3.OperationalError] = None
    for delay in (*_RETRY_DELAYS, None):
        try:
            return fn(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc):
                raise
            last_err = exc
            if delay is None:
                break
            time.sleep(delay)
    raise last_err  # type: ignore[misc]


# =============================================================================
# CONNECTION MANAGEMENT
# =============================================================================

def get_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Open a connection to the Commons database.

    Returns a connection with row_factory set to sqlite3.Row
    so results behave like dicts. Uses a 30-second busy timeout
    and retries with exponential backoff on "database is locked".

    Args:
        db_path: Override database file path (useful for testing).

    Returns:
        sqlite3.Connection with Row factory and foreign keys enabled.
    """
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    def _connect() -> sqlite3.Connection:
        conn = sqlite3.connect(str(path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    return retry_on_locked(_connect)


def close_db(conn: sqlite3.Connection) -> None:
    """
    Close a database connection safely.

    Args:
        conn: The connection to close.
    """
    if conn:
        conn.close()


# =============================================================================
# DATABASE INITIALIZATION
# =============================================================================

def init_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Initialize the database: create tables from flattened schema.sql,
    seed default rooms, secret rooms, and room personalities.

    The schema is fully flattened - no migrations needed. All 16 tables
    are created via CREATE IF NOT EXISTS in a single schema file.

    Args:
        db_path: Override database file path (useful for testing).

    Returns:
        sqlite3.Connection to the initialized database.
    """
    conn = get_db(db_path)

    # Load and execute flattened schema
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)

    # Seed default rooms
    _seed_default_rooms(conn)

    # Seed room personalities
    _seed_room_personalities(conn)

    # Seed secret rooms
    _seed_secret_rooms(conn)

    # Auto-register branches from BRANCH_REGISTRY
    _register_branches(conn)

    logger.info("[commons.db] Database initialized successfully")
    json_handler.log_operation("db_init", {"db_path": str(db_path or DB_PATH), "success": True})
    return conn


# =============================================================================
# SEED DATA
# =============================================================================

def _seed_default_rooms(conn: sqlite3.Connection) -> None:
    """
    Create default rooms if they don't exist.

    The Commons starts with five rooms:
    - general: main gathering space
    - dev: development discussions
    - watercooler: casual, off-topic chat
    - announcements: system-wide announcements
    - ideas: brainstorming and proposals
    """
    default_rooms = [
        ("general", "General", "Main gathering space for all branches", "SYSTEM"),
        ("dev", "Dev", "Development discussions, code reviews, technical topics", "SYSTEM"),
        ("watercooler", "Watercooler", "Casual chat, random thoughts, off-topic", "SYSTEM"),
        ("announcements", "Announcements", "System-wide announcements and updates", "SYSTEM"),
        ("ideas", "Ideas", "Brainstorming, proposals, and feature requests", "SYSTEM"),
    ]

    # Ensure SYSTEM agent exists as the room creator
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name, description) "
        "VALUES (?, ?, ?)",
        ("SYSTEM", "System", "The Commons system account"),
    )

    for name, display_name, description, created_by in default_rooms:
        conn.execute(
            "INSERT OR IGNORE INTO rooms (name, display_name, description, created_by) "
            "VALUES (?, ?, ?, ?)",
            (name, display_name, description, created_by),
        )

    conn.commit()


def _seed_room_personalities(conn: sqlite3.Connection) -> None:
    """
    Set default personality data for built-in rooms.

    Only updates rooms that still have default/empty personality values
    so manual customizations are preserved.
    """
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
        # Only update if mood is still 'neutral' (default) or empty
        row = conn.execute(
            "SELECT mood FROM rooms WHERE name = ?", (room_name,)
        ).fetchone()

        if row and (not row["mood"] or row["mood"] == "neutral"):
            conn.execute(
                "UPDATE rooms SET mood = ?, flavor_text = ?, entrance_message = ? WHERE name = ?",
                (personality["mood"], personality["flavor_text"],
                 personality["entrance_message"], room_name),
            )

    conn.commit()


def _seed_secret_rooms(conn: sqlite3.Connection) -> None:
    """
    Seed secret (hidden) rooms if they don't already exist.

    These rooms are discoverable through the 'explore' command
    and don't show up in normal room listings.
    """
    secret_rooms = [
        ("the-void", "The Void", "Where deleted thoughts echo",
         "Look beyond what's listed", "SYSTEM"),
        ("glitch-garden", "Glitch Garden", "Where beautiful failures bloom",
         "Errors have their own beauty", "SYSTEM"),
        ("time-capsule-vault", "Time Capsule Vault", "Sealed messages await their moment",
         "Some things need patience", "SYSTEM"),
    ]

    for name, display_name, description, hint, created_by in secret_rooms:
        existing = conn.execute(
            "SELECT name FROM rooms WHERE name = ?", (name,)
        ).fetchone()

        if not existing:
            conn.execute(
                "INSERT INTO rooms (name, display_name, description, created_by, hidden, discovery_hint) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (name, display_name, description, created_by, hint),
            )

    conn.commit()


def _register_branches(conn: sqlite3.Connection) -> None:
    """
    Auto-register all branches from AIPASS_REGISTRY.json as agents.

    Reads the registry and inserts any missing branches. Existing
    branches are left untouched (INSERT OR IGNORE).

    Searches for AIPASS_REGISTRY.json in standard locations:
    1. AIPASS_ROOT environment variable
    2. ~/.aipass/AIPASS_REGISTRY.json
    3. ~/AIPASS_REGISTRY.json (legacy)
    """
    registry_path = _find_branch_registry()
    if not registry_path:
        return

    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    branches = registry.get("branches", [])
    for branch in branches:
        name = branch.get("name", "")
        if not name:
            continue

        description = branch.get("description", "")
        display_name = name.replace("_", " ").title()

        conn.execute(
            "INSERT OR IGNORE INTO agents (branch_name, display_name, description) "
            "VALUES (?, ?, ?)",
            (name, display_name, description),
        )

    conn.commit()


def _find_branch_registry() -> Optional[Path]:
    """
    Locate AIPASS_REGISTRY.json by searching standard paths.

    Returns:
        Path to registry file, or None if not found.
    """
    search_paths = []

    # Check AIPASS_ROOT env var
    aipass_root = os.environ.get("AIPASS_ROOT", "")
    if aipass_root:
        search_paths.append(Path(aipass_root) / "AIPASS_REGISTRY.json")

    # Walk up from this package to find project root
    current = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = current / "AIPASS_REGISTRY.json"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Standard locations
    search_paths.extend([
        Path.home() / ".aipass" / "AIPASS_REGISTRY.json",
        Path.home() / "AIPASS_REGISTRY.json",
    ])

    for path in search_paths:
        if path.exists():
            return path

    return None


# =============================================================================
# DIRECT EXECUTION
# =============================================================================

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
