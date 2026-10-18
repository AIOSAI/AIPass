# =================== AIPass ====================
# Name: store.py
# Description: Compass storage core — SQLite/FTS5 rated decision store
# Version: 1.0.0
# Created: 2026-06-16
# Modified: 2026-10-17
# =============================================

"""Compass storage core — the SQLite/FTS5 layer for rated decisions.

Kept apart from the @memory vector store on purpose: compass is curated truth, @memory is ingest-all story.
"""

import logging
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

try:
    from aipass.prax.apps.modules.logger import system_logger as logger
except Exception as _prax_exc:  # pragma: no cover - defensive fallback only
    logger = logging.getLogger("aipass.devpulse.compass")
    logger.info("[compass] prax logger unavailable, using stdlib logging: %s", _prax_exc)

from aipass.devpulse.apps.handlers.json import json_handler
from aipass.devpulse.apps.handlers.module_root import module_file

_BRANCH_ROOT = module_file(__file__).parents[3]
DEFAULT_DB_PATH = _BRANCH_ROOT / "devpulse_json" / "compass" / "compass.db"

VALID_RATINGS = ("good", "bad", "impressive", "interesting")
VALID_SOURCES = ("devpulse", "user")
VALID_STATUSES = ("active", "archived")

# ``score`` is absent on purpose: the column stays on disk as inert NULL and no Python surface reads it.
_DECISION_COLUMNS = (
    "id",
    "created",
    "context",
    "decision",
    "rating",
    "note",
    "tags",
    "source",
    "status",
    "last_reviewed",
    "times_surfaced",
    "supersedes",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id              INTEGER PRIMARY KEY,
    created         TEXT,
    context         TEXT NOT NULL,
    decision        TEXT NOT NULL,
    rating          TEXT NOT NULL CHECK(rating IN ('good','bad','impressive','interesting')),
    note            TEXT,
    tags            TEXT,
    source          TEXT NOT NULL DEFAULT 'devpulse',
    score           INTEGER,
    status          TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
    last_reviewed   TEXT,
    times_surfaced  INTEGER NOT NULL DEFAULT 0,
    supersedes      INTEGER
);

CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
    context,
    decision,
    note,
    tags,
    content='decisions',
    content_rowid='id'
);

