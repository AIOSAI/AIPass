# =================== AIPass ====================
# Name: test_edit_gate.py
# Version: 1.6.0
# Description: Tests for edit_gate security handler
# Branch: hooks
# Created: 2026-05-21
# Modified: 2026-10-15
# =============================================

"""Tests for apps/handlers/security/edit_gate.py and its PreToolUse sibling settings_backup.py."""

# settings_backup.py is pinned here, not in a file of its own: new test files are gated
# (.aipass/test_write_policy.json) and FPLAN-0645 named this file. A move is @devpulse's word.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that edit_gate.py parses and imports, ruff and collection cover it
# seedgo: no-test-needed(documentation) — handle()'s docstring, the documentation checker covers it
# seedgo: no-test-needed(stdlib) — tempfile.gettempdir's choice of directory, the stdlib's own

import datetime
import hashlib
import json
import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.lifecycle import auto_fix
from aipass.hooks.apps.handlers.security.edit_gate import handle
from aipass.hooks.apps.handlers.security import settings_backup
from aipass.hooks.apps.modules import diagnostics_state as ds
from aipass.hooks.apps.modules import engine_closure

# A made-up session for the seat pins: no real session or agent id is written here.
_SESSION = "a-test-session"
_PYRIGHT_TIMES_OUT = subprocess.TimeoutExpired("pyright", 15)


def _seat(agent: str = "", session: str = _SESSION) -> dict:
    """The seat fields of a hook payload: a session, and an agent id for a sub-agent."""
    seat: dict = {}
    if session:
        seat["session_id"] = session
    if agent:
        seat["agent_id"] = agent
    return seat


def _auto_fix_edit(target: Path, seat: dict, ruff: list, pyright: list) -> dict:
    """auto_fix's real entry after an Edit of *target*, the two structured checks answering as given."""
    with (
        patch.object(auto_fix, "_run_python_checks", return_value=[]),
        patch.object(auto_fix, "_run_seedgo_checklist", return_value=[]),
        patch.object(auto_fix, "_run_ruff_lint_structured", return_value=ruff),
        patch.object(auto_fix, "_run_pyright_check", return_value=pyright),
    ):
        return auto_fix.handle({"tool_name": "Edit", "tool_input": {"file_path": str(target)}, **seat})


def _auto_fix_edit_pyright_times_out(target: Path, seat: dict) -> dict:
    """auto_fix's real entry after an Edit of *target*: ruff finds nothing, pyright times out."""
    with (
        patch.object(auto_fix, "_run_python_checks", return_value=[]),
        patch.object(auto_fix, "_run_seedgo_checklist", return_value=[]),
        patch.object(auto_fix, "_run_ruff_lint_structured", return_value=[]),
        patch.object(auto_fix.subprocess, "run", side_effect=_PYRIGHT_TIMES_OUT),
    ):
        return auto_fix.handle({"tool_name": "Edit", "tool_input": {"file_path": str(target)}, **seat})


