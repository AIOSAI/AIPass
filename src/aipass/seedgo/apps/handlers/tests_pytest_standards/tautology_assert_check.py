# =================== AIPass ====================
# Name: tautology_assert_check.py
# Description: nominator - an assert whose two sides are the same object (TAUTOLOGY-ASSERT)
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-10-17
# =============================================

"""An assertion whose two sides are provably the same thing cannot fail.

Reference: tautology_assert.md
"""

import ast
from typing import Dict, List, Optional, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

GROUP = "static_tautology_assert"

ALWAYS_TRUE_OPS: tuple = (ast.Eq, ast.Is)

#: A guaranteed red, not a guaranteed green: reported in its own words.
ALWAYS_FALSE_OPS: tuple = (ast.NotEq, ast.IsNot)

RELOAD_FUNCTION = "reload"

RELOAD_MODULE = "importlib"

MODULE_TABLE = "sys.modules"


def _tautology_why(operator_text: str, source: str) -> str:
    """Wording for a structural self-comparison that can never fail."""
    return (
        f"both sides of this `{operator_text}` are the same expression ({source}), so the assertion "
        f"holds whatever the code under test does - it reports the colour a working assertion "
        f"reports and measures nothing"
    )


def _contradiction_why(operator_text: str, source: str) -> str:
    """Wording for a structural self-comparison that can never pass."""
    return (
        f"both sides of this `{operator_text}` are the same expression ({source}), so the assertion "
        f"can never hold - this is a guaranteed failure rather than a check, and the opposite "
        f"defect to a tautology"
    )


SPECIFICATION = {
    "rule": "TAXONOMY section 5 rule 10 - an assertion whose two sides are the same object",
    "species": ["TAUTOLOGY-ASSERT"],
    "flags": [
        "an `assert` whose `==`/`is` compares two structurally identical expressions - it cannot fail",
        "an `assert` whose `!=`/`is not` compares two structurally identical expressions - it cannot pass",
        "an `assert` comparing a name bound from importlib.reload(X) against another name for the "
        "same module: reload returns the object it was handed, so both sides are one object",
    ],
    "exempts": [
        "any comparison whose two sides differ in any way - this rule makes no judgement call",
        "a reload compared against a value captured BEFORE the reload, which is the correct shape",
        "a sys.modules lookup no reload touched - the rule reads reload bindings, not the table",
        "a module object laundered through an intermediate variable, which is not resolved here",
    ],
    "fix": (
        "capture the value BEFORE the action under test and compare the after against the "
        "captured before, or assert against a spelled-out expected value. importlib.reload "
        "returns the same module object it was handed, so reloading proves nothing on its own."
    ),
    "limits": [
        "a deliberate `__eq__` pin on a value type is nominated; that is why this tier nominates "
        "and the execution tier convicts (Law M1)",
        "two identical CALL expressions are reported as identical, and a call with side effects "
        "may legitimately return different values each time",
        "module identity is resolved through import aliases and sys.modules only - any other "
        "route to the same object is invisible, which biases this rule toward FEWER nominations",
    ],
    "evidence": (
        "canary's test_branch_name_is_set_at_import_time asserts reloaded.__version__ == "
        "canary_entry.__version__ under a docstring explaining that the reload is what makes it "
        "meaningful; reload returns its own argument, so the line compares an attribute to itself"
    ),
}


def _source(node: ast.AST) -> str:
    """Source text for an expression, or "" when it will not unparse.

    A failure is logged: "could not read" and "read and clean" must differ (Law S1).
    """
    try:
        return ast.unparse(node)
    except (ValueError, AttributeError, RecursionError) as exc:
        logger.warning(f"[AUDIT-TESTS] tautology_assert could not read an expression, so it cleared nothing: {exc}")
        return ""


def _shape(node: ast.AST) -> str:
    """The node's structure with line and column information stripped.

    Nothing normalised beyond position, on purpose: the rule has no judgement call in it.
    """
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def _operator_text(operator: ast.cmpop) -> str:
    """The comparison operator as a reader would type it."""
    return {ast.Eq: "==", ast.NotEq: "!=", ast.Is: "is", ast.IsNot: "is not"}.get(type(operator), "?")


