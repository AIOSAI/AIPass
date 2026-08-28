# =================== AIPass ====================
# Name: test_trinity_standard.py
# Description: Red-first pins for the trinity standard machinery (DPLAN-0318)
# Version: 1.0.0
# Created: 2026-08-25
# Modified: 2026-08-25
# =============================================

"""Trinity standard machinery — the pins that were red before the build.

Every class here corresponds to one item in the DPLAN-0318 machinery
dispatch, and every test in it FAILED against the code as it stood on
2026-08-25 before this file landed.

The four measurement defects (B1, B2, B4) share one sin: *measurement that
cannot fail loud*.  A field the gate cannot measure was silently treated as
zero characters, and an off-by-one archived an entry the standard says to
keep.  The pins below assert the opposite property in each case: an
unmeasurable field is a VIOLATION, and keep-N keeps N.
"""

import json
import sys
from pathlib import Path

import pytest

from aipass.memory.apps.handlers.json import entry_limits as el
from aipass.memory.apps.handlers.json import lint_handler


_MEMORY_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATES = _MEMORY_ROOT / "templates"


def _limits(max_chars: int = 300, field: str = "note", container: str = "observations") -> dict:
    """Minimal effective-limits dict shaped like load_entry_limits() output."""
    return {
        "enabled": True,
        "enforce": True,
        "entry_types": {
            "observations": {
                "file": "observations.json",
                "container": container,
                "kind": "list",
                "field": field,
                "max_chars": max_chars,
            }
        },
    }


# =============================================================================
# B1 — entry_limits: a field the gate cannot measure is a VIOLATION
# =============================================================================


class TestUnmeasurableFieldIsAViolation:
    """B1: _extract_text() returned "" for a non-string — len 0, always passes."""

    def test_extract_text_says_unmeasurable_rather_than_empty(self):
        """A list-shaped note is UNMEASURABLE, not a zero-length string.

        Returning "" conflated 'no text' with 'cannot read the text'. The
        first is compliant, the second is a violation — one sentinel cannot
        mean both.
        """
        entry = {"note": [{"title": "a", "detail": "b"}], "number": 1}
        assert el._extract_text(entry, "note") is None

    def test_a_measurable_field_still_returns_its_text(self):
        assert el._extract_text({"note": "plain"}, "note") == "plain"
        assert el._extract_text("bare string", "note") == "bare string"

    def test_check_entry_refuses_a_non_string(self):
        """check_entry() called len() on whatever it was handed."""
        verdict = el.check_entry("observations", [{"title": "a"}], _limits())
        assert verdict["ok"] is False
        assert verdict["reason"] == "unmeasurable"

    def test_a_new_list_shaped_entry_is_refused(self):
        """The defect in one line: 5 fat dicts measured as 0 chars and passed."""
        before = {"observations": []}
        after = {"observations": [{"number": 1, "note": [{"title": "x" * 500}]}]}
        hits = el.changed_entries(before, after, _limits())
        assert len(hits) == 1
        assert hits[0]["reason"] == "unmeasurable"
        assert hits[0]["found_type"] == "list"

    def test_a_legacy_unchanged_list_entry_is_now_refused(self):
        """Rewritten 2026-08-27 — the fleet the exemption protected no longer exists.

        The nine branches carrying list-shaped notes were cured by the trinity
        push; every one of those entries is in vectors and out of the files.
        Keeping the exemption past that point protects nothing and hides the
        next list-shaped note somebody writes. `todos` keep it, and only todos:
        that is the one container no machine may prune, so refusing writes
        there would brick the branch's rollover.
        """
        legacy = {"number": 1, "note": [{"title": "x" * 500}]}
        before = {"observations": [legacy]}
        after = {"observations": [dict(legacy)]}
        hits = el.changed_entries(before, after, _limits())
        assert len(hits) == 1
        assert hits[0]["key"] == "0"

    def test_the_exemption_survives_for_todos_alone(self):
        """The container the push may not cure keeps its rollover-safety."""
        limits = _limits(max_chars=150, field="task", container="todos")
        legacy = {"number": 1, "task": [{"title": "x" * 500}]}
        before = {"todos": [legacy]}
        after = {"todos": [dict(legacy)]}
        assert el.changed_entries(before, after, limits) == []

    def test_both_list_entries_are_refused_in_an_archivable_container(self):
        """Post-narrowing there is nothing to exempt here: both are reported."""
        legacy = {"number": 1, "note": [{"title": "old"}]}
        before = {"observations": [legacy]}
        after = {"observations": [{"number": 2, "note": [{"title": "new"}]}, dict(legacy)]}
        hits = el.changed_entries(before, after, _limits())
        assert {hit["key"] for hit in hits} == {"0", "1"}

    def test_a_second_list_shaped_todo_beside_a_legacy_one_is_still_refused(self):
        """The hole a text-identity dedup would leave, in the container that kept the exemption.

        If unmeasurable entries all collapse to one sentinel, a branch with a
        single legacy list-shaped todo could add ten more and every one would
        read as 'already on disk'. Identity must be the raw value, not the
        sentinel. Moved here from observations when the clause was narrowed —
        `todos` is now the only place the exemption can be exploited at all.
        """
        limits = _limits(max_chars=150, field="task", container="todos")
        legacy = {"number": 1, "task": [{"title": "old"}]}
        before = {"todos": [legacy]}
        after = {"todos": [{"number": 2, "task": [{"title": "new"}]}, dict(legacy)]}
        hits = el.changed_entries(before, after, limits)
        assert len(hits) == 1
        assert hits[0]["key"] == "0"
        assert hits[0]["key"] == "0"

    def test_a_dict_container_entry_that_changed_shape_is_refused(self):
        limits = _limits()
        limits["entry_types"]["observations"]["kind"] = "dict"
        before = {"observations": {"a": {"note": "was a string"}}}
        after = {"observations": {"a": {"note": ["now a list"]}}}
        hits = el.changed_entries(before, after, limits)
        assert len(hits) == 1
        assert hits[0]["reason"] == "unmeasurable"

    def test_the_violation_still_carries_the_keys_its_consumers_print(self):
        """@hooks edit_gate formats these with %d — a None would raise there."""
        before = {"observations": []}
        after = {"observations": [{"number": 1, "note": ["x"]}]}
        hit = el.changed_entries(before, after, _limits())[0]
        for key in ("entry_type", "container", "key", "length", "cap", "over_by"):
            assert key in hit
        assert isinstance(hit["length"], int)
        assert isinstance(hit["over_by"], int)


