# =================== AIPass ====================
# Name: test_registry_gate.py
# Version: 1.0.3
# Description: Tests for registry_gate security handler
# Branch: hooks
# Created: 2026-07-10
# Modified: 2026-10-05
# =============================================

"""Tests for apps/handlers/security/registry_gate.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(documentation) — that the gate's functions carry docstrings
# seedgo: no-test-needed(ruff) — that the module parses and its logger import resolves
# seedgo: no-test-needed(stdlib) — re's matching and pathlib's Path.name; the gate's own patterns are pinned here

import json
from unittest.mock import patch

from aipass.hooks.apps.handlers.security.registry_gate import handle

# Every helper of the gate is read through handle()'s answer (fleet green leg 9, through the command):
# refused is exit 2 with the block JSON, let through is exit 0 with empty stdout.


def _bash(command: str) -> dict:
    """handle()'s answer to a Bash call running `command`."""
    return handle({"tool_name": "Bash", "tool_input": {"command": command}})


def _edit(file_path: str) -> dict:
    """handle()'s answer to an Edit call on `file_path`."""
    return handle({"tool_name": "Edit", "tool_input": {"file_path": file_path}})


def _refused(result: dict) -> bool:
    """True when the answer is the gate's block, False when it is the plain allow."""
    if result == {"stdout": "", "exit_code": 0}:
        return False
    assert result["exit_code"] == 2
    assert json.loads(result["stdout"])["decision"] == "block"
    return True


def _named(result: dict) -> str:
    """The registry name a refusal opens with."""
    return json.loads(result["stdout"])["reason"].split(" is a sealed registry")[0]


class TestIsRegistryFile:
    def test_aipass_registry(self):
        assert _refused(_edit("AIPASS_REGISTRY.json")) is True

    def test_vera_registry(self):
        assert _refused(_edit("VERA_REGISTRY.json")) is True

    def test_full_path(self, tmp_path):
        assert _refused(_edit(str(tmp_path / "projects" / "AIPass" / "AIPASS_REGISTRY.json"))) is True

    def test_not_registry(self):
        assert _refused(_edit("config.json")) is False

    def test_partial_match(self):
        assert _refused(_edit("REGISTRY.json")) is False

    def test_wrong_extension(self):
        assert _refused(_edit("AIPASS_REGISTRY.yaml")) is False

    def test_registry_in_path(self, tmp_path):
        assert _refused(_edit(str(tmp_path / "path" / "to" / "FOO_REGISTRY.json"))) is True


class TestIsDroneSpawn:
    """A drone spawn clause is exempt: an rm after @spawn is spawn's argument, not a delete."""

    def test_drone_at_spawn(self):
        assert _refused(_bash("drone @spawn rm AIPASS_REGISTRY.json")) is False

    def test_drone_spawn(self):
        assert _refused(_bash("drone spawn rm AIPASS_REGISTRY.json")) is False

    def test_leading_space(self):
        assert _refused(_bash("echo hi &&   drone @spawn rm AIPASS_REGISTRY.json")) is False

    def test_not_drone(self):
        assert _refused(_bash("echo drone @spawn rm AIPASS_REGISTRY.json")) is True


class TestStripQuotes:
    """Quoted text is data: the same redirect refused bare is let through inside quotes."""

    def test_double_quotes(self):
        assert _refused(_bash('echo "a > AIPASS_REGISTRY.json"')) is False

    def test_single_quotes(self):
        assert _refused(_bash("echo 'a > AIPASS_REGISTRY.json'")) is False

    def test_no_quotes(self):
        assert _refused(_bash("echo a > AIPASS_REGISTRY.json")) is True


class TestSplitClauses:
    """Each operator ends the spawn clause, so the delete behind it is judged on its own."""

    def test_and_operator(self):
        assert _refused(_bash("drone @spawn list && rm AIPASS_REGISTRY.json")) is True

    def test_semicolon(self):
        assert _refused(_bash("drone @spawn list; rm AIPASS_REGISTRY.json")) is True

    def test_pipe(self):
        assert _refused(_bash("drone @spawn list | tee AIPASS_REGISTRY.json")) is True

    def test_subshell(self):
        assert _refused(_bash("drone @spawn list $(rm AIPASS_REGISTRY.json)")) is True