class TestEditGateHandler:
    def test_allow_normal_edit(self):
        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/srv/example/AIPass/src/aipass/hooks/apps/test.py"},
                "cwd": "/srv/example/AIPass/src/aipass/hooks",
            }
        )
        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_block_inbox_write(self):
        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/srv/example/AIPass/src/aipass/hooks/.ai_mail.local/inbox.json"},
                "cwd": "/srv/example/AIPass/src/aipass/hooks",
            }
        )
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "inbox.json" in parsed["reason"]

    def test_block_cross_branch(self):
        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/srv/example/AIPass/src/aipass/hooks/apps/test.py"},
                "cwd": "/srv/example/AIPass/src/aipass/api",
            }
        )
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "Cross-branch" in parsed["reason"]

    def test_a_cross_branch_write_is_the_verified_admin_seats_never_a_names(self):
        """DPLAN-0356 item 5: a seat standing in .../devpulse crossed on its directory name alone."""
        data = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/srv/example/AIPass/src/aipass/hooks/apps/test.py"},
            "cwd": "/srv/example/AIPass/src/aipass/devpulse",
        }
        with patch("aipass.ai_mail.apps.modules.door_verified_caller.is_verified_admin_caller", return_value=False):
            assert handle(data)["exit_code"] == 2
        with patch("aipass.ai_mail.apps.modules.door_verified_caller.is_verified_admin_caller", return_value=True):
            assert handle(data)["exit_code"] == 0

    def test_block_daemon_cross_branch(self):
        with patch.dict("os.environ", {"AIPASS_SESSION_TYPE": "daemon"}):
            result = handle(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/srv/example/AIPass/src/aipass/hooks/apps/test.py"},
                    "cwd": "/srv/example/AIPass/src/aipass/api",
                }
            )
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert "daemon" in parsed["reason"]

    def test_allow_daemon_own_branch(self):
        with patch.dict("os.environ", {"AIPASS_SESSION_TYPE": "daemon"}):
            result = handle(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/srv/example/AIPass/src/aipass/api/apps/test.py"},
                    "cwd": "/srv/example/AIPass/src/aipass/api",
                }
            )
        assert result["exit_code"] == 0

    def test_skip_non_edit_tool(self):
        result = handle(
            {
                "tool_name": "Bash",
                "tool_input": {"file_path": "/srv/example/AIPass/src/aipass/hooks/.ai_mail.local/inbox.json"},
            }
        )
        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_empty_file_path(self):
        result = handle({"tool_name": "Edit", "tool_input": {"file_path": ""}})
        assert result["exit_code"] == 0

    def test_empty_hook_data(self):
        result = handle({})
        assert result["exit_code"] == 0

    # The owner's ruling, 2026-09-18 22:17 (devpulse 1d041cfc): "Everyone else: own files only."

    def test_block_ordinary_citizen_writing_a_project_level_file(self, registered_projects: dict):
        """A file outside every branch row belongs to the project's manager, not to whoever reaches it."""
        result = _write(registered_projects["hooks"], registered_projects["aipass"] / "README.md")
        assert result["exit_code"] == 2
        reason = json.loads(result["stdout"])["reason"]
        assert "Project-level write blocked" in reason
        assert "@devpulse" in reason

    def test_branch_identity_is_read_from_the_registry_rows(self, tmp_path: Path):
        """A project whose branches do not sit at src/<pkg>/<branch> is fenced by its rows."""
        root = tmp_path / "Studio"
        for name in ("alpha", "beta"):
            (root / "agents" / name).mkdir(parents=True)
        rows = [{"name": name, "path": f"agents/{name}"} for name in ("alpha", "beta")]
        (root / "STUDIO_REGISTRY.json").write_text(json.dumps({"branches": rows}), encoding="utf-8")

        result = _write(str(root / "agents" / "alpha"), root / "agents" / "beta" / "notes.md")
        assert result["exit_code"] == 2
        assert "'alpha' cannot write to 'beta'" in json.loads(result["stdout"])["reason"]
        assert _write(str(root / "agents" / "alpha"), root / "agents" / "alpha" / "notes.md")["exit_code"] == 0

    def test_seedgo_and_spawn_write_their_own_branch_like_everyone_else(self, registered_projects: dict):
        """DPLAN-0356 item 5: TRUSTED_CROSS_WRITERS let these two names write all of AIPass."""
        for seat in ("seedgo", "spawn"):
            for target in (
                registered_projects["aipass"] / "src" / "aipass" / "hooks" / "apps" / "x.py",
                registered_projects["aipass"] / "README.md",
            ):
                assert _write(registered_projects[seat], target)["exit_code"] == 2, (seat, target)

    def test_a_file_outside_every_project_is_nobodys(self, registered_projects: dict, tmp_path: Path):
        """Scratch and temp files belong to no project: the ownership rule has nothing to say."""
        scratch = tmp_path / "scratch" / "notes.md"
        assert _write(registered_projects["hooks"], scratch)["exit_code"] == 0
        command = f"echo x > {scratch.as_posix()}"
        bash = handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": registered_projects["hooks"]})
        assert bash["exit_code"] == 0

    def test_the_registry_owner_row_grants_nothing_the_verified_grant_does(self, registered_projects: dict):
        """DPLAN-0356 item 5: an ``owner: true`` row wrote across its project with no grant."""
        for target in (registered_projects["aipass"] / "README.md", Path(registered_projects["memory"]) / "x.py"):
            with patch("aipass.ai_mail.apps.modules.door_verified_caller.is_verified_admin_caller", return_value=False):
                assert _write(registered_projects["devpulse"], target)["exit_code"] == 2
            with patch("aipass.ai_mail.apps.modules.door_verified_caller.is_verified_admin_caller", return_value=True):
                assert _write(registered_projects["devpulse"], target)["exit_code"] == 0


