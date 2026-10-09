# =================== AIPass ====================
# Name: test_audit_tests_lane_statement_deletion.py
# Description: audit-tests statement deletion operator and its diff scope (split from test_audit_tests_lane.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/tests_pytest_standards/statement_deletion.py and diff_scope.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in handlers/audit_tests/ and handlers/tests_pytest_standards/ parses
# seedgo: no-test-needed(documentation) — that the public lane functions carry docstrings

import pytest

from aipass.seedgo.apps.handlers.audit_tests import spine
from aipass.seedgo.apps.handlers.tests_pytest_standards import (
    adapter,
    diff_scope,
    envcopy,
    statement_deletion as SD,
)
from aipass.seedgo.apps.modules import audit_tests
from aipass.seedgo.tests.support_audit_tests_lane import _spec_for

# =============================================================================
# STATEMENT DELETION — the operator commissioned by DPLAN-0352 round 2
#
# The species is three-instanced: a statement that executes, is documented as
# doing something, and that no test observes. Whole-body gutting cannot
# isolate it because the body has other work in it.
# =============================================================================


class TestStatementDeletionStaysAtStatementLevel:
    """The brief's hard boundary: statement level, never branch deletion."""

    def _sites(self, tmp_path, source):
        apps = tmp_path / "apps"
        apps.mkdir()
        (apps / "mod.py").write_text(source, encoding="utf-8")
        return SD.discover_statements(tmp_path)

    def test_a_compound_header_is_never_a_deletion_site(self, tmp_path):
        """Deleting an `if` deletes its block, which is branch deletion and a
        different, harder operator. The boundary is enforced, not documented."""
        source = (
            "def f(flag):\n"
            "    if flag:\n"
            "        trail('taken')\n"
            "    for item in flag:\n"
            "        trail(item)\n"
            "    return 1\n"
        )
        kinds = {s.kind for s in self._sites(tmp_path, source)}
        assert "If" not in kinds
        assert "For" not in kinds
        assert "Expr" in kinds, "but it must still reach the statements INSIDE the block"

    def test_statements_inside_a_compound_are_reached(self, tmp_path):
        """The trail call round 3 found was inside a block, not beside one."""
        source = (
            "def f(x):\n    try:\n        trail('before')\n        raise ValueError(x)\n"
            "    finally:\n        trail('after')\n"
        )
        lines = {s.source_line for s in self._sites(tmp_path, source)}
        assert "trail('before')" in lines
        assert "trail('after')" in lines
        assert "raise ValueError(x)" in lines


