# =================== AIPass ====================
# Name: test_passport_seeds.py
# Description: Repo pins for tracked passport seeds - shape, leak-guard, naming
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-08-28
# =============================================

"""Pins for the tracked passport seeds (TDPLAN-0017).

A seed is ``src/aipass/<branch>/.aipass/passport.seed.json``: the branch's
evolved identity, TRACKED, so a fresh clone receives a soul instead of a blank
template. The live ``.trinity/passport.json`` stays gitignored -- the ignore IS
the pull protection -- and the seed is its shipped counterpart, MINUS the facts
that belong to one machine.

Three rules, and the middle one is the reason this file exists
--------------------------------------------------------------
1. SHAPE -- a seed parses and carries the 2.0 passport shape, because an
   invalid seed reaching mint would write a broken passport onto a new install.
2. THE LEAK-GUARD -- no seed carries a machine-local field. ``registry_id``,
   ``citizen_id`` and ``registered`` are facts about one installation's
   registry, and ``citizenship.seed`` is the mint stamp a LIVE passport gets
   when it is born FROM a seed; a seed carrying its own stamp is a snake eating
   its tail. Live passports may carry all four. Seeds never may: these files are
   pushed to a public repo, so a leak here is published, and published is
   forever even after a later commit removes it.
3. NAMING -- ``branch_info.branch_name`` matches the branch directory the seed
   sits in, so a copy-paste export cannot hand one branch another's identity.

The guard is deliberately INDEPENDENT of the machinery it guards: it re-reads
the files from disk and re-derives the rules here rather than importing spawn's
exporter. A guard that asks the exporter what it exported would agree with it
about a bug.

Zero seeds is a SKIP, never a pass
----------------------------------
The exporter (``drone @spawn export-seeds``) lands in a parallel lane, so this
suite is written before its subject exists. An empty glob skips loudly and
names why. Because a suite that skips forever is itself a silent pass, the
discovery is pinned separately against a synthetic tree, and every rule is
proved RED against a synthetic violating seed -- so these pins are known to
bite before the first real seed is ever written.

What is NOT judged here: extra top-level sections, prose, or dates. The seed is
a passport's identity carried forward; only the shape that mint depends on, the
fields that must never ship, and the name are pinned.
"""

import json
from pathlib import Path

import pytest

# The machine-local set, per the TDPLAN ruling. Each name is a fact about one
# installation, never about the agent: the first three are the registry's own
# bookkeeping and the fourth is the mint stamp, which records WHICH seed a live
# passport was born from and is therefore meaningless inside a seed.
_MACHINE_LOCAL_FIELDS = ("registry_id", "citizen_id", "registered", "seed")

# The 2.0 passport sections. document_metadata carries the schema version; the
# other three are the identity itself.
_REQUIRED_SECTIONS = ("document_metadata", "branch_info", "citizenship", "identity")

_SCHEMA_VERSION = "2.0.0"

_SEED_NAME = "passport.seed.json"
_SEED_DIR = ".aipass"

