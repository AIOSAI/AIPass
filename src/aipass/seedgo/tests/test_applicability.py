"""Tests for standard applicability (production / tests / everywhere) across both lanes."""

# =================== META ====================
# Name: test_applicability.py
# Description: Unit tests for aipass_standards/applicability.py and its two consumers
# Version: 1.16.0
# Created: 2026-08-09
# Modified: 2026-09-25
# =============================================

from types import SimpleNamespace

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import applicability
from aipass.seedgo.apps.handlers.audit import branch_audit
from aipass.seedgo.apps.handlers.audit.branch_audit import discover_checkers
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import SOURCE_SKIP_DIRS
from aipass.seedgo.apps.handlers.bypass.ignore_handler import AUDIT_IGNORE_PATTERNS
from aipass.seedgo.apps.modules import checklist


@pytest.fixture(autouse=True)
def _clear_path_caches():
    """The path predicates are lru_cached; tmp_path names differ per test but be explicit."""
    applicability.is_test_path.cache_clear()
    applicability.is_retired_path.cache_clear()
    yield


def _checker(applies_to=None, **attrs):
    """A stand-in checker module carrying only the constants the lanes read."""
    if applies_to is not None:
        attrs["APPLIES_TO"] = applies_to
    return SimpleNamespace(__name__="fake_check", **attrs)


# ---------------------------------------------------------------------------
# Path classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/repo/trigger/tests/test_events.py",
        "/repo/trigger/tests/unit/test_events.py",
        "/repo/spawn/tests/conftest.py",
        "/repo/spawn/conftest.py",
        r"C:\repo\trigger\tests\test_events.py",
    ],
)
def test_is_test_path_matches_test_trees_on_both_separators(path):
    assert applicability.is_test_path(path) is True


def test_is_test_path_does_not_match_a_production_module_named_test_something():
    """test_map.py is a real seedgo module — a filename heuristic would exempt it silently."""
    assert applicability.is_test_path("/repo/seedgo/apps/modules/test_map.py") is False
    assert applicability.is_test_path("/repo/seedgo/apps/handlers/test_map/function_scanner.py") is False


@pytest.mark.parametrize(
    "path",
    [
        "/repo/trigger/apps/handlers/events/.archive/bulletin_created.py",
        "/repo/commons/apps/modules/.archive/feed_module.py",
        "/repo/x/apps/deprecated/old.py",
        r"C:\repo\trigger\apps\handlers\events\.archive\bulletin_created.py",
    ],
)
def test_is_retired_path_matches_archived_trees_on_both_separators(path):
    assert applicability.is_retired_path(path) is True


def test_is_retired_path_leaves_live_source_alone():
    assert applicability.is_retired_path("/repo/trigger/apps/handlers/events/bulletin_created.py") is False


def test_retired_dirs_stay_in_step_with_the_lists_they_mirror():
    """RETIRED_DIRS must not become a third scope list that drifts from the other two."""
    assert {".archive", ".sorting_unprocessed"} <= SOURCE_SKIP_DIRS
    assert {".archive", ".sorting_unprocessed"} <= applicability.RETIRED_DIRS
    audit_patterns = "".join(AUDIT_IGNORE_PATTERNS)
    for name in (".archive", ".backup", "deprecated"):
        assert name in audit_patterns


# ---------------------------------------------------------------------------
# The declaration itself
# ---------------------------------------------------------------------------


def test_a_checker_with_no_declaration_applies_everywhere():
    """Fail-open: forgetting the constant costs noise, never a missed bug."""
    assert applicability.applies_to(_checker()) == applicability.EVERYWHERE


def test_an_unrecognised_declaration_falls_back_to_everywhere():
    assert applicability.applies_to(_checker("prod")) == applicability.EVERYWHERE


