# =================== AIPass ====================
# Name: test_plans_processor.py
# Description: Tests for the plans_processor handler — chunking, manifest, memory python and process_plans
# Version: 1.0.1
# Created: 2026-04-26
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/intake/plans_processor.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — the embed_subprocess.py child _embed_texts() spawns; sealed at subprocess
# seedgo: no-test-needed(covered_elsewhere) — chroma_subprocess.py's store: tests/test_chroma_source_match.py

import hashlib
import json
import subprocess
from unittest.mock import MagicMock, patch

from aipass.memory.apps.handlers.intake import plans_processor


def _sha(path):
    """The content hash the manifest records — spelled here so fixtures cannot drift from it."""
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


class TestChunkPlanText:
    """Test _chunk_plan_text function."""

    def test_chunks_by_markdown_headers(self, monkeypatch):
        mod = plans_processor
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
        assert result[0]["text"].startswith("## Introduction\n"), result[0]["text"][:40]

    def test_flushes_last_section(self, monkeypatch):
        mod = plans_processor
        text = (
            "## Header One\n"
            "Content for header one, long enough to pass thirty characters.\n"
            "Trailing content without a following header, also long enough to be a real section."
        )

        result = mod._chunk_plan_text(text, "plan.md")

        assert len(result) == 1
        assert result[0]["section"] == "Header One"
        assert "Trailing content" in result[0]["text"]

    def test_skips_short_sections(self, monkeypatch):
        mod = plans_processor
        text = (
            "## Short\n"
            "Tiny.\n"
            "## Long Section\n"
            "This section has enough content to pass the thirty-character minimum requirement.\n"
        )

        result = mod._chunk_plan_text(text, "plan.md")

        assert len(result) == 1
        assert result[0]["section"] == "Long Section"

    def test_fallback_to_size_chunking(self, monkeypatch):
        mod = plans_processor
        # Every section is under 30 chars, so the header pass yields nothing and the size fallback runs.
        num_sections = (mod.MAX_CHUNK_CHARS // 8) + 50
        header_lines = []
        for i in range(num_sections):
            header_lines.append(f"## H{i:04d}")
            header_lines.append("x")
        text = "\n".join(header_lines)
        assert len(text) > mod.MAX_CHUNK_CHARS

        result = mod._chunk_plan_text(text, "plan.md")

        assert len(result) >= 2
        assert result[0]["section"].startswith("plan.md_part")

    def test_small_text_no_headers(self, monkeypatch):
        mod = plans_processor
        text = "This is a plain text plan without any markdown headers at all."

        result = mod._chunk_plan_text(text, "plan.md")

        assert len(result) == 1
        assert result[0]["section"] == "plan.md"
        assert result[0]["text"] == text

    def test_tiny_text_skipped(self, monkeypatch):
        mod = plans_processor
        text = "Short."

        result = mod._chunk_plan_text(text, "plan.md")

        assert result == []

    def test_splits_oversized_chunks(self, monkeypatch):
        mod = plans_processor
        big_body = "X" * (mod.MAX_CHUNK_CHARS * 3)
        text = f"## Big Section\n{big_body}\n"

        result = mod._chunk_plan_text(text, "plan.md")

        assert [chunk["section"] for chunk in result] == [
            "Big Section_part0",
            "Big Section_part1",
            "Big Section_part2",
        ]

    def test_empty_text(self, monkeypatch):
        mod = plans_processor

        result = mod._chunk_plan_text("", "plan.md")

        assert result == []


class TestUnfilledPlaceholderSectionsAreNotVectorized:
    """A section whose every content line is a bracketed template prompt is not vectorized.

    Chunk-level and narrow on purpose: one line of real prose keeps the chunk.
    """

    def test_an_unfilled_section_is_dropped(self, monkeypatch):
        mod = plans_processor
        text = "### Goal\n[What do you want to achieve? Specific end state.]\n"
        assert mod._chunk_plan_text(text, "p.md") == []

    def test_a_trailing_horizontal_rule_does_not_save_it(self, monkeypatch):
        """The live shape: the two biggest blocks both end in a `---` separator."""
        mod = plans_processor
        text = "## Notes\n\n[Working notes, issues encountered, decisions made]\n\n---\n"
        assert mod._chunk_plan_text(text, "p.md") == []

    def test_one_line_of_real_prose_keeps_the_whole_section(self, monkeypatch):
        mod = plans_processor
        text = (
            "### Goal\n"
            "[What do you want to achieve? Specific end state.]\n"
            "Actually we want the rollover valve to stop refusing today's entries.\n"
        )
        chunks = mod._chunk_plan_text(text, "p.md")
        assert len(chunks) == 1
        assert "rollover valve" in chunks[0]["text"]

    def test_a_filled_section_is_untouched(self, monkeypatch):
        mod = plans_processor
        text = "## Summary\n\nThe declared-roots anchor shipped and the fleet reads 28 citizens.\n"
        chunks = mod._chunk_plan_text(text, "p.md")
        assert len(chunks) == 1

    def test_a_section_that_is_only_a_rule_or_blank_is_not_called_a_placeholder(self, monkeypatch):
        """Absence of content is not an unfilled prompt; the length gate, not the placeholder rule, drops it."""
        mod = plans_processor
        assert mod._is_placeholder_only("## Notes\n\n---\n") is False
        assert mod._is_placeholder_only("## Notes\n\n") is False

    def test_markdown_link_syntax_is_not_a_placeholder(self, monkeypatch):
        """`[text](url)` opens with a bracket and is real content."""
        mod = plans_processor
        assert mod._is_placeholder_only("## Refs\n[the seedgo audit](./audit.md)\n") is False


class TestManifest:
    """Test _load_manifest and _save_manifest."""

    def test_load_manifest_file_exists(self, monkeypatch, tmp_path):
        mod = plans_processor
        manifest_path = tmp_path / "config" / ".plans_processed.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_data = {"plan1.md": "2026-01-01T00:00:00", "plan2.md": "2026-01-02T00:00:00"}
        manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)

        result = mod._load_manifest()

        assert result == manifest_data

    def test_load_manifest_file_missing(self, monkeypatch, tmp_path):
        mod = plans_processor
        manifest_path = tmp_path / "config" / ".plans_processed.json"
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)

        result = mod._load_manifest()

        assert result == {}

    def test_save_manifest_creates_parent_dirs(self, monkeypatch, tmp_path):
        mod = plans_processor
        manifest_path = tmp_path / "deep" / "nested" / "config" / ".plans_processed.json"
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)
        data = {"file.md": "2026-04-26T12:00:00"}

        mod._save_manifest(data)

        assert manifest_path.exists()
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert loaded == data