class TestStatementDeletionAridList:
    """Declared from line one, with the reason each cannot change behaviour."""

    def _sites(self, tmp_path, source):
        apps = tmp_path / "apps"
        apps.mkdir(exist_ok=True)
        (apps / "mod.py").write_text(source, encoding="utf-8")
        return SD.discover_statements(tmp_path)

    def test_a_docstring_is_arid_and_carries_its_reason(self, tmp_path):
        sites = self._sites(tmp_path, 'def f():\n    """The docstring."""\n    return work()\n')
        doc = [s for s in sites if s.source_line.startswith('"""')]
        assert doc and doc[0].arid_reason == SD.ARID_DOCSTRING
        assert SD.ARID_REASONS[SD.ARID_DOCSTRING]

    def test_every_arid_reason_is_declared_with_a_why(self, tmp_path):
        """A suppression with no reason is a denylist, which is the thing the
        brief said must not happen."""
        for name in (SD.ARID_DOCSTRING, SD.ARID_PASS, SD.ARID_ELLIPSIS, SD.ARID_SOLE_RETURN_NONE):
            assert SD.ARID_REASONS.get(name), f"{name} is suppressed with no reason"

    def test_a_logging_call_is_never_arid(self, tmp_path):
        """Trail and telemetry calls LOOK arid and are the species itself.
        Suppressing them would have suppressed all three sightings."""
        sites = self._sites(tmp_path, "def f():\n    logger.info('did the thing')\n    return 1\n")
        trail = [s for s in sites if "logger.info" in s.source_line]
        assert trail and trail[0].arid_reason is None

    def test_arid_statements_are_returned_not_dropped(self, tmp_path):
        """A list that quietly drops half the tree then reports a rate is
        lying about its denominator."""
        sites = self._sites(tmp_path, 'def f():\n    """Doc."""\n    return work()\n')
        assert any(s.arid_reason for s in sites), "arid sites stay in the list"
        assert all(s.arid_reason is None for s in SD.probeable(sites)), "but never get probed"

    def _return_arid(self, tmp_path, source):
        """The arid reason on every bare `return` in `source`, in line order."""
        sites = self._sites(tmp_path, source)
        return [s.arid_reason for s in sorted(sites, key=lambda s: s.lineno) if s.kind == "Return"]

    def test_a_guard_return_is_never_arid(self, tmp_path):
        """THE ROUND-5 DEFECT (devpulse, canary a36f500a). `is_last` was
        computed per BLOCK, so the `return` closing an `if` was declared arid.
        That is the definition of a guard clause and the species this operator
        exists to probe: canary's `kv.py:238` was filtered out before it was
        ever run, and deleting it leaves 91 tests green while
        `kv --json FILE set K V` prints its refusal, exits 2, AND writes."""
        source = "def f(a):\n    if a:\n        log('refused')\n        return\n    write(a)\n"
        assert self._return_arid(tmp_path, source) == [None]

    def test_a_return_in_tail_position_is_still_arid(self, tmp_path):
        """The cure must not simply stop suppressing. Both of these DO fall
        off the end of the function, so deleting them changes nothing."""
        flat = "def f(a):\n    write(a)\n    return\n"
        assert self._return_arid(tmp_path, flat) == [SD.ARID_SOLE_RETURN_NONE]

        nested = "def f(a):\n    if a:\n        write(a)\n        return\n"
        assert self._return_arid(tmp_path, nested) == [SD.ARID_SOLE_RETURN_NONE]

    def test_a_return_closing_a_loop_body_is_never_arid(self, tmp_path):
        """Not in the round-5 report — measured here. Reaching the end of a
        loop body starts the next iteration, so deleting the `return` keeps
        looping instead of leaving the function."""
        source = "def f(xs):\n    for x in xs:\n        if x:\n            return\n    write('done')\n"
        assert self._return_arid(tmp_path, source) == [None]

        while_tail = "def f(xs):\n    while xs:\n        xs.pop()\n        return\n"
        assert self._return_arid(tmp_path, while_tail) == [None]

    def test_a_return_closing_a_finally_is_never_arid(self, tmp_path):
        """Also measured here, not reported. A `return` in a `finally`
        SWALLOWS the pending return value or exception; deleting it stops the
        swallowing, which is the opposite of a no-op."""
        source = "def f():\n    try:\n        return compute()\n    finally:\n        return\n"
        assert self._return_arid(tmp_path, source) == [None, None]

    def test_a_return_closing_a_try_body_with_an_else_is_never_arid(self, tmp_path):
        """An `else` runs when the try completes normally, so falling off the
        try body runs code the `return` skipped."""
        source = "def f():\n    try:\n        return\n    except E:\n        h()\n    else:\n        k()\n"
        assert self._return_arid(tmp_path, source) == [None]

    def test_a_return_closing_an_except_handler_at_the_tail_is_arid(self, tmp_path):
        """Falling off a handler leaves the whole `try`, and here that is the
        end of the function. Keeping this one arid is what stops the cure from
        convicting equivalent mutants."""
        source = "def f():\n    try:\n        g()\n    except E:\n        return\n"
        assert self._return_arid(tmp_path, source) == [SD.ARID_SOLE_RETURN_NONE]


class TestStatementDeletionDiscoveryIsUnique:
    """One statement, one site. A double-counted tree lies about its rate."""

    def test_a_nested_def_is_walked_once_not_twice(self, tmp_path):
        """Found here, not in the round-5 report. `discover_statements` finds
        functions with `ast.walk`, which already reaches every nested `def`,
        and `_walk_block` descended into them as well — so each nested
        statement was emitted twice, once under each qualname. It inflates any
        denominator built on the site count and pays to run one mutant twice."""
        apps = tmp_path / "apps"
        apps.mkdir()
        (apps / "mod.py").write_text(
            "def outer(a):\n    x = 1\n    def inner(b):\n        y = 2\n        return y\n    return inner(a) + x\n",
            encoding="utf-8",
        )
        sites = SD.discover_statements(tmp_path)
        addresses = [(s.relpath, s.lineno) for s in sites]
        assert len(addresses) == len(set(addresses)), f"a line was emitted twice: {addresses}"
        inner_y = [s for s in sites if s.source_line == "y = 2"]
        assert len(inner_y) == 1
        assert inner_y[0].function_qualname == "inner", "attributed to its own function"


