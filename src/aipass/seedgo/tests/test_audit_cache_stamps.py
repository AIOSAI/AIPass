# =================== META ====================
# Name: test_audit_cache_stamps.py
# Description: The audit cache's invalidation stamps — what busts a branch entry and what does not
# Version: 1.0.0
# Created: 2026-09-21
# Modified: 2026-09-21
# =============================================

"""Tests for incremental_cache's stamp functions — the cache's whole invalidation surface.

Split out of test_incremental_audit.py on 2026-09-21: that file tests
audit_branch_incremental's BEHAVIOUR (what re-runs), these test the stamps it
decides with. Nothing here loads a branch or runs a checker, so nothing here
needs that file's infrastructure mocks.
"""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — that hashlib.sha1 and json.dumps are deterministic
# seedgo: no-test-needed(behaviour) — what a moved stamp costs a run; test_incremental_audit.py
# seedgo: no-test-needed(constant) — CACHE_VERSION's literal value; the bust it causes is behaviour

from aipass.seedgo.apps.handlers.audit import incremental_cache


class TestStamps:
    def test_pack_stamp_no_longer_moves_when_a_checker_is_edited(self, tmp_path):
        """REVERSED 2026-09-21. This asserted the opposite until the per-checker
        stamp landed, and the old assertion was the cost: one comment line in
        one checker discarded every branch's whole entry, 1261.3s of fleet
        re-scan measured against 9.7s for the same run with nothing touched.
        A checker's own stamp carries it now — see compute_checker_stamps.
        """
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
        """A bypass/ edit must re-scan every branch, not just seedgo's own tree.

        FPLAN-0382 changed is_bypassed's matching semantics and nothing in the
        stamp noticed: all 17 branches kept serving results computed under the
        old rules, reading 17/17 green while uncached CI showed 99%.
        """
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
        """Suppressing the rules is an input change, exactly like editing them.

        compute_bypass_stamp() fingerprints the bypass.json FILE, which is
        byte-identical across a normal and a --no-bypass run — so the stamp
        itself has to carry whether those rules were applied.
        """
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
