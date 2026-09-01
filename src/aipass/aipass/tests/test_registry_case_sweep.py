# =================== AIPass ====================
# Name: test_registry_case_sweep.py
# Description: Case-insensitive filesystem pins for *_REGISTRY.json discovery
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""Every ``*_REGISTRY.json`` walk in this tree must be case-SENSITIVE.

``Path.glob`` asks the FILESYSTEM to match.  On Windows -- and on macOS by
default -- that match is case-insensitive, so ``*_REGISTRY.json`` also matches
``*_registry.json``.  The bait ships in every branch: ``flow_json/*_registry.json``
plan counters and a ``.spawn/.template_registry.json`` (pathlib's ``*`` matches
dotfiles, unlike the ``glob`` module).  Measured on CI: ``find_registry()``
returned ``drone_command_registry.json`` as the fleet trust-anchor candidate.

A registry is a TRUST ANCHOR -- it decides which installation a caller belongs
to, what project name lands on an identity, and where the delete lane thinks
root is.  A plan counter answering that is not a near miss; it is a different
question.

These pins run RED ON LINUX by emulating the widened match, so no Windows box
is needed to keep them honest.

1.1.0 -- the CONTROL was the thing that assumed a host.  It asserted the raw
glob returns nothing, which is false on NTFS, so it failed on the Windows leg
of ebb8075d: broken on the exact platform the defect lives on.  The host is
PROBED now and both outcomes are pinned (see :func:`host_folds_case`).  A
``skipif`` was refused for the same reason -- it would retire the control where
it matters most.
"""

from __future__ import annotations

import ast
import fnmatch
import re
from pathlib import Path

import pytest

from aipass.aipass.shared.registry_discovery import find_registry, registries_in

BRANCH_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# the emulation
# ---------------------------------------------------------------------------


@pytest.fixture
def case_insensitive_fs(monkeypatch: pytest.MonkeyPatch):
    """Make ``Path.glob`` behave the way Windows/macOS behave.

    A real case-insensitive filesystem matches ANY case permutation, so this
    translates the pattern through ``fnmatch`` and re-matches ``iterdir()`` with
    ``re.IGNORECASE``.  Valid only for single-component, non-recursive patterns
    -- which is every registry walk in this tree.
    """
    real_iterdir = Path.iterdir

    def widened(self: Path, pattern: str, *args, **kwargs):
        rx = re.compile(fnmatch.translate(pattern), re.IGNORECASE)
        try:
            entries = list(real_iterdir(self))
        except (OSError, ValueError):
            return iter(())
        return iter(sorted(p for p in entries if rx.match(p.name)))

    monkeypatch.setattr(Path, "glob", widened)
    return widened


def host_folds_case(tmp_path: Path) -> bool:
    """Does THIS filesystem fold case? Asked in the DEFECT'S OWN DIRECTION.

    Writes a LOWERCASE name and globs the UPPERCASE pattern: an uppercase
    pattern reaching a lowercase file is exactly the direction the defect
    travels.  The reverse direction is a different question and a filesystem is
    entitled to answer it differently, so asking it backwards would measure
    something this file does not care about (@ai_mail's direction lesson,
    2026-08-31).

    A PROBE, never a ``skipif``: the host answers and BOTH answers are pinned.
    A skip would retire the control on the very platform the defect lives on.

    The probe writes into its own subdirectory, so it can never join the decoy
    set of the world under test.
    """
    probe = tmp_path / "_case_probe"
    probe.mkdir(exist_ok=True)
    (probe / "probe_registry.json").write_text("{}", encoding="utf-8")
    return [path.name for path in probe.glob("*_REGISTRY.json")] == ["probe_registry.json"]


def _project(tmp_path: Path) -> tuple[Path, Path]:
    """A project root with the real anchor, and a DECOY one level down.

    The decoy is placed so that a widened match does not merely add a wrong
    entry to a list -- it changes the ANSWER, because the walk meets ``sub``
    before it meets ``root``.  Every assertion below is about where discovery
    POINTS, never about set membership.

    Every decoy carries a DISTINCT STEM (``flow``, ``.template``), never a case
    twin of ``AIPASS``.  Two names differing only by case CANNOT COEXIST on a
    folding filesystem: the second write lands in the first file while the
    directory keeps the original spelling, so a case-twin decoy would silently
    overwrite the real anchor's content and build a DIFFERENT WORLD on Windows
    than on Linux (@memory's coexistence fact, 2026-08-31).
    """
    root = tmp_path / "root"
    deep = root / "sub" / "deep"
    deep.mkdir(parents=True)
    (root / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    (root / "sub" / "flow_registry.json").write_text("{}", encoding="utf-8")
    (root / "sub" / ".template_registry.json").write_text("{}", encoding="utf-8")
    return root, deep


# ---------------------------------------------------------------------------
# positive control -- the emulation must genuinely widen
# ---------------------------------------------------------------------------


#: The two lowercase baits ``_project`` plants one level below the real anchor.
DECOY_NAMES = {"flow_registry.json", ".template_registry.json"}


class TestTheEmulationIsNotBlind:
    """A blinded fixture reports green identically to a cure.  Prove it bites."""

    def test_the_raw_glob_answers_exactly_as_the_host_folds(self, tmp_path: Path) -> None:
        """The control, pinned in BOTH worlds rather than assuming one.

        This assertion used to read ``== []`` unconditionally.  It failed on the
        Windows CI leg of ebb8075d -- correctly: NTFS folds case, so the raw
        glob really does return the decoys there, and a control that asserts
        otherwise is broken on the exact host the defect lives on.

        Where the host folds, the emulation is redundant rather than absent:
        the real filesystem already supplies the widened match, so every pin
        below is exercised against the genuine article.  Where it does not
        fold, the emulation is the only thing that widens -- which is what the
        companion test proves.
        """
        root, _ = _project(tmp_path)
        found = {path.name for path in (root / "sub").glob("*_REGISTRY.json")}
        if host_folds_case(tmp_path):
            assert found == DECOY_NAMES, (
                f"host folds case, so the raw glob must reach the lowercase decoys -- got {found}"
            )
        else:
            assert found == set(), f"host does NOT fold case, so the raw glob must reach nothing -- got {found}"

    def test_with_emulation_the_lowercase_decoy_IS_matched(self, tmp_path: Path, case_insensitive_fs) -> None:
        """If this goes green-by-accident the whole file proves nothing."""
        root, _ = _project(tmp_path)
        names = {p.name for p in (root / "sub").glob("*_REGISTRY.json")}
        assert names == DECOY_NAMES, f"emulation did not widen -- these pins would pass blind: {names}"

    def test_the_probe_reads_the_world_not_a_platform_string(self, tmp_path: Path, case_insensitive_fs) -> None:
        """The probe must be an experiment, not ``sys.platform`` in disguise.

        It is allowed to disagree with the platform -- a case-sensitive volume
        can be mounted on Windows and a folding one on Linux -- so a probe that
        answered from ``sys.platform`` would be wrong exactly where it matters
        and no case-sensitive host could ever catch it.

        Running it inside the folding EMULATION is what makes that catchable
        here: a platform string still says False on this Linux runner, while a
        probe that genuinely globs says True.  The opposite mutant (a probe
        hardwired to True) is killed by the control above, which then demands
        decoys the raw glob does not return.
        """
        assert host_folds_case(tmp_path) is True, (
            "the probe did not see a folding world it was standing in -- it is not measuring the filesystem"
        )


# ---------------------------------------------------------------------------
# the reader
# ---------------------------------------------------------------------------


class TestRegistriesIn:
    def test_rejects_lowercase_even_on_a_case_insensitive_filesystem(self, tmp_path: Path, case_insensitive_fs) -> None:
        root, _ = _project(tmp_path)
        assert registries_in(root / "sub") == []

    def test_still_finds_the_real_anchor(self, tmp_path: Path, case_insensitive_fs) -> None:
        root, _ = _project(tmp_path)
        assert [p.name for p in registries_in(root)] == ["AIPASS_REGISTRY.json"]

    def test_suffix_not_stem_external_projects_name_registries_after_themselves(
        self, tmp_path: Path, case_insensitive_fs
    ) -> None:
        """``VERA-STUDIO_REGISTRY.json`` is valid; nothing promises an uppercase stem."""
        tmp_path.joinpath("Vera-Studio_REGISTRY.json").write_text("{}", encoding="utf-8")
        assert [p.name for p in registries_in(tmp_path)] == ["Vera-Studio_REGISTRY.json"]

    def test_unreadable_directory_is_empty_not_an_exception(self, tmp_path: Path) -> None:
        assert registries_in(tmp_path / "does_not_exist") == []


# ---------------------------------------------------------------------------
# the behaviour that actually matters
# ---------------------------------------------------------------------------


class TestFindRegistryUnderCaseInsensitivity:
    def test_the_decoy_does_not_become_the_trust_anchor(self, tmp_path: Path, case_insensitive_fs) -> None:
        """The assertion is WHERE discovery points, not what a list contains.

        Widened matching makes ``root/sub/flow_registry.json`` -- a plan
        counter -- answer the question "where is this project rooted?".  The
        project root would silently become ``root/sub``.
        """
        root, deep = _project(tmp_path)
        found = find_registry(start_path=deep)
        assert found is not None
        assert found == root / "AIPASS_REGISTRY.json"
        assert found.parent == root, f"project root resolved to {found.parent}, not {root}"

    def test_a_directory_holding_only_counters_is_registry_free(self, tmp_path: Path, case_insensitive_fs) -> None:
        """No anchor anywhere -- absence, not a counter dressed as an anchor."""
        only = tmp_path / "counters"
        only.mkdir()
        (only / "fplan_registry.json").write_text("{}", encoding="utf-8")
        (only / ".template_registry.json").write_text("{}", encoding="utf-8")
        assert find_registry(start_path=only, package_root=str(only)) is None

    def test_package_root_walk_is_filtered_too(self, tmp_path: Path, case_insensitive_fs) -> None:
        """Priority 3 is a second walk -- it needs the same filter as priority 2."""
        root, deep = _project(tmp_path)
        isolated = tmp_path / "isolated"
        isolated.mkdir()
        assert find_registry(start_path=isolated, package_root=str(deep)) == (root / "AIPASS_REGISTRY.json")


# ---------------------------------------------------------------------------
# the structural pin -- an eighth private copy must be impossible to write
# ---------------------------------------------------------------------------


def _private_registry_globs(root: Path) -> tuple[list[str], int]:
    """Every direct ``glob("*_REGISTRY.json")`` under *root*, and the file count.

    Returns the count too so a caller can prove the walk actually WALKED --
    see ``TestNoPrivateRegistryGlobSurvives``.
    """
    offenders: list[str] = []
    scanned = 0
    for py in sorted(root.rglob("*.py")):
        rel = py.relative_to(root).as_posix()
        if rel.startswith((".backup/", ".archive/")):
            continue
        if rel in {"tests/test_registry_case_sweep.py", "shared/registry_discovery.py"}:
            continue  # the pin itself, and the one sanctioned implementation
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        scanned += 1
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"glob", "rglob"}:
                continue
            for arg in node.args:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and arg.value.endswith("_REGISTRY.json")
                ):
                    offenders.append(f"{rel}:{node.lineno}")
    return offenders, scanned


class TestNoPrivateRegistryGlobSurvives:
    """One reader, called by every walk.

    The eighth private copy of ``glob("*_REGISTRY.json")`` is how a fix lands on
    some of N identical paths.  This pin names every offender by file and line
    so a new one cannot be added quietly.
    """

    def test_no_module_globs_the_registry_pattern_directly(self) -> None:
        offenders, scanned = _private_registry_globs(BRANCH_ROOT)
        assert offenders == [], "private *_REGISTRY.json glob(s) -- call shared registries_in() instead: " + ", ".join(
            offenders
        )

    def test_the_walk_actually_walked(self) -> None:
        """A scan that visits nothing reports clean.  Refuse to call that a pass.

        Found by a mutant: blinding the skip-list to ``if True`` made the walk
        visit zero files and every assertion above still passed.  A positive
        control that exercises a COPY of the logic cannot catch that -- only one
        that measures the instrument can.
        """
        _, scanned = _private_registry_globs(BRANCH_ROOT)
        assert scanned > 50, f"walk only parsed {scanned} modules -- it is blind, not clean"

    def test_the_same_walk_convicts_a_planted_offender(self, tmp_path: Path) -> None:
        """Positive control through the REAL function, not a re-implementation."""
        (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "guilty.py").write_text(
            'from pathlib import Path\nx = Path(".").glob("*_REGISTRY.json")\n',
            encoding="utf-8",
        )
        offenders, scanned = _private_registry_globs(tmp_path)
        assert offenders == ["guilty.py:2"]
        assert scanned == 2

    def test_the_walk_also_catches_rglob(self, tmp_path: Path) -> None:
        """``rglob`` is the same defect one keystroke away."""
        (tmp_path / "guilty.py").write_text(
            'from pathlib import Path\nx = Path(".").rglob("*_REGISTRY.json")\n',
            encoding="utf-8",
        )
        offenders, _ = _private_registry_globs(tmp_path)
        assert offenders == ["guilty.py:2"]