class TestClauseTargetsRegistry:
    def test_redirect_overwrite(self):
        assert _refused(_bash("echo data > AIPASS_REGISTRY.json")) is True

    def test_redirect_append(self):
        assert _refused(_bash("echo data >> AIPASS_REGISTRY.json")) is True

    def test_redirect_with_path(self):
        assert _refused(_bash("echo data > /path/to/AIPASS_REGISTRY.json")) is True

    def test_tee(self):
        assert _refused(_bash("tee AIPASS_REGISTRY.json")) is True

    def test_tee_append(self):
        assert _refused(_bash("tee -a AIPASS_REGISTRY.json")) is True

    def test_sed_inplace(self):
        assert _refused(_bash("sed -i 's/foo/bar/' AIPASS_REGISTRY.json")) is True

    def test_sed_inplace_backup(self):
        assert _refused(_bash("sed -i.bak 's/foo/bar/' AIPASS_REGISTRY.json")) is True

    def test_mv_onto_registry(self):
        assert _refused(_bash("mv temp.json AIPASS_REGISTRY.json")) is True

    def test_mv_registry_away(self):
        assert _refused(_bash("mv AIPASS_REGISTRY.json backup.json")) is True

    def test_mv_with_flag(self):
        assert _refused(_bash("mv -f temp.json AIPASS_REGISTRY.json")) is True

    def test_cp_onto_registry(self):
        assert _refused(_bash("cp temp.json AIPASS_REGISTRY.json")) is True

    def test_cp_from_registry_allowed(self):
        assert _refused(_bash("cp AIPASS_REGISTRY.json backup.json")) is False

    def test_rm_registry(self):
        assert _refused(_bash("rm AIPASS_REGISTRY.json")) is True

    def test_rm_with_flag(self):
        assert _refused(_bash("rm -f AIPASS_REGISTRY.json")) is True

    def test_unlink_registry(self):
        assert _refused(_bash("unlink AIPASS_REGISTRY.json")) is True

    def test_absolute_path_rm(self):
        assert _refused(_bash("/usr/bin/rm AIPASS_REGISTRY.json")) is True

    def test_drone_spawn_allowed(self):
        assert _refused(_bash("drone @spawn register AIPASS_REGISTRY.json")) is False

    def test_drone_spawn_no_at_allowed(self):
        assert _refused(_bash("drone spawn update AIPASS_REGISTRY.json")) is False

    def test_cat_allowed(self):
        assert _refused(_bash("cat AIPASS_REGISTRY.json")) is False

    def test_jq_read_allowed(self):
        assert _refused(_bash("jq '.branches' AIPASS_REGISTRY.json")) is False

    def test_head_allowed(self):
        assert _refused(_bash("head -5 AIPASS_REGISTRY.json")) is False

    def test_no_registry_mention(self):
        assert _refused(_bash("rm some_file.txt")) is False

    def test_vera_registry(self):
        assert _refused(_bash("rm VERA_REGISTRY.json")) is True


class TestFindRegistryName:
    def test_finds_aipass(self):
        assert _named(_bash("rm AIPASS_REGISTRY.json")) == "AIPASS_REGISTRY.json"

    def test_finds_vera(self):
        assert _named(_bash("rm VERA_REGISTRY.json")) == "VERA_REGISTRY.json"

    def test_fallback_when_the_name_does_not_end_the_clause(self):
        assert _named(_bash("rm AIPASS_REGISTRY.json -f")) == "*_REGISTRY.json"


