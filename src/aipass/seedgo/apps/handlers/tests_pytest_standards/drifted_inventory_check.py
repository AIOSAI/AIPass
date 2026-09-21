# =================== AIPass ====================
# Name: drifted_inventory_check.py
# Description: nominator - a hand-kept module list that claims to be complete and is not (DRIFTED-INVENTORY)
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""
A hand-maintained list that CLAIMS to enumerate a tree, and no longer does.

    # Every importable module in canary's tree.
    CANARY_MODULES = [...]

    @pytest.mark.parametrize("module", CANARY_MODULES)
    def test_module_imports_with_no_readable_cwd(module, world):
        ...

THE DEFECT, AND WHY IT IS QUIET. The list is both the input and the oracle.
Every module it forgets is a module the probe never runs, and nothing goes
red - the suite reports the same green it reported when the list was whole,
with a smaller number of cases nobody counts. A new module lands, the list
stays as it was, and the coverage claim in the comment above it quietly stops
being true. Measured on the calibration fixture: the list names eight modules,
the tree holds eleven, and the three it forgot are never import-probed.

THE COMPLETENESS CLAIM IS WHAT MAKES IT A DEFECT. An ordinary list of module
names promises nothing; a list under "Every importable module in canary's
tree" promises everything, and only a promise can be broken. So this rule
requires the claim in writing - in a comment directly above the list, in the
module docstring, or in the docstring of the test that parametrizes over it -
before it will say a word. No claim, no nomination, however short the list is.

Comments are read from the FILE'S SOURCE by line number, because the parser
throws them away. That is the only place the claim usually lives.

DRIFT RUNS BOTH WAYS. A name the tree has and the list lacks is an untested
module. A name the list has and the tree lacks is a probe pointed at nothing -
it either errors loudly or, worse, was renamed and the list now pins the old
spelling. Both are reported, separately, in the same row.

WHAT IT DELIBERATELY DOES NOT FLAG:

  - a list with no completeness claim attached to it. Most module lists are
    deliberate subsets and saying so is the author's business, not this rule's.
  - a list nothing parametrizes over. If it is not the oracle, its drift costs
    no coverage.
  - a list that matches the tree exactly, in both directions.
  - a list whose entries mostly do NOT exist in the tree. That is evidence the
    walk root was inferred WRONG, not that the list is stale, and the rule
    says so in the log rather than publishing a row it cannot stand behind.

NOMINATION, NEVER CONVICTION (Law M1). A module can be legitimately excluded -
an optional extra, a platform-specific shim, a module the probe cannot run on
this box - and the list's author may have meant every word of it. The static
tier names the gap and lists the exact missing modules so the author can
answer in one line; the execution tier convicts.
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

#: The adapter group this nominator fills. Namespaced by the core.
GROUP = "static_drifted_inventory"

#: Words that turn a list into a promise. Matched as whole words against a
#: tokenised claim, never as substrings - "all" inside "allow" is not a claim.
COMPLETENESS_WORDS: frozenset = frozenset(
    {"every", "all", "each", "complete", "completely", "exhaustive", "exhaustively", "entire", "entirely"}
)

#: How a word is cut out of a comment or docstring for that match.
WORD_PATTERN = re.compile(r"[a-z]+")

#: What a string constant must look like before it is read as a module path.
#: At least one dot: a bare identifier is a word, not an import target.
DOTTED_MODULE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")

#: Below this, a literal is a pair of examples rather than an inventory.
MIN_INVENTORY_ENTRIES = 2

#: The decorator that turns a list into the suite's oracle.
PARAMETRIZE = "parametrize"

#: What makes a directory an importable package, and what a module file is.
PACKAGE_MARKER = "__init__.py"
MODULE_SUFFIX = ".py"

#: Never walked when enumerating a tree's importable modules. `.archive` holds
#: verbatim disposal copies that must never be read as live modules, and the
#: test directories are not what a production inventory claims to cover. Any
#: dot-directory is skipped on top of this list.
WALK_SKIP_DIRS: frozenset = frozenset({"__pycache__", "tests", "test", "docs", "node_modules", "site-packages"})

#: The share of a literal's entries that must EXIST in the walked tree before
#: the walk is accepted as the tree the literal is talking about. The walk root
#: is inferred from the literal's own common prefix, and an inferred root that
#: explains less than half the list has not earned the right to call the rest
#: drift - it is far likelier that the root is wrong.
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