# =============================================================================
# B2 — lint: len() on a list counts elements, not characters
# =============================================================================


class TestLintRefusesWhatItCannotMeasure:
    """B2: the second independent silent pass over the same corruption."""

    def _branch(self, tmp_path: Path, note) -> str:
        trinity = tmp_path / "b" / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "observations.json").write_text(
            json.dumps({"observations": [{"number": 1, "date": "2026-08-25", "note": note}]}),
            encoding="utf-8",
        )
        return str(tmp_path / "b")

    def test_a_list_note_is_reported_not_counted_as_three_chars(self, tmp_path):
        """Three fat dicts measured as len()==3 and cleared a 300-char cap."""
        path = self._branch(tmp_path, [{"detail": "x" * 400}, {"detail": "y" * 400}, {"detail": "z"}])
        hits = lint_handler._lint_branch("b", path, _limits())
        assert len(hits) == 1
        assert hits[0]["reason"] == "unmeasurable"

    def test_a_string_note_over_cap_is_still_reported_with_its_length(self, tmp_path):
        path = self._branch(tmp_path, "x" * 400)
        hits = lint_handler._lint_branch("b", path, _limits())
        assert len(hits) == 1
        assert hits[0]["length"] == 400
        assert hits[0]["over_by"] == 100
        assert "reason" not in hits[0] or hits[0]["reason"] != "unmeasurable"

    def test_a_string_note_within_cap_is_clean(self, tmp_path):
        path = self._branch(tmp_path, "short")
        assert lint_handler._lint_branch("b", path, _limits()) == []


# =============================================================================
# Item 4 + 5 — the templates are the only source of prose
# =============================================================================


class TestRendererReadsTheTemplate:
    """The renderer carried its own copy of _usage and overwrote live files."""

    def test_the_module_holds_no_usage_prose_of_its_own(self):
        """Guard against reintroducing the constants this build retired."""
        source = (_MEMORY_ROOT / "apps" / "handlers" / "tracking" / "tab_renderer.py").read_text(encoding="utf-8")
        # The ASSIGNMENT, not the name: the comment recording why the constants
        # were retired is worth keeping, and a scan that forbids naming them
        # would delete its own explanation.
        assert "_CORRECTED_USAGE_LOCAL =" not in source
        assert "_CORRECTED_USAGE_OBS =" not in source
        assert "Automated file — add entries" not in source

    def test_usage_is_read_from_the_local_template_verbatim(self):
        from aipass.memory.apps.handlers.tracking import tab_renderer

        expected = json.loads((_TEMPLATES / "LOCAL.template.json").read_text(encoding="utf-8"))
        assert tab_renderer.template_usage("local") == expected["document_metadata"]["_usage"]

    def test_usage_is_read_from_the_observations_template_verbatim(self):
        from aipass.memory.apps.handlers.tracking import tab_renderer

        expected = json.loads((_TEMPLATES / "OBSERVATIONS.template.json").read_text(encoding="utf-8"))
        assert tab_renderer.template_usage("observations") == expected["document_metadata"]["_usage"]

    def test_the_semantics_sentence_is_the_template_line_minus_its_placeholder(self):
        from aipass.memory.apps.handlers.tracking import tab_renderer

        template = json.loads((_TEMPLATES / "LOCAL.template.json").read_text(encoding="utf-8"))
        raw = template["sessions_meta"]
        assert raw.startswith("{{SESSIONS_META}}")
        assert tab_renderer.template_semantics("sessions") == raw.replace("{{SESSIONS_META}}", "").strip()

    def test_the_todos_tab_carries_numbers_only_not_prose(self):
        """render_tab() baked a RULE sentence into the todos tab.

        Prose is template-owned now; a second copy in the renderer is exactly
        the drift the one-source rule exists to end.
        """
        from aipass.memory.apps.handlers.tracking import tab_renderer

        tab = tab_renderer.render_tab("todos", {}, {"entry_types": {"todos": {"max_chars": 150}}}, "memory")
        assert tab.startswith("⟦")
        assert tab.endswith("⟧")
        assert "RULE: DELETE" not in tab
        assert "BAU" not in tab

    def test_an_unreadable_template_refuses_rather_than_inventing_prose(self, tmp_path, monkeypatch):
        """No silent fallback to a hardcoded sentence — that is the constant again."""
        from aipass.memory.apps.handlers.tracking import tab_renderer

        monkeypatch.setattr(tab_renderer, "_TEMPLATES_DIR", tmp_path)
        with pytest.raises(FileNotFoundError):
            tab_renderer.template_usage("local")