class TestEmbedTexts:
    """Test _embed_texts subprocess wrapper."""

    def test_embed_texts_success(self, monkeypatch):
        mod = plans_processor
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
        mod = plans_processor
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "model not found"

        with patch.object(subprocess, "run", return_value=mock_result):
            result = mod._embed_texts(["hello"])

        assert result["success"] is False
        assert "model not found" in result["error"]

    def test_an_embedder_refusal_names_its_cause(self, monkeypatch, tmp_path):
        """The embedder's real refusal: exit 1, its reason as JSON on stdout, stderr empty."""
        plans = tmp_path / "plans"
        plans.mkdir()
        (plans / "FPLAN-0001_probe_2026-10-03.md").write_text(
            "## Summary\n\nthe probe plan, long enough for the chunker to keep its section\n", encoding="utf-8"
        )
        monkeypatch.setattr(plans_processor, "_PROCESSED_MANIFEST", tmp_path / ".plans_processed.json")
        monkeypatch.setattr(plans_processor, "_find_repo_root", lambda: tmp_path)
        config = MagicMock()
        config.section.return_value = {
            "enabled": True,
            "path": str(plans),
            "supported_extensions": [".md"],
            "collection_name": "flow_plans",
        }
        monkeypatch.setattr(plans_processor, "config_loader", config)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = json.dumps({"success": False, "error": "inhomogeneous shape"})
        mock_result.stderr = ""

        with patch.object(subprocess, "run", return_value=mock_result):
            result = plans_processor.process_plans()

        assert result["errors"] == [
            "FPLAN-0001_probe_2026-10-03.md: embed error: Embedding failed (exit 1): inhomogeneous shape"
        ]

    def test_embed_texts_exception(self, monkeypatch):
        mod = plans_processor

        with patch.object(subprocess, "run", side_effect=OSError("no such binary")):
            result = mod._embed_texts(["hello"])

        assert result["success"] is False
        assert "no such binary" in result["error"]


class TestStoreVectors:
    """Test _store_vectors subprocess wrapper."""

    def test_store_vectors_success(self, monkeypatch):
        mod = plans_processor
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
        mod = plans_processor
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
        mod = plans_processor

        with patch.object(subprocess, "run", side_effect=TimeoutError("timed out")):
            result = mod._store_vectors(
                embeddings=[[0.1]],
                documents=["doc"],
                metadatas=[{}],
            )

        assert result["success"] is False
        assert "timed out" in result["error"]


class TestFindRepoRoot:
    """This lane no longer walks — it delegates to ``handlers/repo_root.py`` (the walk is pinned there)."""

    def test_it_delegates_instead_of_walking_itself(self, monkeypatch, tmp_path):
        """A private walk here is how the first cure missed nine other files."""
        mod = plans_processor
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
        mod = plans_processor
        monkeypatch.chdir(tmp_path)

        assert mod._find_repo_root() != tmp_path


