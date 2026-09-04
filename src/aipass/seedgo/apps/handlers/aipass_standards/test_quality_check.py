# =================== AIPass ====================
# Name: test_quality_check.py
# Description: Test Quality Standards Checker — 11 categories (consolidated)
# Version: 5.1.0
# Created: 2026-03-24
# Modified: 2026-03-27
# =============================================

"""
Test Quality Standards Checker Handler

Branch-level checker that scans ALL test files in a branch's tests/
directory and evaluates coverage across 11 standard test categories
(10 pattern categories + module coverage).

Consolidates the former test_coverage_check.py (import-based module
coverage analysis) into this single comprehensive test checker.

Does NOT require specific filenames. Does NOT run pytest -- analyses
test files statically via text scan + import mapping.

Scoring model:
    Score = (total_items_covered / total_items) * 100
"""

import ast
import re
from functools import lru_cache
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import SOURCE_SKIP_DIRS, is_disabled_file
from aipass.seedgo.apps.handlers.bypass.ignore_handler import is_seedgo_ignored, load_ignore_entries

AUDIT_SCOPE = "branch_level"
# The one standard that is about tests. Branch-level, so check_branch() below owns
# the corpus (tests/) and this constant documents it rather than enforcing it --
# see applicability.py on why per-file lanes cannot filter a self-collecting checker.
APPLIES_TO = "tests"

# -- Directories to skip when scanning for module coverage --------------------
SKIP_DIRS: set[str] = set(SOURCE_SKIP_DIRS)

# -- Regex patterns for module coverage (from test_coverage_check.py) ---------
RE_TEST_FUNC = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)", re.MULTILINE)
RE_IMPORT_FROM = re.compile(r"from\s+(?:aipass\.)?\w+\.apps\.(?:modules|handlers)[./]?([\w.]*)\s+import")
RE_IMPORT_DIRECT = re.compile(r"import\s+(?:aipass\.)?\w+\.apps\.(?:modules|handlers)[./]?([\w.]*)")