class TestRefreshPreservesTheSemantics:
    """refresh overwrote the whole *_meta value with just the caps tab."""

    def _local(self, tmp_path: Path) -> Path:
        trinity = tmp_path / ".trinity"
        trinity.mkdir(parents=True)
        path = trinity / "local.json"
        path.write_text(
            json.dumps(
                {
                    "document_metadata": {"document_name": "X.LOCAL", "_usage": "stale text"},
                    "todos_meta": "⟦ stale ⟧ stale prose",
                    "todos": [],
                    "key_learnings_meta": "⟦ stale ⟧",
                    "key_learnings": [],
                    "sessions_meta": "⟦ stale ⟧",
                    "sessions": [],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_the_meta_line_is_tab_then_template_semantics(self, tmp_path):
        from aipass.memory.apps.handlers.tracking import tab_renderer

        path = self._local(tmp_path)
        rollover_cfg = {"defaults": {"local": {"sessions": {"count": 15}}}}
        limits_cfg = {"entry_types": {"sessions": {"field": "summary", "max_chars": 300}}}
        ok, err = tab_renderer._refresh_local("memory", path, rollover_cfg, limits_cfg)
        assert ok, err

        written = json.loads(path.read_text(encoding="utf-8"))
        tab = tab_renderer.render_tab("sessions", rollover_cfg, limits_cfg, "memory")
        assert written["sessions_meta"] == f"{tab} {tab_renderer.template_semantics('sessions')}"

    def test_refresh_restores_the_usage_from_the_template(self, tmp_path):
        from aipass.memory.apps.handlers.tracking import tab_renderer

        path = self._local(tmp_path)
        ok, _ = tab_renderer._refresh_local("memory", path, {"defaults": {}}, {"entry_types": {}})
        assert ok
        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["document_metadata"]["_usage"] == tab_renderer.template_usage("local")

    def test_a_refresh_never_leaves_a_bare_tab(self, tmp_path):
        """The regression this pins: every rollover stripped the meaning."""
        from aipass.memory.apps.handlers.tracking import tab_renderer

        path = self._local(tmp_path)
        tab_renderer._refresh_local("memory", path, {"defaults": {}}, {"entry_types": {}})
        written = json.loads(path.read_text(encoding="utf-8"))
        for key in ("todos_meta", "key_learnings_meta", "sessions_meta"):
            assert written[key].rstrip().endswith(".") and "⟧ " in written[key], key


# =============================================================================
# Item 6 — health is computed, never stamped
# =============================================================================


class TestNoHealthStamping:
    """Patrick's ruling: status.health is deleted from the standard."""

    def test_the_rollover_extractor_writes_no_status_block(self, monkeypatch):
        from .test_handlers import _import_extractor  # noqa: PLC0415  # relative: `tests.` resolves only on a branch-dir rootdir, not a repo-root run

        extractor, _mocks = _import_extractor(monkeypatch)
        assert not hasattr(extractor, "_update_metadata_after_extraction")

    @staticmethod
    def _stamps_health(source: str) -> bool:
        """True when the source WRITES the field, not merely names it.

        Prose about a removed field is how the next reader learns why it went;
        a scan that forbade the name outright would delete its own explanation.
        The write forms are what matter: a quoted dict key, or a keyword
        argument.
        """
        return '"last_health_check"' in source or "'last_health_check'" in source or "last_health_check=" in source

    def test_line_counter_stamps_no_health_date(self):
        source = (_MEMORY_ROOT / "apps" / "handlers" / "tracking" / "line_counter.py").read_text(encoding="utf-8")
        assert not self._stamps_health(source)

    def test_the_normalizer_adds_no_status_block(self):
        source = (_MEMORY_ROOT / "apps" / "handlers" / "schema" / "normalize.py").read_text(encoding="utf-8")
        assert not self._stamps_health(source)

    def test_no_handler_stamps_health_anywhere(self):
        """One sweep so the next copy of this cannot land quietly."""
        offenders = [
            str(path.relative_to(_MEMORY_ROOT))
            for path in (_MEMORY_ROOT / "apps").rglob("*.py")
            if self._stamps_health(path.read_text(encoding="utf-8"))
        ]
        assert offenders == []

    def test_the_generic_status_writer_is_gone(self):
        """update_metadata() existed only to write the forbidden block.

        Asserted against the source, not `hasattr`: sibling tests swap this
        package for a MagicMock, and a MagicMock answers hasattr True for
        anything you ask it — including a function you just deleted.
        """
        source = (_MEMORY_ROOT / "apps" / "handlers" / "json" / "memory_files.py").read_text(encoding="utf-8")
        assert "def update_metadata(" not in source

        exports = (_MEMORY_ROOT / "apps" / "handlers" / "json" / "__init__.py").read_text(encoding="utf-8")
        assert "update_metadata" not in exports

    def test_the_real_module_has_no_status_writer_after_a_clean_reimport(self, monkeypatch):
        """The same claim against the LOADED module, not just the file on disk.

        Sibling tests in this suite swap `handlers.json` for a stand-in, and a
        MagicMock answers `hasattr` True for a function that no longer exists —
        so the import has to be forced fresh before the question means anything.
        This is the assertion the retired TestUpdateMetadata class used to carry.

        The eviction is `monkeypatch.delitem`, not a bare `del`. As a bare del
        it was one-way, and it warmed the cache for the receipt tests LOWER IN
        THIS FILE by re-importing memory_files on its way out — which is why
        this file passed standalone and why the receipt tests could still go
        red when xdist packed them into a worker without this test. A test that
        silently supplies another test's precondition is worse than no test.
        """
        import importlib
        import sys

        for name in [n for n in sys.modules if n.startswith("aipass.memory.apps.handlers.json")]:
            monkeypatch.delitem(sys.modules, name, raising=False)

        memory_files = importlib.import_module("aipass.memory.apps.handlers.json.memory_files")
        importlib.reload(memory_files)

        assert not hasattr(memory_files, "update_metadata")
        assert hasattr(memory_files, "read_memory_file_data"), "reload loaded the wrong module"


# =============================================================================
# B4 — keep-N keeps N, and the detector agrees with the extractor
# =============================================================================


class TestKeepNKeepsN:
    """B4: max(len - limit, 1) archived one entry at exactly the limit.

    Every branch that reached keep-15 settled permanently at 14 — the
    fleet-wide "exactly 14" oddity. Fixing the extractor alone is not enough:
    the detector fired at `>=`, so a file resting at the limit would make it
    re-fire forever while the extractor drained nothing. That is the
    NOTHING DRAINED skip loop this branch has already been bitten by twice
    (DPLAN-0290 item 3, and the 2026-08-16 runaway). The two must agree.
    """

    def _entries(self, n: int) -> list:
        return [
            {"number": n - i, "date": "2026-01-01", "summary": f"s{n - i}", "status": "completed"} for i in range(n)
        ]

    def test_nothing_is_archived_at_exactly_the_limit(self, monkeypatch):
        from .test_handlers import _import_extractor  # noqa: PLC0415  # relative: `tests.` resolves only on a branch-dir rootdir, not a repo-root run

        ext, _ = _import_extractor(monkeypatch)
        assert ext._extract_tail_excess(self._entries(15), 15, 99, "sessions", "memory") == []

    def test_only_the_excess_is_archived_above_the_limit(self, monkeypatch):
        from .test_handlers import _import_extractor  # noqa: PLC0415  # relative: `tests.` resolves only on a branch-dir rootdir, not a repo-root run

        ext, _ = _import_extractor(monkeypatch)
        archived = ext._extract_tail_excess(self._entries(17), 15, 99, "sessions", "memory")
        assert [e["number"] for e in archived] == [2, 1]

    def test_a_file_settles_at_the_limit_not_one_below(self, monkeypatch):
        from .test_handlers import _import_extractor  # noqa: PLC0415  # relative: `tests.` resolves only on a branch-dir rootdir, not a repo-root run

        ext, _ = _import_extractor(monkeypatch)
        entries = self._entries(16)
        archived = ext._extract_tail_excess(entries, 15, 99, "sessions", "memory")
        assert len(entries) - len(archived) == 15

    def test_the_detector_does_not_fire_at_exactly_the_limit(self, tmp_path, monkeypatch):
        """Detector as the oracle — if it fires here, the extractor loops."""
        mem_file = tmp_path / ".trinity" / "local.json"
        mem_file.parent.mkdir(parents=True)
        mem_file.write_text(
            json.dumps({"document_metadata": {"schema_version": "3.0.0"}, "sessions": self._entries(15)}),
            encoding="utf-8",
        )

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {"per_branch": {}, "defaults": {"local": {"sessions": {"count": 15}}}},
        )
        assert detector.check_single_file(mem_file)["should_rollover"] is False

    def test_the_detector_fires_above_the_limit(self, tmp_path, monkeypatch):
        mem_file = tmp_path / ".trinity" / "local.json"
        mem_file.parent.mkdir(parents=True)
        mem_file.write_text(
            json.dumps({"document_metadata": {"schema_version": "3.0.0"}, "sessions": self._entries(16)}),
            encoding="utf-8",
        )

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {"per_branch": {}, "defaults": {"local": {"sessions": {"count": 15}}}},
        )
        result = detector.check_single_file(mem_file)
        assert result["should_rollover"] is True
        assert "16/15 sessions" in result["trigger"].v2_reason

    def test_detector_and_extractor_never_disagree(self, tmp_path, monkeypatch):
        """The property, swept across the boundary rather than sampled at it.

        Honest note: this one was GREEN before the fix too — both sides used
        `>=`, so they agreed while both were wrong. It is a guard against
        moving one threshold and forgetting the other, not a red-first pin;
        the red-first pins for B4 are the two "at exactly the limit" tests.
        """
        from aipass.memory.apps.handlers.monitor import detector
        from .test_handlers import _import_extractor  # noqa: PLC0415  # relative: `tests.` resolves only on a branch-dir rootdir, not a repo-root run

        ext, _ = _import_extractor(monkeypatch)
        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {"per_branch": {}, "defaults": {"local": {"sessions": {"count": 5}}}},
        )
        for count in range(1, 10):
            mem_file = tmp_path / str(count) / ".trinity" / "local.json"
            mem_file.parent.mkdir(parents=True)
            mem_file.write_text(
                json.dumps({"document_metadata": {"schema_version": "3.0.0"}, "sessions": self._entries(count)}),
                encoding="utf-8",
            )
            fires = detector.check_single_file(mem_file)["should_rollover"]
            drains = bool(ext._extract_tail_excess(self._entries(count), 5, 999, "sessions", "memory"))
            assert fires == drains, f"count={count}: detector={fires} extractor={drains}"


