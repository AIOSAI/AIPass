# =================== AIPass ====================
# Name: test_config_verbs_refusals.py
# Description: The config verbs' refusal sentences, verbatim - the API contract a refused set prints
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/rollover_config.py — the refusals the config verbs print, through apps/modules/rollover.py."""

# The refusal sentences ARE the API contract (@api exec's this CLI), so they are pinned verbatim.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — get_count_ceilings() arithmetic, pinned in tests/test_config_loader.py

from types import SimpleNamespace

from aipass.memory.tests.support_config_verbs import _payload, _rollover_section, _run, _streams, _unwrapped


def _ceiling(verbs: SimpleNamespace, entry_type: str, branch: str | None = None) -> int:
    """The keep-count ceiling the THROWAWAY config publishes for *entry_type*; read, never hard-coded."""
    return verbs.loader.get_count_ceilings(branch)[entry_type]["ceiling"]


def _budget_chars(verbs: SimpleNamespace, entry_type: str) -> int:
    """The whole-file budget the ceiling for *entry_type* was measured against."""
    return verbs.loader.get_count_ceilings()[entry_type]["budget_chars"]


class TestUnknownBranchRefusal:
    """Registry is truth; an unknown branch never reaches the writer."""

    def test_set_unknown_branch_message(self, verbs, capsys) -> None:
        _run(verbs, "set", "@wizard", "sessions", "12")
        assert "Unknown branch: @wizard" in _streams(capsys)

    def test_set_unknown_branch_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "set", "@wizard", "sessions", "12")
        assert "Registry is truth — run 'drone systems' to list branches" in _streams(capsys)

    def test_get_unknown_branch_refuses(self, verbs, capsys) -> None:
        _run(verbs, "get", "@wizard")
        assert "Unknown branch: @wizard" in _streams(capsys)

    def test_unknown_branch_writes_nothing(self, verbs) -> None:
        before = verbs.path.read_bytes()
        _run(verbs, "set", "@wizard", "sessions", "12")
        assert verbs.path.read_bytes() == before

    def test_refusal_echoes_the_branch_as_typed(self, verbs, capsys) -> None:
        """Echo what the operator typed -- not a normalized form they never used."""
        _run(verbs, "set", "@WiZaRd", "sessions", "12")
        assert "Unknown branch: @WiZaRd" in _streams(capsys)


class TestUnknownTypeRefusal:
    """Only three entry types are settable; anything unknown is refused by name (todos: see section 8)."""

    def test_set_unknown_type_message(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "foo", "12")
        assert "Unknown entry type: 'foo'" in _streams(capsys)

    def test_set_unknown_type_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "foo", "12")
        assert "Valid types: sessions, key_learnings, observations" in _streams(capsys)

    def test_set_default_unknown_type_message(self, verbs, capsys) -> None:
        _run(verbs, "set-default", "wizard", "12")
        assert "Unknown entry type: 'wizard'" in _streams(capsys)

    def test_unknown_type_writes_nothing(self, verbs) -> None:
        before = verbs.path.read_bytes()
        _run(verbs, "set", "@memory", "foo", "12")
        assert verbs.path.read_bytes() == before


class TestCountRefusals:
    """A limit is a whole number in [1, 100] AND under its file's ceiling."""

    def test_non_numeric_message(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "abc")
        assert "Count must be a whole number: 'abc'" in _streams(capsys)

    def test_non_numeric_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "abc")
        assert "Example: drone @memory config set @devpulse sessions 12" in _streams(capsys)

    def test_decimal_is_not_a_whole_number(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "12.5")
        assert "Count must be a whole number: '12.5'" in _streams(capsys)

    def test_zero_message(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "0")
        assert "Count must be at least 1 (got 0)" in _streams(capsys)

    def test_zero_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "0")
        assert "A limit of 0 would roll over every entry immediately" in _streams(capsys)

    def test_negative_message(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "-5")
        assert "Count must be at least 1 (got -5)" in _streams(capsys)

    def test_above_cap_message(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "500")
        assert "Count must not exceed 100 (got 500)" in _streams(capsys)

    def test_above_cap_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "500")
        assert "100 is the cap — larger limits defeat rollover entirely" in _streams(capsys)

    def test_one_hundred_and_one_is_over(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "101")
        assert "Count must not exceed 100 (got 101)" in _streams(capsys)

    def test_bounds_are_inclusive(self, verbs) -> None:
        """1 and the file ceiling are legal; the file budget is a lower bound than the flat cap of 100."""
        assert _run(verbs, "set", "@memory", "sessions", "1") is True
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 1
        ceiling = _ceiling(verbs, "sessions")
        assert _run(verbs, "set", "@memory", "sessions", str(ceiling)) is True
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == ceiling

    def test_bad_count_writes_nothing(self, verbs) -> None:
        before = verbs.path.read_bytes()
        _run(verbs, "set", "@memory", "sessions", "0")
        assert verbs.path.read_bytes() == before