def _write(cwd: str, target: Path, tool: str = "Edit") -> dict:
    return handle({"tool_name": tool, "tool_input": {"file_path": str(target)}, "cwd": cwd})


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
        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(nested_projects["core_file"])},
                "cwd": str(nested_projects["baud"]),
            }
        )
        assert result["exit_code"] == 2

    def test_block_sideways_write_between_sibling_projects(self, nested_projects: dict):
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
        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(nested_projects["baud_file"])},
                "cwd": str(nested_projects["baud_seat"]),
            }
        )
        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_block_host_seat_writing_down_into_nested_project(self, nested_projects: dict):
        """REVERSED by the owner's ruling, 2026-09-18 22:17: trust no longer runs downward.

        Until then the host could write into any project it contains, so every
        AIPass citizen could edit projects/baud. A nested project keeps its own
        registry, and "an AIPass agent must have no way to touch another
        project's files". The seat here is named devpulse and holds no grant:
        the name opens nothing.
        """
        with patch("aipass.ai_mail.apps.modules.door_verified_caller.is_verified_admin_caller", return_value=False):
            result = handle(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": str(nested_projects["baud_file"])},
                    "cwd": str(nested_projects["host_seat"]),
                }
            )
        assert result["exit_code"] == 2
        assert "Cross-project" in json.loads(result["stdout"])["reason"]

    def test_verified_admin_still_writes_down_into_nested_project(self, nested_projects: dict):
        with patch("aipass.ai_mail.apps.modules.door_verified_caller.is_verified_admin_caller", return_value=True):
            result = handle(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": str(nested_projects["baud_file"])},
                    "cwd": str(nested_projects["host_seat"]),
                }
            )
        assert result["exit_code"] == 0

    def test_seedgo_and_spawn_never_reach_beyond_aipass(self, registered_projects: dict):
        """ "seedgo and spawn edit any file inside AIPass and NEVER beyond AIPass." """
        targets = (
            Path(registered_projects["writer"]) / "draft.md",
            registered_projects["vera"] / "README.md",
            Path(registered_projects["baud_seat"]) / "app.py",
        )
        with patch("aipass.ai_mail.apps.modules.door_verified_caller.is_verified_admin_caller", return_value=False):
            for seat in ("seedgo", "spawn"):
                for target in targets:
                    result = _write(registered_projects[seat], target)
                    assert result["exit_code"] == 2, (seat, target)
                    assert "Cross-project" in json.loads(result["stdout"])["reason"]

    def test_an_artifact_registry_is_not_a_project_boundary(self, registered_projects: dict):
        """flow_json/PLAN_REGISTRY.json catalogues plans, not branches: its directory stays flow's."""
        target = Path(registered_projects["flow"]) / "flow_json" / "PLAN_REGISTRY.json"
        assert _write(registered_projects["flow"], target)["exit_code"] == 0
        refused = _write(registered_projects["hooks"], target)
        assert refused["exit_code"] == 2
        assert "Cross-branch" in json.loads(refused["stdout"])["reason"]

    def test_project_seat_named_like_a_trusted_writer_is_still_blocked(self, nested_projects: dict):
        """A project seat cannot borrow the devpulse/seedgo/spawn exemption.

        Those names are trusted inside the host tree only — a nested project
        with a src/<pkg>/devpulse directory resolves the same branch name.
        """
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
    """A two-file branch; the diagnostics state is conftest's sandbox, one seat per payload.

    Shaped src/<pkg>/<branch>/... so _get_branch resolves, with no *_REGISTRY.json
    anywhere so the project fence stays out of the way. The payloads here carry no
    session, so the state is written for the "nosession" seat.
    """
    branch = tmp_path / "src" / "aipass" / "seedgo"
    (branch / "tests").mkdir(parents=True)
    (branch / "apps" / "modules").mkdir(parents=True)

    red_test = branch / "tests" / "test_track_e.py"
    red_test.write_text("from aipass.x import _is_live_inbox\n", encoding="utf-8")
    impl = branch / "apps" / "modules" / "inbox_audit.py"
    impl.write_text("x = 1\n", encoding="utf-8")

    return {
        "branch": branch,
        "red_test": red_test,
        "impl": impl,
        "ds": ds,
        "write_state": lambda errors: ds.save_seat("nosession", str(red_test), errors),
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

    def _errored_at(self, tree: dict, relative: str, text: str, error: dict) -> dict:
        errored = tree["branch"] / relative
        errored.parent.mkdir(parents=True, exist_ok=True)
        errored.write_text(text, encoding="utf-8")
        ds.save_seat("nosession", str(errored), [error])
        with patch.object(tree["ds"], "revalidate", return_value=[error]):
            return self._edit_other_file(tree)

    def test_an_error_on_a_placeholder_line_does_not_block(self, branch_tree: dict):
        """spawn 94b406f9: a {{ placeholder }} line held every other .py edit for a day."""
        text = "import os\n\nVALUE = {{ value }}\nOTHER = os.sep\n"
        error = {"line": 2, "message": "Expected expression"}  # pyright counts from 0: the {{ line
        assert self._errored_at(branch_tree, "apps/modules/gen.py", text, error)["exit_code"] == 0
        error = {"line": 3, "message": "Expected expression"}  # the line after it: still the tree's
        assert self._errored_at(branch_tree, "apps/modules/gen.py", text, error)["exit_code"] == 2

    def test_an_error_in_a_file_under_templates_does_not_block(self, branch_tree: dict):
        assert self._errored_at(branch_tree, "templates/citizen/x.py", "x: int = 's'\n", LOCAL_ERROR)["exit_code"] == 0

    def test_stale_state_is_dropped_when_the_file_is_clean_now(self, branch_tree: dict):
        """Defect 2: a resolving write the hook never saw left a permanent block."""
        branch_tree["write_state"]([LOCAL_ERROR])
        with patch.object(branch_tree["ds"], "revalidate", return_value=[]):
            result = self._edit_other_file(branch_tree)
        assert result["exit_code"] == 0

    def test_stale_state_file_is_cleared_not_just_ignored(self, branch_tree: dict):
        branch_tree["write_state"]([LOCAL_ERROR])
        assert ds.load_seat("nosession")
        with patch.object(branch_tree["ds"], "revalidate", return_value=[]):
            self._edit_other_file(branch_tree)
        assert ds.load_seat("nosession") == {}

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
        assert ds.is_cross_file_error(UNKNOWN_SYMBOL) is True

    def test_classifies_unresolved_import_as_cross_file(self):
        assert ds.is_cross_file_error(MISSING_IMPORT) is True

    def test_does_not_classify_a_local_type_error_as_cross_file(self):
        assert ds.is_cross_file_error(LOCAL_ERROR) is False

    def test_all_cross_file_is_false_for_an_empty_list(self):
        """No errors is not 'all resolvable elsewhere' — callers must not read it as allow."""
        assert ds.all_cross_file([]) is False

    def test_revalidate_returns_none_when_pyright_is_unavailable(self, tmp_path: Path):
        target = tmp_path / "thing.py"
        target.write_text("x = 1\n", encoding="utf-8")
        with patch.object(ds.subprocess, "run", side_effect=FileNotFoundError()):
            assert ds.revalidate(str(target)) is None

    def test_revalidate_returns_none_on_timeout(self, tmp_path: Path):
        import subprocess as sp

        target = tmp_path / "thing.py"
        target.write_text("x = 1\n", encoding="utf-8")
        with patch.object(ds.subprocess, "run", side_effect=sp.TimeoutExpired("pyright", 1)):
            assert ds.revalidate(str(target)) is None

    def test_revalidate_returns_empty_list_for_a_clean_file(self, tmp_path: Path):
        """Real pyright, three-state honest.

        revalidate has THREE outcomes: [] clean, [...] findings, None could-not-tell.
        This used to assert == [] flatly, which conflates could-not-tell with clean —
        the exact confusion the contract exists to prevent. On the Windows runner
        pyright exceeded its 15s budget (0.82s locally, ~18x headroom), revalidate
        correctly answered None, and the test called that a failure. A longer budget
        would have masked a slow runner instead of fixing a dishonest assertion.
        """
        target = tmp_path / "thing.py"
        target.write_text("x: int = 1\n", encoding="utf-8")
        found = ds.revalidate(str(target))
        if found is None:
            pytest.skip("pyright could not answer here (missing or timed out) — a contract-legal outcome, not clean")
        assert found == []

    def test_revalidate_reports_a_real_type_error(self, tmp_path: Path):
        """Same three-state honesty. This one hid the flaw better: `assert found and ...`
        reads None as falsy, so a timeout failed here too, just without saying why."""
        target = tmp_path / "broken.py"
        target.write_text('x: int = "not an int"\n', encoding="utf-8")
        found = ds.revalidate(str(target))
        if found is None:
            pytest.skip("pyright could not answer here (missing or timed out) — a contract-legal outcome")
        assert found and any("int" in e["message"] for e in found)

    def test_revalidate_returns_none_for_a_file_that_does_not_exist(self, tmp_path: Path):
        assert ds.revalidate(str(tmp_path / "gone.py")) is None

    def test_load_returns_empty_dict_when_there_is_no_state(self):
        assert ds.load_seat("a-seat-with-nothing") == {}

    def test_load_returns_none_on_corrupt_state(self, tmp_path: Path):
        """An unreadable seat file answers None, which no readable file can answer."""
        ds.save_seat("a-seat", str(tmp_path / "a.py"), [LOCAL_ERROR])
        (seat_file,) = ds.STATE_DIR.glob("*.json")
        seat_file.write_text("{not json", encoding="utf-8")

        assert ds.load_seat("a-seat") is None

    def test_clear_is_safe_when_the_file_is_already_gone(self):
        """Clearing an absent seat leaves nothing behind and reads back empty.

        Had no oracle once: it called clear and asserted nothing, so a clear that
        CREATED the file, or left a partial one behind, was green. The gate
        reads this state to decide whether an edit is fenced, so "absent" and
        "empty" are the two answers that matter.
        """
        ds.clear_seat("a-seat-with-nothing")

        assert not list(ds.STATE_DIR.glob("*"))
        assert ds.load_seat("a-seat-with-nothing") == {}


@pytest.fixture
def seat_tree(tmp_path: Path) -> dict:
    """A two-file branch under tmp_path; the diagnostics state is conftest's sandbox, patched nowhere else.

    Both handlers run whole: auto_fix writes the state, edit_gate reads it. Only the
    checkers' answers are given, and revalidate answers "could not tell" so the gate
    decides on what was recorded.
    """
    branch = tmp_path / "src" / "aipass" / "seedgo"
    (branch / "tests").mkdir(parents=True)
    (branch / "apps" / "modules").mkdir(parents=True)
    red_test = branch / "tests" / "test_track_e.py"
    red_test.write_text("x = 1\n", encoding="utf-8")
    impl = branch / "apps" / "modules" / "inbox_audit.py"
    impl.write_text("x = 1\n", encoding="utf-8")
    return {"branch": branch, "red_test": red_test, "impl": impl}


class TestDiagnosticsStateBySeat:
    """Each seat has its own diagnostics state (hooks, leg 4, devpulse's decisions A and B).

    A seat is the session and, for a sub-agent, its agent id. Before leg 4 every seat
    on the machine shared one state: a worker's open error refused its siblings, and a
    sibling's clean edit erased it. Pins 1 and 2 and the no-answer pin were red on the
    shared state; pins 3 and 6 were green and stay green.
    """

    def _gate_edit(self, tree: dict, target: Path, seat: dict) -> dict:
        with patch.object(ds, "revalidate", return_value=None):
            return handle(
                {
                    "tool_name": "Edit",
                    "cwd": str(tree["branch"]),
                    "tool_input": {"file_path": str(target), "old_string": "x", "new_string": "y"},
                    **seat,
                }
            )

    def test_pin1_a_seat_is_not_refused_for_a_sibling_seats_open_error(self, seat_tree: dict):
        _auto_fix_edit(seat_tree["red_test"], _seat("worker-one"), [LOCAL_ERROR], [])

        result = self._gate_edit(seat_tree, seat_tree["impl"], _seat("worker-two"))

        assert result["exit_code"] == 0

    def test_pin2_a_siblings_clean_edit_does_not_erase_a_seats_open_error(self, seat_tree: dict):
        _auto_fix_edit(seat_tree["red_test"], _seat("worker-one"), [LOCAL_ERROR], [])
        _auto_fix_edit(seat_tree["impl"], _seat("worker-two"), [], [])

        result = self._gate_edit(seat_tree, seat_tree["impl"], _seat("worker-one"))

        assert result["exit_code"] == 2
        assert "test_track_e.py" in json.loads(result["stdout"])["reason"]

    def test_pin3_a_seat_is_still_refused_for_its_own_open_error(self, seat_tree: dict):
        _auto_fix_edit(seat_tree["red_test"], _seat("worker-one"), [LOCAL_ERROR], [])

        result = self._gate_edit(seat_tree, seat_tree["impl"], _seat("worker-one"))

        assert result["exit_code"] == 2

    def test_pin6_a_payload_without_a_session_is_one_seat_of_its_own(self, seat_tree: dict):
        _auto_fix_edit(seat_tree["red_test"], _seat(session=""), [LOCAL_ERROR], [])

        refused = self._gate_edit(seat_tree, seat_tree["impl"], _seat(session=""))
        allowed = self._gate_edit(seat_tree, seat_tree["impl"], _seat())

        assert refused["exit_code"] == 2
        assert allowed["exit_code"] == 0

    def test_a_check_that_gave_no_answer_never_clears_an_open_error(self, seat_tree: dict):
        """Decision B: pyright timed out and ruff found nothing, so the file was not judged clean."""
        _auto_fix_edit(seat_tree["red_test"], _seat(), [LOCAL_ERROR], [])
        _auto_fix_edit_pyright_times_out(seat_tree["red_test"], _seat())

        result = self._gate_edit(seat_tree, seat_tree["impl"], _seat())

        assert result["exit_code"] == 2

    def test_pin4_a_version_1_file_is_nobodys_and_replaced_on_the_next_write(self, seat_tree: dict):
        """Green from its first run, as the shape it reads did not exist before; its proof is a mutant."""
        ds.LEGACY_FILE.write_text(
            json.dumps({"file": str(seat_tree["red_test"]), "errors": [LOCAL_ERROR]}), encoding="utf-8"
        )

        result = self._gate_edit(seat_tree, seat_tree["impl"], _seat(session=""))
        _auto_fix_edit(seat_tree["red_test"], _seat(), [LOCAL_ERROR], [])

        assert result["exit_code"] == 0
        assert not ds.LEGACY_FILE.exists()

    def test_pin5_an_entry_older_than_24_hours_is_ignored(self, seat_tree: dict):
        """The clock is handed in through diagnostics_state's _now seam. Proof: a mutant."""
        written_at = 1_000_000.0
        with patch.object(ds, "_now", return_value=written_at):
            _auto_fix_edit(seat_tree["red_test"], _seat(), [LOCAL_ERROR], [])
        with patch.object(ds, "_now", return_value=written_at + 23 * 3600):
            fresh = self._gate_edit(seat_tree, seat_tree["impl"], _seat())
        with patch.object(ds, "_now", return_value=written_at + 25 * 3600):
            stale = self._gate_edit(seat_tree, seat_tree["impl"], _seat())

        assert fresh["exit_code"] == 2
        assert stale["exit_code"] == 0


class TestEditGateExternalProject:
    """Verify edit gate works for non-AIPass projects (e.g. src/vera_studio/)."""

    def test_block_cross_branch_external(self):
        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/srv/example/vera/src/vera_studio/designer/apps/test.py"},
                "cwd": "/srv/example/vera/src/vera_studio/writer",
            }
        )
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "Cross-branch" in parsed["reason"]

    def test_allow_own_branch_external(self):
        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/srv/example/vera/src/vera_studio/writer/apps/test.py"},
                "cwd": "/srv/example/vera/src/vera_studio/writer",
            }
        )
        assert result["exit_code"] == 0

    def test_block_daemon_cross_branch_external(self):
        with patch.dict("os.environ", {"AIPASS_SESSION_TYPE": "daemon"}):
            result = handle(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/srv/example/vera/src/vera_studio/designer/apps/test.py"},
                    "cwd": "/srv/example/vera/src/vera_studio/writer",
                }
            )
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert "daemon" in parsed["reason"]

    def test_allow_daemon_own_branch_external(self):
        with patch.dict("os.environ", {"AIPASS_SESSION_TYPE": "daemon"}):
            result = handle(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/srv/example/vera/src/vera_studio/writer/apps/test.py"},
                    "cwd": "/srv/example/vera/src/vera_studio/writer",
                }
            )
        assert result["exit_code"] == 0

    # The owner's ruling, 2026-09-18 22:17: "A manager (e.g. @vera in Vera Studio, like devpulse
    # in AIPass) edits her own project's agents' files, within her project only."

    def test_the_manager_row_no_longer_writes_her_projects_agents_files(self, registered_projects: dict):
        """DPLAN-0356 item 5: the manager short-circuit is gone; her own branch is hers, the rest is not."""
        for target in (Path(registered_projects["writer"]) / "draft.md", registered_projects["vera"] / "README.md"):
            assert _write(registered_projects["vera_seat"], target)["exit_code"] == 2, target

    def test_the_manager_reaches_nothing_outside_her_project(self, registered_projects: dict):
        with patch("aipass.ai_mail.apps.modules.door_verified_caller.is_verified_admin_caller", return_value=False):
            for target in (Path(registered_projects["hooks"]) / "x.py", registered_projects["aipass"] / "README.md"):
                result = _write(registered_projects["vera_seat"], target)
                assert result["exit_code"] == 2, target
                assert "Cross-project" in json.loads(result["stdout"])["reason"]

    def test_an_ordinary_agent_writes_its_own_branch_only(self, registered_projects: dict):
        writer = registered_projects["writer"]
        assert _write(writer, Path(writer) / "draft.md")["exit_code"] == 0
        for target in (Path(registered_projects["vera_seat"]) / "brand.md", registered_projects["vera"] / "README.md"):
            assert _write(writer, target)["exit_code"] == 2, target

    def test_a_trusted_writers_name_is_no_licence_outside_aipass(self, registered_projects: dict):
        """A Vera branch called seedgo is not @seedgo: the grant is AIPass's, read from its registry."""
        result = _write(registered_projects["vera_seedgo"], Path(registered_projects["writer"]) / "draft.md")
        assert result["exit_code"] == 2
        assert "Cross-branch" in json.loads(result["stdout"])["reason"]