# =============================================================================
# The receipt — .template_version.json
# =============================================================================


class TestTemplateVersionReceipt:
    """Which branches actually carry the current standard is a lookup, not an audit."""

    def test_template_versions_come_from_the_gold_source(self):
        from aipass.memory.apps.handlers.templates import receipt

        local = json.loads((_TEMPLATES / "LOCAL.template.json").read_text(encoding="utf-8"))
        obs = json.loads((_TEMPLATES / "OBSERVATIONS.template.json").read_text(encoding="utf-8"))
        assert receipt.template_versions() == {
            "local": local["document_metadata"]["schema_version"],
            "observations": obs["document_metadata"]["schema_version"],
        }

    def test_write_receipt_stamps_the_spec_shape(self, tmp_path):
        from aipass.memory.apps.handlers.templates import receipt

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        result = receipt.write_receipt(trinity, receipt.STAMPED_BY_PUSH)
        assert result["success"] is True

        written = json.loads((trinity / ".template_version.json").read_text(encoding="utf-8"))
        assert set(written) == {"template_versions", "stamped", "stamped_by", "config_rendered"}
        assert written["stamped_by"] == "memory push"
        assert written["template_versions"] == receipt.template_versions()

    def test_only_the_three_sanctioned_lanes_may_stamp(self, tmp_path):
        from aipass.memory.apps.handlers.templates import receipt

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        assert {receipt.STAMPED_BY_PUSH, receipt.STAMPED_BY_BIRTH, receipt.STAMPED_BY_RESET} == {
            "memory push",
            "spawn birth",
            "reset",
        }
        result = receipt.write_receipt(trinity, "whoever felt like it")
        assert result["success"] is False

    def test_a_skipped_branch_keeps_its_old_stamp(self, tmp_path, monkeypatch):
        """Honest: the receipt reports THIS branch, never the fleet's intent.

        The clock is pinned rather than raced — at the spec's one-second
        resolution a real bump inside the same second is indistinguishable
        from no bump at all, and a test that passes on timing is not a test.
        """
        from aipass.memory.apps.handlers.templates import receipt

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        monkeypatch.setattr(receipt, "_now", lambda: "2026-08-25T20:00:00")
        receipt.write_receipt(trinity, receipt.STAMPED_BY_BIRTH)
        first = json.loads((trinity / ".template_version.json").read_text(encoding="utf-8"))

        monkeypatch.setattr(receipt, "_now", lambda: "2026-08-26T09:30:00")
        receipt.bump_config_rendered(trinity)
        after = json.loads((trinity / ".template_version.json").read_text(encoding="utf-8"))
        assert after["stamped"] == first["stamped"] == "2026-08-25T20:00:00"
        assert after["stamped_by"] == "spawn birth"
        assert after["config_rendered"] == "2026-08-26T09:30:00"
        assert after["template_versions"] == first["template_versions"]

    def test_the_renderer_never_invents_a_stamp_it_did_not_make(self, tmp_path):
        """No receipt = the renderer has no authority to claim a template version."""
        from aipass.memory.apps.handlers.templates import receipt

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        result = receipt.bump_config_rendered(trinity)
        assert result["success"] is False
        assert not (trinity / ".template_version.json").exists()

    def test_read_receipt_returns_none_when_absent(self, tmp_path):
        from aipass.memory.apps.handlers.templates import receipt

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        assert receipt.read_receipt(trinity) is None


