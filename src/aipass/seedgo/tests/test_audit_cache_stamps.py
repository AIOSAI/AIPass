# =================== META ====================
# Name: test_audit_cache_stamps.py
# Description: The audit cache's invalidation stamps and what its branch line reports
# Version: 1.1.1
# Created: 2026-09-21
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/audit/incremental_cache.py's stamp functions."""

# These test the stamps audit_branch_incremental decides with, not what re-runs; nothing here loads a branch.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — that hashlib.sha1 and json.dumps are deterministic
# seedgo: no-test-needed(behaviour) — what a moved stamp costs a run; test_incremental_audit.py
# seedgo: no-test-needed(constant) — CACHE_VERSION's literal value; the bust it causes is behaviour

from aipass.seedgo.apps.handlers.audit import audit_display, incremental_cache


class TestStamps:
    def test_pack_stamp_no_longer_moves_when_a_checker_is_edited(self, tmp_path):
        """REVERSED 2026-09-21. This asserted the opposite until the per-checker
        stamp landed: one comment line in one checker discarded every branch's whole entry."""
        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        checker = pack_dir / "naming_check.py"
        checker.write_text("def check_module(p): return {}\n", encoding="utf-8")
        stamp1 = incremental_cache.compute_pack_stamp(pack_dir)
        checker.write_text("def check_module(p): return {'x': 1}\n", encoding="utf-8")
        stamp2 = incremental_cache.compute_pack_stamp(pack_dir)
        assert stamp1 == stamp2

    def test_pack_stamp_still_moves_when_a_shared_helper_is_edited(self, tmp_path):
        """The other half of the split: what every checker answers through still busts all."""
        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        helper = pack_dir / "applicability.py"
        helper.write_text("def applies_to_file(c, f): return True\n", encoding="utf-8")
        stamp1 = incremental_cache.compute_pack_stamp(pack_dir)
        helper.write_text("def applies_to_file(c, f): return False\n", encoding="utf-8")
        stamp2 = incremental_cache.compute_pack_stamp(pack_dir)
        assert stamp1 != stamp2

    def test_pack_stamp_ignores_a_prose_page_and_a_content_module(self, tmp_path):
        """Both are read by standards_query, never by the audit — no output carries their text."""
        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        (pack_dir / "naming.md").write_text("# Naming\n", encoding="utf-8")
        (pack_dir / "naming_content.py").write_text("CONTENT = 'old'\n", encoding="utf-8")
        stamp1 = incremental_cache.compute_pack_stamp(pack_dir)
        (pack_dir / "naming.md").write_text("# Naming, reworded\n", encoding="utf-8")
        (pack_dir / "naming_content.py").write_text("CONTENT = 'new'\n", encoding="utf-8")
        stamp2 = incremental_cache.compute_pack_stamp(pack_dir)
        assert stamp1 == stamp2

    def test_a_pack_asset_that_is_neither_still_moves_the_stamp(self, tmp_path):
        """Over-exclusion guard: only .md and *_content.py drop out, not every non-checker."""
        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        (pack_dir / "diagnostics.json").write_text('{"strict": false}\n', encoding="utf-8")
        stamp1 = incremental_cache.compute_pack_stamp(pack_dir)
        (pack_dir / "diagnostics.json").write_text('{"strict": true}\n', encoding="utf-8")
        stamp2 = incremental_cache.compute_pack_stamp(pack_dir)
        assert stamp1 != stamp2

    def test_bypass_stamp_changes_when_seedgoignore_added(self, tmp_path):
        branch_path = tmp_path / "branch"
        branch_path.mkdir()
        stamp1 = incremental_cache.compute_bypass_stamp(branch_path)
        (branch_path / ".seedgoignore").write_text("tools/\n", encoding="utf-8")
        stamp2 = incremental_cache.compute_bypass_stamp(branch_path)
        assert stamp1 != stamp2

    def test_machinery_stamp_changes_when_bypass_package_edited(self, tmp_path, monkeypatch):
        """A bypass/ edit must re-scan every branch, not just seedgo's own tree."""
        machinery = tmp_path / "bypass"
        machinery.mkdir()
        utils = machinery / "utils.py"
        utils.write_text("def is_bypassed(): ...\n", encoding="utf-8")
        monkeypatch.setattr(incremental_cache, "MACHINERY_DIRS", (machinery,))

        stamp1 = incremental_cache.compute_machinery_stamp()
        utils.write_text("def is_bypassed(): ...  # comment only\n", encoding="utf-8")
        stamp2 = incremental_cache.compute_machinery_stamp()
        assert stamp1 != stamp2

    def test_current_stamp_includes_the_machinery_stamp(self, tmp_path, monkeypatch):
        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        branch_path = tmp_path / "branch"
        branch_path.mkdir()
        machinery = tmp_path / "bypass"
        machinery.mkdir()
        (machinery / "utils.py").write_text("x = 1\n", encoding="utf-8")
        monkeypatch.setattr(incremental_cache, "MACHINERY_DIRS", (machinery,))

        stamp1 = incremental_cache.current_stamp(branch_path, pack_dir)
        # Size must change, not just content: the fingerprint is (mtime_ns, size)
        # and two writes inside one filesystem timestamp tick are indistinguishable.
        (machinery / "utils.py").write_text("x = 1  # changed\n", encoding="utf-8")
        assert incremental_cache.current_stamp(branch_path, pack_dir) != stamp1

    def test_current_stamp_differs_when_bypasses_are_disabled(self, tmp_path):
        """Suppressing the rules is an input change, exactly like editing them."""
        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        branch_path = tmp_path / "branch"
        branch_path.mkdir()

        normal = incremental_cache.current_stamp(branch_path, pack_dir)
        no_bypass = incremental_cache.current_stamp(branch_path, pack_dir, no_bypass=True)
        assert normal != no_bypass

    def test_current_stamp_stable_when_nothing_changes(self, tmp_path):
        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        branch_path = tmp_path / "branch"
        branch_path.mkdir()
        stamp1 = incremental_cache.current_stamp(branch_path, pack_dir)
        stamp2 = incremental_cache.current_stamp(branch_path, pack_dir)
        assert stamp1 == stamp2