class TestCountCeilingRefusal:
    """A keep-count multiplies an entry cap, so it is refused at the FILE budget.

    The refusal carries the arithmetic (ceiling, worst case, budget, co-tenants); a bare "too big" is unanswerable.
    """

    def test_set_names_the_ceiling(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "40")
        assert f"sessions may keep at most {_ceiling(verbs, 'sessions')}" in _streams(capsys)

    def test_set_names_the_budget_and_the_worst_case(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "40")
        out = _unwrapped(_streams(capsys))
        assert _unwrapped(f"against its {_budget_chars(verbs, 'sessions'):,} budget") in out
        assert _unwrapped("local.json's worst case at 40 would be 41,623 chars") in out

    def test_set_names_the_co_tenants(self, verbs, capsys) -> None:
        """Naming only sessions would be a half-truth: local.json is shared."""
        _run(verbs, "set", "@memory", "sessions", "40")
        assert _unwrapped("(with key_learnings 15, todos 10)") in _unwrapped(_streams(capsys))

    def test_set_suggestion_names_where_the_budget_lives(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "40")
        assert _unwrapped("memory.config.json entry_limits.file_budgets") in _unwrapped(_streams(capsys))

    def test_set_default_names_the_ceiling_and_the_budget(self, verbs, capsys) -> None:
        _run(verbs, "set-default", "sessions", "40")
        out = _unwrapped(_streams(capsys))
        assert _unwrapped(f"sessions may keep at most {_ceiling(verbs, 'sessions')}") in out
        assert _unwrapped(f"against its {_budget_chars(verbs, 'sessions'):,} budget") in out

    def test_observations_is_measured_against_its_own_file(self, verbs, capsys) -> None:
        """A sole tenant says so rather than listing an empty company."""
        _run(verbs, "set", "@memory", "observations", "90")
        out = _unwrapped(_streams(capsys))
        assert _unwrapped(f"against its {_budget_chars(verbs, 'observations'):,} budget") in out
        assert _unwrapped("observations is observations.json's only tenant") in out

    def test_an_over_ceiling_set_writes_nothing(self, verbs) -> None:
        before = verbs.path.read_bytes()
        _run(verbs, "set", "@memory", "sessions", "40")
        assert verbs.path.read_bytes() == before

    def test_an_over_ceiling_set_default_writes_nothing(self, verbs) -> None:
        before = verbs.path.read_bytes()
        _run(verbs, "set-default", "sessions", "40")
        assert verbs.path.read_bytes() == before

    def test_exactly_the_ceiling_is_accepted_by_set(self, verbs, capsys) -> None:
        """The ceiling is the largest LEGAL count, not the first illegal one - written, and never refused on screen."""
        ceiling = _ceiling(verbs, "sessions")
        assert _run(verbs, "set", "@memory", "sessions", str(ceiling)) is True
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == ceiling
        assert "may keep at most" not in _unwrapped(_streams(capsys))

    def test_exactly_the_ceiling_is_accepted_by_set_default(self, verbs) -> None:
        ceiling = _ceiling(verbs, "sessions", None)
        assert _run(verbs, "set-default", "sessions", str(ceiling)) is True
        assert _rollover_section(verbs)["defaults"]["local"]["sessions"]["count"] == ceiling

    def test_one_above_the_ceiling_is_refused(self, verbs) -> None:
        before = verbs.path.read_bytes()
        _run(verbs, "set", "@memory", "sessions", str(_ceiling(verbs, "sessions") + 1))
        assert verbs.path.read_bytes() == before

    def test_the_refusal_is_a_json_payload_too(self, verbs, capsys) -> None:
        payload = _payload(verbs, capsys, "set", "@memory", "sessions", "40", "--json")
        assert payload["ok"] is False
        assert f"at most {_ceiling(verbs, 'sessions')}" in payload["error"]
        assert "entry_limits.file_budgets" in payload["suggestion"]

    def test_the_flat_cap_still_answers_first(self, verbs, capsys) -> None:
        """101 is out of bounds before it is over budget -- the older, cheaper no, and the only one."""
        _run(verbs, "set", "@memory", "sessions", "101")
        out = _unwrapped(_streams(capsys))
        assert _unwrapped("Count must not exceed 100 (got 101)") in out
        assert "may keep at most" not in out


