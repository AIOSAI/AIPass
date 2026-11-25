# =================== AIPass ====================
# Name: cli_ux_check.py
# Description: CLI UX Standards Checker Handler
# Version: 2.0.0
# Created: 2026-07-17
# Modified: 2026-11-25
# =============================================

"""
CLI UX Standards Checker Handler

Validates that every help surface and every piece of command output in a
branch follows the AIPass house pattern: the entry point and each discovered
module carry the two-tier help, and every print keeps its styling deliberate.
"""

import ast
import re
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from rich.errors import StyleSyntaxError
from rich.style import Style

from aipass.prax import logger
from aipass.sentry.apps.handlers.json import json_handler
from aipass.sentry.apps.handlers.bypass.utils import is_bypassed

APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"

_RICH_TAG = re.compile(r"\[/?[^\[\]]*\]")
#: A tag Rich would apply: no backslash before it, and its inside parses as a style.
_UNESCAPED_TAG = re.compile(r"(?<!\\)\[(/?)([^\[\]]*)\]")
_HELP_NAME = re.compile(r"help|usage|introspection")
#: aipass.cli display helpers: each styles what it prints.
STYLED_HELPERS = frozenset(
    {"header", "success", "error", "warning", "fatal", "section", "operation_start", "operation_complete"}
)
STYLE_KEYWORDS = frozenset({"style", "header_style", "title_style", "border_style", "row_styles"})
#: An interpolated value named like a number, which Rich's highlighter colours on an unstyled line.
_NUMERIC_NAME = re.compile(r"(?i)(count|total|version|num|score|size|percent|pct|elapsed|seconds)")
_NUMERIC_SPEC = re.compile(r"[dfe%n]$|,")
#: A count after a heading's name, "Branches ({}):", is not one of its words.
_COUNT = re.compile(r"\(\{\}\)")


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if entry point follows the AIPass CLI UX house pattern."""
    checks: List[Dict] = []
    path = Path(module_path)

    module_path = Path(module_path).as_posix()

    if is_bypassed(module_path, "cli_ux", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .sentry/bypass.json"}],
            "score": 100,
            "standard": "CLI_UX",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "CLI_UX",
        }

    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [{"name": "CLI UX check", "passed": True, "message": "__init__.py skipped", "declined": True}],
            "score": 100,
            "standard": "CLI_UX",
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading file: {e}"}],
            "score": 0,
            "standard": "CLI_UX",
        }

    if not content.strip():
        return {
            "passed": True,
            "checks": [{"name": "CLI UX check", "passed": True, "message": "Empty file skipped", "declined": True}],
            "score": 100,
            "standard": "CLI_UX",
        }

    try:
        tree = ast.parse(content, filename=module_path)
    except (SyntaxError, ValueError) as e:
        logger.info("Skipped %s: SyntaxError during parse", path)
        return {
            "passed": False,
            "checks": [{"name": "File parseable", "passed": False, "message": f"Syntax error: {e}"}],
            "score": 0,
            "standard": "CLI_UX",
        }

    entry = _is_entry_point(module_path, path)
    introspection_func = _find_function(tree, "print_introspection")
    help_func = _find_function(tree, "print_help")

    if entry or _is_discovered_module(path, tree):
        checks.append(_check_two_tier_help(tree, path.name))
        checks.append(_check_rich_console(introspection_func, help_func, path.name))
        checks.append(_check_title_markup(introspection_func, path.name))
        checks.append(_check_purpose_line(introspection_func, path.name))
        checks.append(_check_help_pointer(introspection_func, path.name))
        checks.append(_check_usage_section(help_func, path.name))
        checks.append(_check_examples_section(help_func, path.name))
    elif introspection_func is not None or help_func is not None:
        checks.append(_check_rich_console(introspection_func, help_func, path.name))
    if entry:
        checks.append(_check_no_internal_modules(path))
    checks.extend(_surface_checks(tree))

    if not checks:
        return {"passed": True, "checks": [], "score": 100, "standard": "CLI_UX"}

    passed_checks = sum(1 for check in checks if check["passed"])
    score = int(passed_checks / len(checks) * 100)
    overall_passed = all(check["passed"] for check in checks)

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "cli_ux"})
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "CLI_UX"}


def _is_entry_point(module_path: str, path: Path) -> bool:
    """Detect if file is an entry point: apps/{name}.py (directly in apps/, not in subdirectory)."""
    if not path.name.endswith(".py"):
        return False
    posix_path = Path(module_path).as_posix()
    if "apps/" not in posix_path:
        return False
    return path.parent.name == "apps"


def _find_function(tree: ast.Module, name: str) -> Optional[ast.FunctionDef]:
    """Find a top-level function definition by name."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _collect_string_constants(func_node: ast.FunctionDef) -> List[str]:
    """Extract all string constants from a function body, including f-string parts."""
    return [
        node.value for node in ast.walk(func_node) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _check_two_tier_help(tree: ast.Module, filename: str) -> Dict:
    """Check 1: Entry point has BOTH print_introspection AND print_help."""
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ("print_introspection", "print_help"):
            found.add(node.name)

    missing = {"print_introspection", "print_help"} - found

    if not missing:
        return {
            "name": "two_tier_help",
            "passed": True,
            "message": f"Both print_introspection() and print_help() found in {filename}",
        }

    missing_str = ", ".join(sorted(missing))
    return {
        "name": "two_tier_help",
        "passed": False,
        "message": f"Entry point must define both print_introspection() and print_help() — {missing_str} not found",
    }


def _check_rich_console(
    introspection_func: Optional[ast.FunctionDef],
    help_func: Optional[ast.FunctionDef],
    filename: str,
) -> Dict:
    """Check 2: Help functions use console.print(), not bare print()."""
    funcs_to_check = []
    if introspection_func is not None:
        funcs_to_check.append(("print_introspection", introspection_func))
    if help_func is not None:
        funcs_to_check.append(("print_help", help_func))

    if not funcs_to_check:
        # Neither function exists -- auto-fail (two_tier_help already catches the root cause)
        return {
            "name": "rich_console",
            "passed": False,
            "message": "Help functions must use console.print() from aipass.cli, not bare print()",
        }

    has_console_print = False
    has_bare_print = False

    for _func_name, func_node in funcs_to_check:
        for node in ast.walk(func_node):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute):
                if (
                    node.func.attr == "print"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "console"
                ):
                    has_console_print = True
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                has_bare_print = True

    if has_bare_print:
        return {
            "name": "rich_console",
            "passed": False,
            "message": "Help functions must use console.print() from aipass.cli, not bare print()",
        }

    if not has_console_print:
        return {
            "name": "rich_console",
            "passed": False,
            "message": "Help functions must use console.print() from aipass.cli, not bare print()",
        }

    return {
        "name": "rich_console",
        "passed": True,
        "message": f"Help functions in {filename} use console.print() (no bare print())",
    }


