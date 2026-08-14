# =================== AIPass ====================
# Name: test_edit_gate.py
# Version: 1.1.0
# Description: Tests for edit_gate security handler
# Branch: hooks
# Created: 2026-05-21
# Modified: 2026-08-12
# =============================================

"""Tests for handlers/security/edit_gate.py."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


class TestEditGateHandler:
    def test_allow_normal_edit(self):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/home/patrick/Projects/AIPass/src/aipass/hooks/apps/test.py"},
                "cwd": "/home/patrick/Projects/AIPass/src/aipass/hooks",
            }
        )
        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_block_inbox_write(self):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/home/patrick/Projects/AIPass/src/aipass/hooks/.ai_mail.local/inbox.json"},
                "cwd": "/home/patrick/Projects/AIPass/src/aipass/hooks",
            }
        )
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "inbox.json" in parsed["reason"]

    def test_block_cross_branch(self):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/home/patrick/Projects/AIPass/src/aipass/hooks/apps/test.py"},
                "cwd": "/home/patrick/Projects/AIPass/src/aipass/api",
            }
        )
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "Cross-branch" in parsed["reason"]

    def test_allow_trusted_cross_branch(self):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/home/patrick/Projects/AIPass/src/aipass/hooks/apps/test.py"},
                "cwd": "/home/patrick/Projects/AIPass/src/aipass/devpulse",
            }
        )
        assert result["exit_code"] == 0

    def test_block_daemon_cross_branch(self):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        with patch.dict("os.environ", {"AIPASS_SESSION_TYPE": "daemon"}):
            result = handle(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/home/patrick/Projects/AIPass/src/aipass/hooks/apps/test.py"},
                    "cwd": "/home/patrick/Projects/AIPass/src/aipass/api",
                }
            )
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert "daemon" in parsed["reason"]

    def test_allow_daemon_own_branch(self):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        with patch.dict("os.environ", {"AIPASS_SESSION_TYPE": "daemon"}):
            result = handle(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/home/patrick/Projects/AIPass/src/aipass/api/apps/test.py"},
                    "cwd": "/home/patrick/Projects/AIPass/src/aipass/api",
                }
            )
        assert result["exit_code"] == 0

    def test_skip_non_edit_tool(self):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle(
            {
                "tool_name": "Bash",
                "tool_input": {"file_path": "/home/patrick/Projects/AIPass/src/aipass/hooks/.ai_mail.local/inbox.json"},
            }
        )
        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_empty_file_path(self):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle({"tool_name": "Edit", "tool_input": {"file_path": ""}})
        assert result["exit_code"] == 0

    def test_empty_hook_data(self):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle({})
        assert result["exit_code"] == 0


@pytest.fixture
def nested_projects(tmp_path: Path) -> dict:
    """Build a host project with two nested projects, mirroring the real tree.

    host/                       AIPASS_REGISTRY.json   (the AIPass repo root)
      src/aipass/drone/apps/    core citizen code
      projects/baud/            BAUD_REGISTRY.json     (nested project, @baud's seat)
        src/baud/baud/
      projects/earmark/         EARMARK_REGISTRY.json  (sibling project)
    """
    host = tmp_path / "host"
    (host / "src" / "aipass" / "drone" / "apps").mkdir(parents=True)
    (host / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")

    baud = host / "projects" / "baud"
    (baud / "src" / "baud" / "baud").mkdir(parents=True)
    (baud / "BAUD_REGISTRY.json").write_text("{}", encoding="utf-8")

    earmark = host / "projects" / "earmark"
    (earmark / "src").mkdir(parents=True)
    (earmark / "EARMARK_REGISTRY.json").write_text("{}", encoding="utf-8")

    return {
        "host": host,
        "host_seat": host / "src" / "aipass" / "devpulse",
        "core_file": host / "src" / "aipass" / "drone" / "apps" / "exceptions.py",
        "baud": baud,
        "baud_seat": baud / "src" / "baud" / "baud",
        "baud_file": baud / "src" / "baud" / "baud" / "app.py",
        "earmark": earmark,
        "earmark_file": earmark / "src" / "widget.py",
    }


class TestEditGateProjectBoundary:
    """GH #733 — a projects/* seat could write into src/aipass/* unchallenged.

    The mail fence refused the same agent's send; the file fence keyed on the
    src/<package>/<branch> shape, which no project seat has, so both sides
    resolved to an empty branch and every write fell through to allow.
    """

    @pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit", "NotebookEdit"])
    def test_block_upward_write_into_host_project(self, nested_projects: dict, tool: str):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle(
            {
                "tool_name": tool,
                "tool_input": {"file_path": str(nested_projects["core_file"])},
                "cwd": str(nested_projects["baud_seat"]),
            }
        )
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "Cross-project" in parsed["reason"]

    def test_block_upward_write_from_project_root_seat(self, nested_projects: dict):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(nested_projects["core_file"])},
                "cwd": str(nested_projects["baud"]),
            }
        )
        assert result["exit_code"] == 2

    def test_block_sideways_write_between_sibling_projects(self, nested_projects: dict):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(nested_projects["earmark_file"]), "content": "x = 1"},
                "cwd": str(nested_projects["baud_seat"]),
            }
        )
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert "Cross-project" in parsed["reason"]

    def test_reason_names_both_projects_and_the_target(self, nested_projects: dict):
        """Attribution must match the mail fence: caller project, target project."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(nested_projects["core_file"])},
                "cwd": str(nested_projects["baud_seat"]),
            }
        )
        reason = json.loads(result["stdout"])["reason"]
        assert "baud" in reason
        assert "host" in reason
        assert "exceptions.py" in reason

    def test_allow_write_inside_own_project(self, nested_projects: dict):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(nested_projects["baud_file"])},
                "cwd": str(nested_projects["baud_seat"]),
            }
        )
        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_allow_host_seat_writing_down_into_nested_project(self, nested_projects: dict):
        """Trust runs downward: the host may write into a project it hosts.

        This direction also covers the host's own artifact registries
        (flow_json/PLAN_REGISTRY.json, backup snapshots), which sit under the
        repo root and would otherwise read as foreign projects to their owners.
        """
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(nested_projects["baud_file"])},
                "cwd": str(nested_projects["host_seat"]),
            }
        )
        assert result["exit_code"] == 0

    def test_project_seat_named_like_a_trusted_writer_is_still_blocked(self, nested_projects: dict):
        """A project seat cannot borrow the devpulse/seedgo/spawn exemption.

        Those names are trusted inside the host tree only — a nested project
        with a src/<pkg>/devpulse directory resolves the same branch name.
        """
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        impostor = nested_projects["baud"] / "src" / "baud" / "devpulse"
        impostor.mkdir(parents=True)
        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(nested_projects["core_file"])},
                "cwd": str(impostor),
            }
        )
        assert result["exit_code"] == 2

    def test_allow_when_no_project_root_is_resolvable(self, tmp_path: Path):
        """No registry on either side: fail open, exactly as before this fence."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        loose_a = tmp_path / "loose_a"
        loose_b = tmp_path / "loose_b"
        loose_a.mkdir()
        loose_b.mkdir()
        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(loose_b / "note.py")},
                "cwd": str(loose_a),
            }
        )
        assert result["exit_code"] == 0

    def test_daemon_session_from_project_seat_is_blocked(self, nested_projects: dict):
        """Dispatched project agents are fenced too — the daemon confinement
        below also keys on the src/<package>/<branch> shape and skips them."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        with patch.dict("os.environ", {"AIPASS_SESSION_TYPE": "daemon"}):
            result = handle(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": str(nested_projects["core_file"])},
                    "cwd": str(nested_projects["baud_seat"]),
                }
            )
        assert result["exit_code"] == 2

    def test_inbox_write_still_blocked_from_a_project_seat(self, nested_projects: dict):
        """The project fence must not shadow the inbox rule's own message."""
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        inbox = nested_projects["host"] / "src" / "aipass" / "drone" / ".ai_mail.local" / "inbox.json"
        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(inbox)},
                "cwd": str(nested_projects["baud_seat"]),
            }
        )
        assert result["exit_code"] == 2
        assert "inbox.json" in json.loads(result["stdout"])["reason"]


