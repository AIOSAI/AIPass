# =================== AIPass ====================
# Name: test_pre_compact_prep.py
# Version: 1.1.0
# Description: Tests for pre_compact_prep lifecycle handler
# Branch: hooks
# Created: 2026-07-20
# Modified: 2026-10-25
# =============================================

"""Tests for apps/handlers/lifecycle/pre_compact_prep.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — _git_snapshot's three git subprocess.run calls; their text is git's own
# seedgo: no-test-needed(generated) — the logger.info line on each read failure; its text is the exception's own
# seedgo: no-test-needed(constant) — _DEFAULT_SUMMARY_CAP's value, asserted only as the fallback it is

import contextlib
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aipass.hooks.apps.handlers.lifecycle import pre_compact_prep
from aipass.hooks.apps.handlers.lifecycle.pre_compact_prep import (
    handle,
)
from aipass.hooks.apps.modules import context_window

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

    def test_a_codex_rollout_stamps_its_fill_over_its_window(self, tmp_path, monkeypatch):
        monkeypatch.setattr(context_window, "codex_config_path", lambda: tmp_path / "codex_config.toml")
        branch_dir = _make_branch(tmp_path)
        rollout = tmp_path / "rollout.jsonl"
        meta = {"type": "session_meta", "payload": {"id": "s", "source": "cli"}}
        info = {"last_token_usage": {"input_tokens": 21_545, "output_tokens": 568, "total_tokens": 22_113}}
        info["model_context_window"] = 475_000
        count = {"type": "event_msg", "payload": {"type": "token_count", "info": info}}
        rollout.write_text(json.dumps(meta) + "\n" + json.dumps(count) + "\n", encoding="utf-8")

        with patch(f"{MODULE}._find_repo_root", return_value=None):
            result = handle({"cwd": str(branch_dir), "transcript_path": str(rollout), "provider": "codex"})

        assert "context ~22k/475k (5%)" in result["stdout"]

    def test_prepends_number_as_max_plus_one(self, tmp_path):

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

    def test_a_write_that_does_not_land_leaves_local_json_whole(self, tmp_path):
        """Staged and renamed: a failed write leaves the old file, never a torn one rollover then reads."""
        branch_dir = _make_branch(tmp_path, sessions=[{"number": 3, "date": "2026-01-01", "summary": "old"}])
        local = branch_dir / ".trinity" / "local.json"
        before = local.read_text(encoding="utf-8")
        with (
            patch(f"{MODULE}._find_repo_root", return_value=None),
            patch("aipass.hooks.apps.handlers.json.files._replace_with_retry", side_effect=OSError("disk full")),
        ):
            handle({"cwd": str(branch_dir)})
        assert local.read_text(encoding="utf-8") == before
        assert [p.name for p in local.parent.iterdir()] == ["local.json"]

    def test_no_branch_dir_resolved_is_a_noop(self, tmp_path):

        result = handle({"cwd": str(tmp_path)})
        assert result == {"stdout": "", "exit_code": 0}

    def test_missing_local_json_skips_write_but_still_returns_snapshot(self, tmp_path):

        branch_dir = _make_branch(tmp_path, with_local=False)

        with patch(f"{MODULE}._find_repo_root", return_value=None):
            result = handle({"cwd": str(branch_dir)})

        assert result["exit_code"] == 0
        assert "AUTO-COMPACT SNAPSHOT" in result["stdout"]

    def test_malformed_local_json_never_raises_and_is_untouched(self, tmp_path):

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

        branch_dir = _make_branch(tmp_path, sessions=[])

        with patch(f"{MODULE}._find_repo_root", return_value=None):
            with patch(f"{MODULE}._build_snapshot", return_value="X" * 500):
                handle({"cwd": str(branch_dir)})

        data = json.loads((branch_dir / ".trinity" / "local.json").read_text(encoding="utf-8"))
        assert len(data["sessions"][0]["summary"]) == 300

    def test_never_raises_on_unexpected_error(self, tmp_path):
        with patch("aipass.hooks.apps.modules.context_window.find_branch_dir", side_effect=RuntimeError("boom")):
            result = handle({"cwd": str(tmp_path)})

        assert result == {"stdout": "", "exit_code": 0}


def _snapshot(branch_dir, repo_root=None) -> str:
    """The AUTO-COMPACT SNAPSHOT handle() returns for *branch_dir*.

    The plan, dispatch-lock and inbox counts are read as the snapshot's own
    parts (fleet green leg 8), not _count_open_plans / _count_active_dispatch_locks
    / _inbox_unread by name. A part the gate could not read is absent.
    """
    with patch(f"{MODULE}._find_repo_root", return_value=repo_root):
        return handle({"cwd": str(branch_dir)})["stdout"]


class TestCountOpenPlans:
    def test_counts_only_matching_location(self, tmp_path):

        branch_dir = _make_branch(tmp_path)

        fake_plans = [
            ("0001", {"location": str(branch_dir.resolve())}),
            ("0002", {"location": str(tmp_path / "somewhere" / "else")}),
            ("0003", {"location": str(branch_dir.resolve())}),
        ]

        with patch("aipass.flow.apps.modules.door_open_plans.get_open_plans", return_value=fake_plans):
            snapshot = _snapshot(branch_dir)

        assert "2 open plan(s)" in snapshot

    def test_returns_none_on_import_failure(self, tmp_path):

        branch_dir = _make_branch(tmp_path)

        with patch("aipass.flow.apps.modules.door_open_plans.get_open_plans", side_effect=RuntimeError("no")):
            snapshot = _snapshot(branch_dir)

        assert "open plan" not in snapshot


class TestCountActiveDispatchLocks:
    def test_counts_lock_files_across_branches(self, tmp_path):

        (tmp_path / "src" / "aipass" / "a" / ".ai_mail.local").mkdir(parents=True)
        (tmp_path / "src" / "aipass" / "a" / ".ai_mail.local" / ".dispatch.lock").write_text("{}", encoding="utf-8")
        (tmp_path / "src" / "aipass" / "b" / ".ai_mail.local").mkdir(parents=True)

        registry = {
            "branches": [
                {"name": "A", "path": "src/aipass/a"},
                {"name": "B", "path": "src/aipass/b"},
            ]
        }
        (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")

        assert "1 active dispatch(es)" in _snapshot(_make_branch(tmp_path), repo_root=tmp_path)

    def test_returns_none_without_repo_root(self, tmp_path):

        assert "active dispatch" not in _snapshot(_make_branch(tmp_path), repo_root=None)


class TestInboxUnread:
    def test_reads_unread_count(self, tmp_path):

        branch_dir = _make_branch(tmp_path)
        mail_dir = branch_dir / ".ai_mail.local"
        mail_dir.mkdir(parents=True)
        (mail_dir / "inbox.json").write_text(json.dumps({"unread_count": 4}), encoding="utf-8")

        assert "4 unread" in _snapshot(branch_dir)

    def test_returns_none_when_missing(self, tmp_path):

        assert "unread" not in _snapshot(_make_branch(tmp_path))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


_ENTRY_LIMITS = "aipass.memory.apps.modules.door_entry_limits"


@contextlib.contextmanager
def _served(module: Any) -> Iterator[None]:
    """Stand `module` in sys.modules as @memory's entry_limits, where the real import_module looks first.

    importlib itself is never replaced (fleet green leg 7, stdlib_patch). None makes
    the real import raise ModuleNotFoundError, the stdlib's documented answer.
    """
    with pytest.MonkeyPatch.context() as mp:
        if module is not None:
            module.__spec__ = None  # a MagicMock's __spec__ reads as a module still initializing
        mp.setitem(sys.modules, _ENTRY_LIMITS, module)
        yield


class TestSummaryCapUsesSupportedDoor:
    """@memory owns the cap. Reading their config file by hardcoded path broke
    silently if they moved it AND ignored per_branch overrides entirely."""

    # The cap is read as the length of the summary handle() stamps from a
    # 500-char snapshot (fleet green leg 8), not _summary_cap by name. 300 is
    # the handler's own default, the declared constant above.

    @staticmethod
    def _stamped_length(tmp_path, el) -> int:
        branch_dir = _make_branch(tmp_path, sessions=[])
        with (
            _served(el),
            patch(f"{MODULE}._find_repo_root", return_value=None),
            patch(f"{MODULE}._build_snapshot", return_value="X" * 500),
        ):
            handle({"cwd": str(branch_dir)})
        data = json.loads((branch_dir / ".trinity" / "local.json").read_text(encoding="utf-8"))
        return len(data["sessions"][0]["summary"])

    def test_reads_through_load_entry_limits(self, tmp_path):

        el = MagicMock()
        el.load_entry_limits.return_value = {"entry_types": {"sessions": {"max_chars": 120}}}
        assert self._stamped_length(tmp_path, el) == 120
        el.load_entry_limits.assert_called_once_with("widget")

    def test_passes_the_branch_so_per_branch_overrides_apply(self, tmp_path):
        """The hardcoded read took the global default and would have stamped one
        branch against another branch's cap."""

        el = MagicMock()
        el.load_entry_limits.side_effect = lambda b: {
            "entry_types": {"sessions": {"max_chars": 140 if b == "widget" else 300}}
        }
        assert self._stamped_length(tmp_path, el) == 140

    def test_falls_back_when_memory_is_unavailable(self, tmp_path):

        assert self._stamped_length(tmp_path, None) == 300

    def test_falls_back_on_reshaped_config(self, tmp_path):

        el = MagicMock()
        el.load_entry_limits.return_value = {"entry_types": {}}
        assert self._stamped_length(tmp_path, el) == 300

    def test_no_hardcoded_memory_config_path_survives(self):
        """Source guard on CODE, not prose.

        KNOWN TRAP: a plain substring guard fires on the docstring that explains
        the fix, so this walks the AST and inspects only real string literals —
        docstrings excluded. Same lesson as the json_handler guard exempting
        os.fdopen: a guard that trips on its own explanation gets deleted.
        """
        import ast

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
