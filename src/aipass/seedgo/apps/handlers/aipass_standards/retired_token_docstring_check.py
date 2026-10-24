# =================== AIPass ====================
# Name: retired_token_docstring_check.py
# Description: Retired Token Docstring Standards Checker Handler
# Version: 1.1.2
# Created: 2026-09-25
# Modified: 2026-10-24
# =============================================

"""
Retired Token Docstring Standards Checker Handler

Reference: retired_token_docstring.md
"""

from functools import partial
import ast
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.check_support import read_text, result

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "RETIRED_TOKEN_DOCSTRING"
STANDARD_KEY = "retired_token_docstring"
NOT_JUDGED = "Not judged: the file does not parse (ruff convicts that)"

#: Provenance 1 of 2: test_quality_check.py's STANDARD_CATEGORIES as of c1e0eeed^, kept in
#: docs.local/v4_test_quality_check.py.txt. Copied, not edited: this rule convicts THAT vocabulary only.
V4_CATEGORIES: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "cli_routing": {
        "help_flag": ("--help",),
        "short_help": ('"-h"', "'-h'"),
        "help_word": ('"help"', "'help'"),
        "no_args": ("test_no_args", "test_introspection", "no_args"),
        "unknown_command": ("unknown_command", "invalid_command", "unrecognized"),
        "return_bool": ("is True", "is False"),
        "print_help": ("print_help",),
        "print_introspection": ("print_introspection",),
        "output_capture": ("capsys", "capfd", "StringIO"),
    },
    "conftest_fixtures": {
        "temp_dir": ("tmp_path", "temp_test_dir", "temp_dir"),
        "sample_data": ("sample_test_data", "sample_data"),
        "mock_infrastructure": ("mock_infrastructure", "autouse"),
        "mock_logger": ("mock_logger", "mock_log"),
        "cleanup": ("rmtree", "yield", "teardown"),
    },
    "error_resilience": {
        "missing_file": ("FileNotFoundError", "missing_file", "file_not_found"),
        "corrupt_json": ("JSONDecodeError", "corrupt", "malformed"),
        "empty_file": ("empty_file", "empty_content", "test_empty"),
        "nonexistent_dir": ("nonexistent", "missing_dir", "not_a_dir"),
    },
    "return_type_contracts": {
        "command_returns_bool": ("isinstance(result, bool)", ", bool)", "returns_bool", "return_type"),
        "paths_return_path": ("isinstance(result, Path)", "pathlib.Path"),
    },
    "success_failure_paths": {
        "known_routes_true": ("assert result is True", "== True"),
        "unknown_returns_false": ("assert result is False", "== False"),
        "help_preempts": ("--help",),
        "no_args_triggers": ("print_introspection",),
    },
    "init_provisioning": {
        "creates_files": (".exists()", "ensure_json_exists"),
        "auto_creates_dir": ("mkdir", "makedirs"),
        "no_overwrite": ("overwrite", "no_clobber", "already_exists"),
    },
    "infrastructure_mocking": {
        "autouse_fixtures": ("autouse=True", "autouse"),
    },
}

