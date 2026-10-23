# =================== AIPass ====================
# Name: compose.py
# Description: Release mail body — version, release URL, CHANGELOG headline, ritual
# Version: 1.0.1
# Created: 2026-09-09
# Modified: 2026-10-22
# =============================================

"""The one body every manager receives (DPLAN-0335 leg 1).

Plain text and NO BACKTICKS: the body can travel as a double-quoted shell argument, where a backtick runs a command.
"""

import re
from pathlib import Path

from aipass.prax import logger
from aipass.devpulse.apps.handlers.json import json_handler

MODULE_NAME = "release_notify"

CHANGELOG_FILENAME = "CHANGELOG.md"
RELEASE_URL = "https://github.com/AIOSAI/AIPass/releases/tag/v{version}"

HEADLINE_LINES = 8

# CHANGELOG bullets here are paragraphs, some past 4,000 characters; the mail links to the full notes.
HEADLINE_CHAR_LIMIT = 220

_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*(?:[-+][0-9A-Za-z.\-]+)?)$")
_SECTION_RE = re.compile(r"^##\s+\[")
_BULLET_RE = re.compile(r"^[-*+]\s+")
_HEADING_RE = re.compile(r"^#+\s*")


def normalize_version(raw: str) -> str:
    """Accept ``v2.8.4`` or ``2.8.4``, return the bare number, or "" when the token is not a version."""
    match = _VERSION_RE.match(raw.strip())
    if not match:
        logger.warning(f"[{MODULE_NAME}] refused version token: {raw!r}")
        return ""
    return match.group(1)


def release_url(version: str) -> str:
    """The GitHub Release URL the tag publishes to."""
    return RELEASE_URL.format(version=version)


def _clean(line: str) -> str:
    """Strip the markdown a plain-text mail cannot render, truncated at HEADLINE_CHAR_LIMIT."""
    text = _HEADING_RE.sub("", line.strip())
    text = _BULLET_RE.sub("", text)
    text = text.replace("**", "").replace("`", "").strip()
    if len(text) > HEADLINE_CHAR_LIMIT:
        text = text[:HEADLINE_CHAR_LIMIT].rstrip() + " ..."
    return text


def changelog_headline(changelog_path: Path, version: str, limit: int = HEADLINE_LINES) -> list[str]:
    """The top of the CHANGELOG section that describes this release; empty when missing or sectionless.

    The version match comes first: the topmost section is often [Unreleased], which is what has NOT shipped.
    """
    try:
        raw = changelog_path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        logger.error(f"[{MODULE_NAME}] {CHANGELOG_FILENAME} unreadable at {changelog_path}: {exc!r}")
        return []

    lines = raw.splitlines()
    starts = [index for index, line in enumerate(lines) if _SECTION_RE.match(line)]
    if not starts:
        logger.warning(f"[{MODULE_NAME}] no '## [' section in {changelog_path}")
        return []

    # A substring test reads v2.8.2 inside v2.8.24, and the newest section sits on top.
    wanted = re.compile(rf"\bv?{re.escape(version)}(?![\d.])")
    chosen = starts[0]
    for index in starts:
        if wanted.search(lines[index]):
            chosen = index
            break

    end = len(lines)
    for index in starts:
        if index > chosen:
            end = index
            break

    headline: list[str] = []
    for line in lines[chosen:end]:
        cleaned = _clean(line)
        if not cleaned or cleaned == "---":
            continue
        headline.append(cleaned)
        if len(headline) >= limit:
            break
    return headline


def compose_subject(version: str) -> str:
    """The subject line every manager sees."""
    return f"AIPass v{version} released - preview your scaffold update before applying"


def compose_body(version: str, headline: list[str]) -> str:
    """The plain-text, backtick-free mail body: what shipped, where to read it, and the ritual."""
    json_handler.log_operation("compose_body", {"version": version}, module_name=MODULE_NAME)
    parts = [
        f"AIPass v{version} is released.",
        "",
        f"Release notes: {release_url(version)}",
        "",
    ]

    if headline:
        parts.append("From the CHANGELOG:")
        parts.extend(f"  {line}" for line in headline)
    else:
        parts.append("The CHANGELOG headline could not be read on the sending machine - open the release notes above.")
    parts.append("")

    parts.extend(
        [
            "Your project scaffold does not update itself, and nothing that changes a file happens without your go.",
            "The ritual, in this order:",
            "",
            "  1. aipass doctor - run it from your project root",
            "  2. aipass init update <your project root> --dry-run - read the plan, nothing is written",
            "  3. ask the owner or devpulse with that plan - apply only on a go. Exception: a plan that",
            "     says stamp only (no file would change) needs no go - run the apply, read the receipt",
            "  4. aipass init update <your project root> - applies it and prints a receipt of what it did",
            "  5. aipass doctor again - confirms the scaffold is current",
            "",
            "Reply to devpulse if the preview shows anything you do not understand.",
        ]
    )

    body = "\n".join(parts)
    if "`" in body:
        logger.warning(f"[{MODULE_NAME}] backticks stripped from the composed body")
        body = body.replace("`", "")
    return body