# =============================================================================
# The receipt is wired into the lanes that may write it
# =============================================================================


def _assert_the_lazy_import_path_is_a_package() -> None:
    """Name sys.modules poisoning instead of letting it read as a wrong count.

    ``tab_renderer._refresh_one_file`` reaches ``memory_files`` through a LAZY
    import, and it reports an import failure the same way it reports a bad
    file: as a per-file error. So a poisoned process surfaces here as
    ``(0, [...]) == (1, [])`` — a COUNT that points at the receipt renderer,
    which is not where the defect is. This says so out loud.

    Checked WITHOUT importing anything. An ``import_module`` probe would repair
    the very state it was measuring, and a pin that fixes its own precondition
    proves nothing.
    """
    package = sys.modules.get("aipass.memory.apps.handlers.json")
    assert package is None or hasattr(package, "__path__"), (
        f"a {type(package).__name__} with no __path__ is standing at "
        "aipass.memory.apps.handlers.json — an earlier test poisoned this process and the "
        "renderer's lazy import cannot resolve. This is an isolation defect, not a receipt defect."
    )


class TestReceiptWiring:
    """Callable is not enough — it has to be called, and only where honest."""

    def test_the_renderer_bumps_the_receipt_after_a_refresh(self, tmp_path, monkeypatch):
        from aipass.memory.apps.handlers.templates import receipt
        from aipass.memory.apps.handlers.tracking import tab_renderer

        trinity = tmp_path / ".trinity"
        trinity.mkdir(parents=True)
        local = trinity / "local.json"
        local.write_text(json.dumps({"document_metadata": {}, "sessions": []}), encoding="utf-8")

        monkeypatch.setattr(receipt, "_now", lambda: "2026-08-25T20:00:00")
        receipt.write_receipt(trinity, receipt.STAMPED_BY_BIRTH)
        monkeypatch.setattr(receipt, "_now", lambda: "2026-08-26T07:00:00")

        _assert_the_lazy_import_path_is_a_package()
        updated, _skipped, errors = tab_renderer._refresh_one_file(
            {"name": "memory"}, "memory", "local", {"defaults": {}}, {"entry_types": {}}, lambda b, m: local
        )
        assert (updated, errors) == (1, [])
        assert receipt.read_receipt(trinity)["config_rendered"] == "2026-08-26T07:00:00"

    def test_a_refresh_on_a_branch_with_no_receipt_still_succeeds(self, tmp_path):
        """The bump is a record, not a gate — a missing receipt must not fail the render."""
        from aipass.memory.apps.handlers.templates import receipt
        from aipass.memory.apps.handlers.tracking import tab_renderer

        trinity = tmp_path / ".trinity"
        trinity.mkdir(parents=True)
        local = trinity / "local.json"
        local.write_text(json.dumps({"document_metadata": {}, "sessions": []}), encoding="utf-8")

        _assert_the_lazy_import_path_is_a_package()
        updated, _skipped, errors = tab_renderer._refresh_one_file(
            {"name": "memory"}, "memory", "local", {"defaults": {}}, {"entry_types": {}}, lambda b, m: local
        )
        assert (updated, errors) == (1, [])
        assert receipt.read_receipt(trinity) is None

    def test_the_push_lane_stamps_only_branches_it_changed(self):
        """Source-level pin: the stamp sits inside the `if written:` arm.

        Stamping every scanned branch would make the receipt report the run's
        INTENT rather than the branch's reality — the one thing the standard
        says it must never do.

        Repointed 2026-08-27: the stamping lane moved from the retired
        pre-.trinity `pusher.py` (archived) to `trinity_push.apply_plan`, which
        is what actually stamped all 22 receipts in the fleet push.
        """
        source = (_MEMORY_ROOT / "apps" / "handlers" / "templates" / "trinity_push.py").read_text(encoding="utf-8")
        arm = source[source.index("    if written:") :]
        assert "receipt.write_receipt(" in arm
        assert "STAMPED_BY_PUSH" in arm