@pytest.fixture
def branch_tree(tmp_path: Path):
    """A two-file branch plus an isolated diagnostics state file.

    Shaped src/<pkg>/<branch>/... so _get_branch resolves, with no *_REGISTRY.json
    anywhere so the project fence stays out of the way.
    """
    import importlib

    ds = importlib.import_module("aipass.hooks.apps.modules.diagnostics_state")
    branch = tmp_path / "src" / "aipass" / "seedgo"
    (branch / "tests").mkdir(parents=True)
    (branch / "apps" / "modules").mkdir(parents=True)

    red_test = branch / "tests" / "test_track_e.py"
    red_test.write_text("from aipass.x import _is_live_inbox\n", encoding="utf-8")
    impl = branch / "apps" / "modules" / "inbox_audit.py"
    impl.write_text("x = 1\n", encoding="utf-8")

    state_file = tmp_path / ".diagnostics_state.json"
    with patch.object(ds, "STATE_FILE", state_file):
        yield {
            "branch": branch,
            "red_test": red_test,
            "impl": impl,
            "state_file": state_file,
            "ds": ds,
            "write_state": lambda errors: state_file.write_text(
                json.dumps({"file": str(red_test), "errors": errors}), encoding="utf-8"
            ),
        }


UNKNOWN_SYMBOL = {"line": 1, "message": '"_is_live_inbox" is unknown import symbol'}
MISSING_IMPORT = {"line": 1, "message": 'Import "aipass.x" could not be resolved'}
LOCAL_ERROR = {"line": 4, "message": 'Argument of type "str" cannot be assigned to parameter of type "int"'}


