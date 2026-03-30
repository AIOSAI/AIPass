# ===================AIPASS====================
# META DATA HEADER
# Name: handler.py - Branch Health skill handler
# Date: 2026-03-29
# Version: 1.0.0
# Category: skills/catalog/branch_health
# =============================================

"""
Branch Health skill handler.

Quick health check for AIPass branches -- counts Python source files,
test files, and test functions per branch.

Called by: drone @skills run branch_health <action>
"""

from pathlib import Path


def run(action, args=None, config=None):
    """Execute a branch health action.

    Args:
        action: One of: summary (default), tests, or a specific branch name
        args: Dict of action arguments (unused for this skill)
        config: Dict of resolved config values (unused for this skill)

    Returns:
        {"success": bool, "output": str, "error": str|None}
    """
    args = args or {}
    config = config or {}

    try:
        if action == "summary":
            return _full_summary()
        if action == "tests":
            return _tests_only()
        return _single_branch(action)
    except Exception as exc:
        return {
            "success": False,
            "output": "",
            "error": f"Action '{action}' failed: {exc}",
        }


def get_actions():
    """List available actions for this skill."""
    return ["summary", "tests", "<branch_name>"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _src_root():
    """Return the src/ directory by navigating up from this handler."""
    # handler.py -> catalog/branch_health/ -> catalog/ -> skills/ -> src/
    return Path(__file__).resolve().parents[3]


def _find_branches():
    """Yield (branch_name, branch_path) for all branches."""
    src = _src_root()

    # src/aipass/*/ branches
    aipass_dir = src / "aipass"
    if aipass_dir.is_dir():
        for branch_dir in sorted(aipass_dir.iterdir()):
            if branch_dir.is_dir() and not branch_dir.name.startswith((".", "_")):
                # Only yield actual branches (have apps/ or tests/ or .trinity/)
                if (
                    (branch_dir / "apps").is_dir()
                    or (branch_dir / "tests").is_dir()
                    or (branch_dir / ".trinity").is_dir()
                ):
                    yield (branch_dir.name, branch_dir)

    # src/skills/ itself
    skills_dir = src / "skills"
    if skills_dir.is_dir():
        yield ("skills", skills_dir)


def _count_py_files(directory):
    """Count .py files recursively in a directory."""
    if not directory.is_dir():
        return 0
    return sum(1 for _ in directory.rglob("*.py"))


def _count_test_files(directory):
    """Count test_*.py files in a directory."""
    if not directory.is_dir():
        return 0
    return sum(1 for f in directory.rglob("*.py") if f.name.startswith("test_"))


def _count_test_functions(directory):
    """Count lines matching 'def test_' in test files."""
    if not directory.is_dir():
        return 0
    count = 0
    for py_file in directory.rglob("*.py"):
        if not py_file.name.startswith("test_"):
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("def test_"):
                    count += 1
        except OSError:
            continue
    return count


def _branch_stats(branch_name, branch_path):
    """Compute stats for a single branch. Returns a dict."""
    apps_dir = branch_path / "apps"
    tests_dir = branch_path / "tests"

    return {
        "name": branch_name,
        "py_files": _count_py_files(apps_dir),
        "test_files": _count_test_files(tests_dir),
        "test_functions": _count_test_functions(tests_dir),
        "has_apps": apps_dir.is_dir(),
        "has_tests": tests_dir.is_dir(),
    }


def _format_row(name, py_files, test_files, test_fns):
    """Format a single branch stats row."""
    return f"  {name:<20s} {py_files:>5d} py  {test_files:>4d} tests  {test_fns:>5d} fns"


def _full_summary():
    """Full stats for all branches."""
    lines = ["Branch Health Summary", "  " + "-" * 55]
    total_py = 0
    total_tests = 0
    total_fns = 0
    branch_count = 0

    for branch_name, branch_path in _find_branches():
        stats = _branch_stats(branch_name, branch_path)
        lines.append(_format_row(
            stats["name"],
            stats["py_files"],
            stats["test_files"],
            stats["test_functions"],
        ))
        total_py += stats["py_files"]
        total_tests += stats["test_files"]
        total_fns += stats["test_functions"]
        branch_count += 1

    lines.append("  " + "-" * 55)
    lines.append(f"  {'TOTAL':<20s} {total_py:>5d} py  {total_tests:>4d} tests  {total_fns:>5d} fns")
    lines.append(f"  ({branch_count} branches)")

    return {"success": True, "output": "\n".join(lines), "error": None}


def _tests_only():
    """Test-only stats for all branches."""
    lines = ["Branch Health -- Test Stats", "  " + "-" * 45]
    total_tests = 0
    total_fns = 0

    for branch_name, branch_path in _find_branches():
        stats = _branch_stats(branch_name, branch_path)
        if stats["test_files"] > 0 or stats["test_functions"] > 0:
            lines.append(
                f"  {stats['name']:<20s} {stats['test_files']:>4d} tests  "
                f"{stats['test_functions']:>5d} fns"
            )
            total_tests += stats["test_files"]
            total_fns += stats["test_functions"]

    if total_tests == 0:
        lines.append("  No test files found.")
    else:
        lines.append("  " + "-" * 45)
        lines.append(f"  {'TOTAL':<20s} {total_tests:>4d} tests  {total_fns:>5d} fns")

    return {"success": True, "output": "\n".join(lines), "error": None}


def _single_branch(branch_name):
    """Stats for a single branch."""
    src = _src_root()

    # Check src/aipass/<branch_name>/ first, then src/<branch_name>/
    candidates = [
        src / "aipass" / branch_name,
        src / branch_name,
    ]

    branch_path = None
    for candidate in candidates:
        if candidate.is_dir():
            branch_path = candidate
            break

    if branch_path is None:
        return {
            "success": True,
            "output": f"Branch Health -- {branch_name}\n  Branch '{branch_name}' not found.",
            "error": None,
        }

    stats = _branch_stats(branch_name, branch_path)
    lines = [
        f"Branch Health -- {branch_name}",
        f"  Source files (apps/): {stats['py_files']}",
        f"  Test files (tests/):  {stats['test_files']}",
        f"  Test functions:       {stats['test_functions']}",
        f"  Has apps/ dir:        {'yes' if stats['has_apps'] else 'no'}",
        f"  Has tests/ dir:       {'yes' if stats['has_tests'] else 'no'}",
    ]

    return {"success": True, "output": "\n".join(lines), "error": None}
