# =================== AIPass ====================
# Name: fresh_clone_extras.py
# Description: fresh_clone - the OPTIONAL_EXTRA species and the primitives it shares with the checker
# Version: 1.0.0
# Created: 2026-10-10
# Modified: 2026-10-17
# =============================================

"""fresh_clone -- the OPTIONAL_EXTRA species and the primitives it shares.

Not named ``*_check.py``: the pack discovers those as checkers. The checker imports
from here, never the reverse, so the shared primitives live here to avoid a cycle.
Reference: fresh_clone.md
"""

import ast
from typing import Dict, List, Sequence, Set, Tuple, Union

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

#: Import names (not distribution names) of the root pyproject's optional extras, mapped
#: by hand and shipped: the pack reads Python files only. Other projects' extras are invisible.
OPTIONAL_EXTRA_MODULES: frozenset = frozenset(
    {
        "openai",  # llm
        "trinity_pattern",  # trinity
        "numpy",  # memory
        "chromadb",  # memory
        "fastembed",  # memory
        "telethon",  # telegram
        "google",  # drive: google-auth imports as google.auth
        "google_auth_oauthlib",  # drive
        "googleapiclient",  # drive: google-api-python-client
        "atproto",  # bluesky
        "fastapi",  # host
        "uvicorn",  # host
        "multipart",  # host: python-multipart
        "python_multipart",  # host: python-multipart's newer spelling
    }
)

#: The handlers that make an import optional rather than required.
IMPORT_ERRORS: frozenset = frozenset({"ImportError", "ModuleNotFoundError"})


def _tail(dotted: str) -> str:
    """The last component of a dotted call spelling."""
    return dotted.rsplit(".", 1)[-1]


def _is_fixture(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
    """True when a function carries a pytest fixture decorator."""
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if _tail(corpus.dotted_name(target)) == "fixture":
            return True
    return False


def _finding(species: str, unit: corpus.TestUnit, line: int, detail: str) -> Dict:
    """One row, in the shape every rule in this pack reports."""
    return {"nodeid": unit.nodeid, "line": line, "species": species, "detail": detail}


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    """True for ``except ImportError`` / ``ModuleNotFoundError`` (alone or in a tuple)."""
    if handler.type is None:
        return False
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(_tail(corpus.dotted_name(kind)) in IMPORT_ERRORS for kind in types)


def _imported_extras(statement: ast.stmt) -> Set[str]:
    """The optional extras a statement imports, by top-level name."""
    found: Set[str] = set()
    for node in ast.walk(statement):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module.split(".")[0])
    return found & OPTIONAL_EXTRA_MODULES


def _guarded_extras(func: ast.AST) -> Set[str]:
    """Extras a function imports inside ``try:`` whose handler catches ImportError."""
    found: Set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Try) and any(_catches_import_error(handler) for handler in node.handlers):
            for statement in node.body:
                found |= _imported_extras(statement)
    return found