#: Provenance 2 of 2: the items ONLY the 7cd59aa4^ STANDARD_CATEGORIES carries, kept in
#: docs.local/v4_test_quality_check_7cd59aa4parent.py.txt. Copied, not edited; every other item is in V4_CATEGORIES.
V4_RETIRED_EARLIER: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "json_handler": {
        "default_factory": (
            "_create_default",
            "_get_default_template",
            "_get_default",
            "_default_template",
            "load_template",
            "_default_config",
            "_default_document",
        ),
        "validate": ("validate_json_structure",),
        "get_path": ("get_json_path",),
        "ensure_exists": ("ensure_json_exists",),
        "load": ("load_json",),
        "save": ("save_json",),
        "log_operation": ("log_operation",),
        "ensure_module": ("ensure_module_jsons",),
    },
    "conftest_fixtures": {
        "mock_json_handler": ("mock_json_handler", "mock_json"),
    },
    "return_type_contracts": {
        "ensure_returns_bool": ("ensure_json_exists", "is True"),
        "load_correct_type": ("isinstance(result, dict)", "isinstance(data, dict)"),
    },
    "exception_contracts": {
        "create_default_raises": ("pytest.raises(ValueError)", "ValueError", "_create_default"),
        "save_invalid_raises": ("pytest.raises", "save_json"),
        "invalid_mode_raises": ("pytest.raises(ValueError)", "invalid_mode", "invalid_type"),
    },
    "data_structure_contracts": {
        "config_keys": ("module_name", "config_keys"),
        "data_keys": ("last_updated", "data_keys"),
        "log_entry_field": ("log_entry", "operation"),
    },
    "init_provisioning": {
        "returns_dict": ("isinstance(result, dict)", "json_type"),
    },
    "infrastructure_mocking": {
        "sys_modules_mock": ("sys.modules",),
        "reimport_after_mock": ("importlib.reload", "reload("),
    },
}

#: The vocabulary this rule convicts: the union of both commits' STANDARD_CATEGORIES,
#: 10 categories and 48 items. No item name is shared, so a merge per category is the union.
V4_VOCABULARY: Dict[str, Dict[str, Tuple[str, ...]]] = {
    category: {**V4_CATEGORIES.get(category, {}), **V4_RETIRED_EARLIER.get(category, {})}
    for category in {**V4_CATEGORIES, **V4_RETIRED_EARLIER}
}

#: The six lowercase single words v4 grepped for that are code, not English.
CODE_WORDS = frozenset({"capsys", "capfd", "tmp_path", "rmtree", "makedirs", "mkdir"})

#: A capital straight after a lowercase letter: StringIO, FileNotFoundError.
INTERNAL_CAPITAL = re.compile(r"[a-z][A-Z]")

#: What may stand between two terms of a run.
SEPARATOR = re.compile(r"(?:[\s,/]|\band\b|\bor\b)+")

#: The auditor-era label on a run: ``capsys, capfd, StringIO tokens``. It must
#: FOLLOW the run -- "token" in its own sense (an argv token, an auth token, a
#: lexer token) beside a real ``--help`` is not the label.
TOKEN_LABEL = re.compile(r"(?:[\s,/]|\band\b|\bor\b)*tokens?\b", re.IGNORECASE)

#: Two v4 items are the fleet's own CLI contract functions, defined by every
#: module: naming them is naming product. They lengthen a bait list, never make one.
PRODUCT_SURFACE = frozenset({"print_help", "print_introspection"})

#: A quoted code span, ``like this`` or `like this`. Inside one a docstring is quoting
#: code -- a signature ``save_json(module_name, json_type, data)`` -- not listing keywords.
INLINE_LITERAL = re.compile(r"``.+?``|`[^`\n]+`", re.DOTALL)

CURE = "drop the retired v4 keywords; say what the test proves"


def _names() -> List[str]:
    """The 10 category names and 48 item names."""
    names = list(V4_VOCABULARY)
    for items in V4_VOCABULARY.values():
        names.extend(item for item in items if item not in names)
    return names


def is_code_shaped(term: str) -> bool:
    """Whether a v4 term is code a reader would not write as prose."""
    return term in CODE_WORDS or any(mark in term for mark in "_().-") or INTERNAL_CAPITAL.search(term) is not None


def _vocabulary() -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """(T1 terms: every name plus the code-shaped patterns, T2 terms: the code-shaped ones)."""
    names = _names()
    patterns: List[str] = []
    for items in V4_VOCABULARY.values():
        for pats in items.values():
            patterns.extend(p for p in pats if p not in patterns and p not in names)
    code = [p for p in patterns if is_code_shaped(p)]
    t1 = tuple(names + code)
    t2 = tuple(term for term in t1 if is_code_shaped(term))
    return t1, t2


T1_TERMS, T2_TERMS = _vocabulary()


