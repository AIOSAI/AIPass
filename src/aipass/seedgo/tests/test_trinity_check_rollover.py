# =================== AIPass ====================
# Name: test_trinity_check_rollover.py
# Description: trinity_check rollover tabs: meta composing, todos pad, draft percent (split from test_trinity_check.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/aipass_standards/trinity_check.py and trinity_groups.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — json.loads() of a well-formed trinity file; only the malformed ones are the subject

import copy
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import trinity_groups
from aipass.seedgo.tests.support_trinity_check import (
    _BRANCH,
    _CONFIG,
    _PROSE,
    _assert_failed,
    _canonical_local,
    _group,
    _write_branch,
)

pytestmark = pytest.mark.usefixtures("_mock_infrastructure")

# @memory's renderer is imported at module scope, before the autouse mock swaps aipass.prax, and found by file
# rather than by catching ImportError, so a real breakage there is never swallowed as "unavailable".
_RENDERER_RELATIVE = ("src", "aipass", "memory", "apps", "modules", "door_tab_renderer.py")
_compose_meta = None
_COMPOSE_META_IMPORT_ERROR = "@memory door_tab_renderer.py is not on disk"

for _parent in Path(__file__).resolve().parents:
    if _parent.joinpath(*_RENDERER_RELATIVE).is_file():
        from aipass.memory.apps.modules.door_tab_renderer import compose_meta as _compose_meta

        _COMPOSE_META_IMPORT_ERROR = ""
        break

_NO_COUNT_TAB = "⟦ rollover ON → no entry limit configured · summary ≤300 chars · draft to 240 ⟧"


def _both_composers(checker):
    """The two inputs the cross-implementation guard needs, or a red naming what is gone."""
    compose = _compose_meta
    assert compose is not None, (
        f"@memory's tab_renderer is the OTHER side of this guard and it is unreachable "
        f"({_COMPOSE_META_IMPORT_ERROR}) - the byte-identity check cannot run, which is a "
        f"finding about the fleet and not a reason to pass"
    )
    config = checker.load_memory_config()
    prose = checker.load_template_prose()
    assert config is not None, "live memory.config.json is unreadable - the meta line has no source"
    assert prose is not None, "the gold templates are unreadable - the meta line has no prose"
    return compose, config, prose