# The cap gate's statement of its reach (the Bash lane refused, the Edit/Write lane
# measured, the offending entry still listed) is pinned through handle() in
# test_edit_gate_trinity.py::test_the_advisory_says_a_shell_write_is_refused_now.
# The three pins that called _evaluate_limits with a stand-in entry_limits moved
# there in fleet green leg 8.


def _pyright_result(diagnostics: list[dict]) -> object:
    """A fake completed pyright run carrying *diagnostics* in its real output shape."""
    from unittest.mock import MagicMock

    completed = MagicMock()
    completed.stdout = json.dumps({"generalDiagnostics": diagnostics})
    return completed


def _diag(message: str, line: int = 0, severity: str = "error") -> dict:
    return {"severity": severity, "message": message, "range": {"start": {"line": line}}}


class TestRevalidateParsesPyrightOutput:
    """The parsing is MY code and deterministic; pyright's wall-clock is not.

    The two real-pyright tests above are honest but can only skip when the tool is
    slow, so on a runner where pyright never answers they assert nothing. These pin
    the same logic hermetically, so the coverage does not evaporate on the platform
    where it is hardest to get — which is exactly where the Windows lane went red.
    """

    def _revalidate(self, tmp_path: Path, diagnostics: list[dict]):
        target = tmp_path / "thing.py"
        target.write_text("x = 1\n", encoding="utf-8")
        with patch.object(ds.subprocess, "run", return_value=_pyright_result(diagnostics)):
            return ds.revalidate(str(target))

    def test_a_scratch_module_beside_the_session_cwd_does_not_turn_clean_into_unknown(self, tmp_path, monkeypatch):
        """memory leg 9: pyright ran from the session cwd, where a types.py broke its interpreter."""
        pytest.importorskip("pyright")
        seat = tmp_path / "seat"
        seat.mkdir()
        (seat / "types.py").write_text("X = 1\n", encoding="utf-8")
        target = tmp_path / "proj" / "clean.py"
        target.parent.mkdir()
        (tmp_path / "proj" / "pyproject.toml").write_text("", encoding="utf-8")
        target.write_text("VALUE = 1\n", encoding="utf-8")
        monkeypatch.chdir(seat)
        assert ds.revalidate(str(target)) == []

    def test_clean_file_is_empty_list_not_none(self, tmp_path: Path):
        """[] and None are different answers — this is the distinction that broke."""
        found = self._revalidate(tmp_path, [])
        assert found == []
        assert found is not None

    def test_error_is_parsed_into_line_and_message(self, tmp_path: Path):
        found = self._revalidate(tmp_path, [_diag('Type "str" is not assignable to "int"', line=7)])
        assert found == [{"line": 7, "message": 'Type "str" is not assignable to "int"'}]

    def test_non_error_severities_are_dropped(self, tmp_path: Path):
        """A warning is not a reason to keep blocking an edit."""
        found = self._revalidate(
            tmp_path,
            [_diag("just a warning", severity="warning"), _diag("real problem", line=2)],
        )
        assert found == [{"line": 2, "message": "real problem"}]

    def test_findings_are_capped_at_ten(self, tmp_path: Path):
        found = self._revalidate(tmp_path, [_diag(f"error {i}", line=i) for i in range(25)])
        assert found is not None and len(found) == 10

    def test_long_messages_are_truncated(self, tmp_path: Path):
        found = self._revalidate(tmp_path, [_diag("x" * 500)])
        assert found is not None and len(found[0]["message"]) == 100

    def test_missing_range_defaults_to_line_zero(self, tmp_path: Path):
        found = self._revalidate(tmp_path, [{"severity": "error", "message": "no range given"}])
        assert found == [{"line": 0, "message": "no range given"}]

    def test_unparseable_output_is_could_not_tell(self, tmp_path: Path):
        """Garbage on stdout must never read as clean."""
        from unittest.mock import MagicMock

        target = tmp_path / "thing.py"
        target.write_text("x = 1\n", encoding="utf-8")
        broken = MagicMock()
        broken.stdout = "not json at all"
        with patch.object(ds.subprocess, "run", return_value=broken):
            assert ds.revalidate(str(target)) is None