def _self_comparisons(unit: corpus.TestUnit) -> List[Tuple[ast.Compare, ast.cmpop, ast.expr]]:
    """Every `assert` comparison whose two sides are structurally identical."""
    found: List[Tuple[ast.Compare, ast.cmpop, ast.expr]] = []

    for statement in corpus.asserts_in(unit):
        for node in ast.walk(statement.test):
            if not isinstance(node, ast.Compare):
                continue
            left = node.left
            for operator, comparator in zip(node.ops, node.comparators):
                if not isinstance(operator, ALWAYS_TRUE_OPS + ALWAYS_FALSE_OPS):
                    continue
                if _shape(left) == _shape(comparator):
                    found.append((node, operator, left))
                left = comparator

    return found


def _structural_rows(unit: corpus.TestUnit) -> List[dict]:
    """Nominations from leg one, one per self-comparing assertion."""
    rows: List[dict] = []

    for node, operator, side in _self_comparisons(unit):
        text = _operator_text(operator)
        source = _source(side)
        always_true = isinstance(operator, ALWAYS_TRUE_OPS)
        why = _tautology_why(text, source) if always_true else _contradiction_why(text, source)
        rows.append(
            corpus.nomination(
                "TAUTOLOGY-ASSERT",
                unit,
                why,
                verdict=corpus.VERDICT_IMPROVE,
                line=node.lineno,
                evidence={
                    "leg": "structural",
                    "operator": text,
                    "expression": source,
                    "outcome": "cannot fail" if always_true else "cannot pass",
                },
            )
        )

    return rows