class TestMetaComposition:
    """expected_meta_line reproduces the renderer, byte for byte."""

    def test_todos_tab_format_is_pinned(self, trinity):
        todo_ctx = {"branch_dir": _BRANCH, "next_number": 3}

        line = trinity.expected_meta_line("todos", _BRANCH, _CONFIG, _PROSE["todos"], todo_ctx)

        assert line == (
            "⟦ pad of 10 · oldest roll to .backup/todo/testbranch/backlog.json · task ≤150 chars · draft to 120"
            " · next #3 ⟧ " + _PROSE["todos"]
        )

    def test_todos_tab_without_branch_context_renders_the_honest_unknowns(self, trinity):
        """@memory's render with no branch (spawn birth): never a guessed directory or number."""
        line = trinity.expected_meta_line("todos", _BRANCH, _CONFIG, _PROSE["todos"])

        assert line.startswith(
            "⟦ pad of 10 · oldest roll to .backup/todo/<branch>/backlog.json · task ≤150 chars · draft to 120"
            " · next #? ⟧"
        )

    def test_todos_pad_size_is_the_config_count_not_a_constant(self, trinity):
        resized = copy.deepcopy(_CONFIG)
        resized["rollover"]["defaults"]["local"]["todos"]["count"] = 7

        line = trinity.expected_meta_line("todos", _BRANCH, resized, _PROSE["todos"])

        assert line.startswith("⟦ pad of 7 · ")

    def test_a_per_branch_todos_count_wins_over_the_default(self, trinity):
        overridden = copy.deepcopy(_CONFIG)
        overridden["rollover"]["per_branch"] = {_BRANCH: {"local": {"todos": {"count": 4}}}}

        line = trinity.expected_meta_line("todos", _BRANCH, overridden, _PROSE["todos"])

        assert line.startswith("⟦ pad of 4 · ")

    def test_a_per_branch_local_block_without_a_todos_count_falls_back_to_the_default(self, trinity):
        """@memory's one exception to the per-file-key rule: a sessions override never unsizes the pad."""
        overridden = copy.deepcopy(_CONFIG)
        overridden["rollover"]["per_branch"] = {_BRANCH: {"local": {"sessions": {"count": 5}}}}

        line = trinity.expected_meta_line("todos", _BRANCH, overridden, _PROSE["todos"])

        assert line.startswith("⟦ pad of 10 · ")

    @pytest.mark.parametrize("count", [0, -1, True, "10", None])
    def test_an_unusable_todos_count_renders_no_pad_size(self, trinity, count):
        unsized = copy.deepcopy(_CONFIG)
        unsized["rollover"]["defaults"]["local"]["todos"]["count"] = count
        todo_ctx = {"branch_dir": _BRANCH, "next_number": 3}

        line = trinity.expected_meta_line("todos", _BRANCH, unsized, _PROSE["todos"], todo_ctx)

        assert line == (
            "⟦ no pad size configured — nothing rolls · task ≤150 chars · draft to 120 · next #3 ⟧ " + _PROSE["todos"]
        )

    @pytest.mark.parametrize("number", [True, "3", 3.0])
    def test_a_next_number_that_is_not_an_int_renders_as_unknown(self, trinity, number):
        todo_ctx = {"branch_dir": _BRANCH, "next_number": number}

        line = trinity.expected_meta_line("todos", _BRANCH, _CONFIG, _PROSE["todos"], todo_ctx)

        assert "· next #? ⟧" in line

    def test_rollover_tab_with_a_count_is_pinned(self, trinity):
        line = trinity.expected_meta_line("sessions", _BRANCH, _CONFIG, _PROSE["sessions"])

        assert line == (
            "⟦ rollover ON → oldest archived to @memory · keep 15 · summary ≤300 chars · draft to 240 ⟧ "
            + _PROSE["sessions"]
        )

    @pytest.mark.parametrize(("cap", "draft"), [(300, 240), (200, 160), (150, 120), (500, 400), (77, 61), (1, 0)])
    def test_the_draft_target_is_eighty_percent_of_the_cap_floored(self, trinity, cap, draft):
        """DPLAN-0342: floor, not round - 77 drafts to 61, where round() says 62."""
        capped = copy.deepcopy(_CONFIG)
        capped["entry_limits"]["entry_types"]["sessions"]["max_chars"] = cap

        line = trinity.expected_meta_line("sessions", _BRANCH, capped, _PROSE["sessions"])

        assert f"≤{cap} chars · draft to {draft} ⟧" in line

    def test_the_draft_follows_a_per_branch_cap_not_the_default(self, trinity):
        """The draft comes from the SAME resolved cap the tab prints."""
        overridden = copy.deepcopy(_CONFIG)
        overridden["entry_limits"]["per_branch"] = {_BRANCH: {"todos": {"max_chars": 125}}}

        line = trinity.expected_meta_line("todos", _BRANCH, overridden, _PROSE["todos"])

        assert "task ≤125 chars · draft to 100 · next #" in line

    def test_rollover_tab_without_a_count_is_pinned(self, trinity):
        countless = copy.deepcopy(_CONFIG)
        countless["rollover"]["defaults"] = {}

        line = trinity.expected_meta_line("sessions", _BRANCH, countless, _PROSE["sessions"])

        assert line == f"{_NO_COUNT_TAB} {_PROSE['sessions']}"

    def test_the_tab_carries_the_config_number_not_a_constant(self, trinity):
        tightened = copy.deepcopy(_CONFIG)
        tightened["entry_limits"]["entry_types"]["sessions"]["max_chars"] = 275
        tightened["rollover"]["defaults"]["local"]["sessions"]["count"] = 9

        line = trinity.expected_meta_line("sessions", _BRANCH, tightened, _PROSE["sessions"])

        assert "keep 9" in line
        assert "≤275 chars" in line

    def test_the_tab_carries_the_config_field_name(self, trinity):
        renamed = copy.deepcopy(_CONFIG)
        renamed["entry_limits"]["entry_types"]["observations"]["field"] = "note_text"

        line = trinity.expected_meta_line("observations", _BRANCH, renamed, _PROSE["observations"])

        assert "note_text ≤300 chars" in line

    def test_per_branch_rollover_count_is_resolved_per_file_key(self, trinity):
        overridden = copy.deepcopy(_CONFIG)
        overridden["rollover"]["per_branch"] = {_BRANCH: {"local": {"sessions": {"count": 5}}}}

        line = trinity.expected_meta_line("sessions", _BRANCH, overridden, _PROSE["sessions"])

        assert "keep 5" in line

    def test_a_per_branch_file_key_shadows_the_defaults_for_that_file(self, trinity):
        """The engine's rule: a per_branch `local` block hides defaults.local."""
        overridden = copy.deepcopy(_CONFIG)
        overridden["rollover"]["per_branch"] = {_BRANCH: {"local": {"sessions": {"count": 5}}}}

        line = trinity.expected_meta_line("key_learnings", _BRANCH, overridden, _PROSE["key_learnings"])

        assert "no entry limit configured" in line

    def test_prose_comes_from_the_caller_not_from_the_module(self, trinity):
        line = trinity.expected_meta_line("observations", _BRANCH, _CONFIG, "SOME OTHER PROSE")

        assert line.endswith(" SOME OTHER PROSE")

    def test_load_template_prose_returns_the_four_sections(self, trinity):
        prose = trinity.load_template_prose()

        assert prose == _PROSE

    def test_load_template_prose_returns_none_when_templates_are_unreadable(self, trinity, monkeypatch):
        monkeypatch.setattr(trinity, "_load_templates", lambda: None)

        assert trinity.load_template_prose() is None

    def test_load_memory_config_returns_none_outside_a_repo(self, checker, monkeypatch):
        monkeypatch.setattr(checker, "_memory_dir", lambda: None)

        assert checker.load_memory_config() is None

    @pytest.mark.parametrize("branch_name", ["memory", "MEMORY", "Memory", "seedgo"])
    @pytest.mark.parametrize("section", ["todos", "key_learnings", "sessions", "observations"])
    def test_expected_meta_line_is_byte_identical_to_the_renderer(self, checker, branch_name, section):
        """The cross-implementation guard: two composers, one string."""
        compose, config, prose = _both_composers(checker)

        mine = checker.expected_meta_line(section, branch_name, config, prose[section])
        theirs = compose(section, config.get("rollover", {}), config.get("entry_limits", {}), branch_name)

        assert mine == theirs

    @pytest.mark.parametrize(
        "todo_ctx",
        [
            {"branch_dir": "memory", "next_number": 41},
            {"branch_dir": "memory", "next_number": None},
            {"branch_dir": None, "next_number": None},
            {"branch_dir": "seedgo", "next_number": 1},
        ],
    )
    def test_the_todos_tab_with_branch_context_is_byte_identical_to_the_renderer(self, checker, todo_ctx):
        """DPLAN-0345: the pad tab carries the backlog directory and next number -- same ctx, one string."""
        compose, config, prose = _both_composers(checker)

        mine = checker.expected_meta_line("todos", "memory", config, prose["todos"], todo_ctx)
        theirs = compose("todos", config.get("rollover", {}), config.get("entry_limits", {}), "memory", todo_ctx)

        assert mine == theirs

    @pytest.mark.parametrize(
        "rollover_edit",
        [
            pytest.param(lambda r: r["defaults"]["local"].pop("todos", None), id="no-default-count"),
            pytest.param(lambda r: r["defaults"]["local"]["todos"].update(count=0), id="zero-count"),
            pytest.param(
                lambda r: r.setdefault("per_branch", {}).update(memory={"local": {"sessions": {"count": 5}}}),
                id="per-branch-local-without-todos",
            ),
            pytest.param(
                lambda r: r.setdefault("per_branch", {}).update(memory={"local": {"todos": {"count": 3}}}),
                id="per-branch-todos-count",
            ),
        ],
    )
    def test_the_todos_pad_size_resolves_like_the_renderer(self, checker, rollover_edit):
        compose, config, prose = _both_composers(checker)
        edited = copy.deepcopy(config)
        rollover_edit(edited.setdefault("rollover", {}))
        todo_ctx = {"branch_dir": "memory", "next_number": 7}

        mine = checker.expected_meta_line("todos", "memory", edited, prose["todos"], todo_ctx)
        theirs = compose("todos", edited.get("rollover", {}), edited.get("entry_limits", {}), "memory", todo_ctx)

        assert mine == theirs

    def test_per_branch_char_cap_override_survives_the_renderer(self, checker):
        compose, config, prose = _both_composers(checker)
        overridden = copy.deepcopy(config)
        overridden.setdefault("entry_limits", {}).setdefault("per_branch", {})["seedgo"] = {
            "observations": {"max_chars": 120}
        }

        mine = checker.expected_meta_line("observations", "seedgo", overridden, prose["observations"])
        theirs = compose(
            "observations",
            overridden.get("rollover", {}),
            overridden.get("entry_limits", {}),
            "seedgo",
        )

        assert mine == theirs


