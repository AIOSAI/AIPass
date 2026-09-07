# =================== AIPass ====================
# Name: generator.py
# Description: Unified diff generation with binary detection and pattern filtering
# Version: 2.0.0
# Created: 2026-04-16
# Modified: 2026-06-12
# =============================================

"""Diff generator — unified diffs between file versions with binary detection."""

import datetime
import difflib
from pathlib import Path

from aipass.prax import logger

from ..audit import trail

DIFF_IGNORE_PATTERNS = [
    "*.pyc",
    "*.pyo",
    "*.so",
    "*.dylib",
    "*.dll",
    "*.exe",
    "*.bin",
    "*.dat",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.jpg",
    "*.jpeg",
    "*.png",
    "*.gif",
    "*.bmp",
    "*.ico",
    "*.svg",
    "*.woff",
    "*.woff2",
    "*.ttf",
    "*.eot",
    "*.mp3",
    "*.mp4",
    "*.wav",
    "*.avi",
    "*.zip",
    "*.tar",
    "*.gz",
    "*.bz2",
    "*.7z",
    "*.rar",
    "*.pdf",
    "*.doc",
    "*.docx",
    "*.xls",
    "*.xlsx",
]

DIFF_INCLUDE_PATTERNS = [
    "*.py",
    "*.js",
    "*.ts",
    "*.jsx",
    "*.tsx",
    "*.json",
    "*.yaml",
    "*.yml",
    "*.toml",
    "*.cfg",
    "*.ini",
    "*.md",
    "*.rst",
    "*.txt",
    "*.html",
    "*.css",
    "*.sh",
    "*.bash",
    "*.sql",
    "*.xml",
    "*.csv",
]


def should_create_diff(file_path: Path) -> bool:
    """Check if file should have diffs created based on patterns.

    Include patterns override ignore patterns. Default = create diff.
    """
    for pattern in DIFF_INCLUDE_PATTERNS:
        if file_path.match(pattern):
            return True
    for pattern in DIFF_IGNORE_PATTERNS:
        if file_path.match(pattern):
            return False
    return True


def is_binary_file(file_path: Path) -> bool:
    """Check if a file is likely binary (null byte in first 1KB)."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(1024)
        return b"\0" in chunk
    except Exception as e:
        logger.info(f"[diff] Could not read {file_path}, assuming binary: {e}")
        return True


def generate_diff_content(old_file: Path, new_file: Path) -> str:
    """Generate unified diff between two file versions.

    Args:
        old_file: Path to old version (store current before overwrite).
        new_file: Path to new version (source file).

    Returns:
        Unified diff string, or binary-change marker.
    """
    try:
        if is_binary_file(old_file) or is_binary_file(new_file):
            return f"Binary file {old_file.name} changed\n"

        with open(old_file, encoding="utf-8", errors="replace") as f:
            old_lines = f.readlines()
        with open(new_file, encoding="utf-8", errors="replace") as f:
            new_lines = f.readlines()

        diff_lines = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{old_file.name}",
            tofile=f"b/{new_file.name}",
            fromfiledate=datetime.datetime.fromtimestamp(old_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            tofiledate=datetime.datetime.fromtimestamp(new_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            lineterm="",
        )

        result = "\n".join(diff_lines)
        trail.log_operation("diff_generated", {"file": old_file.name})
        return result
    except Exception as e:
        logger.warning(f"[diff] Failed to generate diff: {old_file} -> {new_file}: {e}")
        return f"Error generating diff: {e}\n"


# =============================================