# -- Standard test categories and their detection patterns --------------------
STANDARD_CATEGORIES: dict[str, dict[str, list[str]]] = {
    # RETIRED 2026-09-03, DPLAN-0325 part B section 1. Four categories and six
    # further items left this table with the fleet's json handler. The scan is
    # per-branch TEXT; the handler is now ONE service in prax with a byte-
    # identical shim per branch, so the behaviour it used to grep for is tested
    # once, by execution, over all 18 shims in
    # seedgo/tests/test_json_handler_contract.py. A per-branch text scan cannot
    # see fleet-owned coverage, so it must stop scoring it — measured, the four
    # swept trees (devpulse, backup, hooks, aipass) each lost their sole carrier
    # for these items when the DPLAN-0059 stamp files were archived, and CI
    # gates every branch at 100.
    #   json_handler (8)             -- the nine handler functions by name
    #   exception_contracts (3)      -- _create_default / save_json / json_type raising
    #   data_structure_contracts (3) -- the config/data/log document shape
    #   conftest_fixtures/mock_json_handler   -- the fixture conftest v3.0.0 deleted
    #   return_type_contracts/load_correct_type, ensure_returns_bool
    #   init_provisioning/returns_dict
    #   infrastructure_mocking/sys_modules_mock, reimport_after_mock
    #                                -- the stamp's own technique: stub sys.modules,
    #                                   reload the handler module. There is no shim
    #                                   to reload.
    # Retiring an item costs nobody: numerator and denominator move together, so
    # a branch at 100 today is still 100 at 31/31. Verified over all 18 branches.
    # Category 1: CLI Routing (9 items)
    "cli_routing": {
        "help_flag": ["--help"],
        "short_help": ['"-h"', "'-h'"],
        "help_word": ['"help"', "'help'"],
        "no_args": ["test_no_args", "test_introspection", "no_args"],
        "unknown_command": ["unknown_command", "invalid_command", "unrecognized"],
        "return_bool": ["is True", "is False"],
        "print_help": ["print_help"],
        "print_introspection": ["print_introspection"],
        "output_capture": ["capsys", "capfd", "StringIO"],
    },
    # Category 2: Conftest Fixtures (5 items)
    "conftest_fixtures": {
        "temp_dir": ["tmp_path", "temp_test_dir", "temp_dir"],
        "sample_data": ["sample_test_data", "sample_data"],
        "mock_infrastructure": ["mock_infrastructure", "autouse"],
        "mock_logger": ["mock_logger", "mock_log"],
        # mock_json_handler RETIRED with the handler (DPLAN-0325 part B): the
        # citizen template's conftest v3.0.0 deletes that fixture — the seam is
        # AIPASS_TEST_LOG_DIR, read by the service per call.
        "cleanup": ["rmtree", "yield", "teardown"],
    },
    # Category 3: Error Resilience (4 items)
    "error_resilience": {
        "missing_file": ["FileNotFoundError", "missing_file", "file_not_found"],
        "corrupt_json": ["JSONDecodeError", "corrupt", "malformed"],
        # Re-scoped 2026-09-03: @aipass's only carrier was the archived json
        # stamp, yet its live suite has test_empty_project,
        # test_empty_branch_name_ignored and test_empty_path_flagged. The item
        # was measuring a spelling, not the concept. Additive — no branch drops.
        "empty_file": ["empty_file", "empty_content", "test_empty"],
        "nonexistent_dir": ["nonexistent", "missing_dir", "not_a_dir"],
    },
    # Category 4: Return Type Contracts (2 items)
    "return_type_contracts": {
        "command_returns_bool": [
            "isinstance(result, bool)",
            # Re-scoped 2026-09-03: @aipass asserts isinstance(result["ok"], bool)
            # — a real bool return-type contract the literal token missed because
            # the variable is subscripted. Additive; no branch drops.
            ", bool)",
            "returns_bool",
            "return_type",
        ],
        "paths_return_path": ["isinstance(result, Path)", "pathlib.Path"],
        # ensure_returns_bool and load_correct_type RETIRED with the handler.
    },
    # Category 5: Success/Failure Paths (4 items)
    "success_failure_paths": {
        "known_routes_true": ["assert result is True", "== True"],
        "unknown_returns_false": ["assert result is False", "== False"],
        "help_preempts": ["--help"],
        "no_args_triggers": ["print_introspection"],
    },
    # Category 6: Init/Provisioning (3 items)
    "init_provisioning": {
        "creates_files": [".exists()", "ensure_json_exists"],
        "auto_creates_dir": ["mkdir", "makedirs"],
        "no_overwrite": ["overwrite", "no_clobber", "already_exists"],
        # returns_dict RETIRED with the handler — json_type is its concept.
    },
    # Category 7: Infrastructure Mocking (1 item)
    "infrastructure_mocking": {
        "autouse_fixtures": ["autouse=True", "autouse"],
        # sys_modules_mock and reimport_after_mock RETIRED with the handler.
    },
}