class TestMissingArgumentRefusals:
    """Half a command is a question, not an instruction."""

    def test_set_missing_args_message(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory")
        assert "config set needs: @branch <type> <count>" in _streams(capsys)

    def test_set_missing_args_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "set")
        assert "Example: drone @memory config set @devpulse sessions 12" in _streams(capsys)

    def test_set_default_missing_args_message(self, verbs, capsys) -> None:
        _run(verbs, "set-default", "sessions")
        assert "config set-default needs: <type> <count>" in _streams(capsys)

    def test_set_default_missing_args_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "set-default")
        assert "Example: drone @memory config set-default sessions 12" in _streams(capsys)


class TestUnknownSubcommandRefusal:
    """`config` owns three verbs and names them when asked for a fourth."""

    def test_message(self, verbs, capsys) -> None:
        _run(verbs, "reset")
        assert "Unknown subcommand: 'reset'" in _streams(capsys)

    def test_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "reset")
        assert "Available: get, set, set-default" in _streams(capsys)

    def test_still_handled(self, verbs) -> None:
        assert _run(verbs, "reset") is True


class TestUnreadableConfigRefusal:
    """A file we cannot parse may be one comma from correct -- never clobber it."""

    def test_message_on_set(self, verbs, capsys) -> None:
        verbs.path.write_text("{ this is not json", encoding="utf-8")
        _run(verbs, "set", "@memory", "sessions", "12")
        expected = f"Config at {verbs.path} is unreadable — fix or move it aside, then try again"
        assert _unwrapped(expected) in _unwrapped(_streams(capsys))

    def test_message_on_set_default(self, verbs, capsys) -> None:
        verbs.path.write_text("{ this is not json", encoding="utf-8")
        _run(verbs, "set-default", "sessions", "12")
        expected = f"Config at {verbs.path} is unreadable — fix or move it aside, then try again"
        assert _unwrapped(expected) in _unwrapped(_streams(capsys))

    def test_bytes_unchanged(self, verbs) -> None:
        verbs.path.write_text("{ this is not json", encoding="utf-8")
        before = verbs.path.read_bytes()
        _run(verbs, "set", "@memory", "sessions", "12")
        assert verbs.path.read_bytes() == before

    def test_wrong_shape_is_also_refused(self, verbs, capsys) -> None:
        """Valid JSON, wrong type -- same no-clobber path as malformed."""
        verbs.path.write_text('["a", "list"]', encoding="utf-8")
        before = verbs.path.read_bytes()
        _run(verbs, "set", "@memory", "sessions", "12")
        assert _unwrapped("is unreadable — fix or move it aside, then try again") in _unwrapped(_streams(capsys))
        assert verbs.path.read_bytes() == before