class TestEditGateDiagnosticsState:
    """The block must be satisfiable, and must be a live fact rather than a remembered one.

    Reported by @seedgo with a live repro: a red test importing a symbol that does
    not exist yet is the mandated red-first shape, and the only edit that can clear
    it is in another file — which is exactly what the gate blocked.
    """

    def _edit_other_file(self, tree: dict) -> dict:
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        return handle(
            {
                "tool_name": "Edit",
                "cwd": str(tree["branch"]),
                "tool_input": {"file_path": str(tree["impl"]), "old_string": "x", "new_string": "y"},
            }
        )

    def test_cross_file_red_first_is_not_blocked(self, branch_tree: dict):
        """The deadlock: the resolving edit lives in another file by definition."""
        branch_tree["write_state"]([UNKNOWN_SYMBOL])
        with patch.object(branch_tree["ds"], "revalidate", return_value=[UNKNOWN_SYMBOL]):
            result = self._edit_other_file(branch_tree)
        assert result["exit_code"] == 0

    def test_unresolved_module_import_is_also_cross_file(self, branch_tree: dict):
        branch_tree["write_state"]([MISSING_IMPORT])
        with patch.object(branch_tree["ds"], "revalidate", return_value=[MISSING_IMPORT]):
            result = self._edit_other_file(branch_tree)
        assert result["exit_code"] == 0

    def test_local_error_still_blocks(self, branch_tree: dict):
        """The gate keeps doing its job for errors the errored file can actually fix."""
        branch_tree["write_state"]([LOCAL_ERROR])
        with patch.object(branch_tree["ds"], "revalidate", return_value=[LOCAL_ERROR]):
            result = self._edit_other_file(branch_tree)
        assert result["exit_code"] == 2
        assert "before editing other files" in json.loads(result["stdout"])["reason"]

    def test_mixed_errors_still_block(self, branch_tree: dict):
        """Every error must be cross-file; one locally-fixable error keeps the block."""
        branch_tree["write_state"]([UNKNOWN_SYMBOL, LOCAL_ERROR])
        with patch.object(branch_tree["ds"], "revalidate", return_value=[UNKNOWN_SYMBOL, LOCAL_ERROR]):
            result = self._edit_other_file(branch_tree)
        assert result["exit_code"] == 2

    def test_stale_state_is_dropped_when_the_file_is_clean_now(self, branch_tree: dict):
        """Defect 2: a resolving write the hook never saw left a permanent block."""
        branch_tree["write_state"]([LOCAL_ERROR])
        with patch.object(branch_tree["ds"], "revalidate", return_value=[]):
            result = self._edit_other_file(branch_tree)
        assert result["exit_code"] == 0

    def test_stale_state_file_is_cleared_not_just_ignored(self, branch_tree: dict):
        branch_tree["write_state"]([LOCAL_ERROR])
        assert branch_tree["state_file"].exists()
        with patch.object(branch_tree["ds"], "revalidate", return_value=[]):
            self._edit_other_file(branch_tree)
        assert not branch_tree["state_file"].exists()

    def test_block_reports_the_revalidated_errors_not_the_recorded_ones(self, branch_tree: dict):
        """If the file still fails, the reason should quote what is true now."""
        branch_tree["write_state"]([LOCAL_ERROR])
        fresh = [{"line": 9, "message": "A different error that exists right now"}]
        with patch.object(branch_tree["ds"], "revalidate", return_value=fresh):
            result = self._edit_other_file(branch_tree)
        assert result["exit_code"] == 2
        assert "A different error that exists right now" in json.loads(result["stdout"])["reason"]

    def test_unverifiable_state_falls_back_to_the_recorded_errors(self, branch_tree: dict):
        """pyright missing or timed out: keep the old behaviour for local errors."""
        branch_tree["write_state"]([LOCAL_ERROR])
        with patch.object(branch_tree["ds"], "revalidate", return_value=None):
            result = self._edit_other_file(branch_tree)
        assert result["exit_code"] == 2

    def test_unverifiable_state_still_clears_the_deadlock(self, branch_tree: dict):
        """Defect 1 is fixed even when the file cannot be re-checked."""
        branch_tree["write_state"]([UNKNOWN_SYMBOL])
        with patch.object(branch_tree["ds"], "revalidate", return_value=None):
            result = self._edit_other_file(branch_tree)
        assert result["exit_code"] == 0

    def test_editing_the_errored_file_itself_is_still_allowed(self, branch_tree: dict):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        branch_tree["write_state"]([LOCAL_ERROR])
        result = handle(
            {
                "tool_name": "Edit",
                "cwd": str(branch_tree["branch"]),
                "tool_input": {"file_path": str(branch_tree["red_test"]), "old_string": "a", "new_string": "b"},
            }
        )
        assert result["exit_code"] == 0


