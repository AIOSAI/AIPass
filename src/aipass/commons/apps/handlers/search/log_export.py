# =================== AIPass ====================
# Name: log_export.py
# Description: Room Log Export Handler
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""
Room Log Export Handler

Used by the search module's 'log' command.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Dict, List

from aipass.commons.apps.handlers.json import json_handler


def export_room_log(
    conn: sqlite3.Connection,
    room_name: str,
    limit: int = 100,
) -> str:
    """Export a plaintext log of a room's newest `limit` posts and their comments."""
    json_handler.log_operation("log_export", {"room": room_name, "limit": limit})
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    post_rows = conn.execute(
        "SELECT id, title, content, author, vote_score, created_at "
        "FROM posts WHERE room_name = ? ORDER BY created_at DESC LIMIT ?",
        (room_name, limit),
    ).fetchall()

    lines = [
        f"=== r/{room_name} - The Commons Log ===",
        f"Exported: {now}",
        "",
    ]

    if not post_rows:
        lines.append("No posts in this room.")
        return "\n".join(lines)

    for post_row in post_rows:
        post = dict(post_row)
        date_str = post["created_at"][:10] if post["created_at"] else "unknown"
        score_str = f"+{post['vote_score']}" if post["vote_score"] >= 0 else str(post["vote_score"])

        lines.append(f'--- Post #{post["id"]}: "{post["title"]}" by {post["author"]} ({date_str}) [{score_str}] ---')
        lines.append(post["content"] or "")

        comment_rows = conn.execute(
            "SELECT id, parent_id, author, content, vote_score FROM comments WHERE post_id = ? ORDER BY created_at ASC",
            (post["id"],),
        ).fetchall()

        if comment_rows:
            comments = [dict(c) for c in comment_rows]
            comment_lines = _format_comment_tree(comments)
            lines.append("")
            lines.extend(comment_lines)

        lines.append("")

    return "\n".join(lines)


def _format_comment_tree(comments: List[Dict]) -> List[str]:
    """Format comments into an indented tree structure (by parent_id)."""
    children_map: Dict[int, List[Dict]] = {}
    top_level: List[Dict] = []

    for c in comments:
        if c["parent_id"] is None:
            top_level.append(c)
        else:
            children_map.setdefault(c["parent_id"], []).append(c)

    lines: List[str] = []

    def _render(comment: Dict, depth: int = 0) -> None:
        indent = "  " * depth
        score_str = f"+{comment['vote_score']}" if comment["vote_score"] >= 0 else str(comment["vote_score"])
        lines.append(f"  {indent}> {comment['author']}: {comment['content']} [{score_str}]")
        for child in children_map.get(comment["id"], []):
            _render(child, depth + 1)

    for c in top_level:
        _render(c)

    return lines
