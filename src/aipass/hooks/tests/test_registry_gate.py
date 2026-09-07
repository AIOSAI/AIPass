# =================== AIPass ====================
# Name: test_registry_gate.py
# Version: 1.0.0
# Description: Tests for registry_gate security handler
# Branch: hooks
# Created: 2026-07-10
# Modified: 2026-07-10
# =============================================

"""Tests for handlers/security/registry_gate.py."""

import json
from unittest.mock import patch

from aipass.hooks.apps.handlers.security.registry_gate import (
    _clause_targets_registry,
    _find_registry_name,
    _is_drone_spawn,
    _is_registry_file,
    _split_clauses,
    _strip_quotes,
    handle,
)


class TestIsRegistryFile:
    def test_aipass_registry(self):
        assert _is_registry_file("AIPASS_REGISTRY.json") is True

    def test_vera_registry(self):
        assert _is_registry_file("VERA_REGISTRY.json") is True

    def test_full_path(self):
        assert _is_registry_file("/tmp/projects/AIPass/AIPASS_REGISTRY.json") is True

    def test_not_registry(self):
        assert _is_registry_file("config.json") is False

    def test_partial_match(self):
        assert _is_registry_file("REGISTRY.json") is False

    def test_wrong_extension(self):
        assert _is_registry_file("AIPASS_REGISTRY.yaml") is False

    def test_registry_in_path(self):
        assert _is_registry_file("/path/to/FOO_REGISTRY.json") is True


class TestIsDroneSpawn:
    def test_drone_at_spawn(self):
        assert _is_drone_spawn("drone @spawn register") is True

    def test_drone_spawn(self):
        assert _is_drone_spawn("drone spawn register") is True

    def test_leading_space(self):
        assert _is_drone_spawn("  drone @spawn list") is True

    def test_not_drone(self):
        assert _is_drone_spawn("echo drone @spawn") is False

    def test_empty(self):
        assert _is_drone_spawn("") is False


class TestStripQuotes:
    def test_double_quotes(self):
        assert _strip_quotes('echo "AIPASS_REGISTRY.json"') == 'echo ""'

    def test_single_quotes(self):
        assert _strip_quotes("echo 'AIPASS_REGISTRY.json'") == "echo ''"

    def test_no_quotes(self):
        assert _strip_quotes("rm AIPASS_REGISTRY.json") == "rm AIPASS_REGISTRY.json"


class TestSplitClauses:
    def test_and_operator(self):
        clauses = _split_clauses("echo hi && rm AIPASS_REGISTRY.json")
        assert any("AIPASS_REGISTRY" in c for c in clauses)

    def test_semicolon(self):
        clauses = _split_clauses("echo hi; rm AIPASS_REGISTRY.json")
        assert any("AIPASS_REGISTRY" in c for c in clauses)

    def test_pipe(self):
        clauses = _split_clauses("cat foo | tee AIPASS_REGISTRY.json")
        assert any("tee" in c for c in clauses)

    def test_subshell(self):
        clauses = _split_clauses("echo $(cat AIPASS_REGISTRY.json)")
        assert any("AIPASS_REGISTRY" in c for c in clauses)