class TestDiagnosticsStateModule:
    """apps/modules/diagnostics_state.py — one definition of what the state file means."""

    def test_classifies_unknown_import_symbol_as_cross_file(self):
        from aipass.hooks.apps.modules import diagnostics_state as ds

        assert ds.is_cross_file_error(UNKNOWN_SYMBOL) is True

    def test_classifies_unresolved_import_as_cross_file(self):
        from aipass.hooks.apps.modules import diagnostics_state as ds

        assert ds.is_cross_file_error(MISSING_IMPORT) is True

    def test_does_not_classify_a_local_type_error_as_cross_file(self):
        from aipass.hooks.apps.modules import diagnostics_state as ds

        assert ds.is_cross_file_error(LOCAL_ERROR) is False

    def test_all_cross_file_is_false_for_an_empty_list(self):
        """No errors is not 'all resolvable elsewhere' — callers must not read it as allow."""
        from aipass.hooks.apps.modules import diagnostics_state as ds

        assert ds.all_cross_file([]) is False

    def test_revalidate_returns_none_when_pyright_is_unavailable(self, tmp_path: Path):
        from aipass.hooks.apps.modules import diagnostics_state as ds

        target = tmp_path / "thing.py"
        target.write_text("x = 1\n", encoding="utf-8")
        with patch.object(ds.subprocess, "run", side_effect=FileNotFoundError()):
            assert ds.revalidate(str(target)) is None

    def test_revalidate_returns_none_on_timeout(self, tmp_path: Path):
        import subprocess as sp

        from aipass.hooks.apps.modules import diagnostics_state as ds

        target = tmp_path / "thing.py"
        target.write_text("x = 1\n", encoding="utf-8")
        with patch.object(ds.subprocess, "run", side_effect=sp.TimeoutExpired("pyright", 1)):
            assert ds.revalidate(str(target)) is None

    def test_revalidate_returns_empty_list_for_a_clean_file(self, tmp_path: Path):
        from aipass.hooks.apps.modules import diagnostics_state as ds

        target = tmp_path / "thing.py"
        target.write_text("x: int = 1\n", encoding="utf-8")
        assert ds.revalidate(str(target)) == []

    def test_revalidate_reports_a_real_type_error(self, tmp_path: Path):
        from aipass.hooks.apps.modules import diagnostics_state as ds

        target = tmp_path / "broken.py"
        target.write_text('x: int = "not an int"\n', encoding="utf-8")
        found = ds.revalidate(str(target))
        assert found and any("int" in e["message"] for e in found)

    def test_revalidate_returns_none_for_a_file_that_does_not_exist(self, tmp_path: Path):
        from aipass.hooks.apps.modules import diagnostics_state as ds

        assert ds.revalidate(str(tmp_path / "gone.py")) is None

    def test_load_returns_empty_dict_when_there_is_no_state(self, tmp_path: Path):
        from aipass.hooks.apps.modules import diagnostics_state as ds

        with patch.object(ds, "STATE_FILE", tmp_path / "absent.json"):
            assert ds.load() == {}

    def test_load_returns_empty_dict_on_corrupt_state(self, tmp_path: Path):
        from aipass.hooks.apps.modules import diagnostics_state as ds

        corrupt = tmp_path / "corrupt.json"
        corrupt.write_text("{not json", encoding="utf-8")
        with patch.object(ds, "STATE_FILE", corrupt):
            assert ds.load() == {}

    def test_clear_is_safe_when_the_file_is_already_gone(self, tmp_path: Path):
        from aipass.hooks.apps.modules import diagnostics_state as ds

        with patch.object(ds, "STATE_FILE", tmp_path / "absent.json"):
            ds.clear()


