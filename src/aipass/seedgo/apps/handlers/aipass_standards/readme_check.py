# =================== AIPass ====================
# Name: readme_check.py
# Description: README Standards Checker Handler
# Version: 1.3.4
# Created: 2026-03-05
# Modified: 2026-10-24
# =============================================

"""
README Standards Checker Handler

Reference: readme.md
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import SOURCE_SKIP_DIRS, is_disabled_file
from aipass.seedgo.apps.handlers.bypass.ignore_handler import is_seedgo_ignored, load_ignore_entries

# APPLIES_TO: README.md through the entry point.
APPLIES_TO = "production"
AUDIT_SCOPE = "entry_point"


# Runtime / generated paths that may be absent in a clean checkout (e.g. CI): a README naming one is not a
# violation when it is missing. Pure local-file check, never git or .gitignore.
_RUNTIME_ARTIFACTS = {
    "logs",
    "artifacts",
    "dropbox",
    "tools",
    "system_logs",
    "docs.local",
    "backups",
    ".trinity",
    "DASHBOARD.local.json",
}


def _is_runtime_artifact(path: Path) -> bool:
    """True if path is a runtime/generated artifact that may be absent in a
    clean checkout. Local-file only — never consults git or .gitignore."""
    name = path.name
    if name in _RUNTIME_ARTIFACTS:
        return True
    if name.endswith("_json"):
        return True
    return False


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if branch README follows standards"""
    checks = []

    if is_bypassed(module_path, "readme", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "README",
        }

    # Derive branch root: module_path is apps/[branch].py, go up 2 levels
    entry_path = Path(module_path)
    branch_root = entry_path.parent.parent

    readme_path = branch_root / "README.md"
    readme_exists_check = check_readme_exists(readme_path)
    checks.append(readme_exists_check)

    if not readme_exists_check["passed"]:
        for name in [
            "Required sections",
            "Last Updated freshness",
            "Directory tree accuracy",
            "Module list completeness",
            "Command list presence",
            "Test count accuracy",
            "Markdown link validity",
        ]:
            checks.append({"name": name, "passed": False, "message": "Cannot check - README.md missing"})

        passed_checks = sum(1 for c in checks if c["passed"])
        total_checks = len(checks)
        score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

        return {"passed": score >= 75, "checks": checks, "score": score, "standard": "README"}

    try:
        content = readme_path.read_text(encoding="utf-8")
        lines = content.split("\n")
    except Exception as e:
        logger.info("Cannot read README at %s: %s", readme_path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading README: {e}"}],
            "score": 0,
            "standard": "README",
        }

    sections_check = check_required_sections(lines, module_path, bypass_rules)
    checks.append(sections_check)

    freshness_check = check_last_updated_freshness(lines, module_path, bypass_rules)
    checks.append(freshness_check)

    tree_check = check_directory_tree(lines, branch_root, module_path, bypass_rules)
    checks.append(tree_check)

    modules_check = check_module_list(lines, branch_root, module_path, bypass_rules)
    checks.append(modules_check)

    commands_check = check_command_list(lines, module_path, bypass_rules)
    checks.append(commands_check)

    test_count_check = check_test_count_accuracy(lines, branch_root, module_path, bypass_rules)
    checks.append(test_count_check)

    link_check = check_markdown_links(lines, branch_root, module_path, bypass_rules)
    checks.append(link_check)

    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "readme"})
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "README"}


def check_readme_exists(readme_path: Path) -> Dict:
    """Check that README.md exists at branch root"""
    if readme_path.exists() and readme_path.is_file():
        return {"name": "README exists", "passed": True, "message": f"Found at {readme_path}"}
    return {"name": "README exists", "passed": False, "message": f"README.md not found at {readme_path.parent}"}