def _term_regex(term: str) -> str:
    """A term as a regex, bounded as a word only at ends that are word characters."""
    head = r"(?<!\w)" if re.match(r"\w", term) else ""
    tail = r"(?!\w)" if re.search(r"\w$", term) else ""
    return head + re.escape(term) + tail


def _alternation(terms: Tuple[str, ...]) -> re.Pattern[str]:
    """One pattern for many terms, longest first so ``test_no_args`` beats ``no_args``."""
    ordered = sorted(terms, key=len, reverse=True)
    return re.compile("|".join(_term_regex(term) for term in ordered))


T1_PATTERN = _alternation(T1_TERMS)
T2_PATTERN = _alternation(T2_TERMS)


def runs(text: str, pattern: re.Pattern[str]) -> List[Tuple[List[str], int]]:
    """(terms, end offset) for every run of terms joined only by separators."""
    found: List[Tuple[List[str], int]] = []
    current: List[str] = []
    last_end = -1
    for match in pattern.finditer(text):
        if current and SEPARATOR.fullmatch(text[last_end : match.start()]):
            current.append(match.group())
        else:
            if current:
                found.append((current, last_end))
            current = [match.group()]
        last_end = match.end()
    if current:
        found.append((current, last_end))
    return found


def labelled_runs(text: str) -> List[List[str]]:
    """T1: every run of v4 terms, one code-shaped, the docstring labels ``token``/``tokens``."""
    return [
        terms
        for terms, end in runs(text, T1_PATTERN)
        if TOKEN_LABEL.match(text, end) and any(is_code_shaped(term) for term in terms)
    ]


def bait_runs(text: str) -> List[List[str]]:
    """T2: every run of two or more code-shaped terms that is not all product surface."""
    return [
        terms
        for terms, _end in runs(text, T2_PATTERN)
        if len(terms) >= 2 and any(term not in PRODUCT_SURFACE for term in terms)
    ]


def judge(docstring: str) -> Tuple[str, List[str]] | None:
    """(shape, matched terms) when a docstring carries v4 cargo, else None.

    Quoted code spans are emptied first, so no term inside one counts and no run
    crosses one.
    """
    prose = INLINE_LITERAL.sub("``", docstring)
    shapes: List[str] = []
    terms: List[str] = []
    for shape, found in (("T1", labelled_runs(prose)), ("T2", bait_runs(prose))):
        if found:
            shapes.append(shape)
            terms.extend(term for run in found for term in run)
    if not shapes:
        return None
    return "+".join(shapes), list(dict.fromkeys(terms))


def docstrings(tree: ast.Module) -> List[Tuple[int, str]]:
    """(line, text) for the module's docstring and every class and function docstring."""
    found: List[Tuple[int, str]] = []
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, owners) or not node.body:
            continue
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            found.append((first.lineno, first.value.value))
    return sorted(found)


def scan(source: str) -> Optional[List[Tuple[int, str, List[str]]]]:
    """(line, shape, terms) for every docstring in the file that carries v4 cargo.

    None when the source does not parse: nothing was judged, which is not the [] of a clean file.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        logger.info("[retired_token_docstring] Unparseable test file: %s", exc)
        return None
    found: List[Tuple[int, str, List[str]]] = []
    for line, text in docstrings(tree):
        verdict = judge(text)
        if verdict:
            found.append((line, verdict[0], verdict[1]))
    return found


_read = partial(read_text, tag="retired_token_docstring", errors="ignore")
_result = partial(result, standard=STANDARD)


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Retired token docstring", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check that no test docstring carries the retired v4 auditor's keywords."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)

    findings = scan(source)
    if findings is None:
        return _result(True, _one_check(True, NOT_JUDGED), 100)
    if not findings:
        return _result(True, _one_check(True, "No docstring carries the retired v4 keywords"), 100)

    # One check for every hit: checklist._format_failure prints only the first failed check plus "(+N more)".
    detail = "\n".join(
        f"{path.name}:{line} docstring carries v4 cargo [{shape}] {', '.join(terms)} - {CURE}"
        for line, shape, terms in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