class TestEveryRefusalIsLogged:
    """A refusal an agent never sees explained is a refusal nobody can diagnose.

    engine.jsonl records exit 2 and the stdout length, never the reason, and it
    holds under an hour of fleet traffic. Measured 2026-09-22: a live block at
    04:37:29 left no line in edit_gate.log at all. Every block goes through
    _refuse(), and _refuse() is where the WARNING is written.
    """

    def test_inbox_refusal_is_logged(self, caplog):
        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/srv/example/AIPass/src/aipass/hooks/.ai_mail.local/inbox.json"},
                "cwd": "/srv/example/AIPass/src/aipass/hooks",
            }
        )
        assert result["exit_code"] == 2
        assert "refused" in caplog.text
        assert "inbox.json" in caplog.text


@pytest.fixture
def engine_home(tmp_path: Path, monkeypatch) -> dict:
    """An install whose hooks.json wires one handler, which imports a copy of the real loader at the top.

    The copy is in the closure only through that import: the walk has to find it.
    A second copy beside it is imported by nothing (the control).
    """
    home = tmp_path / "home"
    (home / ".aipass").mkdir(parents=True)
    wired = {"hooks": {"PreToolUse": [{"handler": "aipass.zz.apps.handlers.gate.handle"}]}}
    (home / ".aipass" / "hooks.json").write_text(json.dumps(wired), encoding="utf-8")
    pkg = home / "src" / "aipass" / "zz"
    for sub in ("apps/handlers", "apps/modules"):
        (pkg / sub).mkdir(parents=True)
    (pkg / "apps" / "handlers" / "gate.py").write_text(
        "from aipass.zz.apps.modules import imported\n\n\ndef handle(data):\n    return imported\n", encoding="utf-8"
    )
    real = Path(__file__).resolve().parents[1] / "apps" / "handlers" / "config" / "loader.py"
    text = real.read_text(encoding="utf-8")
    for name in ("imported.py", "unimported.py"):
        (pkg / "apps" / "modules" / name).write_text(text, encoding="utf-8")
    monkeypatch.setenv("AIPASS_HOME", str(home))
    return {
        "seat": str(pkg),
        "in": pkg / "apps" / "modules" / "imported.py",
        "out": pkg / "apps" / "modules" / "unimported.py",
    }