class TestEditGateExternalProject:
    """Verify edit gate works for non-AIPass projects (e.g. src/vera_studio/)."""

    def test_block_cross_branch_external(self):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/home/user/Projects/vera/src/vera_studio/designer/apps/test.py"},
                "cwd": "/home/user/Projects/vera/src/vera_studio/writer",
            }
        )
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "Cross-branch" in parsed["reason"]

    def test_allow_own_branch_external(self):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/home/user/Projects/vera/src/vera_studio/writer/apps/test.py"},
                "cwd": "/home/user/Projects/vera/src/vera_studio/writer",
            }
        )
        assert result["exit_code"] == 0

    def test_block_daemon_cross_branch_external(self):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        with patch.dict("os.environ", {"AIPASS_SESSION_TYPE": "daemon"}):
            result = handle(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/home/user/Projects/vera/src/vera_studio/designer/apps/test.py"},
                    "cwd": "/home/user/Projects/vera/src/vera_studio/writer",
                }
            )
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert "daemon" in parsed["reason"]

    def test_allow_daemon_own_branch_external(self):
        from aipass.hooks.apps.handlers.security.edit_gate import handle

        with patch.dict("os.environ", {"AIPASS_SESSION_TYPE": "daemon"}):
            result = handle(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/home/user/Projects/vera/src/vera_studio/writer/apps/test.py"},
                    "cwd": "/home/user/Projects/vera/src/vera_studio/writer",
                }
            )
        assert result["exit_code"] == 0