def optional_extra_functions(production_trees: Dict[str, ast.Module]) -> Dict[str, Dict[str, Set[str]]]:
    """Dotted module key -> {module-level function: the extras its own body imports behind except ImportError}.

    Function-local only: a module-level guard is decided at import, a call graph this pack does not follow.
    """
    found: Dict[str, Dict[str, Set[str]]] = {}
    for relpath, tree in production_trees.items():
        functions = {
            node.name: _guarded_extras(node)
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        functions = {name: extras for name, extras in functions.items() if extras}
        if functions:
            key = relpath[: -len(".py")] if relpath.endswith(".py") else relpath
            key = key.replace("/", ".")
            found[key[: -len(".__init__")] if key.endswith(".__init__") else key] = functions
    return found


def _module_key(dotted: str, guarded: Dict[str, Dict[str, Set[str]]]) -> str:
    """The production key an imported dotted name means, by matching the longer tail."""
    for key in guarded:
        shorter = min(dotted, key, key=len)
        if (dotted == key or dotted.endswith("." + key) or key.endswith("." + dotted)) and "." in shorter:
            return key
    return ""


def _from_import_target(module: str, name: str, guarded: Dict[str, Dict[str, Set[str]]]) -> Tuple[str, str]:
    """What ``from module import name`` binds: (key, "") for a module, (key, name) for a guarded function."""
    as_module = _module_key(f"{module}.{name}", guarded)
    if as_module:
        return as_module, ""
    as_member = _module_key(module, guarded)
    if as_member and name in guarded[as_member]:
        return as_member, name
    return "", ""


def product_aliases(tree: ast.Module, guarded: Dict[str, Dict[str, Set[str]]]) -> Dict[str, Tuple[str, str]]:
    """Local name -> (production key, function or "" for the module itself), from the file's imports."""
    aliases: Dict[str, Tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bound = [(alias.asname or alias.name, (_module_key(alias.name, guarded), "")) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            module = node.module
            bound = [
                (alias.asname or alias.name, _from_import_target(module, alias.name, guarded)) for alias in node.names
            ]
        else:
            continue
        aliases.update({local: target for local, target in bound if target[0]})
    return aliases


def _called_guarded(
    call: ast.Call, aliases: Dict[str, Tuple[str, str]], guarded: Dict[str, Dict[str, Set[str]]]
) -> Tuple[str, Set[str]]:
    """(function name, its extras) when the call reaches a guarded product function, else ("", set())."""
    dotted = corpus.dotted_name(call.func)
    if dotted in aliases and aliases[dotted][1]:
        key, name = aliases[dotted]
        return name, guarded[key][name]
    head, _, name = dotted.rpartition(".")
    if head in aliases and not aliases[head][1]:
        functions = guarded[aliases[head][0]]
        if name in functions:
            return name, functions[name]
    return "", set()


def _names_an_extra(nodes: Sequence[ast.AST], extra: str) -> bool:
    """True when a string spelled exactly as the extra (or a submodule of it) appears in any node.

    Exact match, so a docstring that merely mentions the SDK acquits nothing.
    """
    texts = [text for node in nodes for text in corpus.string_constants(node)]
    return any(text == extra or text.startswith(extra + ".") for text in texts)


def _is_autouse(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
    """True when a fixture decorator carries ``autouse=True``."""
    return any(
        keyword.arg == "autouse" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call)
        for keyword in decorator.keywords
    )


def file_extra_controls(tree: ast.Module) -> Tuple[List[ast.AST], Dict[str, ast.AST], List[ast.AST]]:
    """(module-level statements that are not defs or classes, fixtures by name, autouse fixtures)."""
    definitions = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    module_level: List[ast.AST] = [node for node in tree.body if not isinstance(node, definitions)]
    fixtures: Dict[str, ast.AST] = {}
    autouse: List[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_fixture(node):
            fixtures[node.name] = node
            if _is_autouse(node):
                autouse.append(node)
    return module_level, fixtures, autouse


def optional_extra(
    unit: corpus.TestUnit,
    aliases: Dict[str, Tuple[str, str]],
    guarded: Dict[str, Dict[str, Set[str]]],
    controls: Tuple[List[ast.AST], Dict[str, ast.AST], List[ast.AST]],
) -> List[Dict]:
    """OPTIONAL_EXTRA: the unit calls a guarded product function and never takes the extra's presence in hand."""
    module_level, fixtures, autouse = controls
    requested = [fixtures[argument.arg] for argument in unit.node.args.args if argument.arg in fixtures]
    in_scope: List[ast.AST] = [unit.node, *module_level, *requested, *autouse]
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call):
            continue
        name, extras = _called_guarded(node, aliases, guarded)
        inherited = sorted(extra for extra in extras if not _names_an_extra(in_scope, extra))
        if inherited:
            detail = (
                f"calls {name}(), whose `import {inherited[0]}` sits behind except ImportError; the unit neither "
                f"sets sys.modules[{inherited[0]!r}] nor skips on its absence, so the host's install picks the path"
            )
            return [_finding("OPTIONAL_EXTRA", unit, node.lineno, detail)]
    return []
