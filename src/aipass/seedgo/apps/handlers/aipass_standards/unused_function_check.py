# =================== AIPass ====================
# Name: unused_function_check.py
# Description: Unused Function Standards Checker Handler
# Version: 1.1.0
# Created: 2026-03-22
# Modified: 2026-10-17
# =============================================

"""
Unused Function Standards Checker Handler

Reference: unused_function.md
"""

import ast
import importlib.util
import io
import re
import tokenize
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.bypass.ignore_handler import is_seedgo_ignored, load_ignore_entries
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import in_skipped_dir, is_disabled_file

# APPLIES_TO: same discovery problem as dead_code - a test function has no caller by name.
APPLIES_TO = "production"
AUDIT_SCOPE = "branch_level"

# Skipped beside SOURCE_SKIP_DIRS (read through in_skipped_dir, which spares a
# live package such as commons' apps/handlers/artifacts/), whatever they hold.
SKIP_DIRS = frozenset({"tests", "json_templates"})

EXCLUDED_NAMES = {
    "main",
    "handle_command",
}

_MAIN_BLOCK_RE = re.compile(
    r"""^if\s+__name__\s*==\s*["']__main__["']\s*:.*""",
    re.MULTILINE | re.DOTALL,
)


#: A string literal that is a whole dotted path: names or f-string fields, two or more, a name last.
DOTTED_PATH = re.compile(
    r"[rRbBuUfF]*(?P<q>['\"])(?:\{[^{}]*\}|[A-Za-z_]\w*)(?:\.(?:\{[^{}]*\}|[A-Za-z_]\w*))*"
    r"\.(?P<name>[A-Za-z_]\w*)(?P=q)"
)


def _should_skip(path: Path, branch_root: Path, ignore_entries: list) -> bool:
    """True for a skipped dir, a top-level dot dir, a disabled file, or a .seedgoignore match.

    Parts are relative to ``branch_root`` so a branch under ``tests/`` is still read; hooks
    keeps promoted engine copies under ``.live-<stamp>/``, and a row charged to a copy cannot be cured.
    """
    parts = path.relative_to(branch_root).parts
    return (
        in_skipped_dir(path, branch_root)
        or any(part in SKIP_DIRS for part in parts)
        or (len(parts) > 1 and parts[0].startswith("."))
        or is_disabled_file(path.name)
        or is_seedgo_ignored(str(path), branch_root, ignore_entries)
    )


def _collect_python_files(branch_path: Path, ignore_entries: list) -> list[Path]:
    """Collect all .py files in the branch, skipping irrelevant dirs."""
    files: list[Path] = []
    if not branch_path.is_dir():
        return files
    for py_file in branch_path.rglob("*.py"):
        if _should_skip(py_file, branch_path, ignore_entries):
            continue
        files.append(py_file)
    return sorted(files)