def _import_aliases(parsed: corpus.TestFile) -> Tuple[Dict[str, str], Set[str]]:
    """Names this module binds to modules, and every module path it imports."""
    aliases: Dict[str, str] = {}
    modules: Set[str] = set()

    for node in ast.walk(parsed.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.update(_dotted_prefixes(alias.name))
                # `import a.b.c` binds only `a`; _resolve_module walks the rest back on.
                bound = alias.asname or alias.name.split(".")[0]
                aliases[bound] = alias.name if alias.asname else bound
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            modules.update(_dotted_prefixes(node.module))
            for alias in node.names:
                dotted = f"{node.module}.{alias.name}"
                modules.add(dotted)
                aliases[alias.asname or alias.name] = dotted

    return aliases, modules


def _dotted_prefixes(dotted: str) -> Set[str]:
    """`a.b.c` -> {a, a.b, a.b.c}. Importing a module imports its packages."""
    parts = dotted.split(".")
    return {".".join(parts[: index + 1]) for index in range(len(parts))}


def _is_reload_call(node: ast.AST) -> bool:
    """True for `importlib.reload(x)` or a bare `reload(x)` from importlib."""
    if not isinstance(node, ast.Call) or len(node.args) != 1:
        return False
    name = corpus.dotted_name(node.func)
    return name == f"{RELOAD_MODULE}.{RELOAD_FUNCTION}" or name == RELOAD_FUNCTION


def _reload_bindings(scope: List[ast.stmt], aliases: Dict[str, str], modules: Set[str]) -> Dict[str, str]:
    """Names bound from a reload, mapped to the module the reload was handed."""
    bindings: Dict[str, str] = {}

    for statement in scope:
        for node in ast.walk(statement):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            if not _is_reload_call(node.value):
                continue
            dotted, chain = _resolve_module(node.value.args[0], aliases, modules, {})
            if not dotted or chain:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = dotted

    return bindings


def _resolve_module(
    node: ast.AST,
    aliases: Dict[str, str],
    modules: Set[str],
    bindings: Dict[str, str],
) -> Tuple[str, Tuple[str, ...]]:
    """The module an expression names, and the attributes read off it.

    A reload met inline resolves to its own argument, because that is what it returns.
    """
    dotted, chain = _resolve_root(node, aliases, modules, bindings)
    if not dotted:
        return "", ()

    # `a.b.c.__version__` arrives as `a` plus attributes; fold back while still an imported path.
    while chain and f"{dotted}.{chain[0]}" in modules:
        dotted = f"{dotted}.{chain[0]}"
        chain = chain[1:]

    return dotted, chain


def _resolve_root(
    node: ast.AST,
    aliases: Dict[str, str],
    modules: Set[str],
    bindings: Dict[str, str],
) -> Tuple[str, Tuple[str, ...]]:
    """The innermost module reference of an expression, with its attributes."""
    if isinstance(node, ast.Attribute):
        dotted, chain = _resolve_root(node.value, aliases, modules, bindings)
        return (dotted, chain + (node.attr,)) if dotted else ("", ())
    if isinstance(node, ast.Call) and _is_reload_call(node):
        return _resolve_root(node.args[0], aliases, modules, bindings)
    if isinstance(node, ast.Subscript):
        return _module_table_lookup(node)
    if isinstance(node, ast.Name):
        if node.id in bindings:
            return bindings[node.id], ()
        if node.id in aliases:
            return aliases[node.id], ()
    return "", ()


def _module_table_lookup(node: ast.Subscript) -> Tuple[str, Tuple[str, ...]]:
    """`sys.modules["a.b"]` -> `("a.b", ())`, anything else -> `("", ())`."""
    if corpus.dotted_name(node.value) != MODULE_TABLE:
        return "", ()
    index = node.slice
    if isinstance(index, ast.Constant) and isinstance(index.value, str):
        return index.value, ()
    return "", ()


def _reload_rows(
    unit: corpus.TestUnit,
    aliases: Dict[str, str],
    modules: Set[str],
    outer: Dict[str, str],
) -> List[dict]:
    """Nominations from leg two, one per reload compared against its own module."""
    bindings = dict(outer)
    bindings.update(_reload_bindings(list(unit.node.body), aliases, modules))
    if not bindings:
        return []

    rows: List[dict] = []
    for statement in corpus.asserts_in(unit):
        for node in ast.walk(statement.test):
            if isinstance(node, ast.Compare):
                rows.extend(_reload_compare_rows(unit, node, aliases, modules, bindings))

    return rows


def _reload_compare_rows(
    unit: corpus.TestUnit,
    node: ast.Compare,
    aliases: Dict[str, str],
    modules: Set[str],
    bindings: Dict[str, str],
) -> List[dict]:
    """Nominations from one comparison, when both sides are one module."""
    rows: List[dict] = []
    left = node.left

    for operator, comparator in zip(node.ops, node.comparators):
        row = _reload_row(unit, node, operator, left, comparator, aliases, modules, bindings)
        if row:
            rows.append(row)
        left = comparator

    return rows


def _reload_row(
    unit: corpus.TestUnit,
    node: ast.Compare,
    operator: ast.cmpop,
    left: ast.expr,
    right: ast.expr,
    aliases: Dict[str, str],
    modules: Set[str],
    bindings: Dict[str, str],
) -> Optional[dict]:
    """One nomination when `left` and `right` are the same module object."""
    if not isinstance(operator, ALWAYS_TRUE_OPS + ALWAYS_FALSE_OPS):
        return None
    # Leg one's row already; reporting it here would publish one defect as two.
    if _shape(left) == _shape(right):
        return None

    left_module, left_chain = _resolve_module(left, aliases, modules, bindings)
    right_module, right_chain = _resolve_module(right, aliases, modules, bindings)
    if not left_module or left_module != right_module or left_chain != right_chain:
        return None

    reloaded = _reload_side(left, right, bindings)
    if not reloaded:
        return None

    text = _operator_text(operator)
    attribute = ".".join(left_chain) or "the module object itself"
    always_true = isinstance(operator, ALWAYS_TRUE_OPS)
    verb = "holds whatever the code under test does" if always_true else "can never hold"
    return corpus.nomination(
        "TAUTOLOGY-ASSERT",
        unit,
        f"`{_source(left)} {text} {_source(right)}` compares {attribute} on '{left_module}' against "
        f"itself - importlib.reload() returns the module object it was handed, so '{reloaded}' IS the "
        f"other side and this assertion {verb}",
        verdict=corpus.VERDICT_IMPROVE,
        line=node.lineno,
        evidence={
            "leg": "reload",
            "operator": text,
            "module": left_module,
            "attribute": ".".join(left_chain),
            "reload_binding": reloaded,
            "outcome": "cannot fail" if always_true else "cannot pass",
        },
    )


def _reload_side(left: ast.expr, right: ast.expr, bindings: Dict[str, str]) -> str:
    """The reload-bound name in the pair, or "" when neither side is one.

    At least one side must be a reload: other same-object routes are uncalibrated.
    """
    for side in (left, right):
        for node in ast.walk(side):
            if isinstance(node, ast.Name) and node.id in bindings:
                return node.id
            if _is_reload_call(node):
                return _source(node)
    return ""


def nominate(scanned: corpus.Corpus) -> List[dict]:
    """Every assertion whose two sides are provably the same thing."""
    rows: List[dict] = []

    for parsed in scanned.files:
        aliases, modules = _import_aliases(parsed)
        outer = _reload_bindings(list(parsed.tree.body), aliases, modules)
        for unit in parsed.units:
            rows.extend(_structural_rows(unit))
            rows.extend(_reload_rows(unit, aliases, modules, outer))

    return rows
