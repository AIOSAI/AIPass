# =================== AIPass ====================
# Name: search_queries.py
# Description: FTS5 Search Query Handlers
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
FTS5 Search Query Handlers

Full-text search using SQLite FTS5 for posts and comments.
Provides search, filtering, and FTS index sync functions.
"""

import sqlite3
from typing import List, Dict, Any, Optional

from aipass.commons.apps.handlers.json import json_handler


def _quote_fts5_query(query: str) -> str:
    """
    Turn a raw user query into a literal-text FTS5 MATCH expression.

    FTS5 parses the string handed to MATCH as its own query language, not as
    plain text: a hyphen reads as a column-NOT operator, `"` starts a quoted
    phrase, `*`/`^`/`(`/`)` are prefix/NEAR/grouping operators, etc. Since
    docs/search.md promises citizens only `search "query"` -> full-text
    search, with no operator syntax, any of those characters in an ordinary
    search term (a plan ID like "FPLAN-0593", a hyphenated name, a quoted
    phrase) previously caused a raw fts5 syntax error instead of a match.

    This wraps each whitespace-separated token in double quotes, doubling any
    embedded double-quote first (the FTS5 escaping rule for a literal quote
    inside a quoted string), so every token is read as a literal phrase.
    Multiple tokens stay an implicit AND of quoted phrases, preserving the
    existing multi-word search behaviour.

    Args:
        query: Raw user-entered search text.

    Returns:
        An FTS5 MATCH expression that matches the query as literal text.
    """
    tokens = query.split()
    return " ".join('"' + token.replace('"', '""') + '"' for token in tokens)


def search_posts(
    conn: sqlite3.Connection,
    query: str,
    room: Optional[str] = None,
    author: Optional[str] = None,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """
    Search posts using FTS5 full-text index.

    Args:
        conn: Database connection.
        query: Search query string (literal text; internally quoted into
            FTS5 phrase tokens, so no FTS5 operator syntax is honored).
        room: Optional room name filter.
        author: Optional author name filter.
        limit: Maximum results to return.

    Returns:
        List of dicts with post search results.
    """
    sql = """
        SELECT p.id, p.title, substr(p.content, 1, 200) AS content_snippet,
               p.author, p.room_name, p.vote_score, p.created_at
        FROM posts_fts fts
        JOIN posts p ON fts.rowid = p.id
        WHERE posts_fts MATCH ?
    """
    params: List[Any] = [_quote_fts5_query(query)]

    if room:
        sql += " AND p.room_name = ?"
        params.append(room)
    if author:
        sql += " AND p.author = ?"
        params.append(author)

    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def search_comments(
    conn: sqlite3.Connection,
    query: str,
    author: Optional[str] = None,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """
    Search comments using FTS5 full-text index.

    Args:
        conn: Database connection.
        query: Search query string (literal text; internally quoted into
            FTS5 phrase tokens, so no FTS5 operator syntax is honored).
        author: Optional author name filter.
        limit: Maximum results to return.

    Returns:
        List of dicts with comment search results.
    """
    sql = """
        SELECT c.id, substr(c.content, 1, 200) AS content_snippet,
               c.author, c.post_id, p.title AS post_title,
               c.vote_score, c.created_at
        FROM comments_fts fts
        JOIN comments c ON fts.rowid = c.id
        JOIN posts p ON c.post_id = p.id
        WHERE comments_fts MATCH ?
    """
    params: List[Any] = [_quote_fts5_query(query)]

    if author:
        sql += " AND c.author = ?"
        params.append(author)

    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def search_all(
    conn: sqlite3.Connection,
    query: str,
    room: Optional[str] = None,
    author: Optional[str] = None,
    limit: int = 25,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Search both posts and comments, returning combined results.

    Args:
        conn: Database connection.
        query: Search query string (literal text; internally quoted into
            FTS5 phrase tokens, so no FTS5 operator syntax is honored).
        room: Optional room name filter (posts only).
        author: Optional author name filter.
        limit: Maximum results per category.

    Returns:
        Dict with "posts" and "comments" lists.
    """
    posts = search_posts(conn, query, room=room, author=author, limit=limit)
    comments = search_comments(conn, query, author=author, limit=limit)
    json_handler.log_operation(
        "fts_search_all", {"query": query, "posts_found": len(posts), "comments_found": len(comments)}
    )
    return {"posts": posts, "comments": comments}


def sync_post_to_fts(
    conn: sqlite3.Connection,
    post_id: int,
    title: str,
    content: str,
    author: str,
    room_name: str,
) -> None:
    """
    Insert or update a single post in the FTS index.

    Args:
        conn: Database connection.
        post_id: Post ID (rowid in FTS table).
        title: Post title.
        content: Post content.
        author: Post author.
        room_name: Room the post belongs to.
    """
    conn.execute(
        "INSERT OR REPLACE INTO posts_fts(rowid, title, content, author, room_name) VALUES (?, ?, ?, ?, ?)",
        (post_id, title, content, author, room_name),
    )


def sync_comment_to_fts(
    conn: sqlite3.Connection,
    comment_id: int,
    content: str,
    author: str,
) -> None:
    """
    Insert or update a single comment in the FTS index.

    Args:
        conn: Database connection.
        comment_id: Comment ID (rowid in FTS table).
        content: Comment content.
        author: Comment author.
    """
    conn.execute(
        "INSERT OR REPLACE INTO comments_fts(rowid, content, author) VALUES (?, ?, ?)",
        (comment_id, content, author),
    )


def backfill_fts_index(conn: sqlite3.Connection) -> Dict[str, int]:
    """
    Backfill the FTS5 index with all existing posts and comments.

    Intended to be run once to populate the index for content created
    before FTS sync was wired into create_post/add_comment.

    Uses INSERT OR REPLACE so it is safe to run multiple times.

    Args:
        conn: Active database connection.

    Returns:
        Dict with counts: {"posts_indexed": int, "comments_indexed": int}
    """
    # --- Backfill posts ---
    post_rows = conn.execute("SELECT id, title, content, author, room_name FROM posts").fetchall()

    for row in post_rows:
        conn.execute(
            "INSERT OR REPLACE INTO posts_fts(rowid, title, content, author, room_name) VALUES (?, ?, ?, ?, ?)",
            (row["id"], row["title"], row["content"], row["author"], row["room_name"]),
        )

    # --- Backfill comments ---
    comment_rows = conn.execute("SELECT id, content, author FROM comments").fetchall()

    for row in comment_rows:
        conn.execute(
            "INSERT OR REPLACE INTO comments_fts(rowid, content, author) VALUES (?, ?, ?)",
            (row["id"], row["content"], row["author"]),
        )

    conn.commit()

    return {
        "posts_indexed": len(post_rows),
        "comments_indexed": len(comment_rows),
    }