class TestStatementDeletionConviction:
    """The sentence IS the product. A percentage teaches nobody."""

    def _result(self, statement, tests=5, relpath="apps/m.py", line=87):
        site = SD.StatementSite(
            relpath=relpath,
            qualname="f",
            function_qualname="f",
            lineno=line,
            end_lineno=line,
            body_lineno=line,
            body_col_offset=0,
            kind="Expr",
            is_sole_statement=False,
            source_line=statement,
        )
        return SD.StatementResult(site=site, outcome=SD.OUTCOME_SURVIVED, selected_tests=tests)

    def test_a_conviction_names_file_line_statement_and_the_observation(self):
        """The brief's four-part contract, one assertion per part."""
        line = SD.conviction_line(self._result('json_handler.log_operation("table_refused", {})', tests=20))
        assert "apps/m.py:87" in line, "the address a builder navigates by"
        assert "log_operation" in line, "the statement itself"
        assert "reached by 20 tests" in line, "the count that makes it a conviction, not a coverage note"
        assert "operations trail for 'table_refused'" in line, "what would observe it"

    def test_the_observation_clause_follows_the_statement_shape(self):
        assert "captured log record at warning" in SD.observation_clause('logger.warning("x", a)')
        assert "captured stdout" in SD.observation_clause('console.print("hello")')
        assert "refusal reason" in SD.observation_clause('error("kv refused: no verb")')
        assert "did not happen" in SD.observation_clause("return"), "a guard return, the round-5 species"

    def test_a_chained_call_names_the_function_it_actually_calls(self):
        """Reading the FIRST identifier sends the builder to assert on the
        wrong thing: these two are calls to `unlink` and `__init__`, and both
        are real canary a36f500a survivors."""
        assert "unlink()" in SD.observation_clause("Path(temp_name).unlink(missing_ok=True)")
        assert "__init__()" in SD.observation_clause("super().__init__(reason)")

    def test_an_unparseable_statement_still_gets_a_sentence(self):
        """The fall-through matches everything rather than guessing."""
        assert SD.observation_clause("del broken(((")
        assert SD.observation_clause("")

    def test_a_statement_no_test_reaches_is_never_convicted(self):
        """A statement with no covering test is a COVERAGE fact. Convicting it
        would blame the assertions for a gap in what the suite executes."""
        campaign = SD.StatementCampaign(
            baseline=None,
            results=[
                SD.StatementResult(
                    site=self._result("trail('x')").site,
                    outcome=SD.OUTCOME_SURVIVED,
                    reason=SD.REASON_NO_COVERING_TEST,
                )
            ],
        )
        document = SD.summarize(campaign, [])
        assert document["convictions"] == []
        assert document["survived_no_covering_test"] == 1


class TestStatementDeletionCostIsSplit:
    """Fixed setup is not a per-mutant cost, and naming it one misled an owner."""

    def _campaign(self, own_times, elapsed):
        results = []
        for index, seconds in enumerate(own_times):
            site = SD.StatementSite(
                relpath="apps/m.py",
                qualname="f",
                function_qualname="f",
                lineno=index + 1,
                end_lineno=index + 1,
                body_lineno=index + 1,
                body_col_offset=0,
                kind="Expr",
                is_sole_statement=False,
                source_line="trail('x')",
            )
            results.append(SD.StatementResult(site=site, outcome=SD.OUTCOME_KILLED, elapsed_seconds=seconds))
        return SD.StatementCampaign(baseline=None, results=results, elapsed_seconds=elapsed)

    def test_setup_is_not_charged_to_the_mutants(self):
        """THE DEVPULSE CORRECTION, with its own numbers. 278.72s over 2
        mutants published 139.36 s/mutant, while the two mutants' own clocks
        read 0.98 and 1.58. I reported that 139 upward as a per-mutant floor."""
        document = SD.summarize(self._campaign([0.98, 1.58], 278.72), [])
        assert document["setup_seconds"] == 276.16, "the one-time cost, named as one-time"
        assert document["seconds_per_mutant_mean"] == 1.28
        assert document["seconds_per_mutant_max"] == 1.58
        assert "seconds_per_mutant" not in document, "the conflated metric is gone, not renamed"

    def test_the_median_travels_beside_the_mean(self):
        """A deletion campaign's tail is long — canary read a 0.74s median
        against a 2.14s mean with one mutant at 15.13s. A mean alone hides it."""
        document = SD.summarize(self._campaign([0.5, 0.5, 0.5, 30.0], 40.0), [])
        assert document["seconds_per_mutant_median"] == 0.5
        assert document["seconds_per_mutant_mean"] == 7.88
        assert document["seconds_per_mutant_max"] == 30.0

    def test_the_cost_model_says_how_to_project(self):
        """A reader who multiplies the wrong number reprices the whole lane."""
        model = SD.summarize(self._campaign([1.0, 1.0], 50.0), [])["cost_model"]
        assert "setup_seconds" in model and "does NOT scale" in model