def _check_title_markup(introspection_func: Optional[ast.FunctionDef], filename: str) -> Dict:
    """Check 3: print_introspection contains a [bold styled title."""
    if introspection_func is None:
        return {
            "name": "title_markup",
            "passed": False,
            "message": ("print_introspection() must include a styled title line (a bold style tag, e.g. bold cyan)"),
        }

    strings = _collect_string_constants(introspection_func)
    for s in strings:
        if "[bold" in s:
            return {
                "name": "title_markup",
                "passed": True,
                "message": f"print_introspection() in {filename} has a styled title with [bold markup",
            }

    return {
        "name": "title_markup",
        "passed": False,
        "message": "print_introspection() must include a styled title line (a bold style tag, e.g. bold cyan)",
    }


def _check_purpose_line(introspection_func: Optional[ast.FunctionDef], filename: str) -> Dict:
    """Check 4: print_introspection contains a [dim] purpose/tagline line."""
    if introspection_func is None:
        return {
            "name": "purpose_line",
            "passed": False,
            "message": "print_introspection() must include a dim-styled purpose/tagline line",
        }

    strings = _collect_string_constants(introspection_func)
    for s in strings:
        if "[dim]" in s:
            return {
                "name": "purpose_line",
                "passed": True,
                "message": f"print_introspection() in {filename} has a [dim] purpose/tagline line",
            }

    return {
        "name": "purpose_line",
        "passed": False,
        "message": "print_introspection() must include a dim-styled purpose/tagline line",
    }


