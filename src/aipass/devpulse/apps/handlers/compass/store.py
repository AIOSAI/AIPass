# =================== AIPass ====================
# Name: store.py
# Description: Compass storage core — SQLite/FTS5 rated decision store
# Version: 1.0.0
# Created: 2026-06-16
# Modified: 2026-06-16
# =============================================

"""Compass storage core — the SQLite/FTS5 layer for rated decisions.

Compass holds short, *rated* decisions (``good | bad | impressive |
interesting``). The rating is the signal: repeat the good, avoid the bad.
This is deliberately separate from the @memory vector store — compass is
truth (curated), @memory is story (ingest-all). See DPLAN-0212.

Storage is one SQLite file with a ``decisions`` table and an FTS5 virtual
table (``decisions_fts``) mirroring ``context, decision, note, tags``. Search
ranks by FTS5 BM25 relevance. Stdlib ``sqlite3`` only — no embeddings, no
ChromaDB, no extra dependencies. FTS5 is compiled into standard CPython's
sqlite3; availability is verified at runtime and a clear error is raised if
it is missing.

Every public function accepts an optional ``db_path`` so tests can point at a
temp file. The default path is resolved relative to the branch root via
``Path(__file__)`` parents — never a hardcoded absolute path.

This module is the storage core ONLY (FPLAN P1). The drone command, slash
command, and maintenance UX are later phases.
"""

import logging
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

# Prefer the prax system logger so compass logs land with the rest of the
# ecosystem; fall back to stdlib logging if prax is unavailable in this
# context (e.g. an isolated test run). Verified working at build time —
# prax import is clean here, so this is the active path.
try:
    from aipass.prax.apps.modules.logger import system_logger as logger
except Exception as _prax_exc:  # pragma: no cover - defensive fallback only
    logger = logging.getLogger("aipass.devpulse.compass")
    logger.info("[compass] prax logger unavailable, using stdlib logging: %s", _prax_exc)

from aipass.devpulse.apps.handlers.json import json_handler
from aipass.devpulse.apps.handlers.module_root import module_file

# Branch-root-relative default DB path. store.py lives at
# <branch_root>/apps/handlers/compass/store.py, so parents[3] is the branch
# root. NEVER hardcode an absolute /home/... path here.
_BRANCH_ROOT = module_file(__file__).parents[3]
DEFAULT_DB_PATH = _BRANCH_ROOT / "devpulse_json" / "compass" / "compass.db"

VALID_RATINGS = ("good", "bad", "impressive", "interesting")
VALID_SOURCES = ("devpulse", "user")
VALID_STATUSES = ("active", "archived")

