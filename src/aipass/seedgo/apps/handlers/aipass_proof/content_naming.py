# =================== AIPass ====================
# Name: content_naming.py
# Description: Verify content file naming convention (get_{name}_standards)
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-10-17
# =============================================

"""Content Naming Proof -- Verify every *_content.py has correctly named get_{name}_standards()."""

from __future__ import annotations

import ast
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import SOURCE_SKIP_DIRS

_SKIP_DIRS = SOURCE_SKIP_DIRS


def _parse_public_functions(file_path: Path) -> list[str]:
    """Parse a Python file and return module-level public function names."""
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))
    return [
        node.name
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    ]


def scan(pack_dir: Path) -> dict:
    """Scan all *_content.py files and verify naming conventions."""
    logger.info(f"[content_naming] Scanning {pack_dir}")

    correct: list[str] = []
    incorrect: list[str] = []
    issues: list[dict[str, str | list[str]]] = []

    if not pack_dir.is_dir():
        return {
            "passed": True,
            "total": 0,
            "correct": [],
            "incorrect": [],
            "issues": [{"file": str(pack_dir), "issue": "Directory does not exist"}],
            "summary": "0 content files (directory missing)",
        }

    for content_file in sorted(pack_dir.glob("*_content.py")):
        if any(part in _SKIP_DIRS for part in content_file.relative_to(pack_dir).parts):
            continue

        if content_file.name.startswith("_"):
            continue

        stem = content_file.stem.removesuffix("_content")
        expected_fn = f"get_{stem}_standards"

        try:
            public_fns = _parse_public_functions(content_file)
        except SyntaxError as exc:
            logger.info("Skipped %s: SyntaxError during parse", content_file.name)
            incorrect.append(content_file.name)
            issues.append(
                {
                    "file": content_file.name,
                    "expected": expected_fn,
                    "issue": f"SyntaxError: {exc}",
                }
            )
            continue

        if expected_fn in public_fns:
            correct.append(content_file.name)
        else:
            incorrect.append(content_file.name)
            issues.append(
                {
                    "file": content_file.name,
                    "expected": expected_fn,
                    "found_functions": public_fns,
                    "issue": f"Missing expected function {expected_fn}()",
                }
            )

    total = len(correct) + len(incorrect)
    passed = len(incorrect) == 0

    parts = [f"{len(correct)} correct"]
    if incorrect:
        parts.append(f"{len(incorrect)} incorrect")
    parts.append(f"{total} total")
    summary = " | ".join(parts)

    logger.info(f"[content_naming] Result: {summary}")

    json_handler.log_operation("proof_scan", {"proof": "content_naming", "passed": passed})

    return {
        "passed": passed,
        "total": total,
        "correct": correct,
        "incorrect": incorrect,
        "issues": issues,
        "summary": summary,
    }
