# =================== AIPass ====================
# Name: retired_token_docstring_check.py
# Description: Retired Token Docstring Standards Checker Handler
# Version: 1.1.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""
Retired Token Docstring Standards Checker Handler

The v4 keyword auditor (``test_quality``, removed in commit c1e0eeed) scored a
test file by grepping it for keyword patterns. Agents learned the grep and
wrote the keywords into test docstrings as bait:

  ``test_cli_routing.py:762``   "Test output capture -- capsys, capfd, StringIO tokens."
  ``test_handlers_filesystem.py:175``   "Second call doesn't fail -- no_overwrite, already_exists."

The gate is gone; the cargo stays, and it tells a reader nothing about what the
test proves. This rule convicts it, in docstrings only (module, class,
function). Comments and other strings are not judged.

THE VOCABULARY is the retired file's own ``STANDARD_CATEGORIES``, taken from
two commits and embedded verbatim below as their union -- 10 categories, 48 items:
  * c1e0eeed^ (the commit that removed the file), 7 categories and 28 items:
    ``V4_CATEGORIES``.
  * 7cd59aa4^ (the parent of DPLAN-0325 part B, 2026-09-03, which retired 20
    items), the same path apps/handlers/aipass_standards/test_quality_check.py:
    ``V4_RETIRED_EARLIER`` holds the 20 items only it carries -- whole
    categories json_handler, exception_contracts, data_structure_contracts, and
    mock_json_handler, ensure_returns_bool, load_correct_type, returns_dict,
    sys_modules_mock, reimport_after_mock. The auditor graded against them for
    months, so their bait is still in the fleet.
Nothing is added to either: ``patterns, whitelist`` reads like bait and is not
v4's, so it is not convicted.

CODE-SHAPED. A plain English pattern (``yield``, ``corrupt``, ``operation``,
``is True``) is how people write about tests and never counts on its own. A
term is code-shaped when it is a category or item name with an underscore, or
a pattern holding one of ``_ ( ) . -``, or CamelCase (``StringIO``,
``ValueError``), or one of ``capsys capfd tmp_path rmtree makedirs mkdir``.
Four item names have no underscore -- ``cleanup``, ``load``, ``save``,
``validate`` -- and are English: they never count for T2, and a T1 run needs a
code-shaped term besides them ("validate tokens" is about auth, not v4).

QUOTED CODE. A span in backticks is emptied before judging: inside one a
docstring quotes code (``save_json(module_name, json_type, data)``, a real
signature), it does not list keywords. No run crosses a quoted span.

TWO SHAPES, one finding per docstring:
  * T1 TOKEN LABEL -- a run of v4 terms (any category or item name, or a
    code-shaped pattern; at least one code-shaped) that the docstring labels
    ``token``/``tokens``: ``capsys, capfd, StringIO tokens``, ``output_capture
    token``. "token" was the auditor's word for its patterns; the label is the
    fingerprint.
  * T2 BAIT LIST -- two or more code-shaped v4 terms in a row, separated by
    nothing but commas, slashes, ``and``/``or`` and whitespace.

CHECK FIRST (2026-09-25, 596 fleet test files; .archive and seedgo fixtures out).
The first cut read T1 as "says token ANYWHERE and names a v4 term": 20 files,
27 docstrings, and 11 of its 15 T1 hits were "token" in its own sense -- an argv
token beside ``--help`` (daemon, drone, trigger, seedgo, hooks), a shell token
beside ``mkdir``, a wrapped tmp_path "mid-token" (canary, spawn), api's auth
tokens. So the label must FOLLOW the run. Three T2 hits were
``print_introspection and print_help`` naming real functions (api x2, seedgo
test_checkers_batch7): those two items are the fleet's own CLI contract, so
they can lengthen a bait list but never make one. After both: 7 files
convicted, 13 docstrings (T1 4, T2 12, both 3) -- backup 2 files / 8, api 3 / 3,
commons 1 / 1, drone 1 / 1; every one read and every one cargo. The model file
passes.

CHECK AGAIN with the 7cd59aa4^ items (2026-09-25, 598 files; backup had cured
its 8 live). c1e0eeed^ alone: 5 files, 5 docstrings (api 3, commons 1, drone 1).
The union: 7 files, 8 docstrings -- api test_init_provisioning now also names
returns_dict; memory test_contracts 2 new (``_create_default / ValueError``,
``invalid_mode / invalid_type`` -- cargo); aipass conftest 1 new
(``log_operation and ensure_module_jsons`` naming the two functions its
mock_json_handler fixture patches -- read as a false positive, left standing:
quoting them in backticks cures it). Two more in seedgo
test_json_handler_contract.py were the signature ``(module_name, json_type)``
in backticks -- the QUOTED CODE rule, which changes none of the other hits.
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "RETIRED_TOKEN_DOCSTRING"
STANDARD_KEY = "retired_token_docstring"

#: Provenance (1 of 2): STANDARD_CATEGORIES of apps/handlers/aipass_standards/test_quality_check.py
#: as of c1e0eeed^ (the commit that removed it), kept in
#: docs.local/v4_test_quality_check.py.txt. Copied, not edited: this rule convicts
#: THAT vocabulary and no other.
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

#: Provenance (2 of 2): the items ONLY the older STANDARD_CATEGORIES carries -- the same file
#: as of 7cd59aa4^, the parent of the commit (DPLAN-0325 part B, 2026-09-03) that
#: retired 20 of them, kept in docs.local/v4_test_quality_check_7cd59aa4parent.py.txt.
#: Copied, not edited. The auditor graded against these for months, so the bait they
#: taught is still in the fleet (``returns_dict, isinstance(result, dict), json_type
#: tokens``). Every other item at 7cd59aa4^ is in V4_CATEGORIES with the same patterns
#: or a subset of them (``empty_file`` gained ``test_empty``, ``command_returns_bool``
#: gained ``, bool)`` after it), so nothing else differs.
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


def scan(source: str) -> List[Tuple[int, str, List[str]]]:
    """(line, shape, terms) for every docstring in the file that carries v4 cargo."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.info("[retired_token_docstring] Unparseable test file: %s", exc)
        return []
    found: List[Tuple[int, str, List[str]]] = []
    for line, text in docstrings(tree):
        verdict = judge(text)
        if verdict:
            found.append((line, verdict[0], verdict[1]))
    return found


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[retired_token_docstring] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Retired token docstring", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check that no test docstring carries the retired v4 auditor's keywords.

    Args:
        module_path: Path to the file to check.
        bypass_rules: Optional bypass rules, applied per standard.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)

    findings = scan(source)
    if not findings:
        return _result(True, _one_check(True, "No docstring carries the retired v4 keywords"), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per docstring would hide the rest.
    detail = "\n".join(
        f"{path.name}:{line} docstring carries v4 cargo [{shape}] {', '.join(terms)} - {CURE}"
        for line, shape, terms in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