def test_an_unrecognised_declaration_is_reported_not_swallowed(monkeypatch):
    warnings = []
    monkeypatch.setattr(applicability.logger, "warning", lambda *a, **k: warnings.append(a))
    applicability.applies_to(_checker("prod"))
    # The typo itself has to be IN the warning: "something was wrong" sends the
    # author looking, "prod" tells them where. weak_oracle D2 convicted the
    # bare `assert warnings` that stood here.
    assert warnings[0][2] == "prod"


@pytest.mark.parametrize(
    "declared,production,tests",
    [
        (None, True, True),
        ("everywhere", True, True),
        ("production", True, False),
        ("tests", False, True),
    ],
)
def test_applies_to_file_matrix(declared, production, tests):
    checker = _checker(declared)
    assert applicability.applies_to_file(checker, "/repo/b/apps/modules/thing.py") is production
    assert applicability.applies_to_file(checker, "/repo/b/tests/test_thing.py") is tests


def test_no_checker_applies_to_retired_code():
    for declared in (None, "everywhere", "production", "tests"):
        assert applicability.applies_to_file(_checker(declared), "/repo/b/apps/.archive/old.py") is False


# ---------------------------------------------------------------------------
# The declarations the pack actually ships
# ---------------------------------------------------------------------------


def test_structural_standards_are_declared_production_only():
    """These failed on 25-96% of every branch's test files before they were scoped."""
    checkers = discover_checkers()
    for name in ("architecture", "encapsulation", "handlers", "modules", "meta", "documentation", "cli"):
        assert applicability.applies_to(checkers[name]) == applicability.PRODUCTION, name


def test_bug_finding_standards_still_apply_to_tests():
    """Scoping, not muting: Windows CI runs the whole suite, so a bad path in a test is real."""
    checkers = discover_checkers()
    for name in ("windows_compat", "hardcoded_path", "silent_catch", "hardcoded_key", "ruff"):
        assert applicability.applies_to(checkers[name]) == applicability.EVERYWHERE, name


def test_trigger_is_production_only():
    """A fixture unlinking its own scratch file is not a system state change.

    All 19 test-file hits fleet-wide were that; a test that fired real events to
    satisfy the standard would pollute the bus for every other branch.
    """
    assert applicability.applies_to(discover_checkers()["trigger"]) == applicability.PRODUCTION