def _name_before_import(target: Path, seat: str) -> dict:
    """The 10-03 shape: a name used one line before the import that defines it."""
    edit = {
        "file_path": str(target),
        "old_string": "import hashlib\n",
        "new_string": "STAMP = time.time()\nimport hashlib\n",
    }
    return handle({"tool_name": "Edit", "tool_input": edit, "cwd": seat})


class TestTheEngineClosureIsNotLeftCrashing:
    """An edit that would leave a module the engine imports raising NameError is refused before it lands.

    The 10-03 incident (leg 5, item 2): one such edit to a live-imported module
    refused every tool fleet-wide until the owner repaired it by hand.
    """

    def test_a_name_used_before_its_import_in_a_closure_module_is_refused_with_line_and_rule(self, engine_home):
        result = _name_before_import(engine_home["in"], engine_home["seat"])
        assert result["exit_code"] == 2
        reason = json.loads(result["stdout"])["reason"]
        line = engine_home["in"].read_text(encoding="utf-8").splitlines().index("import hashlib") + 1
        assert f"L{line}: F821" in reason
        assert "time" in reason

    def test_the_same_edit_outside_the_closure_is_not_this_gates_business(self, engine_home):
        assert _name_before_import(engine_home["out"], engine_home["seat"])["exit_code"] == 0

    def test_closure_help_is_answered_and_the_list_does_not_run(self, capsys):
        """`closure list --help` describes the verb and lists nothing (fleet green leg 8: the door reads --help)."""
        assert engine_closure.handle_command("closure", ["list", "--help"]) is True
        err = capsys.readouterr().err
        assert "drone @hooks closure list" in err
        assert "files in the hook engine's import closure" not in err


