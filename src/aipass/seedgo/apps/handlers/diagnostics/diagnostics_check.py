# =================== AIPass ====================
# Name: diagnostics_check.py
# Description: Diagnostics Orchestrator
# Version: 2.1.3
# Created: 2026-03-05
# Modified: 2026-10-24
# =============================================

"""
Diagnostics Orchestrator

Runs pyright over a branch's apps/ and scores the type errors it reports.
"""

import sys
import subprocess
import json
from pathlib import Path
from typing import Dict, Optional

from rich.console import Console

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.ignore_handler import audit_ignore_match
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "branch_level"


def should_ignore_file(file_path: str, branch_root: Path) -> bool:
    """Whether the audit ignore list removes file_path, read relative to its branch root like the corpus."""
    try:
        rel = Path(file_path).resolve().relative_to(branch_root.resolve()).as_posix()
    except ValueError as exc:
        logger.info("[diagnostics_check] %s not under branch root %s, kept: %s", file_path, branch_root, exc)
        return False
    return audit_ignore_match(rel) is not None


def check_file(file_path: str) -> Dict:
    """Run pyright on a single file and return its diagnostics."""
    path = Path(file_path)

    if not path.exists():
        return {
            "file": str(file_path),
            "errors": 0,
            "warnings": 0,
            "diagnostics": [],
            "error": f"File not found: {file_path}",
        }

    if not path.suffix == ".py":
        return {"file": str(file_path), "errors": 0, "warnings": 0, "diagnostics": [], "skipped": "Not a Python file"}

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pyright", "--pythonpath", sys.executable, "--outputjson", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.error("Failed to parse pyright JSON output for %s", file_path)
            return {
                "file": str(file_path),
                "errors": 1,
                "warnings": 0,
                "diagnostics": [
                    {
                        "line": 0,
                        "severity": "error",
                        "message": "Pyright failed to run — cannot parse output",
                        "rule": "",
                    }
                ],
                "error": f"Failed to parse pyright output: {result.stderr or result.stdout}",
            }

        diagnostics = []
        errors = 0
        warnings = 0

        for diag in output.get("generalDiagnostics", []):
            severity = diag.get("severity", "error")
            if severity == "error":
                errors += 1
            elif severity == "warning":
                warnings += 1

            diagnostics.append(
                {
                    "line": diag.get("range", {}).get("start", {}).get("line", 0) + 1,
                    "severity": severity,
                    "message": diag.get("message", "Unknown error"),
                    "rule": diag.get("rule", ""),
                }
            )

        return {"file": str(file_path), "errors": errors, "warnings": warnings, "diagnostics": diagnostics}

    except subprocess.TimeoutExpired:
        logger.error("Pyright timed out for %s", file_path)
        return {
            "file": str(file_path),
            "errors": 1,
            "warnings": 0,
            "diagnostics": [{"line": 0, "severity": "error", "message": "Pyright timed out", "rule": ""}],
            "error": "Pyright timed out",
        }
    except Exception as e:
        logger.error("Pyright check failed for %s: %s", file_path, e)
        return {
            "file": str(file_path),
            "errors": 1,
            "warnings": 0,
            "diagnostics": [{"line": 0, "severity": "error", "message": f"Pyright failed: {e}", "rule": ""}],
            "error": str(e),
        }


def check_directory(directory: str) -> Dict:
    """Run pyright on all Python files in a directory."""
    path = Path(directory)

    if not path.exists():
        return {
            "total_files": 0,
            "files_with_errors": 0,
            "total_errors": 0,
            "total_warnings": 0,
            "results": [],
            "error": f"Directory not found: {directory}",
        }

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pyright", "--pythonpath", sys.executable, "--outputjson", str(path)],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes for full directory
        )

        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.error("Failed to parse pyright JSON output for directory %s", directory)
            return {
                "total_files": 0,
                "files_with_errors": 1,
                "total_errors": 1,
                "total_warnings": 0,
                "results": [
                    {
                        "file": str(directory),
                        "errors": 1,
                        "warnings": 0,
                        "diagnostics": [
                            {
                                "line": 0,
                                "severity": "error",
                                "message": "Pyright failed to run — cannot parse output",
                                "rule": "",
                            }
                        ],
                    }
                ],
                "error": "Failed to parse pyright output",
            }

        # The directory is a branch's apps/: the ignore list reads branch-relative paths.
        branch_root = path.parent

        file_diagnostics = {}

        for diag in output.get("generalDiagnostics", []):
            file_path = diag.get("file", "unknown")

            if should_ignore_file(file_path, branch_root):
                continue
            if file_path not in file_diagnostics:
                file_diagnostics[file_path] = {"file": file_path, "errors": 0, "warnings": 0, "diagnostics": []}

            severity = diag.get("severity", "error")
            if severity == "error":
                file_diagnostics[file_path]["errors"] += 1
            elif severity == "warning":
                file_diagnostics[file_path]["warnings"] += 1

            file_diagnostics[file_path]["diagnostics"].append(
                {
                    "line": diag.get("range", {}).get("start", {}).get("line", 0) + 1,
                    "severity": severity,
                    "message": diag.get("message", "Unknown error"),
                    "rule": diag.get("rule", ""),
                }
            )

        results = list(file_diagnostics.values())
        total_errors = sum(r["errors"] for r in results)
        total_warnings = sum(r["warnings"] for r in results)
        files_with_errors = len([r for r in results if r["errors"] > 0])

        return {
            "total_files": output.get("summary", {}).get("filesAnalyzed", 0),
            "files_with_errors": files_with_errors,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "results": sorted(results, key=lambda x: x["errors"], reverse=True),
        }

    except subprocess.TimeoutExpired:
        logger.error("Pyright timed out for directory %s", directory)
        return {
            "total_files": 0,
            "files_with_errors": 1,
            "total_errors": 1,
            "total_warnings": 0,
            "results": [
                {
                    "file": str(directory),
                    "errors": 1,
                    "warnings": 0,
                    "diagnostics": [{"line": 0, "severity": "error", "message": "Pyright timed out", "rule": ""}],
                }
            ],
            "error": "Pyright timed out (directory too large?)",
        }
    except Exception as e:
        logger.error("Pyright directory check failed for %s: %s", directory, e)
        return {
            "total_files": 0,
            "files_with_errors": 1,
            "total_errors": 1,
            "total_warnings": 0,
            "results": [
                {
                    "file": str(directory),
                    "errors": 1,
                    "warnings": 0,
                    "diagnostics": [{"line": 0, "severity": "error", "message": f"Pyright failed: {e}", "rule": ""}],
                }
            ],
            "error": str(e),
        }