def _strip_non_code(source: str) -> str:
    """Remove string literals, comments, and __main__ blocks from source.

    The tokenizer, not a regex: a regex reads ``'\"\"\"'`` in code as a delimiter.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError) as exc:
        # IndentationError (mid-save) is a SyntaxError, not a TokenError; escaping scores the branch 0.
        logger.info("Tokenizer failed, falling back to raw corpus: %s", exc)
        return _MAIN_BLOCK_RE.sub("", source)

    lines = source.split("\n")
    chars = [list(line) for line in lines]

    for start, end, names in _non_code_spans(tokens, lines):
        _blank_span(chars, start, end, " ".join(names))

    result = "\n".join("".join(line) for line in chars)
    return _MAIN_BLOCK_RE.sub("", result)


def _non_code_spans(tokens: list, lines: list[str]):
    """Yield (start, end, kept names) for every string and comment, an f-string whole.

    3.12+ tokenizes an f-string in parts, 3.10/3.11 as one STRING; both yield its field names only.
    """
    fstring_start = getattr(tokenize, "FSTRING_START", None)
    fstring_end = getattr(tokenize, "FSTRING_END", None)
    depth, opened = 0, (0, 0)
    for tok in tokens:
        if fstring_start is not None and tok.type == fstring_start:
            opened = tok.start if depth == 0 else opened
            depth += 1
        elif fstring_end is not None and tok.type == fstring_end:
            depth -= 1
            if depth == 0:
                literal = _segment(lines, opened, tok.end)
                yield opened, tok.end, (_field_names(literal) or []) + _path_target(literal)
        elif depth == 0 and tok.type in (tokenize.STRING, tokenize.COMMENT):
            fields = tok.type == tokenize.STRING and _is_fstring(tok.string)
            named = (_field_names(tok.string) or []) if fields else []
            yield tok.start, tok.end, named + (_path_target(tok.string) if tok.type == tokenize.STRING else [])


def _path_target(literal: str) -> list[str]:
    """The last segment of a string that is a dotted import path and nothing else.

    A registry names a handler by its path and a loader calls it by that name.
    """
    match = DOTTED_PATH.fullmatch(literal)
    return [match.group("name")] if match else []


def _is_fstring(literal: str) -> bool:
    """True when a string token's prefix carries f, in any case and order."""
    prefix = literal[: len(literal) - len(literal.lstrip("rRbBuUfF"))]
    return "f" in prefix.lower()


def _segment(lines: list[str], start: tuple[int, int], end: tuple[int, int]) -> str:
    """The source text between two tokenizer positions (rows count from 1)."""
    (sr, sc), (er, ec) = start, end
    if sr == er:
        return lines[sr - 1][sc:ec]
    return "\n".join([lines[sr - 1][sc:], *lines[sr : er - 1], lines[er - 1][:ec]])


def _field_names(literal: str) -> list[str] | None:
    """Every identifier an f-string's replacement fields name; None when it does not parse."""
    try:
        tree = ast.parse(literal, mode="eval")
    except SyntaxError as exc:
        logger.info("Could not parse an f-string for its fields, blanked whole: %s", exc)
        return None
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            names.append(node.arg)
    return names


def _blank_span(chars: list[list[str]], start: tuple[int, int], end: tuple[int, int], kept: str) -> None:
    """Blank a token span, then write what it keeps at its first column."""
    sr, sc = start[0] - 1, start[1]
    er, ec = end[0] - 1, end[1]
    for row in range(sr, min(er, len(chars) - 1) + 1):
        col_start = sc if row == sr else 0
        col_end = ec if row == er else len(chars[row])
        for col in range(col_start, min(col_end, len(chars[row]))):
            chars[row][col] = " "
    if kept and sr < len(chars):
        row = chars[sr]
        for offset, char in enumerate(kept):
            if sc + offset < len(row):
                row[sc + offset] = char
            else:
                row.append(char)


def _is_excluded(name: str) -> bool:
    """Return True if this function name should never be flagged."""
    if name.startswith("__") and name.endswith("__"):
        return True
    if name in EXCLUDED_NAMES:
        return True
    return False