def test_the_tests_only_bucket_is_an_exact_roster():
    """The tests-only bucket holds exactly the gold-seal rules, and not v4's.

    v4 `test_quality` was the sole APPLIES_TO = tests checker and it left
    2026-09-07; this test pinned the bucket EMPTY from then until 2026-09-20,
    precisely so that a future checker declaring `tests` would be a deliberate
    act and not an inherited one. `router_assert` is that act (owner ruling,
    gold seal phase 2 rules 1 and 2), so the assertion is an exact roster
    rather than being deleted — a further name appearing here still has to be
    argued for, and `test_quality` still has to stay gone. `import_site` is
    the third, argued on 2026-09-21: template v1 item 8, owner 20:11.
    `through_the_command` is the fourth, same day: template v1 item 10,
    owner 2026-09-20 22:28. `named_encoding` is the fifth, 2026-09-21:
    template v1 item 21, @devpulse dispatch a8ef55c8 — a test that writes a
    fixture without naming utf-8 reads it back as cp1252 in the Windows CI
    lane, which is a failure of the test and not of the product.
    `literal_path` is the sixth, 2026-09-22: template v1 item 22, @devpulse
    dispatch cfcb4191. It declares `tests` rather than `everywhere` because
    its cure is `tmp_path`, a fixture that exists only in a test: production
    code builds its paths from config and a rule telling it to use a pytest
    fixture would be nonsense. `hardcoded_path` keeps the production half.
    `file_top` is the seventh, 2026-09-22: template v1 items 5, 6 and 7,
    @devpulse dispatch d3685bc1. `meta` and `documentation` are both
    production-only, so a test file's header and docstring had no checker at
    all; this one declares `tests` because its third sub-rule, the declared
    pass, is a statement about tests and nothing else.
    `mock_console` is the eighth, 2026-09-22: template v1 item 14, @devpulse
    dispatch b552d057 — a console stand-in installed over the product, where
    the oracle should be the channel. `tests`, because `cli` and
    `output_routing` already own how production BUILDS a console, and this one
    is about what a test puts in its place.
    `state_leak` is the ninth, 2026-09-22: template v1 item 18, @devpulse
    dispatch 56121e07 — a write to shared state at test time with nothing to
    put it back. `tests`, because its whole vocabulary of cures is
    `monkeypatch`, a fixture that exists only in a test; production code that
    writes `os.environ` is doing its job.
    `conftest_fixtures` is the tenth, 2026-09-22: template v1 item 20 and the
    page's conftest section, @devpulse dispatch faced7be — the branch conftest
    pins the console width once and resets the command state after every test.
    `tests`, and narrower still: only `conftest.py` is ever judged, because
    item 16 puts these two fixtures in exactly one place and a rule that read
    them anywhere else would convict 563 files for not being the conftest.

    `no_product_call` and `duplicate_test` are the eleventh and twelfth,
    2026-09-22, @devpulse dispatch a3ad380b — the first two of the CRACK
    classes, and the first two names here that are not template items at all.
    They come from the owner's ruling on the eyes-on review of @backup's
    tests: 285 tests, 107 carrying a finding, and every one of the 107 passes
    all ten template checkers above. Those ten measure shape; these two
    measure whether a test reaches the product, and whether another test in
    the same file already said everything it says. Both declare `tests`
    because their unit is a `def test_*`, which production code does not have.

    `discarded_patch` and `weak_oracle` are the thirteenth and fourteenth,
    2026-09-22, @devpulse dispatch eb5602d0 — crack classes R and D from the
    same ruling, and D is the largest verdict class the reviewers found: 51
    WEAK rows out of 285 tests. R judges a patch of the test's OWN branch,
    which is why it needs a `tests` corpus and a path that names a branch; D
    judges a `def test_*`'s complete set of assertions, which production code
    does not have either.

    `flag_never_passed` and `uncalled_public_function` are the fifteenth and
    sixteenth, 2026-09-22, @devpulse dispatch cb55cc37 — crack classes P and O,
    and the first two here that are `branch_level`. Both compare a branch's
    `apps/` against its whole `tests/` tree, so no single file owns the
    verdict, and both declare `tests` because the question each asks is about
    what a TEST does: does any test pass this flag to the parser, does any test
    call this public function.

    `calendar_bound` joined on 2026-09-21 for a different reason and is the
    one name here that is not a template item: it is branch_level, so it walks
    its own corpus and this constant filters nothing for it — but that corpus
    has always been tests/ and lib/*/tests/, and every one of the 36 checkers
    that had no declaration got an explicit one when tests/ entered the audit
    corpus. Declaring it `everywhere` would have been the convenient lie.
    """
    checkers = discover_checkers()
    tests_only = sorted(n for n, c in checkers.items() if applicability.applies_to(c) == applicability.TESTS)
    assert tests_only == [
        "calendar_bound",
        "conftest_fixtures",
        "constant_predicate",
        "declared_pass_contradiction",
        "declared_pass_symbol_resolves",
        "discarded_patch",
        "duplicate_test",
        "file_top",
        "flag_never_passed",
        "import_site",
        "literal_path",
        "mock_console",
        "module_scope_side_effect",
        "named_encoding",
        "no_product_call",
        "oversize_test_file",
        "retired_token_docstring",
        "router_assert",
        "self_set_assert",
        "sleep_in_test",
        "stale_header_date",
        "state_leak",
        "stdlib_patch",
        "subprocess_text_true",
        "through_the_command",
        "uncalled_public_function",
        "unconsumed_side_effect",
        "unused_conftest_fixture",
        "weak_oracle",
    ]
    assert "test_quality" not in checkers