_NO_SEEDS_REASON = (
    f"no src/aipass/*/{_SEED_DIR}/{_SEED_NAME} on disk -- seeds are minted by "
    "drone @spawn export-seeds, which lands in a parallel lane (TDPLAN-0017 lane A). "
    "These pins go live the moment the first seed is written."
)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _repo_root() -> Path | None:
    """Walk up from this file to the repo root -- the dir holding src/aipass."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "src" / "aipass").is_dir():
            return parent
    return None


def _seed_paths(root: Path | None) -> list[Path]:
    """Every tracked seed under *root*, sorted by branch name.

    Exactly one level deep on purpose: ``src/aipass/<branch>/.aipass/``. Spawn's
    class templates live deeper and are not citizens, so they must not be
    measured as though they were.
    """
    if root is None:
        return []
    return sorted(root.glob(f"src/aipass/*/{_SEED_DIR}/{_SEED_NAME}"))


def _seed_params() -> list:
    """One param per seed on disk, or a single sentinel that skips.

    pytest generates NO tests from an empty parametrize list, and no tests is
    indistinguishable from passing tests in a summary line. The sentinel keeps
    the absence visible in the report.
    """
    seeds = _seed_paths(_repo_root())
    if not seeds:
        return [pytest.param(None, id="no-seeds-on-disk")]
    return [pytest.param(path, id=path.parent.parent.name) for path in seeds]


def _branch_of(seed: Path) -> str:
    """The branch directory a seed sits in: <branch>/.aipass/passport.seed.json."""
    return seed.parent.parent.name


def _load(seed: Path | None):
    """Read one seed, skipping when there are none yet.

    Returns the parsed object. Both failure modes are re-raised as an
    AssertionError naming the FILE, because a bare OSError or JSONDecodeError
    in the report tells a reader a test crashed rather than which seed is bad.
    """
    if seed is None:
        pytest.skip(_NO_SEEDS_REASON)
    try:
        raw = seed.read_text(encoding="utf-8")
    except OSError as exc:
        raise AssertionError(f"{seed}: unreadable ({exc})") from exc
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise AssertionError(f"{seed}: not valid JSON ({exc})") from exc


# ---------------------------------------------------------------------------
# The three rules, as pure functions over a parsed seed
# ---------------------------------------------------------------------------


def _leaks(data) -> list[str]:
    """Every machine-local field in *data*, as a dotted path, deepest first found.

    The whole document is walked rather than just ``citizenship``: a leak that
    moved is still a leak, and an export bug that writes ``citizen_id`` under
    ``branch_info`` publishes exactly as much as one that leaves it in place.
    Keys are matched, never values -- a passport whose PROSE mentions a citizen
    id is a different problem and not this guard's to invent.
    """
    found: list[str] = []

    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                here = f"{path}.{key}" if path else key
                if key in _MACHINE_LOCAL_FIELDS:
                    found.append(here)
                walk(value, here)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(data, "")
    return found


def _shape_violations(data) -> list[str]:
    """Why *data* is not a 2.0 passport, or an empty list.

    Presence and type of the four sections plus the schema version. Mint reads
    these; anything softer would let a seed through that cannot become a
    passport.
    """
    if not isinstance(data, dict):
        return [f"top level must be an object, found {type(data).__name__}"]

    violations: list[str] = []
    for section in _REQUIRED_SECTIONS:
        if section not in data:
            violations.append(f"missing section '{section}'")
        elif not isinstance(data[section], dict):
            violations.append(f"'{section}' must be an object, found {type(data[section]).__name__}")

    metadata = data.get("document_metadata")
    if isinstance(metadata, dict):
        version = metadata.get("schema_version")
        if version != _SCHEMA_VERSION:
            violations.append(f"document_metadata.schema_version is {version!r}, expected {_SCHEMA_VERSION!r}")
    return violations


def _name_violation(data, branch: str) -> str:
    """Why the seed's declared branch_name does not match *branch*, or "" ."""
    declared = data.get("branch_info", {}).get("branch_name") if isinstance(data, dict) else None
    if declared == branch:
        return ""
    return f"branch_info.branch_name is {declared!r} but the seed sits in {branch!r}/"


# ---------------------------------------------------------------------------
# Synthetic fixtures -- the deviant corpus, since the live population is zero
# ---------------------------------------------------------------------------


def _clean_seed(branch: str = "testbranch") -> dict:
    """A seed that satisfies all three rules: live passport minus machine-local."""
    return {
        "document_metadata": {
            "document_type": "branch_identity",
            "document_name": f"{branch}.PASSPORT",
            "version": "2.0.0",
            "schema_version": _SCHEMA_VERSION,
            "created": "2026-01-01",
            "last_updated": "2026-08-28",
            "managed_by": branch,
            "tags": ["identity", "passport", "branch_profile"],
        },
        "branch_info": {
            "branch_name": branch,
            "alias": "",
            "path": f"src/aipass/{branch}",
            "module": f"aipass.{branch}",
            "email": f"@{branch}",
            "created": "2026-01-01",
            "git_branch": "dev",
        },
        "citizenship": {
            "residency": "core",
            "registry_path": f"{_SEED_DIR}/registry.json",
            "communications": True,
            "memory": True,
        },
        "identity": {
            "citizen_class": "specialist",
            "role": "standards_auditor",
            "purpose": "Stand in for an evolved identity.",
            "what_i_do": ["Audit branches against the standards"],
            "what_i_dont_do": ["Runtime monitoring"],
            "traits": [],
            "principles": ["Code is truth - fail honestly"],
        },
    }


@pytest.fixture
def planted(tmp_path):
    """Write a synthetic seed into a synthetic tree and hand back its path.

    The tree mirrors the real layout exactly -- ``src/aipass/<branch>/.aipass/``
    -- so discovery is exercised by the same glob the repo pins use.
    """

    def _plant(data, branch: str = "testbranch") -> Path:
        seed = tmp_path / "src" / "aipass" / branch / _SEED_DIR / _SEED_NAME
        seed.parent.mkdir(parents=True, exist_ok=True)
        payload = data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False)
        seed.write_text(payload, encoding="utf-8")
        return seed

    return _plant


# ===========================================================================
# A. THE REPO PINS -- every seed on disk, one param per branch
# ===========================================================================