def check_required_sections(lines: List[str], file_path: str, bypass_rules: list | None = None) -> Dict:
    """Check for required section headers (case-insensitive, ## markdown headers)."""
    if is_bypassed(file_path, "readme", None, bypass_rules):
        return {"name": "Required sections", "passed": True, "message": "Bypassed by bypass rules"}

    content_lower = "\n".join(lines).lower()

    group1_patterns = ["architecture", "directory structure"]
    group1_found = any(re.search(r"^#{1,3}\s+.*" + re.escape(p), content_lower, re.MULTILINE) for p in group1_patterns)

    group2_patterns = ["commands", "usage"]
    group2_found = any(re.search(r"^#{1,3}\s+.*" + re.escape(p), content_lower, re.MULTILINE) for p in group2_patterns)

    group3_patterns = ["integration points", "depends on", "provides to"]
    group3_found = any(re.search(r"^#{1,3}\s+.*" + re.escape(p), content_lower, re.MULTILINE) for p in group3_patterns)

    missing = []
    if not group1_found:
        missing.append("Architecture/Directory Structure")
    if not group2_found:
        missing.append("Commands/Usage")
    if not group3_found:
        missing.append("Integration Points/Depends On/Provides To")

    if not missing:
        return {"name": "Required sections", "passed": True, "message": "All required sections found"}

    return {"name": "Required sections", "passed": False, "message": f"Missing sections: {', '.join(missing)}"}