class TestTheTodosTabIsReadByShape:
    """DPLAN-0345: the todos tab's ``next #N`` is derived when the tab is RENDERED."""

    _PAD_HEAD = "⟦ pad of 10 · oldest roll to .backup/todo/testbranch/backlog.json · task ≤150 chars · draft to 120"

    def _meta_with(self, trinity, tmp_path, todos_meta: str) -> dict:
        local = _canonical_local()
        local["todos_meta"] = todos_meta
        result = trinity.check_branch(str(_write_branch(tmp_path, local=local)))
        return _group(result, "Meta lines & _usage")

    @pytest.mark.parametrize("label", ["41", "3", "1", "0", "?"])
    def test_any_rendered_next_number_passes(self, trinity, tmp_path, label):
        """#41 on a pad whose numbers say #3 is a stale render, not a defect."""
        check = self._meta_with(trinity, tmp_path, f"{self._PAD_HEAD} · next #{label} ⟧ {_PROSE['todos']}")

        assert check["passed"] is True, check["message"]

    def test_the_no_context_rendering_passes_whole(self, trinity, tmp_path):
        """What spawn birth writes: <branch> and #?, byte-identical to @memory's render without a branch."""
        line = trinity.expected_meta_line("todos", _BRANCH, _CONFIG, _PROSE["todos"])

        check = self._meta_with(trinity, tmp_path, line)

        assert "<branch>" in line
        assert check["passed"] is True, check["message"]

    @pytest.mark.parametrize("label", ["", "abc", "041", "3.0", " 3", "3 ", "-0", "#3", "3?"])
    def test_a_slot_no_renderer_writes_fails(self, trinity, tmp_path, label):
        check = self._meta_with(trinity, tmp_path, f"{self._PAD_HEAD} · next #{label} ⟧ {_PROSE['todos']}")

        _assert_failed(check, "todos_meta does not byte-match")

    def test_the_no_context_directory_with_a_number_fails(self, trinity, tmp_path):
        """No renderer writes <branch> beside a number: without a branch there is no backlog to count."""
        head = self._PAD_HEAD.replace("/testbranch/", "/<branch>/")

        check = self._meta_with(trinity, tmp_path, f"{head} · next #3 ⟧ {_PROSE['todos']}")

        _assert_failed(check, "todos_meta does not byte-match")

    def test_another_branch_directory_fails(self, trinity, tmp_path):
        head = self._PAD_HEAD.replace("/testbranch/", "/seedgo/")

        check = self._meta_with(trinity, tmp_path, f"{head} · next #3 ⟧ {_PROSE['todos']}")

        _assert_failed(check, "todos_meta does not byte-match", ".backup/todo/testbranch/")

    def test_the_retired_todos_tab_fails(self, trinity, tmp_path):
        retired = "⟦ rollover OFF — operational, never trimmed · cap ~10 entries · task ≤150 chars · draft to 120 ⟧"

        check = self._meta_with(trinity, tmp_path, f"{retired} {_PROSE['todos']}")

        _assert_failed(check, "todos_meta does not byte-match", "pad of 10")

    def test_drifted_prose_after_a_good_tab_fails(self, trinity, tmp_path):
        """Same length as the gold prose, so only the suffix comparison can see the edit."""
        check = self._meta_with(trinity, tmp_path, f"{self._PAD_HEAD} · next #3 ⟧ {_PROSE['todos'].upper()}")

        _assert_failed(check, "todos_meta does not byte-match")

    def test_a_drifted_pad_size_fails(self, trinity, tmp_path):
        head = self._PAD_HEAD.replace("pad of 10", "pad of 12")

        check = self._meta_with(trinity, tmp_path, f"{head} · next #3 ⟧ {_PROSE['todos']}")

        _assert_failed(check, "todos_meta does not byte-match")