# =============================================================================
# THE LITERAL - a list of dotted module names, written by hand
# =============================================================================


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

    `aipass.canary` for a list whose entries all begin with it. This is what
    names the subtree the literal claims to enumerate, and it is derived from
    the literal rather than configured, so a list about some other package
    measures against that package.

    Args:
        entries: The literal's string entries.

    Returns:
        The shared dotted prefix.
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
    """Every module-level literal that reads as an inventory of module paths.

    Args:
        parsed: The test module.

    Returns:
        `(name, entries, lineno)` per candidate literal.
    """
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


# =============================================================================
# THE CLAIM - what turns the list into a promise
# =============================================================================


def _comment_block_above(source: str, lineno: int) -> str:
    """The unbroken run of `#` comment lines directly above a source line.

    The AST throws comments away, so the claim that makes this rule apply is
    invisible to every other reader in this pack. It is read here from the
    file's own text, by line number, and it stops at the first line that is
    not a comment - a comment three blank lines up is about something else.

    Args:
        source: The file's text.
        lineno: The 1-based line the literal starts on.

    Returns:
        The comment text above it, joined by spaces, without the markers.
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
    """The written promise attached to a literal, and where it was found.

    Args:
        parsed: The test module.
        lineno: The line the literal starts on.
        consumers: Units that parametrize over it.

    Returns:
        `(claim text, where it was found)`, or `("", "")` when there is none.
    """
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


# =============================================================================
# THE ORACLE - the parametrize decorator that consumes the literal
# =============================================================================


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


# =============================================================================
# THE TREE - what is actually importable under the claimed prefix
# =============================================================================


def _is_walkable(name: str) -> bool:
    """True for a directory an importable inventory could legitimately claim."""
    return not name.startswith(".") and name not in WALK_SKIP_DIRS


def _package_contents(directory: Path, dotted: str) -> Set[str]:
    """Dotted names for one package's own modules and subpackages, recursively.

    A directory counts as a package only when it holds an `__init__.py`, and a
    file counts as a module the same way - because that is the rule the import
    system itself applies, and an inventory of "importable modules" is a claim
    about what the import system can reach.

    Args:
        directory: The package directory.
        dotted: The dotted name of that package.

    Returns:
        Every dotted name under it.
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

    THE CORPUS ROOT IS THE ANSWER IN THE ORDINARY CASE and this function
    returns it unchanged there. It exists for the case that is not ordinary,
    and the case was MEASURED rather than imagined: run against a branch that
    keeps a frozen copy of ANOTHER branch inside itself - which is exactly what
    a fixture directory is - mapping the literal's prefix onto the corpus root
    measured canary's eight-entry list against seedgo's 250-module tree and
    called 242 of them missing. That row was a mapping failure wearing a
    coverage failure's clothes.

    So the tree is anchored where the test file itself lives: the OUTERMOST
    package that still contains the file, climbing no higher than the corpus
    root. A branch laid out normally gives back the corpus root on the first
    comparison; a nested copy gives back the copy.

    Args:
        parsed: The test module holding the inventory.
        corpus_root: The corpus root, which is also the ceiling.

    Returns:
        The directory the literal's common prefix names.
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
    """Every importable dotted name under `root`, named from `prefix`.

    Args:
        root: The directory the prefix stands for.
        prefix: The dotted name that root stands for.

    Returns:
        Dotted module names, including `prefix` itself when root is a package.
    """
    if not root.is_dir():
        logger.warning(f"[AUDIT-TESTS] drifted_inventory cannot walk {root}, so it cleared no inventory there")
        return set()

    found = _package_contents(root, prefix)
    if (root / PACKAGE_MARKER).is_file():
        found.add(prefix)
    return found


def _mapping_holds(declared: Sequence[str], found: Set[str], name: str, prefix: str) -> bool:
    """True when the walk explains enough of the literal to be believed.

    A literal whose entries mostly do NOT exist under the walked root is
    evidence that the root is wrong, not that the list is stale, and a rule
    that published in that state would report a mapping failure as a coverage
    failure. The refusal is LOGGED rather than taken quietly, because a rule
    that could not run must never read the same as a rule that found nothing.
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


# =============================================================================
# THE NOMINATION
# =============================================================================


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
    """Every hand-kept inventory whose completeness claim has stopped being true.

    Args:
        scanned: The parsed corpus.

    Returns:
        Nomination rows, one per drifted literal.
    """
    rows: List[dict] = []

    for parsed in scanned.files:
        for literal in _inventory_literals(parsed):
            rows.extend(_nominate_literal(parsed, scanned, literal))

    return rows