class TestClauseTargetsRegistry:
    def test_redirect_overwrite(self):
        assert _clause_targets_registry("echo data > AIPASS_REGISTRY.json") is True

    def test_redirect_append(self):
        assert _clause_targets_registry("echo data >> AIPASS_REGISTRY.json") is True

    def test_redirect_with_path(self):
        assert _clause_targets_registry("echo data > /path/to/AIPASS_REGISTRY.json") is True

    def test_tee(self):
        assert _clause_targets_registry(" tee AIPASS_REGISTRY.json") is True

    def test_tee_append(self):
        assert _clause_targets_registry(" tee -a AIPASS_REGISTRY.json") is True

    def test_sed_inplace(self):
        assert _clause_targets_registry("sed -i 's/foo/bar/' AIPASS_REGISTRY.json") is True

    def test_sed_inplace_backup(self):
        assert _clause_targets_registry("sed -i.bak 's/foo/bar/' AIPASS_REGISTRY.json") is True

    def test_mv_onto_registry(self):
        assert _clause_targets_registry("mv temp.json AIPASS_REGISTRY.json") is True

    def test_mv_registry_away(self):
        assert _clause_targets_registry("mv AIPASS_REGISTRY.json backup.json") is True

    def test_mv_with_flag(self):
        assert _clause_targets_registry("mv -f temp.json AIPASS_REGISTRY.json") is True

    def test_cp_onto_registry(self):
        assert _clause_targets_registry("cp temp.json AIPASS_REGISTRY.json") is True

    def test_cp_from_registry_allowed(self):
        assert _clause_targets_registry("cp AIPASS_REGISTRY.json backup.json") is False

    def test_rm_registry(self):
        assert _clause_targets_registry("rm AIPASS_REGISTRY.json") is True

    def test_rm_with_flag(self):
        assert _clause_targets_registry("rm -f AIPASS_REGISTRY.json") is True

    def test_unlink_registry(self):
        assert _clause_targets_registry("unlink AIPASS_REGISTRY.json") is True

    def test_absolute_path_rm(self):
        assert _clause_targets_registry("/usr/bin/rm AIPASS_REGISTRY.json") is True

    def test_drone_spawn_allowed(self):
        assert _clause_targets_registry("drone @spawn register AIPASS_REGISTRY.json") is False

    def test_drone_spawn_no_at_allowed(self):
        assert _clause_targets_registry("drone spawn update AIPASS_REGISTRY.json") is False

    def test_cat_allowed(self):
        assert _clause_targets_registry("cat AIPASS_REGISTRY.json") is False

    def test_jq_read_allowed(self):
        assert _clause_targets_registry("jq '.branches' AIPASS_REGISTRY.json") is False

    def test_head_allowed(self):
        assert _clause_targets_registry("head -5 AIPASS_REGISTRY.json") is False

    def test_empty_clause(self):
        assert _clause_targets_registry("") is False

    def test_no_registry_mention(self):
        assert _clause_targets_registry("rm some_file.txt") is False

    def test_vera_registry(self):
        assert _clause_targets_registry("rm VERA_REGISTRY.json") is True


class TestFindRegistryName:
    def test_finds_aipass(self):
        assert _find_registry_name("rm AIPASS_REGISTRY.json") == "AIPASS_REGISTRY.json"

    def test_finds_vera(self):
        assert _find_registry_name("rm VERA_REGISTRY.json") == "VERA_REGISTRY.json"

    def test_fallback(self):
        assert _find_registry_name("no match here") == "*_REGISTRY.json"


class TestHandleBash:
    CWD = "/home/patrick/Projects/AIPass/src/aipass/hooks"

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
    CWD = "/home/patrick/Projects/AIPass/src/aipass/hooks"

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

    def test_block_edit(self):
        self._assert_blocked(self._edit("Edit", "/path/AIPASS_REGISTRY.json"))

    def test_block_write(self):
        self._assert_blocked(self._edit("Write", "/path/AIPASS_REGISTRY.json"))

    def test_block_multi_edit(self):
        self._assert_blocked(self._edit("MultiEdit", "/path/AIPASS_REGISTRY.json"))

    def test_block_notebook_edit(self):
        self._assert_blocked(
            handle(
                {
                    "tool_name": "NotebookEdit",
                    "tool_input": {"notebook_path": "/path/AIPASS_REGISTRY.json"},
                    "cwd": self.CWD,
                }
            )
        )

    def test_allow_normal_file(self):
        self._assert_allowed(self._edit("Edit", "/path/config.json"))

    def test_allow_empty_path(self):
        self._assert_allowed(self._edit("Edit", ""))

    def test_allow_read_tool(self):
        result = handle({"tool_name": "Read", "tool_input": {"file_path": "/path/AIPASS_REGISTRY.json"}})
        self._assert_allowed(result)

    def test_sound_key_on_block(self):
        result = self._edit("Edit", "/path/AIPASS_REGISTRY.json")
        assert result.get("sound") == "registry gate"


class TestHandleExceptionSafety:
    @patch("aipass.hooks.apps.handlers.security.registry_gate.logger")
    def test_exception_allows(self, mock_logger):
        result = handle({"tool_name": "Bash", "tool_input": None, "cwd": "/tmp"})
        assert result["exit_code"] == 0
        mock_logger.info.assert_called()