#: Applicability probes: the SUBJECT an item measures, looked for in the
#: branch's OWN ``apps/`` code. An item is scored only when the branch ships
#: something for it to be about — an inapplicable item leaves the numerator AND
#: the denominator for that branch, so it neither convicts nor flatters.
#:
#: Added 2026-09-03 (DPLAN-0325 pair 3). @canary's sweep left it at 87 on these
#: four, and the four had been carried by its archived DPLAN-0059 stamp. The
#: obvious move was to retire them with the rest, and the measurement refused
#: it: 16 of 18 branches earn each of these four from tests that have NOTHING
#: to do with the handler (ai_mail's test_notify, aipass's test_structure_scan,
#: api's test_secrets). Retiring them fleet-wide would delete four live items
#: from sixteen branches to cure one.
#:
#: What canary actually is, is a branch with no subject: its whole production
#: surface is ``apps/canary.py`` plus a handlers ``__init__`` — it parses no
#: JSON, returns no Path, writes no file. Neither does @cli, whose only
#: file-touching code is the handler it has not swept yet; cli scores these
#: today from its json tests and hits the identical wall on its own sweep.
#: So the defect was never the tokens. It was asking every branch for coverage
#: of something two of them do not do.
#:
#: The branch's own ``json_handler.py`` is excluded from the probe on purpose:
#: it is the fleet's file, byte-identical everywhere, and counting it would
#: give every branch every subject and make the gate meaningless.
#:
#: Known and accepted: a branch could shed an item by deleting production code.
#: That is a visible act with its own reviewers, and the alternative — charging
#: a branch for not testing what it does not have — is the failure that is
#: actually happening.
ITEM_SUBJECT_PROBES: dict[tuple[str, str], tuple[str, ...]] = {
    ("error_resilience", "corrupt_json"): ("json.load",),
    ("error_resilience", "empty_file"): (".read_text(", "open("),
    ("return_type_contracts", "paths_return_path"): ("-> Path",),
    ("init_provisioning", "no_overwrite"): (".write_text(", ".mkdir("),
}

# =============================================
# WHICH FILES MAY CARRY AN ITEM
# =============================================
#
# The scan below asks "does this token appear anywhere under tests/". Twice in
# one week that answered yes for the wrong reason, and both shapes are cured
# here (DPLAN-0325, sessions on pairs 7 and 6a):
#
#   THE FILE WAS NOT ABOUT THE CATEGORY. @flow earned
#   cli_routing/output_capture from a ``StringIO`` inside its json handler
#   test. Archiving that file as a duplicate dropped flow to 93 and exposed a
#   gap nothing had ever covered.
#
#   THE FILE DID NOT RUN. @drone's test_contracts.py skipped module-wide on a
#   missing JSON_DIR and was still its sole carrier of command_returns_bool.
#   A text scan cannot tell a passing assertion from a skipped one.
#
# Both gates below are measured against all 18 branches before their strictness
# moves. The two constants are the dials, and each is set to the value that
# costs no branch an item TODAY; each carries the measured cost of the next
# notch and the precondition that makes it free.

#: Discount a file whose module-level skip is CONDITIONAL, not just an
#: unconditional one. Measured 2026-09-04: flipping this to True today costs
#: @daemon 7 points (init_provisioning/no_overwrite and
#: return_type_contracts/command_returns_bool, both carried by its DPLAN-0059
#: stamp files, which skip on a missing JSON_DIR). @api carries the same shape
#: and loses nothing. Those stamp files are archived by the branch's own sweep
#: onto the one json service — @drone's went on 2026-09-04 — so this becomes
#: free once daemon and api sweep, and drone's exact defect is then caught.
DISCOUNT_CONDITIONAL_MODULE_SKIPS = False

#: Scope a category's scan to files that are plausibly ABOUT it: a file carries
#: an item only if it carries at least SUBJECT_MIN_ITEMS_PER_FILE items of that
#: category. Applied only to categories with at least SUBJECT_SCOPED_CATEGORY_SIZE
#: scored items — a one-item category (infrastructure_mocking) can never satisfy
#: a two-item rule, and a two-item one (return_type_contracts) would demand a
#: perfect score to earn anything. Measured: applying it to every category costs
#: all 18 branches, up to -23.
SUBJECT_SCOPED_CATEGORY_SIZE = 5

#: Measured 2026-09-04, threshold by threshold. At 2 no branch moves. At 3 only
#: @prax moves, -4: it earns conftest_fixtures/sample_data from
#: test_json_handler.py rather than from its conftest, which carries 3 of 5 and
#: defines no sample_test_data. One template fixture in prax/tests/conftest.py
#: makes 3 free — the same restore @flow needed on pair 7.
#: Honest limit of the current setting: flow's file carried TWO incidental
#: cli_routing tokens (``is True`` and ``StringIO``), so 2 does not convict the
#: case that produced the finding. 3 does.
SUBJECT_MIN_ITEMS_PER_FILE = 2

