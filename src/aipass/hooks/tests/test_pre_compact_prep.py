# =================== AIPass ====================
# Name: test_pre_compact_prep.py
# Version: 1.0.0
# Description: Tests for pre_compact_prep lifecycle handler
# Branch: hooks
# Created: 2026-07-20
# Modified: 2026-07-20
# =============================================

"""Tests for handlers/lifecycle/pre_compact_prep.py."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

MODULE = "aipass.hooks.apps.handlers.lifecycle.pre_compact_prep"


def _make_branch(tmp_path, with_local=True, sessions=None):
    branch_dir = tmp_path / "src" / "aipass" / "widget"
    branch_dir.mkdir(parents=True)
    if with_local:
        trinity = branch_dir / ".trinity"
        trinity.mkdir()
        (trinity / "local.json").write_text(
            json.dumps({"sessions": sessions if sessions is not None else []}), encoding="utf-8"
        )
    return branch_dir


class TestHandle:
    def test_stamps_session_entry_and_returns_stdout(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import handle

        branch_dir = _make_branch(tmp_path, sessions=[{"number": 3, "date": "2026-01-01", "summary": "old"}])

        with patch(f"{MODULE}._find_repo_root", return_value=None):
            result = handle({"cwd": str(branch_dir)})

        assert result["exit_code"] == 0
        assert "AUTO-COMPACT SNAPSHOT" in result["stdout"]
        assert result["sound"] == "pre compact prep"

        data = json.loads((branch_dir / ".trinity" / "local.json").read_text(encoding="utf-8"))
        assert len(data["sessions"]) == 2
        newest = data["sessions"][0]
        assert newest["number"] == 4
        assert newest["status"] == "auto-compact"
        assert "AUTO-COMPACT SNAPSHOT" in newest["summary"]

    def test_prepends_number_as_max_plus_one(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import handle

        branch_dir = _make_branch(
            tmp_path,
            sessions=[
                {"number": 10, "date": "2026-01-01", "summary": "a"},
                {"number": 7, "date": "2026-01-01", "summary": "b"},
            ],
        )

        with patch(f"{MODULE}._find_repo_root", return_value=None):
            handle({"cwd": str(branch_dir)})

        data = json.loads((branch_dir / ".trinity" / "local.json").read_text(encoding="utf-8"))
        assert data["sessions"][0]["number"] == 11

    def test_no_branch_dir_resolved_is_a_noop(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import handle

        result = handle({"cwd": str(tmp_path)})
        assert result == {"stdout": "", "exit_code": 0}

    def test_missing_local_json_skips_write_but_still_returns_snapshot(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import handle

        branch_dir = _make_branch(tmp_path, with_local=False)

        with patch(f"{MODULE}._find_repo_root", return_value=None):
            result = handle({"cwd": str(branch_dir)})

        assert result["exit_code"] == 0
        assert "AUTO-COMPACT SNAPSHOT" in result["stdout"]

    def test_malformed_local_json_never_raises_and_is_untouched(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import handle

        branch_dir = tmp_path / "src" / "aipass" / "widget"
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)
        local_path = trinity / "local.json"
        local_path.write_text("{not valid json", encoding="utf-8")

        with patch(f"{MODULE}._find_repo_root", return_value=None):
            result = handle({"cwd": str(branch_dir)})

        assert result["exit_code"] == 0
        assert local_path.read_text(encoding="utf-8") == "{not valid json"

    def test_sessions_not_a_list_skips_write(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import handle

        branch_dir = tmp_path / "src" / "aipass" / "widget"
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)
        local_path = trinity / "local.json"
        local_path.write_text(json.dumps({"sessions": "not-a-list"}), encoding="utf-8")

        with patch(f"{MODULE}._find_repo_root", return_value=None):
            result = handle({"cwd": str(branch_dir)})

        assert result["exit_code"] == 0
        data = json.loads(local_path.read_text(encoding="utf-8"))
        assert data["sessions"] == "not-a-list"

    def test_summary_truncated_to_cap(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import handle

        branch_dir = _make_branch(tmp_path, sessions=[])

        with patch(f"{MODULE}._find_repo_root", return_value=None):
            with patch(f"{MODULE}._build_snapshot", return_value="X" * 500):
                handle({"cwd": str(branch_dir)})

        data = json.loads((branch_dir / ".trinity" / "local.json").read_text(encoding="utf-8"))
        assert len(data["sessions"][0]["summary"]) == 300

    def test_never_raises_on_unexpected_error(self):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import handle

        with patch("aipass.hooks.apps.modules.context_window.find_branch_dir", side_effect=RuntimeError("boom")):
            result = handle({"cwd": "/tmp"})

        assert result == {"stdout": "", "exit_code": 0}


class TestCountOpenPlans:
    def test_counts_only_matching_location(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import _count_open_plans

        branch_dir = tmp_path / "src" / "aipass" / "widget"
        branch_dir.mkdir(parents=True)

        fake_plans = [
            ("0001", {"location": str(branch_dir.resolve())}),
            ("0002", {"location": "/somewhere/else"}),
            ("0003", {"location": str(branch_dir.resolve())}),
        ]

        with patch("aipass.flow.apps.handlers.plan.get_open_plans.get_open_plans", return_value=fake_plans):
            count = _count_open_plans(branch_dir)

        assert count == 2

    def test_returns_none_on_import_failure(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import _count_open_plans

        branch_dir = tmp_path / "src" / "aipass" / "widget"
        branch_dir.mkdir(parents=True)

        with patch("aipass.flow.apps.handlers.plan.get_open_plans.get_open_plans", side_effect=RuntimeError("no")):
            count = _count_open_plans(branch_dir)

        assert count is None


class TestCountActiveDispatchLocks:
    def test_counts_lock_files_across_branches(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import _count_active_dispatch_locks

        (tmp_path / "src" / "aipass" / "a" / ".ai_mail.local").mkdir(parents=True)
        (tmp_path / "src" / "aipass" / "a" / ".ai_mail.local" / ".dispatch.lock").write_text("{}")
        (tmp_path / "src" / "aipass" / "b" / ".ai_mail.local").mkdir(parents=True)

        registry = {
            "branches": [
                {"name": "A", "path": "src/aipass/a"},
                {"name": "B", "path": "src/aipass/b"},
            ]
        }
        (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")

        count = _count_active_dispatch_locks(tmp_path)
        assert count == 1

    def test_returns_none_without_repo_root(self):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import _count_active_dispatch_locks

        assert _count_active_dispatch_locks(None) is None


class TestInboxUnread:
    def test_reads_unread_count(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import _inbox_unread

        branch_dir = tmp_path / "widget"
        mail_dir = branch_dir / ".ai_mail.local"
        mail_dir.mkdir(parents=True)
        (mail_dir / "inbox.json").write_text(json.dumps({"unread_count": 4}), encoding="utf-8")

        assert _inbox_unread(branch_dir) == 4

    def test_returns_none_when_missing(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import _inbox_unread

        assert _inbox_unread(tmp_path / "widget") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestSummaryCapUsesSupportedDoor:
    """@memory owns the cap. Reading their config file by hardcoded path broke
    silently if they moved it AND ignored per_branch overrides entirely."""

    def test_reads_through_load_entry_limits(self):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import _summary_cap

        el = MagicMock()
        el.load_entry_limits.return_value = {"entry_types": {"sessions": {"max_chars": 512}}}
        with patch("importlib.import_module", return_value=el):
            assert _summary_cap("widget") == 512
        el.load_entry_limits.assert_called_once_with("widget")

    def test_passes_the_branch_so_per_branch_overrides_apply(self):
        """The hardcoded read took the global default and would have stamped one
        branch against another branch's cap."""
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import _summary_cap

        el = MagicMock()
        el.load_entry_limits.side_effect = lambda b: {
            "entry_types": {"sessions": {"max_chars": 999 if b == "special" else 300}}
        }
        with patch("importlib.import_module", return_value=el):
            assert _summary_cap("special") == 999
            assert _summary_cap("ordinary") == 300

    def test_falls_back_when_memory_is_unavailable(self):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import _DEFAULT_SUMMARY_CAP, _summary_cap

        with patch("importlib.import_module", side_effect=ImportError("no memory")):
            assert _summary_cap("widget") == _DEFAULT_SUMMARY_CAP

    def test_falls_back_on_reshaped_config(self):
        from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import _DEFAULT_SUMMARY_CAP, _summary_cap

        el = MagicMock()
        el.load_entry_limits.return_value = {"entry_types": {}}
        with patch("importlib.import_module", return_value=el):
            assert _summary_cap("widget") == _DEFAULT_SUMMARY_CAP

    def test_no_hardcoded_memory_config_path_survives(self):
        """Source guard on CODE, not prose.

        KNOWN TRAP: a plain substring guard fires on the docstring that explains
        the fix, so this walks the AST and inspects only real string literals —
        docstrings excluded. Same lesson as the json_handler guard exempting
        os.fdopen: a guard that trips on its own explanation gets deleted.
        """
        import ast

        from aipass.hooks.apps.handlers.lifecycle import pre_compact_prep

        tree = ast.parse(Path(pre_compact_prep.__file__).read_text(encoding="utf-8"))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc is not None:
                    docstrings.add(doc)

        literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        code_literals = [v for v in literals if v not in docstrings]

        for forbidden in ("memory.config.json", "memory_json", "custom_config"):
            assert not [v for v in code_literals if forbidden in v], f"{forbidden} is back in code"

    def test_guard_catches_a_reintroduced_hardcoded_path(self):
        """MUTATION-CHECK: prove the AST guard still bites when the path returns."""
        import ast

        mutated = ast.parse(
            '''
"""memory_json docstring mentioning the path is fine."""
def f(root):
    return root / "src" / "aipass" / "memory" / "memory_json" / "custom_config" / "memory.config.json"
'''
        )
        docstrings = {ast.get_docstring(mutated, clean=False)}
        code_literals = [
            n.value
            for n in ast.walk(mutated)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value not in docstrings
        ]
        assert [v for v in code_literals if "memory_json" in v]