class TestLintNamesWhatItCannotMeasure:
    """A refusal that prints 0/300 reads as a pass."""

    def test_the_display_does_not_print_a_zero_length(self):
        source = (_MEMORY_ROOT / "apps" / "modules" / "lint.py").read_text(encoding="utf-8")
        assert "UNMEASURABLE" in source
        assert 'v.get("reason") == "unmeasurable"' in source

    def test_the_display_names_a_missing_field_separately(self):
        """ "UNMEASURABLE — missing, expected str" would be true and unactionable.

        The agent can only fix what it is told: the missing-field line names the
        canonical key to rename, which is the whole repair.
        """
        source = (_MEMORY_ROOT / "apps" / "modules" / "lint.py").read_text(encoding="utf-8")
        assert 'v.get("reason") == "missing_field"' in source
        assert "FIELD" in source


# =============================================================================
# B3 (second half) — a field the gate cannot FIND is also a violation
# =============================================================================


class TestMissingFieldIsAViolation:
    """The other half of B1, reported by @hooks 2026-08-25 after 1.3.0 shipped.

    1.3.0 fixed the WRONG-TYPE case and left the MISSING-FIELD case answering
    ``""`` — so a ``key_learning`` whose text sits under ``learning`` where the
    config says ``value`` measured as zero characters and cleared its cap. Same
    species, same silence: a renamed field is not an absent text, it is a text
    the reader cannot find.
    """

    def test_a_missing_field_says_it_cannot_be_read(self):
        assert el._extract_text({"key": "k", "learning": "x" * 500}, "value") is None

    def test_an_entry_with_the_field_empty_is_still_compliant(self):
        """ "" stays a legitimate answer when the field is genuinely there."""
        assert el._extract_text({"key": "k", "value": ""}, "value") == ""

    def test_the_hooks_repro_is_refused(self):
        """The exact case @hooks proved live: 500 chars under a 200-char cap, 0 violations."""
        limits = _limits(max_chars=200, field="value", container="key_learnings")
        limits["entry_types"]["key_learnings"] = limits["entry_types"].pop("observations")
        before = {"key_learnings": [{"number": 1, "key": "k", "value": "ok"}]}
        after = {"key_learnings": [{"number": 2, "key": "drifted", "learning": "x" * 500}] + before["key_learnings"]}
        hits = el.changed_entries(before, after, limits)
        assert len(hits) == 1
        assert hits[0]["entry_type"] == "key_learnings"

    def test_the_refusal_names_the_canonical_field(self):
        """@hooks' formatter prints "no 'value' field — rename it"; it needs the name.

        Reason is ``missing_field``, not ``unmeasurable``: the consumer renders
        the two differently and "expected a string, found missing" tells the
        agent nothing it can act on.
        """
        before = {"observations": []}
        after = {"observations": [{"number": 1, "observation": "x" * 500}]}
        hits = el.changed_entries(before, after, _limits())
        assert len(hits) == 1
        assert hits[0]["reason"] == "missing_field"
        assert hits[0]["found_type"] == "missing"
        assert hits[0]["field"] == "note"

    def test_the_six_published_keys_are_still_ints(self):
        """@hooks' edit_gate formats length/cap/over_by with %d — a str would raise."""
        before = {"observations": []}
        after = {"observations": [{"number": 1, "observation": "x" * 500}]}
        hit = el.changed_entries(before, after, _limits())[0]
        for key in ("length", "cap", "over_by"):
            assert isinstance(hit[key], int)
        for key in ("entry_type", "container", "key"):
            assert isinstance(hit[key], str)

    def test_untouched_legacy_drift_is_now_refused_too(self):
        """Rewritten 2026-08-27: the push cured the renamed shape fleet-wide.

        The exemption existed so drifted branches could keep writing while the
        reset was pending. The reset happened. What is left in an archivable
        container is not legacy, it is new.
        """
        legacy = {"number": 1, "observation": "x" * 500}
        before = {"observations": [legacy]}
        after = {"observations": [dict(legacy)]}
        hits = el.changed_entries(before, after, _limits())
        assert len(hits) == 1

    def test_carrying_one_drifted_entry_does_not_license_a_second(self):
        """Both are reported now — the new one, and the one that was tolerated."""
        legacy = {"number": 1, "observation": "x" * 500}
        before = {"observations": [legacy]}
        after = {"observations": [{"number": 2, "observation": "y" * 500}, dict(legacy)]}
        hits = el.changed_entries(before, after, _limits())
        assert {hit["key"] for hit in hits} == {"0", "1"}

    def test_a_dict_container_refuses_a_missing_field_too(self):
        limits = _limits(max_chars=200, field="value", container="key_learnings")
        limits["entry_types"]["observations"]["kind"] = "dict"
        before = {"key_learnings": {}}
        after = {"key_learnings": {"drifted": {"learning": "x" * 500}}}
        hits = el.changed_entries(before, after, limits)
        assert len(hits) == 1
        assert hits[0]["reason"] == "missing_field"
        assert hits[0]["found_type"] == "missing"
        assert hits[0]["field"] == "value"

    def test_lint_reports_the_entry_it_cannot_find_a_field_in(self, tmp_path):
        """Read-only lint stayed silent while the write gate refused — the audit lied.

        A branch could ask "am I compliant?", be told yes, and then be blocked
        on its next write for a shape lint had already seen.
        """
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "observations.json").write_text(
            json.dumps({"observations": [{"number": 1, "observation": "x" * 500}]}),
            encoding="utf-8",
        )
        hits = lint_handler._lint_branch("b", str(tmp_path), _limits())
        assert len(hits) == 1
        assert hits[0]["reason"] == "missing_field"
        assert hits[0]["field"] == "note"

    def test_lint_reports_a_dict_container_missing_its_field(self, tmp_path):
        """Both container kinds, or the audit is only half honest.

        key_learnings is dict-shaped on several branches; a scanner that catches
        the list shape and not the dict one still tells those branches nothing.
        """
        limits = _limits(max_chars=200, field="value", container="key_learnings")
        limits["entry_types"]["observations"]["kind"] = "dict"
        limits["entry_types"]["observations"]["file"] = "local.json"
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "local.json").write_text(
            json.dumps({"key_learnings": {"drifted": {"learning": "x" * 500}}}),
            encoding="utf-8",
        )
        hits = lint_handler._lint_branch("b", str(tmp_path), limits)
        assert len(hits) == 1
        assert hits[0]["reason"] == "missing_field"
        assert hits[0]["found_type"] == "missing"
        assert hits[0]["field"] == "value"