def check_branch(branch_path: str, bypass_rules: Optional[list] = None) -> Dict:
    """Run pyright on a branch's apps/ and score its type errors."""
    apps_path = Path(branch_path) / "apps"

    if not apps_path.exists():
        return {
            "passed": True,
            "score": 100,
            "total_files": 0,
            "total_errors": 0,
            "checks": [],
            "standard": "DIAGNOSTICS",
            "error": f"No apps/ directory found in {branch_path}",
        }

    result = check_directory(str(apps_path))
    total_errors = result.get("total_errors", 0)
    total_warnings = result.get("total_warnings", 0)
    total_files = result.get("total_files", 0)
    all_results = result.get("results", [])

    merged_checks = [
        {
            "name": f"Type errors in {Path(file_result['file']).name}",
            "passed": False,
            "message": f"{file_result['errors']} errors",
        }
        for file_result in all_results
        if file_result["errors"] > 0
    ]

    if not merged_checks:
        merged_checks.append(
            {"name": "Type check", "passed": True, "message": f"No type errors ({total_files} files analyzed)"}
        )

    score = 100 if total_errors == 0 else max(0, 100 - (total_errors * 5))

    json_handler.log_operation("diagnostics_run", {"branch": branch_path, "total_errors": total_errors})
    return {
        "passed": total_errors == 0,
        "score": score,
        "total_files": total_files,
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "files_with_errors": len([r for r in all_results if r.get("errors", 0) > 0]),
        "checks": merged_checks,
        "results": all_results,
        "standard": "DIAGNOSTICS",
    }


def format_summary(results: Dict) -> str:
    """Format results as a summary string; tests are its only caller."""
    if "error" in results and results["error"]:
        return f"Error: {results['error']}"

    lines = []
    lines.append(f"Files analyzed: {results['total_files']}")
    lines.append(f"Files with errors: {results['files_with_errors']}")
    lines.append(f"Total errors: {results['total_errors']}")
    lines.append(f"Total warnings: {results['total_warnings']}")

    return "\n".join(lines)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    # Built when run, not at import: Rich fixes colour in __init__.
    console = Console()

    if len(sys.argv) < 2:
        console.print("[yellow]Usage:[/yellow] drone @seedgo diagnostics <file_or_directory>")
        sys.exit(1)

    target = sys.argv[1]

    if Path(target).is_file():
        result = check_file(target)
        console.print_json(json.dumps(result, indent=2))
    else:
        result = check_directory(target)

        console.print()
        console.print("[bold cyan]TYPE ERROR DIAGNOSTICS[/bold cyan]")
        console.print(f"  Files analyzed:     {result['total_files']}")
        console.print(f"  Files with errors:  {result['files_with_errors']}")

        if result["total_errors"] > 0:
            console.print(f"  Total errors:       {result['total_errors']}")
        else:
            console.print("  [green]Total errors:       0[/green]")

        if result["total_warnings"] > 0:
            console.print(f"  Total warnings:     {result['total_warnings']}")

        for file_result in result.get("results", [])[:20]:  # Top 20
            if file_result["errors"] > 0:
                console.print()
                console.print(f"\u2022 {file_result['file']} [dim]({file_result['errors']} errors)[/dim]")
                for diag in file_result["diagnostics"][:5]:  # Top 5 per file
                    console.print(f"  [dim]Line {diag['line']}:[/dim] {diag['message']}")