class TestTheDraftPercentIsRead:
    """The draft percent is read from entry_limits.draft_percent in the config; with nothing usable published the group refuses loud."""

    @pytest.mark.parametrize(("percent", "draft"), [(80, 240), (50, 150), (100, 300), (1, 3), (33, 99)])
    def test_the_tab_moves_when_the_published_percent_moves(self, trinity, percent, draft):
        moved = copy.deepcopy(_CONFIG)
        moved["entry_limits"]["draft_percent"] = percent

        line = trinity.expected_meta_line("sessions", _BRANCH, moved, _PROSE["sessions"])

        assert f"≤300 chars · draft to {draft} ⟧" in line

    @pytest.mark.parametrize("published", [None, 0, 101, -1, "80", 80.0, True])
    def test_an_unusable_percent_renders_a_marker_and_never_a_number(self, trinity, published):
        """Absent, out of 1-100, or the wrong type: no number is invented."""
        broken = copy.deepcopy(_CONFIG)
        if published is None:
            broken["entry_limits"].pop("draft_percent")
        else:
            broken["entry_limits"]["draft_percent"] = published

        line = trinity.expected_meta_line("sessions", _BRANCH, broken, _PROSE["sessions"])

        assert "draft to <entry_limits.draft_percent unpublished>" in line
        assert "draft to 240" not in line

    def test_an_unpublished_percent_fails_the_meta_group_naming_the_key(self, trinity, tmp_path, monkeypatch):
        without = copy.deepcopy(_CONFIG)
        without["entry_limits"].pop("draft_percent")
        monkeypatch.setattr(trinity, "load_memory_config", lambda: copy.deepcopy(without))
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        _assert_failed(
            _group(result, "Meta lines & _usage"),
            "entry_limits.draft_percent",
            "@memory",
            "never assumed",
        )
        assert _group(result, "Meta lines & _usage")["score"] == 0

    def test_no_percent_literal_came_back_into_the_module(self):
        """The mirror is gone from the SOURCE, not merely unreferenced."""
        import ast

        source = Path(trinity_groups.__file__).read_text(encoding="utf-8")
        ints = {
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool)
        }

        assert not hasattr(trinity_groups, "_DRAFT_PERCENT"), "the draft percent mirror is back"
        assert 80 not in ints, "80 is a literal in trinity_groups again - the percent belongs to memory.config.json"