class TestTheTabHonoursPerBranchCharCaps:
    """One source, or the tab instructs an agent to break the rule it enforces.

    Reported by @seedgo 2026-08-26 from the other side of the contract: their
    ``expected_meta_line()`` resolves ``entry_limits.per_branch``; ``render_tab``
    read ``entry_types`` straight off the config and never consulted it. Latent
    only because that map is empty today — the day anyone sets one override, the
    rendered line names the default cap, the gate enforces the override, and the
    branch fails the Meta-lines rule permanently because the renderer keeps
    rewriting the line the checker keeps rejecting.

    Note the asymmetry that made it an oversight rather than a decision:
    ``rollover.per_branch`` was already honoured here, ``entry_limits`` was not.
    """

    @staticmethod
    def _cfg() -> dict:
        return {
            "entry_types": {"sessions": {"max_chars": 300, "field": "summary"}},
            "per_branch": {"baud": {"sessions": {"max_chars": 500}}},
        }

    @staticmethod
    def _rollover() -> dict:
        return {"defaults": {"local": {"sessions": {"count": 15}}}, "per_branch": {}}

    @pytest.fixture(autouse=True)
    def _real_resolver(self, monkeypatch):
        """conftest mocks the whole `handlers.json` package, so the renderer's
        `entry_limits` binds a MagicMock whose every attribute answers another
        MagicMock — a cap assertion would then pass or fail for reasons that have
        nothing to do with the resolver. Hand it the real module.
        """
        from aipass.memory.apps.handlers.tracking import tab_renderer  # noqa: PLC0415

        monkeypatch.setattr(tab_renderer, "entry_limits", el)

    def test_an_overridden_cap_reaches_the_rendered_tab(self):
        from aipass.memory.apps.handlers.tracking import tab_renderer  # noqa: PLC0415

        tab = tab_renderer.render_tab("sessions", self._rollover(), self._cfg(), "baud")
        assert "≤500 chars" in tab

    def test_a_branch_without_an_override_still_reads_the_default(self):
        from aipass.memory.apps.handlers.tracking import tab_renderer  # noqa: PLC0415

        tab = tab_renderer.render_tab("sessions", self._rollover(), self._cfg(), "memory")
        assert "≤300 chars" in tab

    def test_the_branch_name_is_matched_case_insensitively(self):
        """Registry casing varies (MEMORY vs memory); the override must not."""
        from aipass.memory.apps.handlers.tracking import tab_renderer  # noqa: PLC0415

        tab = tab_renderer.render_tab("sessions", self._rollover(), self._cfg(), "BAUD")
        assert "≤500 chars" in tab

    def test_todos_honours_it_too(self):
        from aipass.memory.apps.handlers.tracking import tab_renderer  # noqa: PLC0415

        cfg = {
            "entry_types": {"todos": {"max_chars": 150, "field": "task"}},
            "per_branch": {"baud": {"todos": {"max_chars": 80}}},
        }
        assert "≤80 chars" in tab_renderer.render_tab("todos", self._rollover(), cfg, "baud")

    def test_the_renderer_and_the_enforcer_resolve_identically(self):
        """The two must never disagree — that divergence IS the drift.

        load_entry_limits() is what the write gate measures against; whatever it
        calls the cap is what the tab must print.
        """
        from aipass.memory.apps.handlers.tracking import tab_renderer  # noqa: PLC0415

        section = self._cfg()
        merged = el.resolve_entry_types(section, "baud")
        assert merged["sessions"]["max_chars"] == 500
        assert f"≤{merged['sessions']['max_chars']} chars" in tab_renderer.render_tab(
            "sessions", self._rollover(), section, "baud"
        )


class TestTheReceiptsGoldVersionIsSchemaVersion:
    """@seedgo inferred it and asked to be pinned by the owner, not by itself."""

    def test_the_receipt_reads_schema_version_not_document_version(self):
        """The two templates disagree on `version` (2.0.0 / 1.0.0) and agree on
        schema_version (3.0.0). The contract's example shows two EQUAL values, so
        only schema_version reproduces it — and the receipt reports the STRUCTURE
        a branch was stamped with, which is what schema_version names.
        """
        from aipass.memory.apps.handlers.templates import receipt  # noqa: PLC0415

        local = json.loads((_TEMPLATES / "LOCAL.template.json").read_text(encoding="utf-8"))
        obs = json.loads((_TEMPLATES / "OBSERVATIONS.template.json").read_text(encoding="utf-8"))
        assert local["document_metadata"]["version"] != obs["document_metadata"]["version"]
        versions = receipt.template_versions()
        assert versions == {
            "local": local["document_metadata"]["schema_version"],
            "observations": obs["document_metadata"]["schema_version"],
        }
        assert versions["local"] == versions["observations"]