class TestStatementDeletionHangTimeout:
    """The ceiling has to clear an honest mutant and still catch a hang."""

    def test_the_ceiling_leaves_room_above_the_baseline(self, tmp_path):
        """ROUND-5 DEFECT TWO. The ceiling was `int(baseline)` exactly, argued
        from 'a run over a SUBSET cannot outlast the whole suite'. When
        selection has no coverage entry it falls back to the WHOLE suite, so
        the honest cost IS the baseline and the ceiling loses a coin toss:
        canary's only two `not_run / mutant_timeout` of 153 were its only two
        `unmapped_test_context` mutants, both at 19.03s against a 19s wall."""
        assert SD.hang_timeout(19.0) > 19, "a whole-suite fallback must fit under its own ceiling"
        assert SD.hang_timeout(19.0) == 38

    def test_the_floor_still_holds_for_a_fast_suite(self, tmp_path):
        assert SD.hang_timeout(0.0) == SD.HANG_TIMEOUT_FLOOR_SECONDS
        assert SD.hang_timeout(1.0) == SD.HANG_TIMEOUT_FLOOR_SECONDS


class TestStatementDeletionMutant:
    """The splice itself."""

    def _site(self, tmp_path, source, needle):
        apps = tmp_path / "apps"
        apps.mkdir()
        (apps / "mod.py").write_text(source, encoding="utf-8")
        return next(s for s in SD.discover_statements(tmp_path) if needle in s.source_line)

    def test_deletion_removes_only_that_statement(self, tmp_path):
        """Mutant: the splice leaves a blank line where the statement was in apps/handlers/tests_pytest_standards/statement_deletion.py — killed."""
        source = "def f(x):\n    trail('here')\n    return x + 1\n"
        site = self._site(tmp_path, source, "trail(")
        mutant = SD.delete_statement(source, site)
        assert mutant == "def f(x):\n    return x + 1\n", "the statement's own lines go and nothing else changes"
        assert "trail(" not in mutant
        assert "def f(x):" in mutant, "the signature stays byte-identical or selection is unsound"
        assert "return x + 1" in mutant

    def test_a_sole_statement_becomes_pass_rather_than_a_syntax_error(self, tmp_path):
        """Mutant: pass inserted above the sole statement, which stays, in apps/handlers/tests_pytest_standards/statement_deletion.py — killed."""
        source = "def f(x):\n    if x:\n        trail('only')\n    return x\n"
        site = self._site(tmp_path, source, "trail(")
        mutant = SD.delete_statement(source, site)
        assert mutant == "def f(x):\n    if x:\n        pass\n    return x\n", "pass REPLACES the statement"
        compile(mutant, "mod.py", "exec")

    def test_a_statement_spans_its_own_lines_not_the_functions(self, tmp_path):
        """This IS the cost argument: a statement is judged by the tests that
        execute its own lines, a strictly smaller set than the function's."""
        source = "def f(x):\n    a = 1\n    trail('here')\n    return a + x\n"
        site = self._site(tmp_path, source, "trail(")
        probe = site.as_function_site()
        assert probe.body_lineno == site.lineno == 3
        assert probe.end_lineno == 3, "one statement, not the whole body"