def check_last_updated_freshness(lines: List[str], file_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check that the README declares a well-formed "Last Updated" date.

    Local-file only: present and parseable, never compared against code history (that would score a working
    tree and a clean CI checkout differently).
    """
    if is_bypassed(file_path, "readme", None, bypass_rules):
        return {"name": "Last Updated freshness", "passed": True, "message": "Bypassed by bypass rules"}

    date_pattern = re.compile(r"\*{0,2}Last Updated\*{0,2}:\*{0,2}\s*(\d{4}-\d{2}-\d{2})")

    for line in lines:
        match = date_pattern.search(line)
        if match:
            try:
                datetime.strptime(match.group(1), "%Y-%m-%d")
            except ValueError:
                logger.info("Malformed Last Updated date in README: %s", match.group(1))
                return {
                    "name": "Last Updated freshness",
                    "passed": False,
                    "message": f"Malformed Last Updated date: {match.group(1)}",
                }
            return {
                "name": "Last Updated freshness",
                "passed": True,
                "message": f"Last Updated date present ({match.group(1)})",
            }

    return {"name": "Last Updated freshness", "passed": False, "message": 'No "Last Updated" date found in README'}


def check_directory_tree(lines: List[str], branch_root: Path, file_path: str, bypass_rules: list | None = None) -> Dict:
    """Check directory tree accuracy."""
    if is_bypassed(file_path, "readme", None, bypass_rules):
        return {"name": "Directory tree accuracy", "passed": True, "message": "Bypassed by bypass rules"}

    content = "\n".join(lines)
    tree_block = _extract_tree_block(content)

    if tree_block is None:
        # No tree section found - pass (it's optional to have one)
        return {
            "name": "Directory tree accuracy",
            "passed": True,
            "message": "No directory tree block found (optional check)",
        }

    # Skip the root label line; strip inline comments. Tree formats: "apps/", "├── apps/", "│   ├── handlers/".
    dir_pattern = re.compile(r"[\w\-_.]+/")
    branch_name = branch_root.name.lower()
    mentioned_dirs = set()
    tree_lines = tree_block.split("\n")

    first_content_skipped = False
    for tree_line in tree_lines:
        if not first_content_skipped and tree_line.strip():
            first_content_skipped = True
            continue
        if "#" in tree_line:
            tree_line = tree_line[: tree_line.index("#")]
        for match in dir_pattern.finditer(tree_line):
            dir_name = match.group().rstrip("/")
            if dir_name.lower() == branch_name:
                continue
            if dir_name in ("__pycache__", ".git", "node_modules"):
                continue
            if dir_name.startswith("."):
                continue
            # Skip glob/wildcard patterns (e.g., "*_check.py" produces "*_check/")
            if "*" in dir_name:
                continue
            mentioned_dirs.add(dir_name)

    if not mentioned_dirs:
        return {"name": "Directory tree accuracy", "passed": True, "message": "No directories detected in tree block"}

    missing_dirs = []
    # Recorded, not skipped: a directory "not found" under a subtree the walk
    # could not list is unverified, and the message has to say which subtree.
    unreadable: List[OSError] = []
    for dir_name in mentioned_dirs:
        found = False
        for _, dirs, _ in os.walk(str(branch_root), onerror=unreadable.append):
            if dir_name in dirs:
                found = True
                break
        if not found:
            if _is_runtime_artifact(branch_root / dir_name):
                continue
            missing_dirs.append(dir_name)

    if not missing_dirs:
        return {
            "name": "Directory tree accuracy",
            "passed": True,
            "message": f"All {len(mentioned_dirs)} directories in tree verified",
        }

    message = f"Directories in tree not found on disk: {', '.join(sorted(missing_dirs))}"
    if unreadable:
        unread = sorted({str(error.filename) for error in unreadable})
        message += f"; not verified, {len(unread)} subtree(s) could not be read: {', '.join(unread)}"
    return {
        "name": "Directory tree accuracy",
        "passed": False,
        "message": message,
    }


def _extract_tree_block(content: str) -> Optional[str]:
    """Extract the fenced code block following an Architecture/Directory Structure heading."""
    heading_pattern = re.compile(r"^#{1,3}\s+.*(architecture|directory\s+structure)", re.IGNORECASE | re.MULTILINE)
    heading_match = heading_pattern.search(content)
    if not heading_match:
        return None

    after_heading = content[heading_match.end() :]
    fence_pattern = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
    fence_match = fence_pattern.search(after_heading)
    if not fence_match:
        return None

    return fence_match.group(1)


def check_module_list(lines: List[str], branch_root: Path, file_path: str, bypass_rules: list | None = None) -> Dict:
    """Check that all modules in apps/modules/ are mentioned in the README."""
    if is_bypassed(file_path, "readme", None, bypass_rules):
        return {"name": "Module list completeness", "passed": True, "message": "Bypassed by bypass rules"}

    modules_dir = branch_root / "apps" / "modules"
    if not modules_dir.exists():
        return {
            "name": "Module list completeness",
            "passed": True,
            "message": "No apps/modules/ directory found (skipped)",
        }

    module_files = []
    for py_file in sorted(modules_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        if is_disabled_file(py_file.name):
            continue
        module_files.append(py_file.stem)

    if not module_files:
        return {"name": "Module list completeness", "passed": True, "message": "No module files found in apps/modules/"}

    content_lower = "\n".join(lines).lower()
    missing_modules = []
    for module_name in module_files:
        name_lower = module_name.lower()
        name_spaced = name_lower.replace("_", " ")
        if name_lower not in content_lower and name_spaced not in content_lower:
            missing_modules.append(module_name)

    if not missing_modules:
        return {
            "name": "Module list completeness",
            "passed": True,
            "message": f"All {len(module_files)} modules mentioned in README",
        }

    return {
        "name": "Module list completeness",
        "passed": False,
        "message": f"Modules not mentioned in README: {', '.join(missing_modules)}",
    }


def check_test_count_accuracy(
    lines: List[str], branch_root: Path, file_path: str, bypass_rules: list | None = None
) -> Dict:
    """Check that test count claims in README match actual test function count."""
    if is_bypassed(file_path, "readme", None, bypass_rules):
        return {"name": "Test count accuracy", "passed": True, "message": "Bypassed by bypass rules"}

    content = "\n".join(lines)

    claimed_counts = _extract_test_counts(content)
    if not claimed_counts:
        return {
            "name": "Test count accuracy",
            "passed": True,
            "message": "No test count claims found in README (skipped)",
        }

    tests_dir = branch_root / "tests"
    if not tests_dir.exists():
        return {
            "name": "Test count accuracy",
            "passed": True,
            "message": "No tests/ directory found (skipped)",
        }

    actual_count = _count_test_functions(tests_dir)
    max_claimed = max(claimed_counts)

    if actual_count == 0:
        if max_claimed > 0:
            return {
                "name": "Test count accuracy",
                "passed": False,
                "message": f"README claims {max_claimed} tests but no test functions found",
            }
        return {"name": "Test count accuracy", "passed": True, "message": "Both README and tests/ show 0 tests"}

    drift_pct = abs(max_claimed - actual_count) / actual_count * 100

    if drift_pct <= 10:
        return {
            "name": "Test count accuracy",
            "passed": True,
            "message": f"Test count claim ({max_claimed}) within 10% of actual ({actual_count})",
        }

    return {
        "name": "Test count accuracy",
        "passed": False,
        "message": (
            f"README claims {max_claimed} tests, actual count is"
            f" {actual_count} ({drift_pct:.0f}% drift). Update the README"
            f" to {actual_count}."
        ),
    }


def _extract_test_counts(content: str) -> List[int]:
    """Extract numeric test count claims from README content."""
    counts = []
    pattern = re.compile(r"\b(\d+)\s+tests?\b", re.IGNORECASE)
    for match in pattern.finditer(content):
        counts.append(int(match.group(1)))
    return counts


def _count_test_functions(tests_dir: Path) -> int:
    """Count `def test_` and `async def test_` functions in all test_*.py files under tests/."""
    count = 0
    branch_root = tests_dir.parent
    ignore_entries = load_ignore_entries(branch_root)
    test_func_pattern = re.compile(r"^\s*(?:async\s+)?def\s+test_", re.MULTILINE)
    for test_file in tests_dir.rglob("test_*.py"):
        if any(part in SOURCE_SKIP_DIRS for part in test_file.relative_to(tests_dir).parts):
            continue
        if is_disabled_file(test_file.name):
            continue
        if is_seedgo_ignored(str(test_file), branch_root, ignore_entries):
            continue
        try:
            source = test_file.read_text(encoding="utf-8")
            count += len(test_func_pattern.findall(source))
        except (OSError, UnicodeDecodeError):
            logger.info("Cannot read test file %s for count", test_file)
            continue
    return count


def check_markdown_links(lines: List[str], branch_root: Path, file_path: str, bypass_rules: list | None = None) -> Dict:
    """Check that relative markdown links point to existing paths."""
    if is_bypassed(file_path, "readme", None, bypass_rules):
        return {"name": "Markdown link validity", "passed": True, "message": "Bypassed by bypass rules"}

    content = "\n".join(lines)
    links = _extract_relative_links(content)

    if not links:
        return {
            "name": "Markdown link validity",
            "passed": True,
            "message": "No relative markdown links found (skipped)",
        }

    dead_links = []
    for link_text, link_path in links:
        resolved = (branch_root / link_path).resolve()
        if not resolved.exists():
            if _is_runtime_artifact(branch_root / link_path):
                continue
            dead_links.append(f"{link_path} ({link_text})")

    if not dead_links:
        return {
            "name": "Markdown link validity",
            "passed": True,
            "message": f"All {len(links)} relative links verified",
        }

    return {
        "name": "Markdown link validity",
        "passed": False,
        "message": f"Dead links: {', '.join(dead_links)}",
    }


def _extract_relative_links(content: str) -> List[tuple]:
    """Extract relative markdown links as (text, path) tuples."""
    link_pattern = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
    links = []
    for match in link_pattern.finditer(content):
        text = match.group(1)
        # A link target may carry a "title" and a #fragment; only the file part exists on disk.
        path = match.group(2).split()[0].split("#", 1)[0] if match.group(2).strip() else ""
        if not path or path.startswith(("http://", "https://", "mailto:")):
            continue
        links.append((text, path))
    return links


def check_command_list(lines: List[str], file_path: str, bypass_rules: list | None = None) -> Dict:
    """Check that README has a non-empty commands/usage section."""
    if is_bypassed(file_path, "readme", None, bypass_rules):
        return {"name": "Command list presence", "passed": True, "message": "Bypassed by bypass rules"}

    command_heading_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^#{1,3}\s+.*(commands|usage)", stripped, re.IGNORECASE):
            command_heading_idx = i
            break

    if command_heading_idx is None:
        return {
            "name": "Command list presence",
            "passed": False,
            "message": "No Commands/Usage section found in README",
        }

    content_lines = 0
    for i in range(command_heading_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if re.match(r"^#{1,3}\s+", stripped):
            break
        if stripped:
            content_lines += 1

    if content_lines > 0:
        return {
            "name": "Command list presence",
            "passed": True,
            "message": f"Commands/Usage section has {content_lines} content lines",
        }

    return {"name": "Command list presence", "passed": False, "message": "Commands/Usage section is empty"}


# ADVISORY LANE: docs index, named paths, rot bait, sections. Reported through check_branch_info(), never
# scored; why this channel and not a ninth check is in readme.md, "Advisory Lane".

#: docs/*.md added or deleted must bust the audit's incremental cache, or the index line is served stale.
BRANCH_INPUTS = ("docs/*.md",)

_DOCS_DIRNAME = "docs"

#: An advisory that could not read what it reads says so in one line, never the [] of a clean branch.
UNREAD = "readme advisory not run: cannot read "

#: Nouns whose count in a README rots the moment code lands. Not check 7's duplicate: that one scores a test
#: count's accuracy; this one says the number belongs in `drone @<branch>`, not the face.
_ROT_COUNT_RE = re.compile(
    r"\b(\d[\d,]*)\s+(tests?|rules?|standards?|modules?|handlers?|checkers?|checks?"
    r"|commands?|branches|files?|lines?|entries|hooks?|packs?)\b",
    re.IGNORECASE,
)

_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

#: A heading (or a bold label at line start) that names a moment rather than a
#: capability. "Last Updated" is exempt: check 3 REQUIRES it.
_STATUS_LABEL_RE = re.compile(
    r"^\s*(?:#{1,6}\s+|\*{0,2})(status|latest audit|current status|current state|audit results?|recent audit)\b",
    re.IGNORECASE,
)

_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.*)$")

#: A markdown link, for the SPANS of its target, so this lane can leave link targets to check 8. The scored
#: helper keeps its own copy: this row does not reach into the lane that carries the number.
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

#: A path-shaped token: at least one "/" and a file extension. Directories are
#: NOT collected — check 4 already scores directories named in the tree block.
_PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9_.\-/]*[A-Za-z0-9_\-]/[A-Za-z0-9_.\-/]*[A-Za-z0-9_\-]\.([A-Za-z0-9]{1,6})")

#: Extensions a real repository path ends in. An allowlist, not a denylist:
#: without it "anthropic/claude-3.5" and "apps/handlers/.archive/" read as
#: files that do not exist.
_PATH_EXTENSIONS = frozenset(
    {
        "bash", "cfg", "csv", "css", "html", "ini", "js", "json", "lock", "md",
        "py", "service", "sh", "sql", "toml", "ts", "txt", "xml", "yaml", "yml",
    }
)  # fmt: skip

#: Segments that mark an illustrative path in prose ("/path/to/registry.json").
_PLACEHOLDER_SEGMENTS = frozenset({"path", "to", "your", "example", "examples", "foo", "bar", "tmp"})

#: A line in a Commands section that invokes the branch. A pattern, not string prefixes: a literal like
#: "python -m " reads to the help_text standard as advice to run python.
_INVOCATION_RE = re.compile(r"^(?:drone|python3?)\s+\S")

#: Below this, a Commands section is a pointer rather than a copy of --help.
_COMMAND_LIST_MIN = 3

#: How many names one info line carries before it says "and N more": a silent cap hands back an unactionable count.
_SAMPLE_LIMIT = 6

#: The README face: eight ## sections, names exact, order fixed. Advisory: scored, it would red most branches.
README_SECTIONS: Tuple[str, ...] = (
    "Quick Start",
    "What It Does",
    "Live Inventory",
    "How To Reach Me",
    "Commands",
    "Architecture",
    "Documentation",
    "Integration Points",
)


def check_branch_info(branch_path: str) -> List[str]:
    """Non-scored advisory lines: the docs/ index, named paths, rot bait, and the eight sections.

    Never returns a score, a pass or a violation. Empty when there is nothing to report: silence is the clean state.
    """
    branch_root = Path(branch_path)
    readme_path = branch_root / "README.md"
    if not readme_path.is_file():
        return []
    try:
        content = readme_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.info("[readme] cannot read README for advisory lines at %s: %s", readme_path, e)
        return [f"{UNREAD}{readme_path} ({e})"]

    readme_lines = content.split("\n")
    lines: List[str] = []
    lines.extend(_docs_index_lines(branch_root, content))
    lines.extend(_named_path_lines(branch_root, content))
    lines.extend(_rot_bait_lines(branch_root, content))
    lines.extend(_section_order_lines(readme_lines, _fence_mask(readme_lines)))
    if lines:
        json_handler.log_operation(
            "readme_advisory_lines",
            {"branch": branch_root.name, "count": len(lines), "standard": "readme"},
        )
    return lines


def _safe(text: str) -> str:
    """README text made safe to hand a Rich console.

    Info lines are printed through Rich markup, so a heading like
    "## Status [2026-09-07]" would be swallowed as a style tag — the sample
    would vanish from the very line that exists to quote it.
    """
    return text.replace("[", "(").replace("]", ")")


def _sample(names: List[str]) -> str:
    """Up to _SAMPLE_LIMIT names, with the remainder counted, never hidden."""
    head = ", ".join(_safe(n) for n in names[:_SAMPLE_LIMIT])
    extra = len(names) - _SAMPLE_LIMIT
    return f"{head} and {extra} more" if extra > 0 else head


def _fence_mask(lines: List[str]) -> List[bool]:
    """Per-line True when the line is inside (or is) a fenced code block.

    Without this a bash comment inside a ```fence``` reads as a markdown heading and ends the section scan.
    """
    mask: List[bool] = []
    inside = False
    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            inside = not inside
            mask.append(True)
            continue
        mask.append(inside)
    return mask


def _docs_index_lines(branch_root: Path, content: str) -> List[str]:
    """One line on whether every docs/*.md is reachable from the README.

    Indexed when a relative markdown link resolves to it OR the literal "docs/<name>" appears (a link to docs/
    covers docs/README.md). No docs/ directory, or no *.md in it, is SILENCE.
    """
    docs_dir = branch_root / _DOCS_DIRNAME
    if not docs_dir.is_dir():
        return []
    try:
        docs_files = sorted(docs_dir.glob("*.md"))
    except OSError as e:
        logger.info("[readme] cannot list %s: %s", docs_dir, e)
        return [f"{UNREAD}{docs_dir} ({e})"]
    if not docs_files:
        return []

    targets = set()
    for _text, link_path in _extract_relative_links(content):
        bare = link_path.split("#")[0].strip()
        if not bare:
            continue
        try:
            targets.add((branch_root / bare).resolve())
        except OSError as e:
            logger.info("[readme] cannot resolve README link %s: %s", bare, e)

    dir_linked = docs_dir.resolve() in targets
    unlinked = []
    for doc in docs_files:
        rel = f"{_DOCS_DIRNAME}/{doc.name}"
        if doc.resolve() in targets or rel in content:
            continue
        if doc.name == "README.md" and dir_linked:
            continue
        unlinked.append(rel)

    if not unlinked:
        return [f"readme docs index (advisory): all {len(docs_files)} docs/*.md linked from README"]
    return [
        f"readme docs index (advisory): {len(unlinked)} of {len(docs_files)} docs/*.md not linked from "
        f"README — {_sample(unlinked)}"
    ]


def _named_path_lines(branch_root: Path, content: str) -> List[str]:
    """One line naming branch-rooted paths the README claims that are absent.

    SCOPE: only a token whose first segment is a real top-level entry of THIS branch; an audit of one branch
    cannot tell a stale reference from a neighbour's real file. Link targets (check 8) and directories (check 4)
    are skipped.
    """
    try:
        tops = {entry.name for entry in branch_root.iterdir()}
    except OSError as e:
        logger.info("[readme] cannot list branch root %s: %s", branch_root, e)
        return [f"{UNREAD}{branch_root} ({e})"]

    link_spans = [(m.start(2), m.end(2)) for m in _MARKDOWN_LINK_RE.finditer(content)]
    missing: List[str] = []
    seen = set()
    for match in _PATH_TOKEN_RE.finditer(content):
        token = match.group(0)
        if token in seen or match.group(1).lower() not in _PATH_EXTENSIONS:
            continue
        if any(start <= match.start() < end for start, end in link_spans):
            continue
        parts = token.split("/")
        if token.startswith("/") or parts[0] not in tops:
            continue
        if any(p in _PLACEHOLDER_SEGMENTS for p in parts):
            continue
        if any(p.startswith(".") or p.endswith("_json") or _is_runtime_artifact(branch_root / p) for p in parts[:-1]):
            continue
        seen.add(token)
        if not (branch_root / token).exists():
            missing.append(token)

    if not missing:
        return []
    return [
        f"readme paths (advisory): {len(missing)} branch-rooted path(s) named in README but absent — "
        f"{_sample(sorted(missing))}"
    ]


def _rot_bait_lines(branch_root: Path, content: str) -> List[str]:
    """The three shapes of README content that rot on their own.

    Counts, dated status sections and a copy of --help all stay true only
    while someone re-types them. The contract moves each one to a source that
    regenerates: the live self-map, a plan, `--help`.
    """
    lines = content.split("\n")
    mask = _fence_mask(lines)
    return [
        *_count_claim_lines(content),
        *_dated_heading_lines(lines, mask),
        *_command_list_lines(branch_root, lines, mask),
    ]


def _count_claim_lines(content: str) -> List[str]:
    """One line counting the README's own count claims."""
    claims = [f'"{m.group(1)} {m.group(2)}"' for m in _ROT_COUNT_RE.finditer(content)]
    if not claims:
        return []
    head = ", ".join(claims[:4])
    return [
        f"readme rot bait (advisory): {len(claims)} count claim(s) that go stale — e.g. {head}. "
        f"The live count is drone @<branch> and --help, generated from code"
    ]


def _dated_heading_lines(lines: List[str], mask: List[bool]) -> List[str]:
    """One line naming headings that pin the README to a moment.

    A heading carrying a date, or one labelled Status / Latest Audit, is a
    snapshot: true the day it was written and unfalsifiable afterwards. The
    "Last Updated" line is exempt — check 3 requires it.
    """
    dated = []
    for number, line in enumerate(lines, start=1):
        if mask[number - 1]:
            continue
        lowered = line.lower()
        if "last updated" in lowered or "created:" in lowered:
            continue
        heading = _HEADING_RE.match(line)
        has_date = bool(_DATE_RE.search(line))
        labelled = bool(_STATUS_LABEL_RE.match(line))
        if (heading and (has_date or labelled)) or (labelled and has_date):
            dated.append(f"L{number} {line.strip()[:44]}")
    if not dated:
        return []
    head = "; ".join(_safe(d) for d in dated[:3])
    return [
        f"readme rot bait (advisory): {len(dated)} dated/status heading(s) — {head}. "
        f"A dated section is a snapshot; status belongs on the dashboard, history in a plan"
    ]


def _command_list_lines(branch_root: Path, lines: List[str], mask: List[bool]) -> List[str]:
    """One line when the Commands/Usage section re-types what --help prints.

    Reported, not scored, and it does NOT ask for the section's removal:
    checks 2 and 6 still require a non-empty Commands/Usage heading. The
    contract is a POINTER to `drone @<branch> --help` instead of a list that
    drifts the next time a command is added.
    """
    heading_index = None
    level = 3
    for index, line in enumerate(lines):
        heading = _HEADING_RE.match(line)
        if heading and not mask[index] and re.search(r"(commands|usage)", heading.group(2), re.IGNORECASE):
            heading_index, level = index, len(heading.group(1))
            break
    if heading_index is None:
        return []

    branch = branch_root.name.lower()
    invocations = 0
    for index in range(heading_index + 1, len(lines)):
        line = lines[index]
        heading = _HEADING_RE.match(line)
        if heading and not mask[index] and len(heading.group(1)) <= level:
            break
        stripped = line.strip().lstrip("-*| ").strip().strip("`")
        if stripped.startswith("$ "):
            stripped = stripped[2:]
        if _INVOCATION_RE.match(stripped) or f"`drone @{branch}" in line:
            invocations += 1

    if invocations < _COMMAND_LIST_MIN:
        return []
    return [
        f"readme rot bait (advisory): Commands section lists {invocations} invocation(s) that duplicate "
        f"drone @{branch} --help. Keep a pointer, drop the list (checks 2 and 6 still want the section)"
    ]


def _section_order_lines(lines: List[str], mask: List[bool]) -> List[str]:
    """One line on the README's ## sections against README_SECTIONS: silence when all eight stand in order.

    A ## heading that is not one of the eight but shares its first word with a
    missing one is a rename ("What I Do", "Integration", "How to reach me");
    any other is a stranger. Order is read over the eight as found, a rename
    counted where it stands. H1, H3 and fenced lines are not sections.
    """
    found = [
        match.group(2).strip()
        for index, line in enumerate(lines)
        if not mask[index] and (match := _HEADING_RE.match(line)) and len(match.group(1)) == 2
    ]
    by_word = {name.split()[0].lower(): name for name in README_SECTIONS if name not in found}
    renames: List[str] = []
    strangers: List[str] = []
    order: List[str] = []
    for heading in found:
        words = heading.split()
        target = None if heading in README_SECTIONS else by_word.pop(words[0].lower() if words else "", None)
        if heading in README_SECTIONS or target:
            order.append(target or heading)
            if target:
                renames.append(f"'{heading}' to '{target}'")
        else:
            strangers.append(heading)
    missing = [name for name in README_SECTIONS if name in by_word.values()]
    swaps = [
        f"{first} before {second}"
        for first, second in zip(order, order[1:])
        if README_SECTIONS.index(first) > README_SECTIONS.index(second)
    ]
    parts = [
        f"{label}{', '.join(names)}"
        for label, names in (
            ("missing ", missing),
            ("rename ", renames),
            ("order: ", swaps),
            ("not one of the eight: ", strangers),
        )
        if names
    ]
    if not parts:
        return []
    return [
        f"readme sections (advisory): {_safe('; '.join(parts))} — the face is eight ## sections, "
        f"names exact, order fixed: drone @seedgo standard readme"
    ]