class TestEverySeedInTheRepo:
    """The live population. Skips loudly while the exporter is still being
    built; the moment a seed lands, each rule reports per branch by name.
    """

    @pytest.mark.parametrize("seed", _seed_params())
    def test_the_seed_parses_and_carries_the_2_0_passport_shape(self, seed):
        data = _load(seed)

        violations = _shape_violations(data)

        assert not violations, f"{seed}: {'; '.join(violations)}"

    @pytest.mark.parametrize("seed", _seed_params())
    def test_the_seed_carries_no_machine_local_field(self, seed):
        """THE LEAK-GUARD. A seed is pushed; a machine-local field in one is
        published identity bookkeeping that no clone should ever receive.
        """
        data = _load(seed)

        leaks = _leaks(data)

        assert not leaks, (
            f"{seed}: machine-local field(s) {', '.join(leaks)} must never appear in a tracked seed -- "
            f"re-export with drone @spawn export-seeds rather than editing the file by hand"
        )

    @pytest.mark.parametrize("seed", _seed_params())
    def test_the_seed_names_the_branch_it_sits_in(self, seed):
        data = _load(seed)

        violation = _name_violation(data, _branch_of(seed))

        assert not violation, f"{seed}: {violation}"


# ===========================================================================
# B. THE GUARD BITES -- proved against a synthetic corpus, live population zero
# ===========================================================================


class TestTheLeakGuardBites:
    """Red-first, and it has to be: with no seeds on disk the repo pins above
    skip, so nothing else in this file would prove the rule can see. Each field
    is planted separately because each could be missed alone.
    """

    @pytest.mark.parametrize(
        "field, value",
        [
            ("citizen_id", "a41235f5-1ca9-489f-8191-b106d398c0fa"),
            ("registry_id", "7087bb93-570f-4b9a-b035-4fd7f570200e"),
            ("registered", True),
            ("seed", {"version": "1.0.0", "sha256": "0" * 64}),
        ],
    )
    def test_a_machine_local_field_in_citizenship_is_named(self, planted, field, value):
        data = _clean_seed()
        data["citizenship"][field] = value
        seed = planted(data)

        leaks = _leaks(_load(seed))

        assert leaks == [f"citizenship.{field}"]

    def test_a_leak_that_moved_out_of_citizenship_is_still_found(self, planted):
        """The walk is over the whole document, not over one section. An export
        bug that writes the id somewhere else publishes just as much.
        """
        data = _clean_seed()
        data["branch_info"]["citizen_id"] = "a41235f5-1ca9-489f-8191-b106d398c0fa"
        seed = planted(data)

        assert _leaks(_load(seed)) == ["branch_info.citizen_id"]

    def test_every_leak_is_named_not_just_the_first(self, planted):
        data = _clean_seed()
        data["citizenship"]["citizen_id"] = "a41235f5"
        data["citizenship"]["registered"] = True
        seed = planted(data)

        leaks = _leaks(_load(seed))

        assert sorted(leaks) == ["citizenship.citizen_id", "citizenship.registered"]

    def test_the_mint_stamp_is_a_leak_in_a_seed_though_it_is_canonical_in_a_passport(self, planted):
        """The asymmetry, pinned on purpose. seedgo's trinity checker accepts
        ``citizenship.seed`` in a live passport (it never reads passport content
        at all -- see TestTheMintStampIsNotAViolation in test_trinity_check).
        Here the same field is a violation, because a seed that stamps itself
        claims to have been minted from something.
        """
        data = _clean_seed()
        data["citizenship"]["seed"] = {"version": "1.0.0", "sha256": "0" * 64}
        seed = planted(data)

        assert _leaks(_load(seed)) == ["citizenship.seed"]

    def test_a_clean_seed_leaks_nothing(self, planted):
        """Over-refusal guard: a guard that fails everything protects nothing."""
        seed = planted(_clean_seed())

        assert _leaks(_load(seed)) == []

    def test_a_key_named_like_a_leak_deeper_in_the_identity_is_still_reported(self, planted):
        """Deliberately strict, and stated rather than discovered later: the
        walk matches key NAMES at any depth, so a nested ``seed`` key inside
        identity would be flagged too. No live passport has one; if a legitimate
        use ever appears, this test is where the exception gets argued.
        """
        data = _clean_seed()
        data["identity"]["provenance"] = {"seed": "hand-written"}
        seed = planted(data)

        assert _leaks(_load(seed)) == ["identity.provenance.seed"]