class TestEnvcopySourcesSiblingsForABankedFixture:
    """seedgo todo 123: both banked fixtures refused, and the sentence the
    lane printed named a plugin rather than the cause."""

    def test_a_fixture_borrows_siblings_from_the_running_checkout(self, tmp_path):
        fixture = tmp_path / "src" / "aipass" / "canary"
        fixture.mkdir(parents=True)
        source, basis = envcopy.sibling_source(tmp_path, "canary")
        assert basis == envcopy.SIBLINGS_FROM_HOST_REPO
        assert (source / "prax").is_dir(), "the real dependencies, or the conftest import fails"

    def test_a_real_repo_uses_its_own_siblings(self):
        root = envcopy.host_repo_root()
        assert root is not None
        assert envcopy.sibling_source(root, "canary")[1] == envcopy.SIBLINGS_FROM_OWN_ROOT

    def test_the_host_root_is_found_by_marker_not_by_counting_parents(self):
        """A parent count is a silent liar the day the file moves one level,
        and the first cut of this was off by exactly one."""
        root = envcopy.host_repo_root()
        assert root is not None, "the running checkout always holds src/aipass"
        assert (root / "src" / "aipass").is_dir()

    def test_no_siblings_anywhere_refuses_by_name(self, tmp_path, monkeypatch):
        """Mutant: the host checkout never consulted in apps/handlers/tests_pytest_standards/envcopy.py — killed."""
        (tmp_path / "src" / "aipass" / "canary").mkdir(parents=True)
        asked: list = []
        monkeypatch.setattr(envcopy, "host_repo_root", lambda: asked.append("host"))
        with pytest.raises(envcopy.EnvError) as excinfo:
            envcopy.sibling_source(tmp_path, "canary")
        assert "no sibling packages for canary" in str(excinfo.value)
        assert asked == ["host"], "the running checkout is asked before the refusal"


class TestStatementDeletionIsDeclaredToTheLane:
    """An execution group that runs mutants is bound by the lane's own laws."""

    def test_the_group_is_opt_in_and_flagged(self):
        assert SD.GROUP in adapter.OPT_IN_EXECUTION_GROUPS
        assert adapter.OPT_IN_FLAGS[SD.GROUP] == "--statement-deletion"

    def test_it_is_kill_cause_bound_and_carries_a_contract(self):
        """It executes mutants, so Law S9 requires a kill_cause on every
        record and the artifact needs the contract that reads them."""
        assert SD.GROUP in spine.KILL_CAUSE_BOUND
        assert "branch deletion is out of reach" in spine.GROUP_CONTRACTS[SD.GROUP]

    def test_the_not_requested_reason_names_the_flag_and_not_not_built(self, tmp_path):
        reason = adapter.nominate(_spec_for(tmp_path))[SD.GROUP]["reason"]
        assert "--statement-deletion" in reason
        assert "not built" not in reason

    def test_the_cli_flag_reaches_the_group(self):
        assert audit_tests.OPT_IN_GROUP_FLAGS["--statement-deletion"] == "statement_deletion"
        assert "--statement-deletion" in audit_tests.LANE_FLAGS


class TestStatementDeletionRefusesAnUncompilableMutant:
    """An engine bug must never reach the suite dressed as a perfect kill."""

    def test_a_semicolon_line_is_reported_not_written(self, tmp_path):
        """Two statements on one line are one LINE RANGE, so deleting either
        deletes both and can empty a block. The mutant is compiled before it
        is written, so this comes back `mutation_failed` - which is not
        evidence about the suite - rather than as a green run against a file
        that never imported. It is also this operator's honest limit: a
        semicolon line is mutated as a unit."""
        apps = tmp_path / "apps"
        apps.mkdir()
        source = "def f(x):\n    if x:\n        a = 1; trail('x')\n    return x\n"
        (apps / "mod.py").write_text(source, encoding="utf-8")

        site = next(s for s in SD.discover_statements(tmp_path) if "a = 1" in s.source_line)
        assert site.is_sole_statement is False, "the block holds two statements by AST count"

        mutant, failure = SD._mutant_text(source, site)
        assert mutant is None
        assert failure == SD.REASON_MUTANT_NOT_PARSEABLE

    def test_a_bare_string_is_arid_anywhere_in_the_body(self, tmp_path):
        """Not only at position 0 - a string alone on a line is evaluated and
        discarded wherever it sits."""
        apps = tmp_path / "apps"
        apps.mkdir()
        (apps / "mod.py").write_text(
            'def f(x):\n    """Doc."""\n    x = 1\n    "mid body"\n    return x\n', encoding="utf-8"
        )
        sites = SD.discover_statements(tmp_path)
        mid = next(s for s in sites if "mid body" in s.source_line)
        assert mid.arid_reason == SD.ARID_DOCSTRING


