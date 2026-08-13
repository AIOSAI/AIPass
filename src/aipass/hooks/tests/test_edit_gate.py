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
