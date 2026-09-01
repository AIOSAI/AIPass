# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_plans_processor.py
# Date: 2026-04-26
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for plans_processor handler -- line coverage for all functions.

Covers: from aipass.memory.apps.handlers.intake.plans_processor import process_plans
"""

import hashlib
import json
import subprocess
import sys
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------


def _sha(path):
    """The content hash the manifest records — spelled here so fixtures cannot drift from it."""
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def _import_plans_processor(monkeypatch):
    """Import plans_processor with mocked dependencies."""
    mock_memory_files = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "aipass.memory.apps.handlers.json.memory_files",
        mock_memory_files,
    )

    sys.modules.pop("aipass.memory.apps.handlers.intake.plans_processor", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.intake")
    if parent is not None and hasattr(parent, "plans_processor"):
        delattr(parent, "plans_processor")

    from aipass.memory.apps.handlers.intake import plans_processor

    return plans_processor


# ===========================================================================
# Tests: _chunk_plan_text
# ===========================================================================


class TestChunkPlanText:
    """Test _chunk_plan_text function."""

    def test_chunks_by_markdown_headers(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)
        text = (
            "## Introduction\n"
            "This is the introduction section with enough text to pass the 30-char threshold easily.\n"
            "## Details\n"
            "Here are the details of the plan with plenty of content to exceed thirty characters.\n"
        )

        result = mod._chunk_plan_text(text, "plan.md")

        assert len(result) == 2
        assert result[0]["section"] == "Introduction"
        assert result[1]["section"] == "Details"
        assert "Introduction" in result[0]["text"] or "introduction" in result[0]["text"]

    def test_flushes_last_section(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)
        text = (
            "## Header One\n"
            "Content for header one, long enough to pass thirty characters.\n"
            "Trailing content without a following header, also long enough to be a real section."
        )

        result = mod._chunk_plan_text(text, "plan.md")

        assert len(result) == 1
        # The last section should be flushed since there is only one header
        assert result[0]["section"] == "Header One"
        assert "Trailing content" in result[0]["text"]

    def test_skips_short_sections(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)
        text = (
            "## Short\n"
            "Tiny.\n"
            "## Long Section\n"
            "This section has enough content to pass the thirty-character minimum requirement.\n"
        )

        result = mod._chunk_plan_text(text, "plan.md")

        # The "Short" section has text "## Short\nTiny." stripped -> "## Short\nTiny."
        # which is short, so it should be skipped
        assert len(result) == 1
        assert result[0]["section"] == "Long Section"

    def test_fallback_to_size_chunking(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)
        # Headers present but every section body is tiny (< 30 chars), so the
        # header-based pass produces zero chunks and the size-based fallback
        # triggers on the full text which exceeds MAX_CHUNK_CHARS.
        # Each pair "## Hxxx\nx\n" is ~12 chars; need > 1500 total.
        num_sections = (mod.MAX_CHUNK_CHARS // 8) + 50
        header_lines = []
        for i in range(num_sections):
            header_lines.append(f"## H{i:04d}")
            header_lines.append("x")
        text = "\n".join(header_lines)
        # Confirm text is actually long enough for the size-based fallback
        assert len(text) > mod.MAX_CHUNK_CHARS

        result = mod._chunk_plan_text(text, "plan.md")

        assert len(result) >= 2
        assert result[0]["section"].startswith("plan.md_part")

    def test_small_text_no_headers(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)
        text = "This is a plain text plan without any markdown headers at all."

        result = mod._chunk_plan_text(text, "plan.md")

        assert len(result) == 1
        assert result[0]["section"] == "plan.md"
        assert result[0]["text"] == text

    def test_tiny_text_skipped(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)
        text = "Short."

        result = mod._chunk_plan_text(text, "plan.md")

        assert result == []

    def test_splits_oversized_chunks(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)
        # Create a markdown section that is > MAX_CHUNK_CHARS * 2
        big_body = "X" * (mod.MAX_CHUNK_CHARS * 3)
        text = f"## Big Section\n{big_body}\n"

        result = mod._chunk_plan_text(text, "plan.md")

        # The single chunk was > MAX_CHUNK_CHARS * 2, so it gets split
        assert len(result) >= 2
        for chunk in result:
            assert "_part" in chunk["section"] or chunk["section"] == "Big Section"

    def test_empty_text(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)

        result = mod._chunk_plan_text("", "plan.md")

        assert result == []


# ===========================================================================
# Tests: _load_manifest / _save_manifest
# ===========================================================================


class TestUnfilledPlaceholderSectionsAreNotVectorized:
    """@flow's proposal, 2026-08-30, built as proposed and measured before shipping.

    A plan template ships sections the author is meant to fill in. Unfilled, the
    body is nothing but the bracketed prompt — `[What do you want to achieve?]`
    — and vectorizing it stores a question the template asked, attributed to a
    plan that never answered it.

    NARROW ON PURPOSE. @flow's own plan-level heuristic (`is_template_content`)
    was retired after it false-positived on real-but-minimal FPLANs and destroyed
    the file, the registry row and the archive together. This is chunk-level, so
    the worst case is a dropped empty section rather than a lost plan — and the
    rule only fires when EVERY content line of the body is bracketed. One line of
    real prose anywhere and the chunk is kept.

    Measured against the live collection before building: 452 of 8,433 vectors
    (5.4%) match, and ZERO of them contain unbracketed prose. Not the ~27% @flow
    estimated — most of that redundancy is identical FILLED template prose
    ('## Agent Preparation', '## Notepad', '## Listen'), which is real content
    and stays.
    """

    def test_an_unfilled_section_is_dropped(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)
        text = "### Goal\n[What do you want to achieve? Specific end state.]\n"
        assert mod._chunk_plan_text(text, "p.md") == []

    def test_a_trailing_horizontal_rule_does_not_save_it(self, monkeypatch):
        """The live shape: the two biggest blocks both end in a `---` separator."""
        mod = _import_plans_processor(monkeypatch)
        text = "## Notes\n\n[Working notes, issues encountered, decisions made]\n\n---\n"
        assert mod._chunk_plan_text(text, "p.md") == []

    def test_one_line_of_real_prose_keeps_the_whole_section(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)
        text = (
            "### Goal\n"
            "[What do you want to achieve? Specific end state.]\n"
            "Actually we want the rollover valve to stop refusing today's entries.\n"
        )
        chunks = mod._chunk_plan_text(text, "p.md")
        assert len(chunks) == 1
        assert "rollover valve" in chunks[0]["text"]

    def test_a_filled_section_is_untouched(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)
        text = "## Summary\n\nThe declared-roots anchor shipped and the fleet reads 28 citizens.\n"
        chunks = mod._chunk_plan_text(text, "p.md")
        assert len(chunks) == 1

    def test_a_section_that_is_only_a_rule_or_blank_is_not_called_a_placeholder(self, monkeypatch):
        """Absence of content is not the same as an unfilled prompt.

        A body with no content lines at all is already dropped by the length
        gate. Routing it through the placeholder rule instead would make the
        rule's own log and meaning wrong about why it went.
        """
        mod = _import_plans_processor(monkeypatch)
        assert mod._is_placeholder_only("## Notes\n\n---\n") is False
        assert mod._is_placeholder_only("## Notes\n\n") is False

    def test_markdown_link_syntax_is_not_a_placeholder(self, monkeypatch):
        """`[text](url)` opens with a bracket and is real content."""
        mod = _import_plans_processor(monkeypatch)
        assert mod._is_placeholder_only("## Refs\n[the seedgo audit](./audit.md)\n") is False


class TestManifest:
    """Test _load_manifest and _save_manifest."""

    def test_load_manifest_file_exists(self, monkeypatch, tmp_path):
        mod = _import_plans_processor(monkeypatch)
        manifest_path = tmp_path / "config" / ".plans_processed.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_data = {"plan1.md": "2026-01-01T00:00:00", "plan2.md": "2026-01-02T00:00:00"}
        manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)

        result = mod._load_manifest()

        assert result == manifest_data

    def test_load_manifest_file_missing(self, monkeypatch, tmp_path):
        mod = _import_plans_processor(monkeypatch)
        manifest_path = tmp_path / "config" / ".plans_processed.json"
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)

        result = mod._load_manifest()

        assert result == {}

    def test_load_manifest_bad_json(self, monkeypatch, tmp_path):
        mod = _import_plans_processor(monkeypatch)
        manifest_path = tmp_path / "config" / ".plans_processed.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text("not valid json {{{{", encoding="utf-8")
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)

        result = mod._load_manifest()

        assert result == {}

    def test_save_manifest_creates_parent_dirs(self, monkeypatch, tmp_path):
        mod = _import_plans_processor(monkeypatch)
        manifest_path = tmp_path / "deep" / "nested" / "config" / ".plans_processed.json"
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)
        data = {"file.md": "2026-04-26T12:00:00"}

        mod._save_manifest(data)

        assert manifest_path.exists()
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert loaded == data


# ===========================================================================
# Tests: _embed_texts
# ===========================================================================


class TestEmbedTexts:
    """Test _embed_texts subprocess wrapper."""

    def test_embed_texts_success(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)
        expected = {"success": True, "embeddings": [[0.1, 0.2], [0.3, 0.4]]}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(expected)

        with patch.object(subprocess, "run", return_value=mock_result) as mock_run:
            result = mod._embed_texts(["hello", "world"])

        assert result["success"] is True
        assert result["embeddings"] == [[0.1, 0.2], [0.3, 0.4]]
        mock_run.assert_called_once()

    def test_embed_texts_nonzero_return(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "model not found"

        with patch.object(subprocess, "run", return_value=mock_result):
            result = mod._embed_texts(["hello"])

        assert result["success"] is False
        assert "model not found" in result["error"]

    def test_embed_texts_exception(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)

        with patch.object(subprocess, "run", side_effect=OSError("no such binary")):
            result = mod._embed_texts(["hello"])

        assert result["success"] is False
        assert "no such binary" in result["error"]


# ===========================================================================
# Tests: _store_vectors
# ===========================================================================


class TestStoreVectors:
    """Test _store_vectors subprocess wrapper."""

    def test_store_vectors_success(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)
        expected = {"success": True, "stored": 5}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(expected)

        with patch.object(subprocess, "run", return_value=mock_result):
            result = mod._store_vectors(
                embeddings=[[0.1, 0.2]],
                documents=["doc1"],
                metadatas=[{"key": "val"}],
                collection_name="test_col",
            )

        assert result["success"] is True
        assert result["stored"] == 5

    def test_store_vectors_nonzero_return(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "db locked"

        with patch.object(subprocess, "run", return_value=mock_result):
            result = mod._store_vectors(
                embeddings=[[0.1]],
                documents=["doc"],
                metadatas=[{}],
            )

        assert result["success"] is False
        assert "db locked" in result["error"]

    def test_store_vectors_exception(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)

        with patch.object(subprocess, "run", side_effect=TimeoutError("timed out")):
            result = mod._store_vectors(
                embeddings=[[0.1]],
                documents=["doc"],
                metadatas=[{}],
            )

        assert result["success"] is False
        assert "timed out" in result["error"]


# ===========================================================================
# Tests: _find_repo_root / _get_memory_python (module-level)
# ===========================================================================


class TestFindRepoRoot:
    """This lane no longer walks — it delegates to ``handlers/repo_root.py``.

    THE TEST THAT USED TO LIVE HERE ASSERTED THE DEFECT. ``test_find_repo_root_
    falls_back_to_cwd`` pinned ``result == Path.cwd()``, so the exact construct
    that took CI down twice on 2026-08-31 had a green test standing guard over
    it. Both are rewritten rather than deleted: what a suite used to guarantee
    is worth more in the record than a clean diff, and a reversed pin says out
    loud that the contract changed on purpose.

    The walk itself is pinned once, in ``test_repo_root.py``. Pinning it again
    per lane would recreate the ten-copies problem in the tests.
    """

    def test_it_delegates_instead_of_walking_itself(self, monkeypatch, tmp_path):
        """A private walk here is how the first cure missed nine other files."""
        mod = _import_plans_processor(monkeypatch)
        seen: list[dict] = []
        monkeypatch.setattr(
            mod.repo_root,
            "find_repo_root",
            lambda *args, **kwargs: (seen.append(kwargs), tmp_path)[1],
        )

        assert mod._find_repo_root() == tmp_path
        assert seen and seen[0].get("caller") == "plans_processor", (
            f"the lane did not name itself to the shared resolver: {seen}"
        )

    def test_it_never_returns_the_process_directory(self, monkeypatch, tmp_path):
        """The reversal. Standing somewhere must not change where the code lives."""
        mod = _import_plans_processor(monkeypatch)
        monkeypatch.chdir(tmp_path)

        assert mod._find_repo_root() != tmp_path


class TestGetMemoryPython:
    """Test _get_memory_python function."""

    def test_env_override(self, monkeypatch):
        mod = _import_plans_processor(monkeypatch)
        monkeypatch.setenv("AIPASS_MEMORY_PYTHON", "/custom/python")

        result = mod._get_memory_python()

        assert result == "/custom/python"

    def test_venv_python_exists(self, monkeypatch, tmp_path):
        mod = _import_plans_processor(monkeypatch)
        monkeypatch.delenv("AIPASS_MEMORY_PYTHON", raising=False)
        venv_python = tmp_path / ".venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("#!/usr/bin/env python", encoding="utf-8")
        monkeypatch.setattr(mod, "_MEMORY_VENV_PYTHON", venv_python)

        result = mod._get_memory_python()

        assert result == str(venv_python)

    def test_falls_back_to_sys_executable(self, monkeypatch, tmp_path):
        mod = _import_plans_processor(monkeypatch)
        monkeypatch.delenv("AIPASS_MEMORY_PYTHON", raising=False)
        # Point to a non-existent venv
        monkeypatch.setattr(mod, "_MEMORY_VENV_PYTHON", tmp_path / "nonexistent" / "python")

        result = mod._get_memory_python()

        assert result == sys.executable


# ===========================================================================
# Tests: process_plans
# ===========================================================================


class TestTheManifestKeysOnContentNotOnlyOnAName:
    """@flow's finding, 2026-08-30: a restored plan is never re-vectorized.

    `process_plans` skipped any file whose NAME appeared in the manifest. Restore
    puts the plan file back but nothing removes its manifest row, so when that
    plan is genuinely closed later its FINAL content is silently never stored and
    the collection keeps only its pre-restore text. Three live cases, all APLANs
    @devpulse restored after a mistaken close.

    @flow offered two seams: an entry point they call on restore, or keying the
    manifest on content. Content keying wins because it needs nothing from them
    and it is self-healing — it also covers a plan edited after close, which the
    callback seam would still miss.

    Measured before choosing the migration: 491 manifest rows, 488 files present,
    and ZERO present files modified after they were processed. So backfilling a
    hash for a legacy row cannot skip a change that already happened, and the
    mtime guard below covers one arriving later.
    """

    def _mock_config(self, monkeypatch, mod, plans_dir):
        mock_cl = MagicMock()
        mock_cl.section.return_value = {
            "enabled": True,
            "path": str(plans_dir),
            "supported_extensions": [".md"],
            "collection_name": "flow_plans",
        }
        monkeypatch.setattr(mod, "config_loader", mock_cl)

    def _stub_pipeline(self, monkeypatch, mod, seen):
        monkeypatch.setattr(
            mod, "_embed_texts", lambda texts, timeout=120: {"success": True, "embeddings": [[0.1]] * len(texts)}
        )
        monkeypatch.setattr(
            mod,
            "_store_vectors",
            lambda emb, texts, metas, coll: seen.append(metas[0]["source_file"]) or {"success": True},
        )

    def test_changed_content_reprocesses_even_though_the_name_is_known(self, monkeypatch, tmp_path):
        mod = _import_plans_processor(monkeypatch)
        plans = tmp_path / "plans"
        plans.mkdir()
        plan = plans / "APLAN-0013_branch_audit_api_2026-08-13.md"
        plan.write_text("## Summary\n\nthe text as it was before the restore\n", encoding="utf-8")
        manifest_path = tmp_path / ".plans_processed.json"
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)
        self._mock_config(monkeypatch, mod, plans)
        seen = []
        self._stub_pipeline(monkeypatch, mod, seen)

        first = mod.process_plans()
        assert first["files_processed"] == 1, first

        # Unchanged: must NOT re-embed.
        seen.clear()
        assert mod.process_plans()["files_processed"] == 0
        assert seen == []

        # Restored with different content, same name — this is the defect.
        plan.write_text("## Summary\n\nthe FINAL text, written after the restore\n", encoding="utf-8")
        seen.clear()
        again = mod.process_plans()

        assert again["files_processed"] == 1, "a restored plan's final content was never vectorized"
        assert seen == [plan.name]

    def test_a_newly_processed_plan_records_its_content_not_just_a_time(self, monkeypatch, tmp_path):
        """The write side, pinned separately from the read side.

        A mutant reverting `_manifest_entry` to a bare timestamp survived every
        other test here: the legacy read path is tolerant enough that the next
        run still answered "not stale" via mtime. So the row would quietly go
        back to naming a time instead of a content, and the restore defect would
        return for every plan processed from then on — invisibly, because
        nothing asserted what the row actually said.
        """
        mod = _import_plans_processor(monkeypatch)
        plans = tmp_path / "plans"
        plans.mkdir()
        plan = plans / "FPLAN-9001_new_plan_2026-08-30.md"
        plan.write_text("## Summary\n\nA plan with enough real content to make a chunk.\n", encoding="utf-8")
        manifest_path = tmp_path / ".plans_processed.json"
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)
        self._mock_config(monkeypatch, mod, plans)
        self._stub_pipeline(monkeypatch, mod, [])

        assert mod.process_plans()["files_processed"] == 1

        entry = json.loads(manifest_path.read_text(encoding="utf-8"))[plan.name]
        assert isinstance(entry, dict), f"row is not content-keyed: {entry!r}"
        assert entry["content_sha256"] == _sha(plan)
        assert entry["processed_at"]

    def test_a_legacy_row_is_backfilled_not_re_embedded(self, monkeypatch, tmp_path):
        """491 rows carry a bare timestamp. Re-embedding them all would be a storm.

        The migration records what the row was always missing — the hash — and
        does not pay for embeddings it has no reason to believe are stale.
        """
        mod = _import_plans_processor(monkeypatch)
        plans = tmp_path / "plans"
        plans.mkdir()
        plan = plans / "FPLAN-0208_dashboard_count_test_plan_2026-05-10.md"
        plan.write_text("## Summary\n\nunchanged since the day it was processed\n", encoding="utf-8")
        manifest_path = tmp_path / ".plans_processed.json"
        # The legacy shape, exactly as it sits on disk today: a bare ISO string.
        manifest_path.write_text(json.dumps({plan.name: "2999-01-01T00:00:00"}), encoding="utf-8")
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)
        self._mock_config(monkeypatch, mod, plans)
        seen = []
        self._stub_pipeline(monkeypatch, mod, seen)

        result = mod.process_plans()

        assert result["files_processed"] == 0, "a legacy row with unchanged content must not re-embed"
        assert seen == []
        entry = json.loads(manifest_path.read_text(encoding="utf-8"))[plan.name]
        assert isinstance(entry, dict) and entry.get("content_sha256"), entry

    def test_a_legacy_row_whose_file_is_newer_than_its_row_reprocesses(self, monkeypatch, tmp_path):
        """The safety net for the case the one-time measurement cannot cover.

        A legacy row carries no hash, so 'unchanged' is a belief, not a fact. If
        the file was written AFTER the row was recorded, that belief is wrong —
        which is exactly what a restore does to a plan.
        """
        mod = _import_plans_processor(monkeypatch)
        plans = tmp_path / "plans"
        plans.mkdir()
        plan = plans / "APLAN-0017_branch_audit_commons_2026-08-13.md"
        plan.write_text("## Summary\n\nrestored, and the row predates this file\n", encoding="utf-8")
        manifest_path = tmp_path / ".plans_processed.json"
        manifest_path.write_text(json.dumps({plan.name: "2001-01-01T00:00:00"}), encoding="utf-8")
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)
        self._mock_config(monkeypatch, mod, plans)
        seen = []
        self._stub_pipeline(monkeypatch, mod, seen)

        assert mod.process_plans()["files_processed"] == 1
        assert seen == [plan.name]

    def test_a_manifest_row_whose_file_is_gone_is_left_alone(self, monkeypatch, tmp_path):
        """The three live cases are rows for files that LEFT processed_plans.

        Pruning them would re-vectorize the whole plan from scratch the moment it
        came back, discarding nothing but paying for everything. The row is not
        the problem; trusting the row's NAME was. Left in place on purpose.
        """
        mod = _import_plans_processor(monkeypatch)
        plans = tmp_path / "plans"
        plans.mkdir()
        manifest_path = tmp_path / ".plans_processed.json"
        gone = "APLAN-0018_branch_audit_aipass_2026-08-13.md"
        manifest_path.write_text(json.dumps({gone: "2026-05-10T13:03:05"}), encoding="utf-8")
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)
        self._mock_config(monkeypatch, mod, plans)

        mod.process_plans()

        assert gone in json.loads(manifest_path.read_text(encoding="utf-8"))


class TestProcessPlans:
    """Test process_plans main entry point."""

    def _mock_config(self, monkeypatch, mod, plans_config):
        """Mock config_loader.section on the plans_processor module."""
        mock_cl = MagicMock()
        mock_cl.section.return_value = plans_config
        monkeypatch.setattr(mod, "config_loader", mock_cl)

    def test_process_plans_defaults_no_plans_dir(self, monkeypatch, tmp_path):
        """With default config (self-healed), plans dir absent → success + 0 files."""
        mod = _import_plans_processor(monkeypatch)
        self._mock_config(monkeypatch, mod, {"enabled": True, "path": ".backup/processed_plans"})
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod.process_plans()

        assert result["success"] is True
        assert result["files_processed"] == 0
        assert "not found" in result.get("reason", "")

    def test_process_plans_disabled(self, monkeypatch, tmp_path):
        mod = _import_plans_processor(monkeypatch)
        self._mock_config(monkeypatch, mod, {"enabled": False})

        result = mod.process_plans()

        assert result["success"] is True
        assert result["skipped"] is True
        assert "disabled" in result["reason"]

    def test_process_plans_dir_not_found(self, monkeypatch, tmp_path):
        mod = _import_plans_processor(monkeypatch)
        self._mock_config(monkeypatch, mod, {"enabled": True, "path": "nonexistent/plans"})
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod.process_plans()

        assert result["success"] is True
        assert result["files_processed"] == 0
        assert "not found" in result.get("reason", "")

    def test_process_plans_no_files(self, monkeypatch, tmp_path):
        mod = _import_plans_processor(monkeypatch)
        plans_dir = tmp_path / "plans"
        plans_dir.mkdir()
        self._mock_config(
            monkeypatch,
            mod,
            {"enabled": True, "path": str(plans_dir), "supported_extensions": [".md"]},
        )
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod.process_plans()

        assert result["success"] is True
        assert result["files_processed"] == 0

    def test_process_plans_all_already_processed(self, monkeypatch, tmp_path):
        mod = _import_plans_processor(monkeypatch)
        plans_dir = tmp_path / "plans"
        plans_dir.mkdir()
        plan_file = plans_dir / "done.md"
        plan_file.write_text("Already processed plan content that is long enough.", encoding="utf-8")
        self._mock_config(
            monkeypatch,
            mod,
            {"enabled": True, "path": str(plans_dir), "supported_extensions": [".md"]},
        )
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)
        manifest_path = tmp_path / ".plans_processed.json"
        # The row must POSTDATE the file. Written as 2026-01-01 against a file
        # created moments ago, this fixture was the restore shape by accident —
        # a plan whose content is newer than the row claiming to have processed
        # it — and it only read as "already processed" while the check ignored
        # everything but the name.
        manifest_path.write_text(
            json.dumps({"done.md": {"processed_at": "2026-01-01T00:00:00", "content_sha256": _sha(plan_file)}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)

        result = mod.process_plans()

        assert result["success"] is True
        assert result["files_processed"] == 0
        assert "already processed" in result.get("reason", "")

    def test_process_plans_success(self, monkeypatch, tmp_path):
        mod = _import_plans_processor(monkeypatch)

        plans_dir = tmp_path / "plans"
        plans_dir.mkdir()
        plan_file = plans_dir / "new_plan.md"
        plan_file.write_text(
            "## Objective\nThis is the objective section with enough content to exceed thirty characters.\n"
            "## Steps\nThese are the steps of the plan with sufficient length for chunking.\n",
            encoding="utf-8",
        )

        self._mock_config(
            monkeypatch,
            mod,
            {
                "enabled": True,
                "path": str(plans_dir),
                "supported_extensions": [".md"],
                "collection_name": "test_plans",
            },
        )
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        manifest_path = tmp_path / ".plans_processed.json"
        manifest_path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)

        monkeypatch.setattr(
            mod,
            "_embed_texts",
            lambda texts, timeout=120: {"success": True, "embeddings": [[0.1, 0.2]] * len(texts)},
        )
        monkeypatch.setattr(
            mod,
            "_store_vectors",
            lambda emb, docs, metas, collection_name="flow_plans": {"success": True, "stored": len(docs)},
        )

        mock_jh = MagicMock()
        monkeypatch.setattr(mod, "json_handler", mock_jh)

        result = mod.process_plans()

        assert result["success"] is True
        assert result["files_processed"] == 1
        assert result["total_chunks"] >= 2
        mock_jh.log_operation.assert_called_once()

        updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "new_plan.md" in updated_manifest

    def test_process_plans_embed_fails(self, monkeypatch, tmp_path):
        mod = _import_plans_processor(monkeypatch)

        plans_dir = tmp_path / "plans"
        plans_dir.mkdir()
        plan_file = plans_dir / "plan.md"
        plan_file.write_text(
            "## Section\nThis section has enough content to pass the minimum threshold for chunking.\n",
            encoding="utf-8",
        )

        self._mock_config(
            monkeypatch,
            mod,
            {"enabled": True, "path": str(plans_dir), "supported_extensions": [".md"]},
        )
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        manifest_path = tmp_path / ".plans_processed.json"
        manifest_path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)

        monkeypatch.setattr(
            mod,
            "_embed_texts",
            lambda texts, timeout=120: {"success": False, "error": "GPU out of memory"},
        )

        mock_jh = MagicMock()
        monkeypatch.setattr(mod, "json_handler", mock_jh)

        result = mod.process_plans()

        assert result["success"] is False
        assert "errors" in result
        assert any("embed" in e for e in result["errors"])

    def test_process_plans_no_embeddings(self, monkeypatch, tmp_path):
        mod = _import_plans_processor(monkeypatch)

        plans_dir = tmp_path / "plans"
        plans_dir.mkdir()
        plan_file = plans_dir / "plan.md"
        plan_file.write_text(
            "## Section\nThis section has enough content to pass the minimum threshold for chunking.\n",
            encoding="utf-8",
        )

        self._mock_config(
            monkeypatch,
            mod,
            {"enabled": True, "path": str(plans_dir), "supported_extensions": [".md"]},
        )
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        manifest_path = tmp_path / ".plans_processed.json"
        manifest_path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)

        monkeypatch.setattr(
            mod,
            "_embed_texts",
            lambda texts, timeout=120: {"success": True, "embeddings": []},
        )

        mock_jh = MagicMock()
        monkeypatch.setattr(mod, "json_handler", mock_jh)

        result = mod.process_plans()

        assert "errors" in result
        assert any("no embeddings" in e for e in result["errors"])

    def test_process_plans_store_fails(self, monkeypatch, tmp_path):
        mod = _import_plans_processor(monkeypatch)

        plans_dir = tmp_path / "plans"
        plans_dir.mkdir()
        plan_file = plans_dir / "plan.md"
        plan_file.write_text(
            "## Section\nThis section has enough content to pass the minimum threshold for chunking.\n",
            encoding="utf-8",
        )

        self._mock_config(
            monkeypatch,
            mod,
            {"enabled": True, "path": str(plans_dir), "supported_extensions": [".md"]},
        )
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        manifest_path = tmp_path / ".plans_processed.json"
        manifest_path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)

        monkeypatch.setattr(
            mod,
            "_embed_texts",
            lambda texts, timeout=120: {"success": True, "embeddings": [[0.1, 0.2]] * len(texts)},
        )
        monkeypatch.setattr(
            mod,
            "_store_vectors",
            lambda emb, docs, metas, collection_name="flow_plans": {"success": False, "error": "disk full"},
        )

        mock_jh = MagicMock()
        monkeypatch.setattr(mod, "json_handler", mock_jh)

        result = mod.process_plans()

        assert result["success"] is False
        assert "errors" in result
        assert any("store" in e for e in result["errors"])

    def test_process_plans_empty_chunks(self, monkeypatch, tmp_path):
        mod = _import_plans_processor(monkeypatch)

        plans_dir = tmp_path / "plans"
        plans_dir.mkdir()
        plan_file = plans_dir / "tiny.md"
        plan_file.write_text("Hi.", encoding="utf-8")

        self._mock_config(
            monkeypatch,
            mod,
            {"enabled": True, "path": str(plans_dir), "supported_extensions": [".md"]},
        )
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        manifest_path = tmp_path / ".plans_processed.json"
        manifest_path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)

        mock_jh = MagicMock()
        monkeypatch.setattr(mod, "json_handler", mock_jh)

        result = mod.process_plans()

        assert result["success"] is True
        assert result["files_processed"] == 0

        updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "tiny.md" in updated_manifest
