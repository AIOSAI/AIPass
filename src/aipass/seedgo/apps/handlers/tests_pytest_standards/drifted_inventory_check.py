# =================== AIPass ====================
# Name: drifted_inventory_check.py
# Description: nominator - a hand-kept module list that claims to be complete and is not (DRIFTED-INVENTORY)
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-10-17
# =============================================

"""A hand-maintained list that CLAIMS to enumerate a tree, and no longer does.

Reference: drifted_inventory.md
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

GROUP = "static_drifted_inventory"

#: Words that turn a list into a promise. Matched as whole words against a
#: tokenised claim, never as substrings - "all" inside "allow" is not a claim.
COMPLETENESS_WORDS: frozenset = frozenset(
    {"every", "all", "each", "complete", "completely", "exhaustive", "exhaustively", "entire", "entirely"}
)

WORD_PATTERN = re.compile(r"[a-z]+")

#: At least one dot: a bare identifier is a word, not an import target.
DOTTED_MODULE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")

#: Below this, a literal is a pair of examples rather than an inventory.
MIN_INVENTORY_ENTRIES = 2

PARAMETRIZE = "parametrize"

PACKAGE_MARKER = "__init__.py"
MODULE_SUFFIX = ".py"

#: Never walked; any dot-directory (e.g. `.archive` disposal copies) is skipped on top.
WALK_SKIP_DIRS: frozenset = frozenset({"__pycache__", "tests", "test", "docs", "node_modules", "site-packages"})

#: An inferred root explaining less than this share of the list is likelier wrong than the list stale.
MAPPING_PROOF_SHARE = 0.5

SPECIFICATION = {
    "rule": "TAXONOMY section 5 rule 11 - a hand-kept inventory that claims completeness and drifted",
    "species": ["DRIFTED-INVENTORY"],
    "flags": [
        "a module-level list of dotted module names, parametrized over, carrying a written "
        "completeness claim, that omits modules the tree actually holds - each omission is a "
        "module nothing probes, and the suite stays green because the list is also the oracle",
        "the same list naming modules the tree does NOT hold - a probe pointed at nothing, or a "
        "rename the list never followed",
    ],
    "exempts": [
        "a list with no completeness claim in a comment above it, the module docstring, or the "
        "docstring of a test that parametrizes over it - a subset promises nothing",
        "a list no parametrize decorator consumes; if it is not the oracle its drift costs no coverage",
        "a list that matches the walked tree exactly in both directions",
        "tests/, docs/, __pycache__ and any dot-directory, which an importable inventory never claims",
    ],
    "fix": (
        "derive the list from a walk of the tree instead of maintaining it by hand, or pin the "
        "expected COUNT beside it from an independent source so a forgotten module reds the suite. "
        "A list that is both the input and the oracle cannot notice its own gaps."
    ),
    "limits": [
        "a module may be legitimately excluded - an optional extra, a platform shim - and is still "
        "nominated; that is why this tier nominates and the execution tier convicts (Law M1)",
        "the walk root is inferred - the outermost package still holding the test file, never "
        "above the corpus root - and a literal whose entries mostly do not exist there is LOGGED "
        "and skipped, never published, because the mapping rather than the list is what failed",
        "a literal built at runtime, or spread across several assignments, is invisible to a "
        "static reader - which biases this rule toward FEWER nominations",
    ],
    "evidence": (
        "canary's CANARY_MODULES lists eight modules under the comment 'Every importable module in "
        "canary's tree' while the tree holds eleven; the three it forgot - apps.modules.note, "
        "apps.handlers.notes and apps.handlers.notes.store - are never import-probed"
    ),
}


def _string_entries(value: ast.expr) -> List[str]:
    """The string constants of a list/tuple/set literal, or [] for anything else."""
    if not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        return []
    entries = []
    for element in value.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return []
        entries.append(element.value)
    return entries


def _looks_like_an_inventory(entries: Sequence[str]) -> bool:
    """True when every entry is a dotted module path and there are enough of them."""
    if len(entries) < MIN_INVENTORY_ENTRIES:
        return False
    return all(DOTTED_MODULE_PATTERN.match(entry) for entry in entries)


def _common_prefix(entries: Sequence[str]) -> str:
    """The longest dotted prefix every entry shares, or "" when there is none.

    Derived from the literal, not configured, so a list about another package measures that package.
    """
    split = [entry.split(".") for entry in entries]
    shared: List[str] = []
    for index in range(min(len(parts) for parts in split)):
        segment = split[0][index]
        if any(parts[index] != segment for parts in split):
            break
        shared.append(segment)
    return ".".join(shared)


def _inventory_literals(parsed: corpus.TestFile) -> List[Tuple[str, List[str], int]]:
    """Every module-level literal that reads as an inventory of module paths."""
    found: List[Tuple[str, List[str], int]] = []

    for statement in parsed.tree.body:
        target, value = _assignment_parts(statement)
        if target is None or value is None:
            continue
        entries = _string_entries(value)
        if _looks_like_an_inventory(entries) and _common_prefix(entries):
            found.append((target, entries, statement.lineno))

    return found


def _assignment_parts(statement: ast.stmt) -> Tuple[Optional[str], Optional[ast.expr]]:
    """`(name, value)` for a single-target module-level assignment."""
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        target = statement.targets[0]
        if isinstance(target, ast.Name):
            return target.id, statement.value
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        return statement.target.id, statement.value
    return None, None


def _comment_block_above(source: str, lineno: int) -> str:
    """The unbroken run of `#` comment lines directly above a source line.

    Read from the file's text, since the AST drops comments; stops at the first non-comment line.
    """
    lines = source.splitlines()
    collected: List[str] = []
    index = lineno - 2
    while index >= 0 and lines[index].strip().startswith("#"):
        collected.append(lines[index].strip().lstrip("#").strip())
        index -= 1
    return " ".join(reversed(collected))


def _claims_completeness(text: str) -> bool:
    """True when the text promises the list is whole."""
    return bool(set(WORD_PATTERN.findall(text.lower())) & COMPLETENESS_WORDS)


def _completeness_claim(
    parsed: corpus.TestFile,
    lineno: int,
    consumers: Sequence[corpus.TestUnit],
) -> Tuple[str, str]:
    """The written promise attached to a literal, and where it was found."""
    comment = _comment_block_above(parsed.source, lineno)
    if _claims_completeness(comment):
        return comment, "the comment above the list"

    module_docstring = ast.get_docstring(parsed.tree) or ""
    if _claims_completeness(module_docstring):
        return module_docstring.strip().splitlines()[0], "the module docstring"

    for unit in consumers:
        if _claims_completeness(unit.docstring):
            return unit.docstring.strip().splitlines()[0], f"the docstring of {unit.name}"

    return "", ""


def _parametrize_consumers(parsed: corpus.TestFile, name: str) -> List[corpus.TestUnit]:
    """Units whose `parametrize` decorator reads this literal by name."""
    consumers: List[corpus.TestUnit] = []

    for unit in parsed.units:
        if any(_decorator_reads(decorator, name) for decorator in unit.decorators):
            consumers.append(unit)

    return consumers


def _decorator_reads(decorator: ast.expr, name: str) -> bool:
    """True when this is a `parametrize` decorator mentioning `name`."""
    if not isinstance(decorator, ast.Call):
        return False
    if corpus.dotted_name(decorator.func).rsplit(".", 1)[-1] != PARAMETRIZE:
        return False
    return any(isinstance(node, ast.Name) and node.id == name for node in ast.walk(decorator))


def _is_walkable(name: str) -> bool:
    """True for a directory an importable inventory could legitimately claim."""
    return not name.startswith(".") and name not in WALK_SKIP_DIRS


def _package_contents(directory: Path, dotted: str) -> Set[str]:
    """Dotted names for one package's own modules and subpackages, recursively.

    `__init__.py` decides, because that is the rule the import system applies.
    """
    found: Set[str] = set()

    for child in sorted(directory.iterdir()):
        if child.is_dir():
            found.update(_subpackage_contents(child, dotted))
        elif child.suffix == MODULE_SUFFIX and child.name != PACKAGE_MARKER:
            found.add(f"{dotted}.{child.stem}")

    return found


def _subpackage_contents(child: Path, dotted: str) -> Set[str]:
    """Dotted names under one child directory, or nothing when it is not a package."""
    if not _is_walkable(child.name) or not (child / PACKAGE_MARKER).is_file():
        return set()
    name = f"{dotted}.{child.name}"
    return {name} | _package_contents(child, name)


def _is_inside(candidate: Path, root: Path) -> bool:
    """True when `candidate` is `root` or lives under it."""
    return candidate == root or root in candidate.parents


def _inventory_root(parsed: corpus.TestFile, corpus_root: Path) -> Path:
    """The package tree a file's inventory is talking about.

    The outermost package still holding the test file, never above the corpus root: a
    fixture holding a frozen copy of another branch must measure against the copy.
    """
    root = corpus_root.resolve()
    start = parsed.path.resolve().parent
    if not (start / PACKAGE_MARKER).is_file():
        start = start.parent
    if not _is_inside(start, root):
        return root

    current = start
    while current != root and (current.parent / PACKAGE_MARKER).is_file() and _is_inside(current.parent, root):
        current = current.parent
    return current


def _tree_modules(root: Path, prefix: str) -> Set[str]:
    """Every importable dotted name under `root`, named from `prefix`."""
    if not root.is_dir():
        logger.warning(f"[AUDIT-TESTS] drifted_inventory cannot walk {root}, so it cleared no inventory there")
        return set()

    found = _package_contents(root, prefix)
    if (root / PACKAGE_MARKER).is_file():
        found.add(prefix)
    return found


def _mapping_holds(declared: Sequence[str], found: Set[str], name: str, prefix: str) -> bool:
    """True when the walk explains enough of the literal to be believed.

    A refusal is logged: a rule that could not run must never read like one that found nothing.
    """
    present = len(set(declared) & found)
    if present > len(declared) * MAPPING_PROOF_SHARE:
        return True
    logger.warning(
        f"[AUDIT-TESTS] drifted_inventory could not place '{name}': only {present} of {len(declared)} "
        f"entries exist under the root mapped to '{prefix}', so the walk root is unproven and this "
        f"inventory was NOT cleared - it was skipped"
    )
    return False


def _drift_row(
    unit: corpus.TestUnit,
    name: str,
    lineno: int,
    claim: Tuple[str, str],
    drift: Dict[str, List[str]],
    counts: Tuple[int, int, str],
) -> dict:
    """One DRIFTED-INVENTORY nomination, naming both directions of the drift."""
    missing, stale = drift["missing"], drift["stale"]
    declared_count, found_count, prefix = counts
    claim_text, claim_where = claim
    stale_note = f", and names {len(stale)} the tree does not hold" if stale else ""
    return corpus.nomination(
        "DRIFTED-INVENTORY",
        unit,
        f"'{name}' claims to be complete ({claim_where}: \"{claim_text}\") and is parametrized over, "
        f"but it lists {declared_count} of the {found_count} modules under '{prefix}': it omits "
        f"{len(missing)} module(s){stale_note}. Each omitted module is one nothing probes, and the "
        f"suite stays green because this list is both the input and the oracle",
        verdict=corpus.VERDICT_IMPROVE,
        line=lineno,
        evidence={
            "inventory": name,
            "prefix": prefix,
            "claim": claim_text,
            "claim_source": claim_where,
            "declared": declared_count,
            "found_in_tree": found_count,
            "missing": missing,
            "stale": stale,
        },
    )


def _nominate_literal(
    parsed: corpus.TestFile,
    scanned: corpus.Corpus,
    literal: Tuple[str, List[str], int],
) -> List[dict]:
    """The nomination one inventory literal produces, or none."""
    name, entries, lineno = literal

    consumers = _parametrize_consumers(parsed, name)
    if not consumers:
        return []

    claim = _completeness_claim(parsed, lineno, consumers)
    if not claim[0]:
        return []

    prefix = _common_prefix(entries)
    found = _tree_modules(_inventory_root(parsed, scanned.root), prefix)
    if not found or not _mapping_holds(entries, found, name, prefix):
        return []

    declared = set(entries)
    drift = {"missing": sorted(found - declared), "stale": sorted(declared - found)}
    if not drift["missing"] and not drift["stale"]:
        return []

    return [_drift_row(consumers[0], name, lineno, claim, drift, (len(declared), len(found), prefix))]


def nominate(scanned: corpus.Corpus) -> List[dict]:
    """Every hand-kept inventory whose completeness claim has stopped being true."""
    rows: List[dict] = []

    for parsed in scanned.files:
        for literal in _inventory_literals(parsed):
            rows.extend(_nominate_literal(parsed, scanned, literal))

    return rows