# ---------------------------------------------------------------------------
# Both lanes consult it
# ---------------------------------------------------------------------------


def test_checklist_lane_honours_the_declaration(tmp_path, monkeypatch):
    """Through the command: which standards the lane REPORTS on each kind of file.

    Reads the pack's real declarations rather than a stand-in checker, so the
    lane is measured end to end -- `architecture` is production-only,
    `import_site` is tests-only, `naming` is everywhere.
    """
    monkeypatch.setattr(checklist, "is_throwaway_path", lambda _p: False)

    source = tmp_path / "apps" / "modules" / "thing.py"
    source.parent.mkdir(parents=True)
    source.write_text("X = 1\n", encoding="utf-8")
    test_file = tmp_path / "tests" / "test_thing.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_x():\n    assert True\n", encoding="utf-8")

    on_source = {r["standard"] for r in checklist.run_checklist(str(source))}
    on_test = {r["standard"] for r in checklist.run_checklist(str(test_file))}

    assert "architecture" in on_source and "architecture" not in on_test
    assert "import_site" in on_test and "import_site" not in on_source
    assert {"naming"} <= on_source & on_test


def test_checklist_lane_skips_retired_files(tmp_path, monkeypatch):
    """The audit lane always skipped .archive/; this lane used to flag it.

    tmp_path lives under the system temp dir, which both lanes skip as
    throwaway before anything else — neutered here so the retired rule is what
    is actually under test.
    """
    monkeypatch.setattr(checklist, "is_throwaway_path", lambda _p: False)

    archived = tmp_path / "apps" / "handlers" / ".archive" / "bulletin_created.py"
    archived.parent.mkdir(parents=True)
    archived.write_text("x=1\n", encoding="utf-8")

    results = checklist.run_checklist(str(archived))
    assert [r["standard"] for r in results] == ["(skip)"]
    assert "Retired" in results[0]["detail"]


def test_audit_lane_does_not_collect_retired_files(tmp_path, monkeypatch):
    """Through the command: the audit's own corpus count and violation lines.

    `x=1` is a naming violation in both files, so an archived file that reached
    the corpus would name itself in the report. Asserting on the audit's output
    rather than on the collector proves no checker ever saw it.
    """
    monkeypatch.setattr(branch_audit, "is_throwaway_path", lambda _p: False)

    live = tmp_path / "apps" / "modules" / "live.py"
    live.parent.mkdir(parents=True)
    live.write_text("x=1\n", encoding="utf-8")
    archived = tmp_path / "apps" / "modules" / ".archive" / "old.py"
    archived.parent.mkdir(parents=True)
    archived.write_text("x=1\n", encoding="utf-8")

    output = branch_audit.audit_branch({"name": "tmpb", "path": str(tmp_path), "entry_file": ""}, [])

    assert output["corpus_size"] == 1
    assert {v["file"] for v in output["naming_violations"]} == {"live.py"}


# ---------------------------------------------------------------------------
# The corpus: tests/ joined it on 2026-09-21 (owner ruling 21:20)
# ---------------------------------------------------------------------------


def _branch(tmp_path, **files):
    """A throwaway branch tree: keys are branch-relative paths, values are source."""
    for rel, body in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return tmp_path


#: Every file these corpus tests write carries this line. It is a naming
#: violation, so any file the audit actually measured names itself in
#: naming_violations — which is how the corpus is read here through the
#: command rather than off the collector.
NAMES_ITSELF = "x = 1\n"


def _corpus(branch_path):
    """The file names the audit measured, read from its own output."""
    output = branch_audit.audit_branch({"name": "tmpb", "path": str(branch_path), "entry_file": ""}, [])
    return {v["file"] for v in output["naming_violations"]}