class TestStatementDeletionSurvivorRollup:
    """A survivor list nobody can triage is worse than no operator (the brief).

    Measured on canary's round-4 tree: 230 survivors, 188 of them inside
    `print_help` and `print_introspection` - two functions `pseudo_tested`
    already convicts whole. The statement-level list this operator exists for
    was the other 42, buried under 82% noise from one cause.
    """

    def _campaign(self, rows):
        """rows: (file, qualname, lineno, outcome) -> a campaign to roll up."""
        results = []
        for relpath, qualname, lineno, outcome in rows:
            site = SD.StatementSite(
                relpath=relpath,
                qualname=f"{qualname}:{lineno}",
                function_qualname=qualname,
                lineno=lineno,
                end_lineno=lineno,
                body_lineno=lineno,
                body_col_offset=4,
                kind="Expr",
                is_sole_statement=False,
                source_line="console.print()",
            )
            results.append(SD.StatementResult(site=site, outcome=outcome))
        return SD.StatementCampaign(baseline=None, results=results)

    def test_a_function_whose_every_statement_survived_becomes_one_row(self):
        campaign = self._campaign(
            [("apps/m.py", "print_help", n, SD.OUTCOME_SURVIVED) for n in (10, 11, 12, 13)]
            + [("apps/m.py", "_top", 40, SD.OUTCOME_SURVIVED), ("apps/m.py", "_top", 41, SD.OUTCOME_KILLED)]
        )
        rollup = SD.summarize(campaign, [r.site for r in campaign.results])["survivor_rollup"]

        assert rollup["survivors_total"] == 5
        assert rollup["statements_rolled_up"] == 4
        assert rollup["survivors_after_rollup"] == 1, "the one statement-level finding, not five"
        assert [r["function"] for r in rollup["functions_wholly_unobserved"]] == ["print_help"]
        assert rollup["functions_wholly_unobserved"][0]["first_line"] == 10

    def test_a_function_with_one_kill_is_never_rolled_up(self):
        """One surviving statement inside an otherwise observed function is
        exactly the species this operator was commissioned for - the trail call
        beside a `raise` that kills. Rolling it up would delete the finding."""
        campaign = self._campaign(
            [
                ("apps/h.py", "_refuse", 87, SD.OUTCOME_SURVIVED),
                ("apps/h.py", "_refuse", 88, SD.OUTCOME_KILLED),
            ]
        )
        rollup = SD.summarize(campaign, [r.site for r in campaign.results])["survivor_rollup"]

        assert rollup["functions_wholly_unobserved"] == []
        assert rollup["survivors_after_rollup"] == 1

    def test_a_lone_surviving_statement_is_a_statement_finding_not_a_function_one(self):
        """A function with exactly one executed mutant says nothing about the
        function when that mutant survives - there is no 'every' to be true of."""
        campaign = self._campaign([("apps/m.py", "_add", 99, SD.OUTCOME_SURVIVED)])
        rollup = SD.summarize(campaign, [r.site for r in campaign.results])["survivor_rollup"]

        assert rollup["functions_wholly_unobserved"] == []
        assert rollup["survivors_after_rollup"] == 1
        assert SD.ROLLUP_MIN_STATEMENTS == 2

    def test_the_rollup_is_a_collapse_and_never_a_suppression(self):
        """Law: nothing leaves `mutants[]`. The rollup is a reading aid over a
        record that still carries every verdict."""
        campaign = self._campaign([("apps/m.py", "print_help", n, SD.OUTCOME_SURVIVED) for n in (10, 11)])
        sites = [r.site for r in campaign.results]
        document = SD.summarize(campaign, sites)

        assert document["survived"] == 2, "the headline count is untouched by the rollup"
        assert len(document["mutants"]) == 2, "both mutants still carry their own verdict"
        assert document["survivor_rollup"]["survivors_after_rollup"] == 0
        assert any("never a suppression" in limit for limit in document["limits"])

    def test_a_partly_observed_function_is_the_species_and_keeps_its_rows(self):
        """canary.py's print_help: 41 of 43 statements deleted green, 2 killed.
        Gutting cannot report it - those 2 assertions protect the whole body -
        so the 41 must stay statement-level and the row must say 41 of 43."""
        rows = [("apps/canary.py", "print_help", n, SD.OUTCOME_SURVIVED) for n in range(10, 51)]
        rows += [("apps/canary.py", "print_help", n, SD.OUTCOME_KILLED) for n in (51, 52)]
        campaign = self._campaign(rows)
        rollup = SD.summarize(campaign, [r.site for r in campaign.results])["survivor_rollup"]

        assert rollup["functions_wholly_unobserved"] == [], "one observed statement blocks the rollup"
        assert rollup["survivors_after_rollup"] == 41
        row = rollup["survivors_by_function"][0]
        assert (row["statements"], row["of_executed"]) == (41, 43)

    def test_survivors_by_function_ranks_the_worst_first(self):
        rows = [("apps/a.py", "small", 10, SD.OUTCOME_SURVIVED)]
        rows += [("apps/b.py", "big", n, SD.OUTCOME_SURVIVED) for n in (20, 21, 22)]
        campaign = self._campaign(rows)
        rollup = SD.summarize(campaign, [r.site for r in campaign.results])["survivor_rollup"]

        assert [r["function"] for r in rollup["survivors_by_function"]] == ["big", "small"]