class TestTheManifestKeysOnContentNotOnlyOnAName:
    """A restored plan is re-vectorized: the manifest keys on content, not only on the name."""

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
        mod = plans_processor
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

        # Restored with different content, same name.
        plan.write_text("## Summary\n\nthe FINAL text, written after the restore\n", encoding="utf-8")
        seen.clear()
        again = mod.process_plans()

        assert again["files_processed"] == 1, "a restored plan's final content was never vectorized"
        assert seen == [plan.name]

    def test_an_unreadable_manifest_refuses_the_run_and_keeps_its_bytes(self, monkeypatch, tmp_path):
        """An unreadable manifest refuses the run: no plan is embedded and the manifest is not overwritten."""
        mod = plans_processor
        plans = tmp_path / "plans"
        plans.mkdir()
        (plans / "FPLAN-0001_x.md").write_text("## Summary\n\nsome real text\n", encoding="utf-8")
        manifest_path = tmp_path / ".plans_processed.json"
        manifest_path.write_text("not valid json {{{{", encoding="utf-8")
        before = manifest_path.read_bytes()
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)
        self._mock_config(monkeypatch, mod, plans)
        seen = []
        self._stub_pipeline(monkeypatch, mod, seen)

        result = mod.process_plans()

        assert result["success"] is False
        assert str(manifest_path) in result["error"]
        assert seen == []
        assert manifest_path.read_bytes() == before

    def test_a_manifest_whose_root_is_a_list_refuses_the_run_and_keeps_its_bytes(self, monkeypatch, tmp_path):
        """Valid JSON with a list at the root is refused, not read as a manifest."""
        mod = plans_processor
        plans = tmp_path / "plans"
        plans.mkdir()
        (plans / "FPLAN-0001_x.md").write_text("## Summary\n\n" + "some real text " * 30 + "\n", encoding="utf-8")
        manifest_path = tmp_path / ".plans_processed.json"
        manifest_path.write_text("[]", encoding="utf-8")
        before = manifest_path.read_bytes()
        monkeypatch.setattr(mod, "_PROCESSED_MANIFEST", manifest_path)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)
        self._mock_config(monkeypatch, mod, plans)
        seen = []
        monkeypatch.setattr(
            mod, "_embed_texts", lambda texts, timeout=120: {"success": True, "embeddings": [[0.1]] * len(texts)}
        )
        monkeypatch.setattr(
            mod,
            "_store_vectors",
            lambda emb, texts, metas, coll: seen.append(metas[0]["source_file"]) or {"success": False, "error": "x"},
        )

        result = mod.process_plans()

        assert result == {
            "success": False,
            "error": f"Unreadable processed manifest {manifest_path}: root is not an object",
        }
        assert seen == []
        assert manifest_path.read_bytes() == before

    def test_a_newly_processed_plan_records_its_content_not_just_a_time(self, monkeypatch, tmp_path):
        """A new row records the content hash; the tolerant legacy read path would hide a bare timestamp."""
        mod = plans_processor
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
        """A legacy bare-timestamp row is backfilled with its hash, not re-embedded."""
        mod = plans_processor
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
        """A legacy row older than its file reprocesses: that is what a restore looks like."""
        mod = plans_processor
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
        """A row whose file is gone is kept: pruning it would re-vectorize the plan in full on its return."""
        mod = plans_processor
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
        mod = plans_processor
        self._mock_config(monkeypatch, mod, {"enabled": True, "path": ".backup/processed_plans"})
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod.process_plans()

        assert result["success"] is True
        assert result["files_processed"] == 0
        assert "not found" in result.get("reason", "")

    def test_process_plans_disabled(self, monkeypatch, tmp_path):
        mod = plans_processor
        self._mock_config(monkeypatch, mod, {"enabled": False})

        result = mod.process_plans()

        assert result["success"] is True
        assert result["skipped"] is True
        assert "disabled" in result["reason"]

    def test_process_plans_dir_not_found(self, monkeypatch, tmp_path):
        mod = plans_processor
        self._mock_config(monkeypatch, mod, {"enabled": True, "path": "nonexistent/plans"})
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod.process_plans()

        assert result["success"] is True
        assert result["files_processed"] == 0
        assert "not found" in result.get("reason", "")

    def test_process_plans_no_files(self, monkeypatch, tmp_path):
        mod = plans_processor
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
        mod = plans_processor
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
        # The row carries the content hash: a dated-only row older than the file is the restore shape.
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
        mod = plans_processor

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
        mod = plans_processor

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
        mod = plans_processor

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
        mod = plans_processor

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
        mod = plans_processor

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