class TestTheShapeGuardBites:
    """An invalid seed must never reach mint: it would write a broken passport
    into a fresh install, where nobody is watching.
    """

    @pytest.mark.parametrize("section", _REQUIRED_SECTIONS)
    def test_a_missing_section_is_named(self, planted, section):
        data = _clean_seed()
        del data[section]
        seed = planted(data)

        violations = _shape_violations(_load(seed))

        assert any(section in violation for violation in violations), violations

    def test_a_section_of_the_wrong_type_is_named_with_the_type_found(self, planted):
        data = _clean_seed()
        data["citizenship"] = []
        seed = planted(data)

        violations = _shape_violations(_load(seed))

        assert any("citizenship" in violation and "list" in violation for violation in violations), violations

    def test_a_wrong_schema_version_is_named_with_the_value_found(self, planted):
        data = _clean_seed()
        data["document_metadata"]["schema_version"] = "1.0.0"
        seed = planted(data)

        violations = _shape_violations(_load(seed))

        assert any("1.0.0" in violation and "schema_version" in violation for violation in violations), violations

    def test_a_missing_schema_version_is_a_violation_not_a_skip(self, planted):
        """The one law, borrowed: unmeasurable is never a silent pass."""
        data = _clean_seed()
        del data["document_metadata"]["schema_version"]
        seed = planted(data)

        assert _shape_violations(_load(seed))

    def test_a_top_level_list_is_a_violation_naming_the_type(self, planted):
        seed = planted([_clean_seed()])

        violations = _shape_violations(_load(seed))

        assert violations == ["top level must be an object, found list"]

    def test_a_clean_seed_has_no_shape_violations(self, planted):
        seed = planted(_clean_seed())

        assert _shape_violations(_load(seed)) == []

    def test_an_unparseable_seed_fails_the_run_rather_than_being_skipped(self, planted):
        """``_load`` is the only place a broken file could quietly vanish."""
        seed = planted("{not json")

        with pytest.raises(AssertionError) as excinfo:
            _load(seed)

        assert "not valid JSON" in str(excinfo.value)
        assert str(seed) in str(excinfo.value)


class TestTheNameGuardBites:
    """One branch must never ship another's identity."""

    def test_a_mismatched_branch_name_is_named_with_both_sides(self, planted):
        data = _clean_seed(branch="testbranch")
        seed = planted(data, branch="otherbranch")

        violation = _name_violation(_load(seed), _branch_of(seed))

        assert "testbranch" in violation and "otherbranch" in violation

    def test_a_missing_branch_name_is_a_violation(self, planted):
        data = _clean_seed()
        del data["branch_info"]["branch_name"]
        seed = planted(data)

        assert _name_violation(_load(seed), _branch_of(seed))

    def test_a_matching_branch_name_passes(self, planted):
        seed = planted(_clean_seed(branch="testbranch"), branch="testbranch")

        assert _name_violation(_load(seed), _branch_of(seed)) == ""


# ===========================================================================
# C. THE SKIP IS NOT A HIDING PLACE
# ===========================================================================


class TestDiscoveryItself:
    """A suite that skips because its glob is wrong would report green forever
    -- the same silent-pass shape the trinity standard exists to end. So the
    glob is pinned against a synthetic tree, where seeds are known to exist.
    """

    def test_the_glob_finds_a_seed_in_a_real_shaped_tree(self, planted, tmp_path):
        planted(_clean_seed(branch="alpha"), branch="alpha")
        planted(_clean_seed(branch="beta"), branch="beta")

        found = _seed_paths(tmp_path)

        assert [_branch_of(path) for path in found] == ["alpha", "beta"]

    def test_a_seed_deeper_than_one_level_is_not_a_citizen_seed(self, tmp_path):
        """Spawn's class templates sit deeper and are not branches. Measuring
        them would fail the branch-name rule for a file that never claimed one.
        """
        deep = tmp_path / "src" / "aipass" / "spawn" / "templates" / "specialist" / _SEED_DIR / _SEED_NAME
        deep.parent.mkdir(parents=True)
        deep.write_text("{}", encoding="utf-8")

        assert _seed_paths(tmp_path) == []

    def test_an_empty_tree_finds_nothing_rather_than_raising(self, tmp_path):
        assert _seed_paths(tmp_path) == []

    def test_a_root_that_cannot_be_resolved_finds_nothing(self):
        assert _seed_paths(None) == []

    def test_the_repo_root_resolves_from_this_file(self):
        """If this ever returns None inside the repo, every pin above skips and
        the suite protects nothing.
        """
        root = _repo_root()

        assert root is not None
        assert (root / "src" / "aipass" / "seedgo").is_dir()

    def test_the_skip_reason_says_where_the_machinery_lives(self):
        """A skip nobody can act on is noise. This one names the verb."""
        assert "export-seeds" in _NO_SEEDS_REASON
        assert "parallel lane" in _NO_SEEDS_REASON

    def test_the_parameter_list_is_never_empty(self):
        """Empty parametrize generates zero tests, and zero tests look green."""
        assert _seed_params()