class TestHandleBash:
    CWD = "/srv/aipass/src/aipass/hooks"  # only the shape matters: the gate matches registry names, not the seat

    def _bash(self, command: str) -> dict:
        return handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": self.CWD})

    def _assert_blocked(self, result: dict):
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "drone @spawn" in parsed["reason"]

    def _assert_allowed(self, result: dict):
        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_block_redirect_overwrite(self):
        self._assert_blocked(self._bash("echo '{}' > AIPASS_REGISTRY.json"))

    def test_block_tee(self):
        self._assert_blocked(self._bash("echo data | tee AIPASS_REGISTRY.json"))

    def test_block_sed_inplace(self):
        self._assert_blocked(self._bash("sed -i 's/old/new/' AIPASS_REGISTRY.json"))

    def test_block_mv_onto(self):
        self._assert_blocked(self._bash("mv temp.json AIPASS_REGISTRY.json"))

    def test_block_mv_away(self):
        self._assert_blocked(self._bash("mv AIPASS_REGISTRY.json /tmp/backup.json"))

    def test_block_cp_onto(self):
        self._assert_blocked(self._bash("cp temp.json AIPASS_REGISTRY.json"))

    def test_block_rm(self):
        self._assert_blocked(self._bash("rm AIPASS_REGISTRY.json"))

    def test_block_unlink(self):
        self._assert_blocked(self._bash("unlink AIPASS_REGISTRY.json"))

    def test_block_compound_rm(self):
        self._assert_blocked(self._bash("echo done && rm AIPASS_REGISTRY.json"))

    def test_block_subshell_rm(self):
        self._assert_blocked(self._bash("echo $(rm AIPASS_REGISTRY.json)"))

    def test_block_vera_registry(self):
        self._assert_blocked(self._bash("rm VERA_REGISTRY.json"))

    def test_allow_drone_spawn_with_registry(self):
        self._assert_allowed(self._bash("drone @spawn update AIPASS_REGISTRY.json"))

    def test_allow_cat(self):
        self._assert_allowed(self._bash("cat AIPASS_REGISTRY.json"))

    def test_allow_cp_from_registry(self):
        self._assert_allowed(self._bash("cp AIPASS_REGISTRY.json /tmp/backup.json"))

    def test_allow_no_registry(self):
        self._assert_allowed(self._bash("echo hello"))

    def test_allow_registry_in_quotes(self):
        self._assert_allowed(self._bash('echo "modifying AIPASS_REGISTRY.json"'))

    def test_empty_command(self):
        self._assert_allowed(self._bash(""))

    def test_no_tool_input(self):
        result = handle({"tool_name": "Bash"})
        assert result["exit_code"] == 0

    def test_empty_hook_data(self):
        result = handle({})
        assert result["exit_code"] == 0

    def test_sound_key_on_block(self):
        result = self._bash("rm AIPASS_REGISTRY.json")
        assert result.get("sound") == "registry gate"


class TestHandleEditTools:
    CWD = "/srv/aipass/src/aipass/hooks"  # only the shape matters: the gate matches registry names, not the seat

    def _edit(self, tool_name: str, file_path: str) -> dict:
        return handle({"tool_name": tool_name, "tool_input": {"file_path": file_path}, "cwd": self.CWD})

    def _assert_blocked(self, result: dict):
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "drone @spawn" in parsed["reason"]

    def _assert_allowed(self, result: dict):
        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_block_edit(self, tmp_path):
        self._assert_blocked(self._edit("Edit", str(tmp_path / "path" / "AIPASS_REGISTRY.json")))

    def test_block_write(self, tmp_path):
        self._assert_blocked(self._edit("Write", str(tmp_path / "path" / "AIPASS_REGISTRY.json")))

    def test_block_multi_edit(self, tmp_path):
        self._assert_blocked(self._edit("MultiEdit", str(tmp_path / "path" / "AIPASS_REGISTRY.json")))

    def test_block_notebook_edit(self, tmp_path):
        self._assert_blocked(
            handle(
                {
                    "tool_name": "NotebookEdit",
                    "tool_input": {"notebook_path": str(tmp_path / "path" / "AIPASS_REGISTRY.json")},
                    "cwd": self.CWD,
                }
            )
        )

    def test_allow_normal_file(self, tmp_path):
        self._assert_allowed(self._edit("Edit", str(tmp_path / "path" / "config.json")))

    def test_allow_empty_path(self):
        self._assert_allowed(self._edit("Edit", ""))

    def test_allow_read_tool(self):
        result = handle({"tool_name": "Read", "tool_input": {"file_path": "/path/AIPASS_REGISTRY.json"}})
        self._assert_allowed(result)

    def test_sound_key_on_block(self, tmp_path):
        result = self._edit("Edit", str(tmp_path / "path" / "AIPASS_REGISTRY.json"))
        assert result.get("sound") == "registry gate"


class TestHandleExceptionSafety:
    @patch("aipass.hooks.apps.handlers.security.registry_gate.logger")
    def test_a_crash_refuses_the_call_it_was_checking(self, mock_logger):
        """DPLAN-0356 item 2: `except: allow` became a refusal for the calls this gate guards."""
        result = handle({"tool_name": "Bash", "tool_input": None, "cwd": "/tmp"})
        assert result["exit_code"] == 2
        assert "registry_gate could not check this call" in json.loads(result["stdout"])["reason"]
        mock_logger.error.assert_called()