# Pattern-based items from STANDARD_CATEGORIES
_PATTERN_ITEMS = sum(len(items) for items in STANDARD_CATEGORIES.values())

# Module coverage adds 3 items: test_files_exist, test_functions_exist, module_coverage
_MODULE_COVERAGE_ITEMS = 3

TOTAL_ITEMS = _PATTERN_ITEMS + _MODULE_COVERAGE_ITEMS


# =============================================
# BYPASS HELPER
# =============================================


# =============================================
# FILE HELPERS
# =============================================


def _read_file_safe(path: Path) -> str:
    """Read a file, returning empty string on any error."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.info("Cannot read %s for test quality analysis", path)
        return ""


def _should_skip_dir(name: str) -> bool:
    """Check if a directory name should be skipped."""
    return name in SKIP_DIRS or name.startswith(".")


def _should_skip_file(name: str) -> bool:
    """Check if a file should be skipped (disabled convention)."""
    return is_disabled_file(name)


def _find_test_files_broad(branch_path: Path, ignore_entries: list) -> list[Path]:
    """Find all test files for module coverage analysis.

    Broader than _find_all_test_files — also finds scattered test files
    outside tests/ directory. Used for import-based module mapping.
    """
    test_files: list[Path] = []
    seen: set[Path] = set()

    # 1. Standard tests/ directory
    tests_dir = branch_path / "tests"
    if tests_dir.is_dir():
        for py_file in sorted(tests_dir.rglob("*.py")):
            if py_file.name in ("__init__.py", "conftest.py"):
                continue
            if any(_should_skip_dir(part) for part in py_file.relative_to(tests_dir).parts):
                continue
            if is_seedgo_ignored(str(py_file), branch_path, ignore_entries):
                continue
            resolved = py_file.resolve()
            if resolved not in seen:
                seen.add(resolved)
                test_files.append(py_file)

    # 2. Scattered test_*.py or *_test.py anywhere in the branch
    for py_file in sorted(branch_path.rglob("*.py")):
        if any(_should_skip_dir(part) for part in py_file.relative_to(branch_path).parts):
            continue
        if py_file.name in ("__init__.py", "conftest.py") or _should_skip_file(py_file.name):
            continue
        if is_seedgo_ignored(str(py_file), branch_path, ignore_entries):
            continue
        if py_file.name.startswith("test_") or py_file.name.endswith("_test.py"):
            resolved = py_file.resolve()
            if resolved not in seen:
                seen.add(resolved)
                test_files.append(py_file)

    return test_files


def _analyze_test_file_imports(source: str) -> set[str]:
    """Extract tested module names from a test file source via import patterns."""
    tested_modules: set[str] = set()

    for match in RE_IMPORT_FROM.finditer(source):
        sub_path = match.group(1)
        if sub_path:
            tested_modules.add(sub_path.split(".")[0])

    for match in RE_IMPORT_DIRECT.finditer(source):
        sub_path = match.group(1)
        if sub_path:
            tested_modules.add(sub_path.split(".")[0])

    return tested_modules


def _collect_testable_modules(branch_path: Path, ignore_entries: list) -> set[str]:
    """Collect module names from apps/modules/ and apps/handlers/.

    Returns set of module names:
    - apps/modules/*.py  -> file stem
    - apps/handlers/*.py -> file stem
    - apps/handlers/subdir/ -> directory name if it contains .py files
    """
    modules: set[str] = set()
    apps_dir = branch_path / "apps"
    if not apps_dir.is_dir():
        return modules

    modules_dir = apps_dir / "modules"
    if modules_dir.is_dir():
        for item in sorted(modules_dir.iterdir()):
            if (
                item.is_file()
                and item.suffix == ".py"
                and item.name != "__init__.py"
                and not _should_skip_file(item.name)
                and not is_seedgo_ignored(str(item), branch_path, ignore_entries)
            ):
                modules.add(item.stem)

    handlers_dir = apps_dir / "handlers"
    if handlers_dir.is_dir():
        for item in sorted(handlers_dir.iterdir()):
            if _should_skip_dir(item.name) or is_seedgo_ignored(str(item), branch_path, ignore_entries):
                continue
            if item.is_dir() and item.name != "__pycache__":
                has_py = any(
                    f.suffix == ".py"
                    and f.name != "__init__.py"
                    and not _should_skip_file(f.name)
                    and not is_seedgo_ignored(str(f), branch_path, ignore_entries)
                    for f in item.iterdir()
                    if f.is_file()
                )
                if has_py:
                    modules.add(item.name)
            elif (
                item.is_file()
                and item.suffix == ".py"
                and item.name != "__init__.py"
                and not _should_skip_file(item.name)
            ):
                modules.add(item.stem)

    return modules


def _find_all_test_files(branch_path: Path, ignore_entries: list) -> list[Path]:
    """Find all test files and conftest.py in the branch's tests/ directory.

    Scans for any test_*.py file plus conftest.py -- no naming requirements.
    """
    tests_dir = branch_path / "tests"
    if not tests_dir.is_dir():
        return []

    results: list[Path] = []
    for p in sorted(tests_dir.iterdir()):
        if not p.is_file() or p.suffix != ".py":
            continue
        if is_seedgo_ignored(str(p), branch_path, ignore_entries):
            continue
        if p.name.startswith("test_") or p.name == "conftest.py":
            results.append(p)

    return results


# =============================================
# ANALYSIS
# =============================================


def _find_covering_file(
    patterns: list[str],
    file_sources: list[tuple[str, str]],
) -> str | None:
    """Find the first file that contains any of the given patterns."""
    for filename, source in file_sources:
        for pattern in patterns:
            if pattern in source:
                return filename
    return None


def _module_skip_shape(tree: ast.Module) -> str | None:
    """Name the way this module refuses to run, or None if it runs.

    Two shapes, both decidable without importing anything: a module-level
    ``pytest.skip(..., allow_module_level=True)`` (the only call that can stop
    a module rather than a test), and a module-level ``pytestmark`` carrying
    ``skip``. ``skipif`` is deliberately NOT one of them — it is a statement
    about the host, and a file that runs on the fleet's interpreter is a real
    carrier there.
    """
    for node in tree.body:
        statements = node.body if isinstance(node, ast.If) else [node]
        for statement in statements:
            if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
                continue
            called = statement.value.func
            if isinstance(called, ast.Attribute) and called.attr == "skip":
                if any(keyword.arg == "allow_module_level" for keyword in statement.value.keywords):
                    return "conditional module-level skip" if isinstance(node, ast.If) else "module-level skip"

        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "pytestmark" in names:
                marks = ast.dump(node.value)
                if "'skip'" in marks and "'skipif'" not in marks:
                    return "pytestmark skip"
    return None


def _dead_carrier_reason(filename: str, source: str) -> str | None:
    """Why this file executes no assertion, or None if it does.

    A file that cannot run cannot be a branch's evidence for anything. Only
    shapes that are certain from the text count: the module-level skips above,
    and a test file with no test function in it at all. ``conftest.py`` is
    exempt from the second — holding fixtures and no tests is its whole job.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "does not parse"

    shape = _module_skip_shape(tree)
    if shape:
        if shape.startswith("conditional") and not DISCOUNT_CONDITIONAL_MODULE_SKIPS:
            return None
        return shape

    if filename != "conftest.py" and not RE_TEST_FUNC.search(source):
        return "no test functions"
    return None


def _live_carriers(
    file_sources: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """Split the corpus into files that can carry coverage and files that cannot.

    Returns:
        (live sources, {discounted filename: why}).
    """
    live: list[tuple[str, str]] = []
    discounted: dict[str, str] = {}
    for filename, source in file_sources:
        reason = _dead_carrier_reason(filename, source)
        if reason:
            discounted[filename] = reason
        else:
            live.append((filename, source))
    return live, discounted


@lru_cache(maxsize=64)
def _branch_apps_source(branch_path: str) -> str:
    """Every line of the branch's own production code, concatenated.

    The branch's ``json_handler.py`` is left out: it is the fleet's file, not
    the branch's, and byte-identical everywhere since DPLAN-0325.
    """
    apps = Path(branch_path) / "apps"
    if not apps.is_dir():
        return ""
    chunks: list[str] = []
    for source_file in sorted(apps.rglob("*.py")):
        if ".archive" in source_file.parts or source_file.name == "json_handler.py":
            continue
        try:
            chunks.append(source_file.read_text(encoding="utf-8", errors="ignore"))
        except OSError as exc:
            logger.info("test_quality: unreadable while probing for item subjects: %s", exc)
    return "\n".join(chunks)


def _inapplicable_items(branch_path: str) -> set[tuple[str, str]]:
    """The (category, item) pairs this branch ships no subject for."""
    source = _branch_apps_source(branch_path)
    return {key for key, probes in ITEM_SUBJECT_PROBES.items() if not any(p in source for p in probes)}


def _detect_all_coverage(
    file_sources: list[tuple[str, str]],
    inapplicable: set[tuple[str, str]] | None = None,
) -> dict[str, dict[str, str | None]]:
    """Scan test file sources for coverage across all standard categories.

    For each category, for each item, checks if ANY pattern matches in ANY
    ELIGIBLE source file, and returns the file that covers it. Eligibility is
    the subject gate documented at ``SUBJECT_SCOPED_CATEGORY_SIZE``: in a large
    category, one lone token in a file that carries nothing else of that
    category is an accident of vocabulary, not evidence.

    Args:
        file_sources: List of (filename, source_text) tuples.
        inapplicable: (category, item) pairs this branch ships no subject for.
            They are excluded from the eligibility count as well as from the
            score — an item nobody is charged for cannot make a file eligible.

    Returns:
        dict mapping category -> {item -> covering_filename or None}
    """
    skip = inapplicable or set()
    coverage: dict[str, dict[str, str | None]] = {}

    for category, items in STANDARD_CATEGORIES.items():
        scored = {name: patterns for name, patterns in items.items() if (category, name) not in skip}

        # What each file carries of THIS category, before any of it counts.
        carried: dict[str, set[str]] = {}
        for item_name, patterns in scored.items():
            for filename, source in file_sources:
                if any(pattern in source for pattern in patterns):
                    carried.setdefault(filename, set()).add(item_name)

        if len(scored) >= SUBJECT_SCOPED_CATEGORY_SIZE:
            eligible = {f for f, got in carried.items() if len(got) >= SUBJECT_MIN_ITEMS_PER_FILE}
        else:
            eligible = set(carried)

        # The scan itself is unchanged and still goes through the one helper —
        # narrowing the corpus is the whole intervention. Kept in corpus order,
        # so the named carrier does not depend on which item matched first.
        eligible_sources = [(f, source) for f, source in file_sources if f in eligible]
        coverage[category] = {
            item_name: _find_covering_file(patterns, eligible_sources) for item_name, patterns in scored.items()
        }

    return coverage


# =============================================
# BRANCH-LEVEL CHECK
# =============================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> dict:
    """Run test quality analysis on a branch.

    Scans all test files and evaluates coverage across 8 categories
    (7 pattern categories + module coverage).
    Score = total items covered / total items.

    Args:
        branch_path: Path to branch root directory.
        bypass_rules: Optional list of bypass rules from .seedgo/bypass.json.

    Returns:
        dict: {passed, score, checks, standard: 'TEST_QUALITY'}
    """
    checks: list[dict] = []
    bp = Path(branch_path)

    # Check if entire standard is bypassed
    if is_bypassed(branch_path, "test_quality", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Bypassed",
                    "passed": True,
                    "message": "Standard bypassed via .seedgo/bypass.json",
                }
            ],
            "score": 100,
            "standard": "TEST_QUALITY",
        }

    # Validate branch path exists
    if not bp.is_dir():
        return {
            "passed": False,
            "checks": [
                {
                    "name": "Branch exists",
                    "passed": False,
                    "message": f"Branch directory not found: {branch_path}",
                }
            ],
            "score": 0,
            "standard": "TEST_QUALITY",
        }

    # Phase 1: Find all test files
    ignore_entries = load_ignore_entries(bp)
    test_files = _find_all_test_files(bp, ignore_entries)

    if not test_files:
        checks.append(
            {
                "name": "Test files",
                "passed": False,
                "message": "No test_*.py or conftest.py files found in tests/ directory",
            }
        )

        json_handler.log_operation(
            "check_completed",
            {
                "branch": branch_path,
                "score": 0,
                "standard": "test_quality",
                "test_files": 0,
                "items_covered": 0,
            },
        )

        return {
            "passed": False,
            "score": 0,
            "checks": checks,
            "standard": "TEST_QUALITY",
        }

    checks.append(
        {
            "name": "Test files",
            "passed": True,
            "message": f"Found {len(test_files)} test file(s) in tests/",
        }
    )

    # Phase 2: Read all test file sources
    file_sources: list[tuple[str, str]] = []
    for tf in test_files:
        source = _read_file_safe(tf)
        if source:
            file_sources.append((tf.name, source))

    # Phase 3: Detect coverage across all pattern categories.
    #
    # Drop the items this branch ships no subject for, from BOTH sides of the
    # fraction. Reported below rather than applied quietly — a denominator that
    # changes per branch has to be readable from the outside.
    inapplicable = _inapplicable_items(branch_path)

    # And drop the files that execute nothing, before anything is credited to
    # them. Reported the same way, for the same reason.
    live_sources, discounted = _live_carriers(file_sources)
    if discounted:
        checks.append(
            {
                "name": "Carriers",
                "passed": True,
                "message": (
                    f"{len(discounted)} file(s) execute nothing and were not credited: "
                    + ", ".join(f"{f} ({why})" for f, why in sorted(discounted.items()))
                ),
            }
        )

    all_coverage = _detect_all_coverage(live_sources, inapplicable)
    all_coverage = {name: items for name, items in all_coverage.items() if items}
    branch_items_total = TOTAL_ITEMS - len(inapplicable)

    total_items_covered = 0

    # Per-category summary checks (10 pattern categories)
    for category, item_coverage in all_coverage.items():
        cat_total = len(item_coverage)
        cat_covered = sum(1 for f in item_coverage.values() if f is not None)
        total_items_covered += cat_covered
        missing_items = [item for item, f in item_coverage.items() if f is None]

        if cat_covered == cat_total:
            checks.append(
                {
                    "name": category,
                    "passed": True,
                    "message": f"{category}: {cat_covered}/{cat_total} covered",
                }
            )
        else:
            checks.append(
                {
                    "name": category,
                    "passed": False,
                    "message": (f"{category}: {cat_covered}/{cat_total} covered (missing: {', '.join(missing_items)})"),
                }
            )

    # Phase 4: Module coverage (category 11 — from test_coverage_check.py)
    # Uses broader file discovery + import-based module mapping
    broad_test_files = _find_test_files_broad(bp, ignore_entries)
    total_tests = 0
    tested_modules: set[str] = set()
    for tf in broad_test_files:
        source = _read_file_safe(tf)
        if not source:
            continue
        total_tests += len(RE_TEST_FUNC.findall(source))
        tested_modules.update(_analyze_test_file_imports(source))

    if total_tests == 0:
        tested_modules = set()

    all_modules = _collect_testable_modules(bp, ignore_entries)
    total_modules = len(all_modules)

    # 3 module coverage items
    mc_items_covered = 0

    # Item 1: Test files exist
    has_test_files = len(broad_test_files) > 0
    if has_test_files:
        mc_items_covered += 1

    # Item 2: Test functions exist
    has_test_funcs = total_tests > 0
    if has_test_funcs:
        mc_items_covered += 1

    # Item 3: Module coverage >= 25%
    if total_modules > 0:
        covered_count = len(tested_modules & all_modules)
        coverage_pct = (covered_count / total_modules) * 100
    else:
        covered_count = 0
        coverage_pct = 100.0  # Nothing to test = full coverage

    has_module_coverage = coverage_pct >= 25 or total_modules == 0
    if has_module_coverage:
        mc_items_covered += 1

    total_items_covered += mc_items_covered

    # Module coverage check summary
    mc_details: list[str] = []
    if not has_test_files:
        mc_details.append("no test files")
    if not has_test_funcs:
        mc_details.append("no test functions")
    if not has_module_coverage:
        mc_details.append(f"module coverage {coverage_pct:.0f}% < 25%")

    if mc_items_covered == _MODULE_COVERAGE_ITEMS:
        mc_msg = f"module_coverage: {mc_items_covered}/{_MODULE_COVERAGE_ITEMS} covered"
        if total_modules > 0:
            mc_msg += f" ({covered_count}/{total_modules} modules, {total_tests} tests)"
        checks.append(
            {
                "name": "module_coverage",
                "passed": True,
                "message": mc_msg,
            }
        )
    else:
        checks.append(
            {
                "name": "module_coverage",
                "passed": False,
                "message": (
                    f"module_coverage: {mc_items_covered}/{_MODULE_COVERAGE_ITEMS} covered "
                    f"(missing: {', '.join(mc_details)})"
                ),
            }
        )

    # Score = total coverage percentage
    score = int((total_items_covered / branch_items_total) * 100)

    # Overall pass at 75%
    overall_passed = score >= 75

    inapplicable_note = (
        f" -- {len(inapplicable)} of {TOTAL_ITEMS} not applicable to this branch "
        f"({', '.join(sorted(f'{c}/{i}' for c, i in inapplicable))})"
        if inapplicable
        else ""
    )

    # Total categories = 7 pattern + 1 module coverage = 8
    total_categories = len(STANDARD_CATEGORIES) + 1

    # Overall summary check
    if overall_passed:
        checks.append(
            {
                "name": "Overall coverage",
                "passed": True,
                "message": (
                    f"{total_items_covered}/{branch_items_total} items covered "
                    f"across {total_categories} categories ({score}%){inapplicable_note}"
                ),
            }
        )
    else:
        checks.append(
            {
                "name": "Overall coverage",
                "passed": False,
                "message": (
                    f"{total_items_covered}/{branch_items_total} items covered "
                    f"across {total_categories} categories ({score}%){inapplicable_note} "
                    f"-- minimum 75% required"
                ),
            }
        )

    json_handler.log_operation(
        "check_completed",
        {
            "branch": branch_path,
            "score": score,
            "standard": "test_quality",
            "test_files": len(test_files),
            "items_covered": total_items_covered,
            "items_total": branch_items_total,
            "module_coverage": {
                "covered_modules": covered_count,
                "total_modules": total_modules,
                "total_tests": total_tests,
            },
            "category_detail": {
                **{
                    cat: {
                        "covered": sum(1 for f in items.values() if f is not None),
                        "total": len(items),
                    }
                    for cat, items in all_coverage.items()
                },
                "module_coverage": {
                    "covered": mc_items_covered,
                    "total": _MODULE_COVERAGE_ITEMS,
                },
            },
        },
    )

    return {
        "passed": overall_passed,
        "score": score,
        "checks": checks,
        "standard": "TEST_QUALITY",
    }