def _check_help_pointer(introspection_func: Optional[ast.FunctionDef], filename: str) -> Dict:
    """Check 5: print_introspection contains a closing pointer to --help."""
    if introspection_func is None:
        return {
            "name": "help_pointer",
            "passed": False,
            "message": "print_introspection() must include a closing pointer to --help for more info",
        }

    strings = _collect_string_constants(introspection_func)
    for s in strings:
        if "--help" in s:
            return {
                "name": "help_pointer",
                "passed": True,
                "message": f"print_introspection() in {filename} includes a --help pointer",
            }

    return {
        "name": "help_pointer",
        "passed": False,
        "message": "print_introspection() must include a closing pointer to --help for more info",
    }


def _check_usage_section(help_func: Optional[ast.FunctionDef], filename: str) -> Dict:
    """Check 6: print_help contains a Usage section."""
    if help_func is None:
        return {
            "name": "usage_section",
            "passed": False,
            "message": "print_help() must include a Usage section",
        }

    strings = _collect_string_constants(help_func)
    for s in strings:
        if "usage" in s.lower():
            return {
                "name": "usage_section",
                "passed": True,
                "message": f"print_help() in {filename} includes a Usage section",
            }

    return {
        "name": "usage_section",
        "passed": False,
        "message": "print_help() must include a Usage section",
    }


def _is_print_call(node: ast.Call) -> bool:
    """``print(...)``, or ``.print(...)`` on a receiver named ``console``."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "print"
    if not (isinstance(func, ast.Attribute) and func.attr == "print"):
        return False
    receiver = func.value
    return (isinstance(receiver, ast.Name) and receiver.id == "console") or (
        isinstance(receiver, ast.Attribute) and receiver.attr == "console"
    )


def _literal_text(node: ast.expr) -> str:
    """The literal text of a string argument; an f-string contributes its constant parts."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(str(part.value) for part in node.values if isinstance(part, ast.Constant))
    return ""


def _printed_headings(func_node: ast.FunctionDef) -> List[str]:
    """Each string a print call inside ``func_node`` prints, Rich markup and outer whitespace removed."""
    texts = [
        _literal_text(arg)
        for node in ast.walk(func_node)
        if isinstance(node, ast.Call) and _is_print_call(node)
        for arg in node.args
    ]
    return [_RICH_TAG.sub("", text).strip() for text in texts]


def _check_examples_section(help_func: Optional[ast.FunctionDef], filename: str) -> Dict:
    """Check 7: print_help prints a heading that starts with Examples; a docstring or unprinted string is not one."""
    if help_func is not None and any(text.lower().startswith("examples") for text in _printed_headings(help_func)):
        return {
            "name": "examples_section",
            "passed": True,
            "message": f"print_help() in {filename} prints an Examples heading",
        }

    return {
        "name": "examples_section",
        "passed": False,
        "message": "print_help() must print an Examples heading",
    }


def _check_no_internal_modules(path: Path) -> Dict:
    """Check 8: modules/ directory does not expose internal plumbing files.
    Files whose stems end with _wire, _fix, _impl, or _internal should be
    underscore-prefixed to hide from discovery.
    """
    internal_suffixes = ("_wire", "_fix", "_impl", "_internal")

    branch_root = path.parent.parent
    modules_dir = branch_root / "apps" / "modules"

    if not modules_dir.is_dir():
        return {
            "name": "no_internal_modules",
            "passed": True,
            "message": "No modules/ directory found (nothing to check)",
        }

    exposed_internal: List[str] = []
    for py_file in modules_dir.glob("*.py"):
        stem = py_file.stem
        if stem.startswith("_"):
            continue
        if any(stem.endswith(suffix) for suffix in internal_suffixes):
            exposed_internal.append(py_file.name)

    if exposed_internal:
        names = ", ".join(sorted(exposed_internal))
        return {
            "name": "no_internal_modules",
            "passed": False,
            "message": (
                f"modules/ directory exposes internal plumbing: {names} "
                f"— prefix with underscore or use COMMAND attribute"
            ),
        }

    return {
        "name": "no_internal_modules",
        "passed": True,
        "message": "No exposed internal plumbing files in modules/",
    }