# Columns we return / surface from the decisions table (everything useful).
# NOTE: ``score`` is deliberately absent — it is code-invisible (DPLAN-0246
# seedgo ruling). The column stays physically on disk as inert NULL, but no
# Python surface (SELECTs, returned dicts) touches it.
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
    """Raise a clear error if FTS5 is not compiled into this sqlite3.

    FTS5 ships with standard CPython, but we never assume — a missing module
    must fail loudly, not silently degrade search.
    """
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS _fts5_probe")
    except sqlite3.OperationalError as exc:
        raise RuntimeError(
            "Compass requires SQLite FTS5, which is not available in this "
            "Python's sqlite3 build. Compass cannot operate without it."
        ) from exc


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply idempotent schema migrations to an already-open DB.

    Adds the ``supersedes`` column to DBs created before it existed. Guarded by
    a ``PRAGMA table_info`` pre-check so it is safe to run on every connect —
    never a blind ``ALTER`` (DPLAN-0246 seedgo ruling: idempotent migration).
    Fresh DBs already carry the column from ``_SCHEMA``; the pre-check makes
    this a no-op for them.
    """
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(decisions)")}
    if "supersedes" not in cols:
        conn.execute("ALTER TABLE decisions ADD COLUMN supersedes INTEGER")
        conn.commit()
        logger.info("[compass] migration: added supersedes column")


# FTS5 MATCH treats characters like " * ( ) : - ^ and the words AND/OR/NOT as
# syntax. Untrusted text (a decision's own words) can therefore crash MATCH.
# We defuse it by extracting bare word tokens and OR-ing them as quoted string
# literals — no operator can survive, and quoting a bareword is exact.
_FTS_WORD = re.compile(r"\w+", re.UNICODE)


def _sanitize_fts_query(text: Optional[str]) -> Optional[str]:
    """Turn arbitrary text into a safe FTS5 MATCH expression, or None.

    Returns an ``OR`` of the text's word tokens, each quoted as a string
    literal so FTS5 syntax characters can never reach the parser. Returns None
    when there are no usable tokens (caller should skip the search).
    """
    tokens = _FTS_WORD.findall(text or "")
    if not tokens:
        return None
    return " OR ".join(f'"{t}"' for t in tokens)


def _resolve_db_path(db_path: Optional[Path | str]) -> Path:
    """Resolve the effective DB path, defaulting to the branch-root location."""
    return Path(db_path) if db_path is not None else DEFAULT_DB_PATH


def _connect(db_path: Optional[Path | str]) -> sqlite3.Connection:
    """Open (and lazily initialise) the compass DB.

    Creates parent directories on first use, verifies FTS5, ensures schema, and
    runs idempotent migrations. Rows come back as ``sqlite3.Row`` so we can
    build clean dicts.
    """
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

    Args:
        context: Short description of the situation / the fork.
        decision: Short description of what was chosen.
        rating: One of ``good | bad | impressive | interesting``.
        note: Optional human observation.
        tags: Optional comma-separated tags.
        source: ``devpulse`` or ``user`` (default ``devpulse``).
        db_path: Optional DB path override (tests pass a temp path).
        created: Optional ISO date override; defaults to today. This is the
            ONLY place a "today" date is stamped.
        supersedes: Optional id of the decision this entry corrects. When set,
            the new entry links to it AND that entry is archived — atomically,
            in one transaction. Errors cleanly (no write) if the id is unknown.

    Returns:
        The new row's integer id.

    Raises:
        ValueError: On empty context/decision, invalid rating/source, or a
            ``supersedes`` target that does not exist.
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
        # Validate the supersede target BEFORE any write so a bad id never
        # leaves a partial insert behind.
        if supersedes is not None:
            target = conn.execute("SELECT 1 FROM decisions WHERE id = ?", (supersedes,)).fetchone()
            if target is None:
                raise ValueError(f"cannot supersede #{supersedes}: no decision with that id")

        # Insert + archive-the-target in ONE transaction (commit once at the
        # end); any failure rolls the whole thing back — never half-applied.
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

    Increments ``times_surfaced`` for every returned row. Each result dict
    carries a computed ``superseded_by`` field: the id of the row that
    supersedes this one, or None. Combined with the ``supersedes`` column this
    lets callers render both pointer directions.

    Args:
        query: FTS5 match query (keywords).
        rating: Optional exact rating filter (one of VALID_RATINGS).
        limit: Max rows to return (default 5).
        include_archived: When True, lift the ``status = 'active'`` filter so
            archived rows (the avoid-list) are searchable too. Default False —
            unchanged active-only behaviour.
        db_path: Optional DB path override.

    Returns:
        A list of decision dicts (most relevant first). Each dict includes the
        rating, all useful fields, and the computed ``superseded_by`` pointer.

    Raises:
        ValueError: On empty query, bad rating filter, or non-positive limit.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    if rating is not None and rating not in VALID_RATINGS:
        raise ValueError(f"rating filter must be one of {VALID_RATINGS}, got {rating!r}")
    if limit <= 0:
        raise ValueError(f"limit must be a positive integer, got {limit!r}")

    select_cols = ", ".join(f"d.{c}" for c in _DECISION_COLUMNS)
    sql = f"""
        SELECT {select_cols}
        FROM decisions_fts f
        JOIN decisions d ON d.id = f.rowid
        WHERE decisions_fts MATCH ?
    """
    params: list = [query.strip()]
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
            # Reverse-lookup: which returned rows are pointed AT by a superseder?
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
            # Reflect the increment + attach the reverse pointer without re-query.
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
    """Return ACTIVE decisions whose text overlaps a would-be new entry.

    A write-time, side-effect-free advisory helper: it does NOT increment
    ``times_surfaced`` and never writes. The combined ``context + decision``
    text is sanitised (:func:`_sanitize_fts_query`) so no FTS5 syntax character
    can crash the MATCH. Returns up to ``limit`` active hits by BM25 relevance,
    or an empty list when the text has no usable tokens / nothing overlaps.

    Args:
        context: The would-be new entry's context.
        decision: The would-be new entry's decision.
        limit: Max advisory hits to return (default 3).
        db_path: Optional DB path override.

    Returns:
        A list of active decision dicts (most relevant first), possibly empty.
    """
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
    """Set (replace) the note on an existing decision.

    The FTS5 external-content ``decisions_au`` trigger re-indexes the row on
    UPDATE, so the new note is immediately searchable.

    Args:
        decision_id: Target decision id.
        note: The note text to store (may be empty to clear).
        db_path: Optional DB path override.

    Returns:
        True if a row was updated, False if no such id.
    """
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
    """Return decision counts by rating, by status, and the total.

    Returns:
        ``{"total": int, "by_rating": {...}, "by_status": {...}}`` where each
        valid rating/status key is always present (zero when none).
    """
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
    """Change the rating of an existing decision.

    Args:
        decision_id: Target decision id.
        rating: New rating (one of VALID_RATINGS).
        db_path: Optional DB path override.

    Returns:
        True if a row was updated, False if no such id.

    Raises:
        ValueError: On invalid rating.
    """
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
    """Archive a decision (sets ``status='archived'``).

    Archived rows drop out of ``query_decisions`` and ``review`` but are never
    deleted — bad decisions are kept on purpose as an avoid-list.

    Args:
        decision_id: Target decision id.
        db_path: Optional DB path override.

    Returns:
        True if a row was updated, False if no such id.
    """
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
    """Surface ONE active decision to review and stamp ``last_reviewed``.

    Selection prefers the oldest ``last_reviewed`` (NULL/never-reviewed first);
    among ties it picks randomly. The chosen row's ``last_reviewed`` is stamped
    before returning.

    Args:
        db_path: Optional DB path override.
        reviewed_on: Optional ISO date override for the stamp; defaults to today.

    Returns:
        The reviewed decision dict (with the fresh ``last_reviewed`` stamp), or
        None if there are no active decisions.
    """
    stamp = reviewed_on if reviewed_on is not None else date.today().isoformat()

    conn = _connect(db_path)
    try:
        # NULLs first, then oldest reviewed; random() breaks ties (and orders
        # within the all-NULL group, satisfying "else random").
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


# Ambient recall caps the OR-expansion of a raw prompt: beyond this many unique
# tokens the extra words add noise, not recall, and the MATCH string balloons.
_RECALL_MAX_TOKENS = 64

# Stopwords never reach the MATCH: in an OR-of-tokens query, high-frequency
# filler ("lets keep working on the...") outweighs topic words in BM25 and
# surfaces unrelated entries — proven live in the FPLAN-0332 acceptance run.
# Three categories, all query-side only (entry text is never filtered):
# grammatical stopwords; conversational filler verbs that open most prompts
# ("lets keep working on / need to fix"); greeting/small-talk words ("good
# morning", "how did it go last night"). In a technical store casual words are
# RARE (df 1-2), so rarity scoring alone cannot reject them — they must never
# become query tokens at all. The topic space is open; this filler set is
# closed and small, which is why filtering here works.
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

    The Track 2 read path (DPLAN-0246): a hooks handler passes the raw user
    prompt; governance (@memory's ``should_surface``) judges the candidates.
    Side-effect-free — ``times_surfaced`` is NOT incremented here, because a
    candidate is not yet surfaced; the caller reports actual injections via
    :func:`mark_surfaced` so the counter stays honest.

    The prompt is arbitrary text, never FTS5 syntax: unique word tokens (first
    ``_RECALL_MAX_TOKENS``) are OR-ed as quoted literals, ACTIVE rows only,
    ranked by BM25. Each result dict carries ``relevance`` — the BM25 magnitude
    mapped to (0, 1) via ``m / (1 + m)``, higher = more relevant — so
    governance thresholds live on a bounded scale.

    Args:
        prompt_text: Raw prompt text (any content, any length).
        limit: Max candidates to return (default 3).
        db_path: Optional DB path override.

    Returns:
        A list of active decision dicts (most relevant first), each with a
        ``relevance`` float in (0, 1); empty when the prompt has no usable
        tokens or nothing matches.

    Raises:
        ValueError: On non-positive limit.
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
        # Over-fetch: rare-token scoring below reorders, so BM25's top-N alone
        # would let a filler-heavy row crowd out a topical one.
        rows = conn.execute(sql, (match, max(limit * 3, 10))).fetchall()

        # Rarity cutoff: a token is evidence only if few entries contain it.
        active_total = conn.execute("SELECT count(*) FROM decisions WHERE status = 'active'").fetchone()[0]
        rare_cutoff = max(3, active_total // 10)

        # Document frequency per prompt token, ONE query against the FTS index.
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
            # Rare-token evidence: how many DISTINCTIVE prompt words this entry
            # actually contains. Filler matches score zero — an entry with no
            # rare-token overlap must not surface (FPLAN-0332 acceptance: a
            # haiku prompt surfaced an unrelated ruling on BM25 alone).
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
    """Increment ``times_surfaced`` for decisions actually injected.

    The write half of the recall contract: :func:`recall_decisions` returns
    candidates without side effects; whatever governance approves and the
    caller truly injects gets counted here — never the merely-considered.

    Args:
        decision_ids: Ids of the decisions that were injected.
        db_path: Optional DB path override.

    Returns:
        Number of rows updated (0 for an empty list).
    """
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