class TestCheckerStamps:
    def test_the_keys_are_the_names_discover_checkers_uses(self, tmp_path):
        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        (pack_dir / "naming_check.py").write_text("def check_module(p): return {}\n", encoding="utf-8")
        (pack_dir / "imports_check.py").write_text("def check_module(p): return {}\n", encoding="utf-8")

        assert set(incremental_cache.compute_checker_stamps(pack_dir)) == {"naming", "imports"}

    def test_only_the_edited_checkers_stamp_moves(self, tmp_path):
        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        (pack_dir / "naming_check.py").write_text("def check_module(p): return {}\n", encoding="utf-8")
        (pack_dir / "imports_check.py").write_text("def check_module(p): return {}\n", encoding="utf-8")
        before = incremental_cache.compute_checker_stamps(pack_dir)
        (pack_dir / "naming_check.py").write_text("def check_module(p): return {'x': 1}\n", encoding="utf-8")
        after = incremental_cache.compute_checker_stamps(pack_dir)

        assert incremental_cache.stale_checkers(before, after) == {"naming"}

    def test_a_missing_pack_stamps_nothing(self, tmp_path):
        assert incremental_cache.compute_checker_stamps(tmp_path / "gone") == {}

    def test_stale_checkers_names_an_addition_and_a_removal(self):
        assert incremental_cache.stale_checkers({"gone": "a", "kept": "b"}, {"kept": "b", "new": "c"}) == {
            "gone",
            "new",
        }

    def test_nothing_is_stale_when_the_pack_stands_still(self):
        assert incremental_cache.stale_checkers({"naming": "a"}, {"naming": "a"}) == set()


class TestTheBranchLineSaysWhatWasReRun:
    """A partial hit used to print exactly like a cold scan."""

    def _partial(self, **over):
        base = {"checkers_total": 53, "checkers_cached": 51, "reran": ["imports", "named_encoding"]}
        base.update({"files_total": 101, "files_cached": 101})
        base.update(over)
        return {"_cache_hit": False, "_cache_partial": base}

    def test_a_full_hit_still_reads_cached(self):
        assert audit_display.cache_tag({"_cache_hit": True}) == " [dim](cached)[/dim]"

    def test_a_cold_run_says_nothing(self):
        """No cache was served, so claiming a fraction of one would be a lie."""
        assert audit_display.cache_tag({"_cache_hit": False}) == ""

    def test_a_stale_checker_run_names_what_it_re_ran(self):
        tag = audit_display.cache_tag(self._partial())

        assert tag == " [dim](cached: 51 of 53 checkers; re-ran imports, named_encoding)[/dim]"

    def test_a_changed_file_run_counts_the_files(self):
        tag = audit_display.cache_tag(self._partial(checkers_cached=53, reran=[], files_cached=98))

        assert tag == " [dim](cached: 98 of 101 files)[/dim]"

    def test_both_clauses_appear_when_both_are_true(self):
        tag = audit_display.cache_tag(self._partial(files_cached=98))

        assert "51 of 53 checkers, 98 of 101 files" in tag
        assert "re-ran imports, named_encoding" in tag

    def test_a_long_re_run_list_is_capped_and_says_so(self):
        """A readable line beats a complete one; the count keeps it honest."""
        tag = audit_display.cache_tag(self._partial(checkers_cached=46, reran=list("abcdefg")))

        assert "re-ran a, b, c, d (+3 more)" in tag

    def test_nothing_stale_and_nothing_moved_reads_as_nothing(self):
        """Belt and braces: a partial record with no actual re-run must not print."""
        assert audit_display.cache_tag(self._partial(checkers_cached=53, reran=[])) == ""