# ---- the module tier and every print: help surfaces and command output ---------------------


def _is_discovered_module(path: Path, tree: ast.Module) -> bool:
    """apps/modules/<name>.py, no leading underscore, defining handle_command: a module the CLI discovers."""
    if path.parent.name != "modules" or path.parent.parent.name != "apps" or path.name.startswith("_"):
        return False
    return _find_function(tree, "handle_command") is not None


def _is_any_print(node: ast.AST) -> bool:
    """``print(...)``, or ``.print(...)`` on any receiver whose name ends in ``console``."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "print"
    if not (isinstance(func, ast.Attribute) and func.attr == "print"):
        return False
    receiver = func.value
    name = receiver.id if isinstance(receiver, ast.Name) else getattr(receiver, "attr", "")
    return name.endswith("console")


def _keyword(call: ast.Call, name: str) -> Optional[ast.expr]:
    """The value passed to ``name=``, or None."""
    return next((kw.value for kw in call.keywords if kw.arg == name), None)


def _is_false(node: Optional[ast.expr]) -> bool:
    """A literal False."""
    return isinstance(node, ast.Constant) and node.value is False


def _shape(node: Optional[ast.expr]) -> Optional[str]:
    """A printed string's literal text, each interpolated value as ``{}``; None when it is not a string."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(str(part.value) if isinstance(part, ast.Constant) else "{}" for part in node.values)
    return None


def _first_text(call: Optional[ast.Call]) -> Optional[str]:
    """The shape of a print call's first argument."""
    return _shape(call.args[0]) if call is not None and call.args else None


def _style_tags(text: str) -> List[str]:
    """The tags in ``text`` Rich applies as styles; an unknown word in brackets is not one."""
    tags = []
    for closing, inside in _UNESCAPED_TAG.findall(text):
        if closing and not inside:
            tags.append("[/]")
            continue
        if _is_style(inside):
            tags.append(inside)
    return tags


def _is_style(inside: str) -> bool:
    """Whether Rich parses the inside of a bracket as a style; a placeholder word is not one."""
    try:
        Style.parse(inside)
    except StyleSyntaxError:
        return False
    return True


def _styled_call(call: ast.Call) -> bool:
    """A print that applies a style: a style tag in its text, or a style keyword."""
    if any(kw.arg in STYLE_KEYWORDS for kw in call.keywords):
        return True
    return any(_style_tags(_shape(arg) or "") for arg in call.args)


def _numeric_value(node: ast.expr) -> bool:
    """An f-string interpolating ``len(...)``, a number-named value, or a number format."""
    if not isinstance(node, ast.JoinedStr):
        return False
    for part in node.values:
        if not isinstance(part, ast.FormattedValue):
            continue
        spec = _shape(part.format_spec) or ""
        if spec and _NUMERIC_SPEC.search(spec):
            return True
        value = part.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "len":
            return True
        name = value.id if isinstance(value, ast.Name) else getattr(value, "attr", "")
        if name and _NUMERIC_NAME.search(name):
            return True
    return False


def _plain(text: str) -> str:
    """The text with its markup tags removed."""
    return _RICH_TAG.sub("", text)


def _heading(text: str) -> bool:
    """A heading names a section in a few words: column 0, a capital, at most four words, one closing ``:``."""
    plain = _plain(text).rstrip()
    words = _COUNT.sub("", plain[:-1]).split()
    return bool(words) and plain[0].isupper() and plain.endswith(":") and ":" not in plain[:-1] and len(words) <= 4


def _help_scopes(tree: ast.Module) -> List[ast.FunctionDef]:
    """Every function at any depth whose name says it prints help: print_help, print_introspection, _print_usage."""
    return [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and _HELP_NAME.search(node.name)]


def _help_styled(func: ast.FunctionDef) -> bool:
    """A help function styles something: a style tag in any literal, a style keyword, or an aipass.cli helper."""
    for node in ast.walk(func):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _style_tags(node.value):
            return True
        if isinstance(node, ast.keyword) and node.arg in STYLE_KEYWORDS:
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in STYLED_HELPERS:
            return True
    return False


