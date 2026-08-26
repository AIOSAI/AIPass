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

    def test_a_legacy_unchanged_list_entry_is_left_alone(self):
        """Rollover-safety is not sacrificed to catch the drift.

        Nine branches carry list-shaped notes today and enforce is ON. If an
        unmeasurable entry already on disk were refused, every one of those
        branches would be unable to write its memory file at all — the fix
        would brick the citizens it is meant to protect.
        """
        legacy = {"number": 1, "note": [{"title": "x" * 500}]}
        before = {"observations": [legacy]}
        after = {"observations": [dict(legacy)]}
        assert el.changed_entries(before, after, _limits()) == []

    def test_a_second_list_entry_beside_a_legacy_one_is_still_refused(self):
        """The hole a text-identity dedup would leave.

        If unmeasurable entries all collapse to one sentinel, a branch with a
        single legacy list-note could add ten more and every one would read as
        'already on disk'. Identity must be the raw value, not the sentinel.
        """
        legacy = {"number": 1, "note": [{"title": "old"}]}
        before = {"observations": [legacy]}
        after = {"observations": [{"number": 2, "note": [{"title": "new"}]}, dict(legacy)]}
        hits = el.changed_entries(before, after, _limits())
        assert len(hits) == 1
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

    def test_the_real_module_has_no_status_writer_after_a_clean_reimport(self):
        """The same claim against the LOADED module, not just the file on disk.

        Sibling tests in this suite swap `handlers.json` for a MagicMock, and a
        MagicMock answers `hasattr` True for a function that no longer exists —
        so the import has to be forced fresh before the question means anything.
        This is the assertion the retired TestUpdateMetadata class used to carry.
        """
        import importlib
        import sys

        for name in list(sys.modules):
            if name.startswith("aipass.memory.apps.handlers.json"):
                del sys.modules[name]

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

        updated, _skipped, errors = tab_renderer._refresh_one_file(
            {"name": "memory"}, "memory", "local", {"defaults": {}}, {"entry_types": {}}, lambda b, m: local
        )
        assert (updated, errors) == (1, [])
        assert receipt.read_receipt(trinity) is None

    def test_the_push_lane_stamps_only_branches_it_changed(self):
        """Source-level pin: the stamp sits inside the `branch_changed` arm.

        Stamping every scanned branch would make the receipt report the run's
        INTENT rather than the branch's reality — the one thing the standard
        says it must never do.
        """
        source = (_MEMORY_ROOT / "apps" / "handlers" / "templates" / "pusher.py").read_text(encoding="utf-8")
        arm = source[source.index("if branch_changed:") :]
        arm = arm[: arm.index("\n    if not dry_run and result")]
        assert "receipt.write_receipt(" in arm
        assert "STAMPED_BY_PUSH" in arm


class TestLintNamesWhatItCannotMeasure:
    """A refusal that prints 0/300 reads as a pass."""

    def test_the_display_does_not_print_a_zero_length(self):
        source = (_MEMORY_ROOT / "apps" / "modules" / "lint.py").read_text(encoding="utf-8")
        assert "UNMEASURABLE" in source
        assert 'v.get("reason") == "unmeasurable"' in source