def test_the_corpus_takes_test_files_and_conftest(tmp_path, monkeypatch):
    """The whole point of the ruling: a tests-only standard needs files to score."""
    monkeypatch.setattr(branch_audit, "is_throwaway_path", lambda _p: False)
    root = _branch(
        tmp_path,
        **{
            "apps/modules/live.py": NAMES_ITSELF,
            "tests/test_thing.py": NAMES_ITSELF,
            "tests/conftest.py": NAMES_ITSELF,
        },
    )

    assert _corpus(root) == {"live.py", "test_thing.py", "conftest.py"}


def test_a_helper_beside_the_tests_is_not_in_the_corpus(tmp_path, monkeypatch):
    """A standard written for a test's author has nothing to say to a helper module."""
    monkeypatch.setattr(branch_audit, "is_throwaway_path", lambda _p: False)
    root = _branch(
        tmp_path,
        **{"apps/modules/live.py": NAMES_ITSELF, "tests/helpers.py": NAMES_ITSELF, "tests/test_x.py": NAMES_ITSELF},
    )

    assert _corpus(root) == {"live.py", "test_x.py"}


@pytest.mark.parametrize(
    "rel",
    [
        "tests/parked/conftest.py",
        "tests/parked/dead_lane/test_old.py",
        "tests/.archive/test_scaffold.py",
        "tests/test_thing(disabled).py",
    ],
)
def test_set_aside_test_code_never_enters_the_corpus(tmp_path, monkeypatch, rel):
    """Four ways a test file is already retired, and each keeps it out.

    `parked` is the one that had to be ADDED (2026-09-21): six of the fleet's
    nine parked files carry the house `(disabled)` suffix, but the three
    `tests/parked/conftest.py` collection barriers carry nothing, and they
    would have entered the corpus as live test files.
    """
    monkeypatch.setattr(branch_audit, "is_throwaway_path", lambda _p: False)
    root = _branch(tmp_path, **{"apps/modules/live.py": NAMES_ITSELF, rel: NAMES_ITSELF})

    assert _corpus(root) == {"live.py"}


def test_a_tests_only_standard_scores_a_row_when_the_branch_has_tests(tmp_path, monkeypatch):
    """The gate fix: a tests-only checker used to be dropped at the ENTRY file.

    applies_to_file(checker, entry_file) is False for a tests-only standard,
    because the entry file is production source. That `continue` skipped the
    whole checker, so the all_files scan below it never ran and the standard
    stayed off the board even with tests/ in the corpus.
    """
    monkeypatch.setattr(branch_audit, "is_throwaway_path", lambda _p: False)
    root = _branch(
        tmp_path,
        **{
            "apps/modules/live.py": "X = 1\n",
            "tests/test_thing.py": "def test_x():\n    from aipass.prax import logger\n    assert logger\n",
        },
    )

    output = branch_audit.audit_branch({"name": "tmpb", "path": str(root), "entry_file": ""}, [])

    assert "import_site" in output["scores"]
    assert output["scores"]["import_site"] == 0
    assert {v["file"] for v in output["import_site_violations"]} == {"test_thing.py"}


def test_a_branch_with_no_tests_stands_the_standard_down_rather_than_dropping_it(tmp_path, monkeypatch):
    """The CI tripwire counts standards CONSULTED, so the slot has to stay filled.

    Scoring 0 would blame the branch for having no tests yet; scoring 100 would
    claim a measurement that never happened; reporting nothing would trip the
    tripwire on the first branch that ships without a tests/ directory.
    """
    monkeypatch.setattr(branch_audit, "is_throwaway_path", lambda _p: False)
    root = _branch(tmp_path, **{"apps/modules/live.py": "X = 1\n"})

    output = branch_audit.audit_branch({"name": "tmpb", "path": str(root), "entry_file": ""}, [])

    assert "import_site" not in output["scores"]
    assert output["results"]["import_site"]["not_applicable"] is True