class TestDiffScopeIsLinesNotFiles:
    """The brief's first boundary: a one-line fix probes one statement."""

    def test_a_hunk_header_yields_only_its_own_lines(self):
        diff = "+++ b/src/aipass/seedgo/apps/m.py\n@@ -10,1 +10,3 @@\n+a\n+b\n+c\n"
        assert diff_scope.parse_changed_lines(diff) == {"src/aipass/seedgo/apps/m.py": {10, 11, 12}}

    def test_a_pure_deletion_puts_nothing_in_scope(self):
        """A `+` count of 0 adds no line, so there is nothing to splice into -
        limit 2 falling out of the parse rather than bolted on after it."""
        diff = "+++ b/apps/m.py\n@@ -10,4 +9,0 @@\n-gone\n"
        assert diff_scope.parse_changed_lines(diff) == {}

    def test_the_granularity_is_published_not_inferred(self):
        """The brief: if file scope ever ships because line scope is harder,
        the artifact must SAY so rather than let a count imply line scope."""
        scope = diff_scope.DiffScope(changed={"apps/m.py": {4}}, ref="HEAD~1")
        document = scope.to_document()
        assert document["granularity"] == diff_scope.GRANULARITY_LINE
        assert diff_scope.GRANULARITY is diff_scope.GRANULARITY_LINE
        assert document["ref"] == "HEAD~1"

    def test_a_multi_line_statement_is_in_scope_when_its_middle_changed(self):
        scope = diff_scope.DiffScope(changed={"apps/m.py": {21}})
        assert scope.holds("apps/m.py", 20, 23) is True
        assert scope.holds("apps/m.py", 30, 33) is False
        assert scope.holds("apps/other.py", 20, 23) is False

    def test_the_scope_carries_its_blind_spots(self):
        """The load-bearing one is the statement that did not change and became
        unobserved anyway. A cost strategy that reads as a coverage claim is
        the way this feature goes wrong."""
        limits = " ".join(diff_scope.SCOPE_LIMITS).lower()
        assert "unobserved because of a change elsewhere" in limits
        assert "untracked files are invisible" in limits
        assert "never a coverage claim" in limits
        assert diff_scope.DiffScope().to_document()["limits"] == list(diff_scope.SCOPE_LIMITS)

    def test_a_target_outside_the_repository_refuses_by_name(self, tmp_path):
        """An empty scope would probe nothing and report it as a clean run."""
        with pytest.raises(diff_scope.DiffScopeError) as caught:
            diff_scope.read_scope(tmp_path / "not_in_here", tmp_path / "repo", ref=None)
        assert "not inside" in str(caught.value)