-- Keep the FTS5 mirror in sync with the decisions table via triggers.
CREATE TRIGGER IF NOT EXISTS decisions_ai AFTER INSERT ON decisions BEGIN
    INSERT INTO decisions_fts(rowid, context, decision, note, tags)
    VALUES (new.id, new.context, new.decision, new.note, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS decisions_ad AFTER DELETE ON decisions BEGIN
    INSERT INTO decisions_fts(decisions_fts, rowid, context, decision, note, tags)
    VALUES ('delete', old.id, old.context, old.decision, old.note, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS decisions_au AFTER UPDATE ON decisions BEGIN
    INSERT INTO decisions_fts(decisions_fts, rowid, context, decision, note, tags)
    VALUES ('delete', old.id, old.context, old.decision, old.note, old.tags);
    INSERT INTO decisions_fts(rowid, context, decision, note, tags)
    VALUES (new.id, new.context, new.decision, new.note, new.tags);
END;
"""


def _verify_fts5(conn: sqlite3.Connection) -> None:
    """Raise a clear error if FTS5 is not compiled into this sqlite3, never degrade search silently."""
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS _fts5_probe")
    except sqlite3.OperationalError as exc:
        raise RuntimeError(
            "Compass requires SQLite FTS5, which is not available in this "
            "Python's sqlite3 build. Compass cannot operate without it."
        ) from exc


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply idempotent schema migrations to an already-open DB; runs on every connect, never a blind ALTER."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(decisions)")}
    if "supersedes" not in cols:
        conn.execute("ALTER TABLE decisions ADD COLUMN supersedes INTEGER")
        conn.commit()
        logger.info("[compass] migration: added supersedes column")


# FTS5 MATCH parses " * ( ) : - ^ and AND/OR/NOT, so untrusted text crashes it; only quoted word tokens reach MATCH.
_FTS_WORD = re.compile(r"\w+", re.UNICODE)


def _sanitize_fts_query(text: Optional[str], join: str = " OR ") -> Optional[str]:
    """Turn arbitrary text into a safe FTS5 MATCH expression, or None.

    ``" OR "`` serves the advisories (any token matches); ``" "`` is FTS5's implicit AND, the user-query contract.
    """
    tokens = _FTS_WORD.findall(text or "")
    if not tokens:
        return None
    return join.join(f'"{t}"' for t in tokens)


def _resolve_db_path(db_path: Optional[Path | str]) -> Path:
    """Resolve the effective DB path, defaulting to the branch-root location."""
    return Path(db_path) if db_path is not None else DEFAULT_DB_PATH


def _connect(db_path: Optional[Path | str]) -> sqlite3.Connection:
    """Open (and lazily initialise) the compass DB."""
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _verify_fts5(conn)
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a decisions ``sqlite3.Row`` into a plain dict of useful fields."""
    return {col: row[col] for col in _DECISION_COLUMNS}


def add_decision(
    context: str,
    decision: str,
    rating: str,
    note: Optional[str] = None,
    tags: Optional[str] = None,
    source: str = "devpulse",
    db_path: Optional[Path | str] = None,
    created: Optional[str] = None,
    supersedes: Optional[int] = None,
) -> int:
    """Add a rated decision and return its new id.

    ``supersedes`` links to the corrected entry and archives it in the same transaction; an unknown id writes nothing.
    """
    if not context or not context.strip():
        raise ValueError("context must be a non-empty string")
    if not decision or not decision.strip():
        raise ValueError("decision must be a non-empty string")
    if rating not in VALID_RATINGS:
        raise ValueError(f"rating must be one of {VALID_RATINGS}, got {rating!r}")
    if source not in VALID_SOURCES:
        raise ValueError(f"source must be one of {VALID_SOURCES}, got {source!r}")

    stamp = created if created is not None else date.today().isoformat()

    conn = _connect(db_path)
    try:
        if supersedes is not None:
            target = conn.execute("SELECT 1 FROM decisions WHERE id = ?", (supersedes,)).fetchone()
            if target is None:
                raise ValueError(f"cannot supersede #{supersedes}: no decision with that id")

        # One commit at the end: the insert and the archive land together or not at all.
        cur = conn.execute(
            """
            INSERT INTO decisions (created, context, decision, rating, note, tags, source, supersedes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (stamp, context.strip(), decision.strip(), rating, note, tags, source, supersedes),
        )
        if cur.lastrowid is None:  # pragma: no cover - sqlite always sets this on INSERT
            raise RuntimeError("compass: INSERT did not return a rowid")
        new_id = int(cur.lastrowid)

        if supersedes is not None:
            conn.execute("UPDATE decisions SET status = 'archived' WHERE id = ?", (supersedes,))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    logger.info(
        "[compass] added decision id=%s rating=%s source=%s supersedes=%s",
        new_id,
        rating,
        source,
        supersedes,
    )
    json_handler.log_operation(
        "compass_add", {"id": new_id, "rating": rating, "source": source, "supersedes": supersedes}
    )
    return new_id


def query_decisions(
    query: str,
    rating: Optional[str] = None,
    limit: int = 5,
    include_archived: bool = False,
    db_path: Optional[Path | str] = None,
) -> list[dict]:
    """Search decisions, ranked by FTS5 BM25 relevance.

    Increments ``times_surfaced`` on every returned row and attaches ``superseded_by``, the reverse pointer.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    if rating is not None and rating not in VALID_RATINGS:
        raise ValueError(f"rating filter must be one of {VALID_RATINGS}, got {rating!r}")
    if limit <= 0:
        raise ValueError(f"limit must be a positive integer, got {limit!r}")

    # Raw text in MATCH crashes the parser ("opt-in"); implicit AND keeps "old choice" meaning both words.
    match = _sanitize_fts_query(query, join=" ")
    if match is None:
        raise ValueError(f"query has no searchable words (letters, digits, underscore): {query!r}")

    select_cols = ", ".join(f"d.{c}" for c in _DECISION_COLUMNS)
    sql = f"""
        SELECT {select_cols}
        FROM decisions_fts f
        JOIN decisions d ON d.id = f.rowid
        WHERE decisions_fts MATCH ?
    """
    params: list = [match]
    if not include_archived:
        sql += " AND d.status = 'active'"
    if rating is not None:
        sql += " AND d.rating = ?"
        params.append(rating)
    sql += " ORDER BY bm25(decisions_fts) ASC LIMIT ?"
    params.append(limit)

    conn = _connect(db_path)
    try:
        rows = conn.execute(sql, params).fetchall()
        results = [_row_to_dict(r) for r in rows]
        for r in results:
            r["superseded_by"] = None
        ids = [r["id"] for r in results]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            successors: dict = {}
            for row in conn.execute(
                f"SELECT id, supersedes FROM decisions WHERE supersedes IN ({placeholders})",
                ids,
            ):
                successors[row["supersedes"]] = row["id"]
            conn.execute(
                f"UPDATE decisions SET times_surfaced = times_surfaced + 1 WHERE id IN ({placeholders})",
                ids,
            )
            conn.commit()
            for r in results:
                r["times_surfaced"] = (r["times_surfaced"] or 0) + 1
                r["superseded_by"] = successors.get(r["id"])
    finally:
        conn.close()

    logger.info(
        "[compass] query %r rating=%s include_archived=%s -> %d hit(s)",
        query,
        rating,
        include_archived,
        len(results),
    )
    return results


def find_conflicts(
    context: str,
    decision: str,
    limit: int = 3,
    db_path: Optional[Path | str] = None,
) -> list[dict]:
    """Return ACTIVE decisions whose text overlaps a would-be new entry; an advisory, it never writes."""
    match = _sanitize_fts_query(f"{context or ''} {decision or ''}")
    if match is None:
        return []

    select_cols = ", ".join(f"d.{c}" for c in _DECISION_COLUMNS)
    sql = f"""
        SELECT {select_cols}
        FROM decisions_fts f
        JOIN decisions d ON d.id = f.rowid
        WHERE decisions_fts MATCH ?
          AND d.status = 'active'
        ORDER BY bm25(decisions_fts) ASC
        LIMIT ?
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(sql, (match, limit)).fetchall()
        results = [_row_to_dict(r) for r in rows]
    finally:
        conn.close()

    logger.info("[compass] conflict-check -> %d active hit(s)", len(results))
    return results


def set_note(
    decision_id: int,
    note: Optional[str],
    db_path: Optional[Path | str] = None,
) -> bool:
    """Set (replace) the note on an existing decision; False if no such id. The update trigger re-indexes it."""
    conn = _connect(db_path)
    try:
        cur = conn.execute("UPDATE decisions SET note = ? WHERE id = ?", (note, decision_id))
        conn.commit()
        changed = cur.rowcount > 0
    finally:
        conn.close()

    logger.info("[compass] note id=%s (changed=%s)", decision_id, changed)
    json_handler.log_operation("compass_note", {"id": decision_id, "changed": changed})
    return changed


def stats(db_path: Optional[Path | str] = None) -> dict:
    """Return decision counts by rating, by status, and the total; every valid key is present."""
    conn = _connect(db_path)
    try:
        total = int(conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0])

        by_rating = {r: 0 for r in VALID_RATINGS}
        for row in conn.execute("SELECT rating, COUNT(*) AS n FROM decisions GROUP BY rating"):
            by_rating[row["rating"]] = int(row["n"])

        by_status = {s: 0 for s in VALID_STATUSES}
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM decisions GROUP BY status"):
            by_status[row["status"]] = int(row["n"])
    finally:
        conn.close()

    return {"total": total, "by_rating": by_rating, "by_status": by_status}


def rate(decision_id: int, rating: str, db_path: Optional[Path | str] = None) -> bool:
    """Change the rating of an existing decision; False if no such id."""
    if rating not in VALID_RATINGS:
        raise ValueError(f"rating must be one of {VALID_RATINGS}, got {rating!r}")

    conn = _connect(db_path)
    try:
        cur = conn.execute("UPDATE decisions SET rating = ? WHERE id = ?", (rating, decision_id))
        conn.commit()
        changed = cur.rowcount > 0
    finally:
        conn.close()

    logger.info("[compass] rate id=%s -> %s (changed=%s)", decision_id, rating, changed)
    json_handler.log_operation("compass_rate", {"id": decision_id, "rating": rating, "changed": changed})
    return changed


def archive(decision_id: int, db_path: Optional[Path | str] = None) -> bool:
    """Archive a decision, never delete it: archived rows are the avoid-list. False if no such id."""
    conn = _connect(db_path)
    try:
        cur = conn.execute("UPDATE decisions SET status = 'archived' WHERE id = ?", (decision_id,))
        conn.commit()
        changed = cur.rowcount > 0
    finally:
        conn.close()

    logger.info("[compass] archive id=%s (changed=%s)", decision_id, changed)
    json_handler.log_operation("compass_archive", {"id": decision_id, "changed": changed})
    return changed


def review(
    db_path: Optional[Path | str] = None,
    reviewed_on: Optional[str] = None,
) -> Optional[dict]:
    """Surface ONE active decision to review and stamp ``last_reviewed``; None when none is active."""
    stamp = reviewed_on if reviewed_on is not None else date.today().isoformat()

    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT * FROM decisions
            WHERE status = 'active'
            ORDER BY (last_reviewed IS NOT NULL), last_reviewed ASC, random()
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None

        decision_id = row["id"]
        conn.execute("UPDATE decisions SET last_reviewed = ? WHERE id = ?", (stamp, decision_id))
        conn.commit()

        refreshed = conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()
        result = _row_to_dict(refreshed)
    finally:
        conn.close()

    logger.info("[compass] review surfaced id=%s stamped=%s", result["id"], stamp)
    json_handler.log_operation("compass_review", {"id": result["id"], "last_reviewed": stamp})
    return result


_RECALL_MAX_TOKENS = 64

# Query-side only. Casual words are rare in a technical store, so rarity scoring cannot reject them;
# in an OR query they outweigh topic words in BM25. The filler set is closed and small; the topic space is not.
_RECALL_STOPWORDS = frozenset(
    """a an and about again also are as at back be bit but by can could did do
    does for from had has have how i if in is it its just me my no not of on
    or our so still sure than thanks thank that the their then there these
    they this to too u ur us was way we well were what when where which who
    why will with would yes you your
    add check doing done fix get go going keep lets look make need now see
    should try use want work working write
    day days good hello hey hi im ive last morning night ok okay please right
    today tomorrow tonight week yesterday""".split()
)


def recall_decisions(
    prompt_text: str,
    limit: int = 3,
    db_path: Optional[Path | str] = None,
) -> list[dict]:
    """Return scored ambient-recall candidates for raw prompt text.

    Side-effect-free: a candidate is not yet surfaced, so the caller reports injections through mark_surfaced.
    ``relevance`` is m / (1 + m) over rare matched tokens, a bounded scale for @memory's governance thresholds.
    """
    if limit <= 0:
        raise ValueError(f"limit must be a positive integer, got {limit!r}")

    tokens = _FTS_WORD.findall(prompt_text or "")
    unique: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        lowered = t.lower()
        if lowered not in seen and lowered not in _RECALL_STOPWORDS:
            seen.add(lowered)
            unique.append(t)
        if len(unique) >= _RECALL_MAX_TOKENS:
            break
    if not unique:
        return []
    match = " OR ".join(f'"{t}"' for t in unique)

    select_cols = ", ".join(f"d.{c}" for c in _DECISION_COLUMNS)
    sql = f"""
        SELECT {select_cols}, bm25(decisions_fts) AS rank,
               (d.context || ' ' || d.decision || ' ' ||
                COALESCE(d.note, '') || ' ' || COALESCE(d.tags, '')) AS _text
        FROM decisions_fts f
        JOIN decisions d ON d.id = f.rowid
        WHERE decisions_fts MATCH ?
          AND d.status = 'active'
        ORDER BY bm25(decisions_fts) ASC
        LIMIT ?
    """
    conn = _connect(db_path)
    try:
        # Over-fetch: rare-token scoring reorders, so BM25's top-N would let filler crowd out a topical row.
        rows = conn.execute(sql, (match, max(limit * 3, 10))).fetchall()

        active_total = conn.execute("SELECT count(*) FROM decisions WHERE status = 'active'").fetchone()[0]
        rare_cutoff = max(3, active_total // 10)

        df: dict[str, int] = {}
        for t in unique:
            df[t.lower()] = conn.execute(
                "SELECT count(*) FROM decisions_fts f JOIN decisions d ON d.id = f.rowid "
                "WHERE decisions_fts MATCH ? AND d.status = 'active'",
                (f'"{t}"',),
            ).fetchone()[0]

        results = []
        for row in rows:
            item = _row_to_dict(row)
            text = row["_text"].lower()
            # Filler matches score zero: an entry with no rare-token overlap must not surface on BM25 alone.
            matched_rare = sum(
                1
                for t in unique
                if df[t.lower()] <= rare_cutoff and re.search(rf"\b{re.escape(t)}", text, re.IGNORECASE)
            )
            item["relevance"] = matched_rare / (1.0 + matched_rare)
            item["_bm25"] = row["rank"]
            results.append(item)

        results.sort(key=lambda r: (-r["relevance"], r["_bm25"]))
        results = results[:limit]
        for r in results:
            del r["_bm25"]
    finally:
        conn.close()

    logger.info("[compass] recall -> %d candidate(s)", len(results))
    return results


def mark_surfaced(
    decision_ids: list[int],
    db_path: Optional[Path | str] = None,
) -> int:
    """Increment ``times_surfaced`` for decisions actually injected, never the merely-considered."""
    if not decision_ids:
        return 0

    conn = _connect(db_path)
    try:
        placeholders = ",".join("?" for _ in decision_ids)
        cur = conn.execute(
            f"UPDATE decisions SET times_surfaced = times_surfaced + 1 WHERE id IN ({placeholders})",
            list(decision_ids),
        )
        conn.commit()
        updated = cur.rowcount
    finally:
        conn.close()

    logger.info("[compass] mark_surfaced -> %d row(s)", updated)
    return updated
