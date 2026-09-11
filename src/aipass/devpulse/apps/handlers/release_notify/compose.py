# =================== AIPass ====================
# Name: compose.py
# Description: Release mail body — version, release URL, CHANGELOG headline, ritual
# Version: 1.0.0
# Created: 2026-09-09
# Modified: 2026-09-09
# =============================================

"""The one body every manager receives (DPLAN-0335 leg 1).

Plain text, no markdown, and above all NO BACKTICKS: the body travels as a
shell argument to ``drone @ai_mail email``, and a backtick in a double-quoted
bash argument is command substitution. Every command the ritual names is
therefore written bare, and :func:`compose_body` strips any backtick that
survives composition rather than trusting the writer to remember.
"""

import re
from pathlib import Path

from aipass.prax import logger
from aipass.devpulse.apps.handlers.json import json_handler

MODULE_NAME = "release_notify"

CHANGELOG_FILENAME = "CHANGELOG.md"
RELEASE_URL = "https://github.com/AIOSAI/AIPass/releases/tag/v{version}"

# Enough of the top block to say what shipped, short enough that the mail is
# still read: the section header plus the first bullets. The link carries the rest.
HEADLINE_LINES = 8

# One CHANGELOG bullet in this repo runs past 4,000 characters (the entries are
# written as paragraphs, not one-liners). A headline is a headline: the mail
# links to the full notes.
HEADLINE_CHAR_LIMIT = 220

_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*(?:[-+][0-9A-Za-z.\-]+)?)$")
_SECTION_RE = re.compile(r"^##\s+\[")
_BULLET_RE = re.compile(r"^[-*+]\s+")
_HEADING_RE = re.compile(r"^#+\s*")


def normalize_version(raw: str) -> str:
    """Accept ``v2.8.4`` or ``2.8.4``, return the bare number.

    Args:
        raw: The version as typed on the command line.

    Returns:
        The version without its leading v, or "" when the token is not a version.
    """
    match = _VERSION_RE.match(raw.strip())
    if not match:
        logger.warning(f"[{MODULE_NAME}] refused version token: {raw!r}")
        return ""
    return match.group(1)


def release_url(version: str) -> str:
    """The GitHub Release URL the tag publishes to.

    Args:
        version: A bare version number.

    Returns:
        The release URL.
    """
    return RELEASE_URL.format(version=version)


def _clean(line: str) -> str:
    """Strip the markdown a plain-text mail cannot render.

    Args:
        line: One raw CHANGELOG line.

    Returns:
        The line as prose: no heading hashes, no bullet, no bold or backtick
        markers, truncated at HEADLINE_CHAR_LIMIT.
    """
    text = _HEADING_RE.sub("", line.strip())
    text = _BULLET_RE.sub("", text)
    text = text.replace("**", "").replace("`", "").strip()
    if len(text) > HEADLINE_CHAR_LIMIT:
        text = text[:HEADLINE_CHAR_LIMIT].rstrip() + " ..."
    return text


def changelog_headline(changelog_path: Path, version: str, limit: int = HEADLINE_LINES) -> list[str]:
    """The top of the CHANGELOG section that describes this release.

    Prefers the section whose header names the version being announced, and
    falls back to the topmost ``## [`` section. The fallback is not the same
    thing: at the moment a tag goes out the top section is usually
    ``[Unreleased]``, whose contents are what has NOT shipped — so announcing
    it verbatim would describe the wrong release. When the merge train has
    already dated the section (the normal case) the version match finds it.

    Args:
        changelog_path: Path to CHANGELOG.md.
        version: The bare version being announced.
        limit: How many non-empty lines to keep, header line included.

    Returns:
        Cleaned lines, empty when the file is missing or has no section.
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

    chosen = starts[0]
    for index in starts:
        header = lines[index]
        if f"v{version}" in header or f"[{version}]" in header:
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
    """The subject line every manager sees.

    Args:
        version: The bare version being announced.

    Returns:
        The subject.
    """
    return f"AIPass v{version} released - preview your scaffold update before applying"


def compose_body(version: str, headline: list[str]) -> str:
    """The mail body: what shipped, where to read it, and the ritual.

    Args:
        version: The bare version being announced.
        headline: Cleaned CHANGELOG lines from :func:`changelog_headline`.

    Returns:
        The plain-text body, backtick-free.
    """
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
            "  3. ask Patrick or devpulse with that plan - apply only on a go. Exception: a plan that",
            "     says stamp only (no file would change) needs no go - run the apply, read the receipt",
            "  4. aipass init update <your project root> - applies it and prints a receipt of what it did",
            "  5. aipass doctor again - confirms the scaffold is current",
            "",
            "Reply to devpulse if the preview shows anything you do not understand.",
        ]
    )

    body = "\n".join(parts)
    if "`" in body:
        # Belt and braces: this body is handed to a shell as an argument, where
        # a backtick is command substitution, not punctuation.
        logger.warning(f"[{MODULE_NAME}] backticks stripped from the composed body")
        body = body.replace("`", "")
    return body