def _row(name: str, findings: List[str], rule: str) -> Dict:
    """One check row: passed with no findings, else every finding and the spelling to use."""
    if not findings:
        return {"name": name, "passed": True, "message": f"{name}: no site found"}
    return {"name": name, "passed": False, "message": f"{name}: {'; '.join(findings)} - {rule}"}


def _blocks(tree: ast.Module) -> Iterator[List[ast.stmt]]:
    """Every statement list in the tree: a body, an else, a finally."""
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                yield block


def _printed_call(stmt: ast.stmt) -> Optional[ast.Call]:
    """The print call a statement is, or None."""
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and _is_any_print(stmt.value):
        return stmt.value
    return None


def _line_findings(prints: List[ast.Call], in_help: set) -> Dict[str, List[str]]:
    """markup_kept, heading_styled and highlight_deliberate sites, one pass over the print calls."""
    found: Dict[str, List[str]] = {"markup_kept": [], "heading_styled": [], "highlight_deliberate": []}
    for call in prints:
        text = _first_text(call)
        off = _is_false(_keyword(call, "markup"))
        if off and (id(call) in in_help or _style_tags(text or "")):
            found["markup_kept"].append(f"line {call.lineno} prints with markup=False")
        if text is None or off or _styled_call(call):
            continue
        if _heading(text):
            found["heading_styled"].append(f"line {call.lineno} '{_plain(text).strip()}'")
        if _is_false(_keyword(call, "highlight")):
            continue
        if any(ch.isdigit() for ch in _plain(text).replace("{}", "")) or _numeric_value(call.args[0]):
            found["highlight_deliberate"].append(f"line {call.lineno}")
    return found


def _unexplained_groups(tree: ast.Module, in_help: set) -> List[str]:
    """Command-output headings that open a list with no [dim] line saying what the group is."""
    found = []
    for block in _blocks(tree):
        for index, stmt in enumerate(block):
            call = _printed_call(stmt)
            text = _first_text(call)
            if call is None or text is None or id(call) in in_help or not _heading(text) or "[dim" in text:
                continue
            following = block[index + 1] if index + 1 < len(block) else None
            if _opens_a_list(following):
                found.append(f"line {call.lineno} '{_plain(text).strip()}'")
    return found


def _opens_a_list(stmt: Optional[ast.stmt]) -> bool:
    """What follows a heading is its list: a loop, or a print of an indented item; a [dim] line explains it instead."""
    if isinstance(stmt, (ast.For, ast.AsyncFor)):
        return True
    text = _first_text(_printed_call(stmt)) if stmt is not None else None
    return bool(text) and "[dim" not in text and _plain(text)[:1].isspace()


def _surface_checks(tree: ast.Module) -> List[Dict]:
    """The rules every print obeys, in help surfaces and command output alike."""
    prints = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and _is_any_print(node)]
    if not prints:
        return []
    help_funcs = _help_scopes(tree)
    in_help = {id(node) for func in help_funcs for node in ast.walk(func)}
    found = _line_findings(prints, in_help)
    unstyled_help = [
        f"{func.name}() line {func.lineno} prints with no style"
        for func in help_funcs
        if any(_is_any_print(node) for node in ast.walk(func)) and not _help_styled(func)
    ]
    highlighted = found["highlight_deliberate"]
    return [
        _row("markup_kept", found["markup_kept"], "keep markup on; escape() the literal brackets (aipass.cli escape)"),
        _row("help_styled", unstyled_help, "style the title, section headings and verbs with Rich markup"),
        _row("heading_styled", found["heading_styled"], "give the heading a style tag, e.g. bold cyan"),
        _row(
            "group_explained",
            _unexplained_groups(tree, in_help),
            "follow a group heading with a dim-styled line saying what the group is",
        ),
        _row(
            "highlight_deliberate",
            [f"{', '.join(highlighted)} coloured only by Rich's number highlighter"] if highlighted else [],
            "style the line, or pass highlight=False",
        ),
    ]