def _has_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if the function has any decorator."""
    return len(node.decorator_list) > 0


def _imported_names(tree: ast.AST) -> dict[str, str]:
    """Map each name an absolute import binds to the dotted path it names."""
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                names[alias.asname or top] = alias.name if alias.asname else top
    return names


def _dotted_base(base: ast.expr, imports: dict[str, str]) -> str | None:
    """Resolve a class base (Name or attribute chain) through the imports, or None."""
    attrs: list[str] = []
    while isinstance(base, ast.Attribute):
        attrs.insert(0, base.attr)
        base = base.value
    if not isinstance(base, ast.Name) or base.id not in imports:
        return None
    return ".".join([imports[base.id], *attrs])


def _module_file(module: str) -> Path | None:
    """Locate a module's .py source WITHOUT importing it.

    find_spec runs only on the top-level name (a submodule's find_spec would
    execute its parent package); the rest of the path is walked on disk.
    """
    parts = module.split(".")
    spec = importlib.util.find_spec(parts[0])
    if spec is None or not spec.origin:
        return None
    path = Path(spec.origin)
    locations = list(spec.submodule_search_locations or [])
    for part in parts[1:]:
        candidates = [Path(loc) / part / "__init__.py" for loc in locations]
        candidates += [Path(loc) / f"{part}.py" for loc in locations]
        found = next((c for c in candidates if c.is_file()), None)
        if found is None:
            return None
        path = found
        locations = [str(found.parent)] if found.name == "__init__.py" else []
    return path if path.suffix == ".py" else None


_BASE_METHODS: dict[str, set[str]] = {}


def _base_methods(dotted: str) -> set[str]:
    """Names of the methods an imported class defines in its own body (read, never run)."""
    if dotted not in _BASE_METHODS:
        module, _, class_name = dotted.rpartition(".")
        source_file = _module_file(module) if module else None
        methods: set[str] = set()
        if source_file is not None:
            try:
                tree = ast.parse(source_file.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                logger.info("Skipped base %s: SyntaxError in %s", dotted, source_file)
                tree = ast.Module(body=[], type_ignores=[])
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    methods = {
                        item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    }
        _BASE_METHODS[dotted] = methods
    return _BASE_METHODS[dotted]


def _overrides(tree: ast.AST) -> set[int]:
    """ids of methods that override a method their imported base class defines.

    The base calls its own method by name, so the override is used though nothing here names it.
    """
    imports = _imported_names(tree)
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        inherited: set[str] = set()
        for base in node.bases:
            dotted = _dotted_base(base, imports)
            if dotted is not None:
                inherited |= _base_methods(dotted)
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in inherited:
                found.add(id(item))
    return found


def _extract_functions(py_file: Path) -> list[tuple[str, int]] | None:
    """(name, line) of each judged function; None when the file does not parse.

    None is not "no functions": check_branch names the file under ``unparsed``.
    """
    try:
        source = py_file.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError:
        logger.info("Skipped %s: SyntaxError during parse", py_file)
        return None

    overrides = _overrides(tree)
    results: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_excluded(node.name):
                continue
            if _has_decorator(node):
                continue
            if id(node) in overrides:
                continue
            results.append((node.name, node.lineno))
    return results


def _count_references_in_corpus(func_name: str, corpus: str) -> int:
    """Count word-bounded occurrences of func_name, def lines included."""
    pattern = re.compile(rf"\b{re.escape(func_name)}\b")
    return len(pattern.findall(corpus))


def _count_def_lines(func_name: str, corpus: str) -> int:
    """Count definition lines (def func_name / async def func_name) in corpus."""
    pattern = re.compile(
        rf"\basync\s+def\s+{re.escape(func_name)}\b"
        rf"|\bdef\s+{re.escape(func_name)}\b"
    )
    return len(pattern.findall(corpus))


# For a name of word characters only, `\bNAME\b` matches exactly the runs equal to NAME.
_WORD = re.compile(r"\w+")

# Zero-width lookahead: `async def NAME` counts once, as the per-name alternation does.
_DEF = re.compile(r"(?=\bdef\s+(\w+))")


def _corpus_counts(corpus: str) -> tuple[dict[str, int], dict[str, int]]:
    """(word counts, definition-line counts) for the corpus, in one pass each.

    A name with a non-``\\w`` character is not answered here; the caller scans for it by name.
    """
    words: dict[str, int] = {}
    for word in _WORD.findall(corpus):
        words[word] = words.get(word, 0) + 1
    defs: dict[str, int] = {}
    for name in _DEF.findall(corpus):
        defs[name] = defs.get(name, 0) + 1
    return words, defs


def check_branch(branch_path: str, bypass_rules: list | None = None) -> dict:
    """Check a branch for unused function definitions."""
    branch = Path(branch_path)

    if is_bypassed(branch_path, "unused_function", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "score": 100,
            "checks": [
                {
                    "name": "Bypassed",
                    "passed": True,
                    "message": "Standard bypassed via .seedgo/bypass.json",
                }
            ],
            "standard": "UNUSED_FUNCTION",
        }

    ignore_entries = load_ignore_entries(branch)
    py_files = _collect_python_files(branch, ignore_entries)
    if not py_files:
        json_handler.log_operation(
            "check_completed",
            {"branch": branch_path, "score": 100, "standard": "unused_function"},
        )
        return {
            "passed": True,
            "score": 100,
            "checks": [
                {
                    "name": "Unused functions",
                    "passed": True,
                    "message": "No .py files found in branch",
                }
            ],
            "standard": "UNUSED_FUNCTION",
        }

    file_sources: dict[Path, str] = {}
    for py_file in py_files:
        try:
            raw = py_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            logger.info("Cannot read %s for unused function analysis", py_file)
            continue
        file_sources[py_file] = _strip_non_code(raw)

    corpus = "\n".join(file_sources.values())

    all_functions: list[tuple[str, int, Path]] = []
    unparsed: list[str] = []
    for py_file in py_files:
        functions = _extract_functions(py_file)
        if functions is None:
            unparsed.append(py_file.relative_to(branch).as_posix())
            continue
        for func_name, lineno in functions:
            all_functions.append((func_name, lineno, py_file))

    total_functions = len(all_functions)

    if total_functions == 0:
        json_handler.log_operation(
            "check_completed",
            {"branch": branch_path, "score": 100, "standard": "unused_function"},
        )
        return {
            "passed": True,
            "score": 100,
            "checks": [
                {
                    "name": "Unused functions",
                    "passed": True,
                    "message": "No eligible functions found",
                }
            ],
            "standard": "UNUSED_FUNCTION",
            "unparsed": unparsed,
        }

    unused_functions: list[dict] = []
    word_counts, def_counts = _corpus_counts(corpus)

    for func_name, lineno, py_file in all_functions:
        if is_bypassed(str(py_file), "unused_function", lineno, bypass_rules, name=func_name):
            continue

        if _WORD.fullmatch(func_name):
            total_refs = word_counts.get(func_name, 0)
            def_count = def_counts.get(func_name, 0)
        else:
            total_refs = _count_references_in_corpus(func_name, corpus)
            def_count = _count_def_lines(func_name, corpus)
        call_refs = total_refs - def_count

        if call_refs <= 0:
            try:
                rel_path = py_file.relative_to(branch)
            except ValueError:
                logger.info("File %s not relative to branch, using full path", py_file)
                rel_path = py_file
            unused_functions.append(
                {
                    "name": func_name,
                    "file": str(rel_path),
                    "line": lineno,
                }
            )

    clean_count = total_functions - len(unused_functions)
    score = int(clean_count / total_functions * 100) if total_functions > 0 else 100
    passed = score >= 75

    if unused_functions:
        details = [f"  {uf['name']} ({uf['file']}:{uf['line']})" for uf in unused_functions[:15]]
        if len(unused_functions) > 15:
            details.append(f"  ... and {len(unused_functions) - 15} more")
        detail_text = "\n".join(details)

        # Says "no caller in this branch", never "unused": cross-branch and importlib callers are invisible.
        checks = [
            {
                "name": "Unused functions",
                "passed": passed,
                "message": (
                    f"{len(unused_functions)} with no caller in this branch, out of "
                    f"{total_functions} functions ({score}% clean) — a static per-branch scan; "
                    f"cross-branch and dynamic (importlib) callers are NOT visible to it, so "
                    f"confirm before deleting\n{detail_text}"
                ),
                "unused": unused_functions,
            }
        ]
    else:
        checks = [
            {
                "name": "Unused functions",
                "passed": True,
                "message": f"All {total_functions} functions are referenced",
            }
        ]

    json_handler.log_operation(
        "check_completed",
        {
            "branch": branch_path,
            "score": score,
            "standard": "unused_function",
            "total_functions": total_functions,
            "unused_count": len(unused_functions),
        },
    )

    return {
        "passed": passed,
        "score": score,
        "checks": checks,
        "standard": "UNUSED_FUNCTION",
        "unparsed": unparsed,
    }