@pytest.fixture
def claude_home(tmp_path: Path, monkeypatch) -> Path:
    """A tmp ~/.claude holding a settings.json and settings.local.json; the gate's home seam points at it."""
    claude = tmp_path / "home" / ".claude"
    claude.mkdir(parents=True)
    # Bytes, not text: the test below pins the backup to the file's exact bytes, and
    # text mode on Windows would write CRLF and fail that oracle for the wrong reason.
    (claude / "settings.json").write_bytes(b'{"model": "before"}\n')
    (claude / "settings.local.json").write_bytes(b'{"local": "before"}\n')
    monkeypatch.setattr(settings_backup, "_claude_dir", lambda: claude)
    return claude


def _receipts(claude: Path) -> list[dict]:
    text = (claude / ".backup" / "settings" / "receipts.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def _backups(claude: Path) -> list[str]:
    return sorted(p.name for p in (claude / ".backup" / "settings").iterdir() if p.name != "receipts.jsonl")


class TestSettingsBackup:
    """FPLAN-0645: ~/.claude/settings*.json never changes without a copy and a receipt."""

    def test_an_edit_keeps_the_original_bytes_and_one_receipt_then_allows(self, claude_home, tmp_path):
        seat = tmp_path / "AIPass" / "src" / "aipass" / "hooks"
        (seat / ".trinity").mkdir(parents=True)
        edit = {"file_path": str(claude_home / "settings.json"), "old_string": "before", "new_string": "after"}
        result = settings_backup.handle({"tool_name": "Edit", "tool_input": edit, "cwd": str(seat)})
        assert result == {"stdout": "", "exit_code": 0}
        (backup,) = _backups(claude_home)
        assert re.fullmatch(r"settings\.json\.\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d\.edit-tool", backup)
        kept = (claude_home / ".backup" / "settings" / backup).read_bytes()
        assert kept == b'{"model": "before"}\n'
        (receipt,) = _receipts(claude_home)
        assert receipt["door"] == "edit-tool" and receipt["file"] == "settings.json" and receipt["backup"] == backup
        assert receipt["before_sha256"] == hashlib.sha256(kept).hexdigest()
        assert receipt["actor"] == "hooks" and receipt["after_sha256"] is None
        assert receipt["summary"] == ["Edit", "before → after"]

    def test_a_write_to_settings_local_is_the_write_tool_door(self, claude_home, tmp_path):
        write = {"file_path": str(claude_home / "settings.local.json"), "content": "{}"}
        result = settings_backup.handle({"tool_name": "Write", "tool_input": write, "cwd": str(tmp_path)})
        assert result["exit_code"] == 0
        (receipt,) = _receipts(claude_home)
        assert receipt["door"] == "write-tool" and receipt["file"] == "settings.local.json"
        assert receipt["actor"] == str(tmp_path.resolve())
        assert _backups(claude_home) == [receipt["backup"]]

    def test_a_bash_write_is_the_bash_door_and_the_summary_carries_the_command(self, claude_home, tmp_path):
        command = f"sed -i s/before/after/ {claude_home / 'settings.json'}"
        result = settings_backup.handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(tmp_path)})
        assert result["exit_code"] == 0
        (receipt,) = _receipts(claude_home)
        assert receipt["door"] == "bash" and receipt["file"] == "settings.json"
        assert receipt["summary"] == ["Bash", command]

    def test_a_backup_folder_that_cannot_be_made_refuses_and_names_the_path(self, claude_home, tmp_path):
        blocker = claude_home / ".backup" / "settings"
        blocker.parent.mkdir()
        blocker.write_text("a file where the folder goes", encoding="utf-8")
        edit = {"file_path": str(claude_home / "settings.json"), "old_string": "before", "new_string": "after"}
        result = settings_backup.handle({"tool_name": "Edit", "tool_input": edit, "cwd": str(tmp_path)})
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert f"Backup: {blocker}" in parsed["reason"]

    def test_an_edit_anywhere_else_is_allowed_with_no_backup_and_no_folder(self, claude_home, tmp_path):
        elsewhere = tmp_path / "other" / "settings.json"
        project = tmp_path / "repo" / ".claude" / "settings.json"
        for path in (elsewhere, project):
            path.parent.mkdir(parents=True)
            path.write_text("{}", encoding="utf-8")
            edit = {"file_path": str(path), "old_string": "{}", "new_string": "[]"}
            result = settings_backup.handle({"tool_name": "Edit", "tool_input": edit, "cwd": str(tmp_path)})
            assert result == {"stdout": "", "exit_code": 0}
        assert not (claude_home / ".backup").exists()

    def test_two_edits_in_one_second_keep_two_backups_the_second_suffixed(self, claude_home, tmp_path, monkeypatch):
        instant = datetime.datetime(2026, 10, 15, 17, 30, 2).astimezone()
        monkeypatch.setattr(settings_backup, "_now", lambda: instant)
        edit = {"file_path": str(claude_home / "settings.json"), "old_string": "before", "new_string": "after"}
        for _ in range(2):
            assert (
                settings_backup.handle({"tool_name": "Edit", "tool_input": edit, "cwd": str(tmp_path)})["exit_code"]
                == 0
            )
        first = "settings.json.2026-10-15T17-30-02.edit-tool"
        assert _backups(claude_home) == [first, f"{first}-2"]
        assert [r["backup"] for r in _receipts(claude_home)] == [first, f"{first}-2"]
