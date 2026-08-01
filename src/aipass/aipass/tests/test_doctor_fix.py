# =================== AIPass ====================
# Name: test_doctor_fix.py
# Description: Tests for doctor --fix remediation report (DPLAN-0177 Phase 2)
# Version: 1.0.0
# Created: 2026-05-15
# Modified: 2026-05-15
# =============================================

"""Tests for doctor_fix — remediation generation, text/JSON formatting, severity classification."""

import json
from pathlib import Path
from unittest.mock import patch

from aipass.aipass.apps.modules._doctor_fix import (
    RemediationItem,
    detect_project_name,
    format_json_report,
    format_text_report,
    generate_remediation,
    print_json_report,
    print_remediation_report,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_agent(tmp_path: Path, name: str, registry_id: str = "uuid-1", subdir: str = "") -> Path:
    """Create a minimal agent directory with passport."""
    if subdir:
        agent_dir = tmp_path / "src" / subdir / name
    else:
        agent_dir = tmp_path / "src" / name
    trinity = agent_dir / ".trinity"
    trinity.mkdir(parents=True, exist_ok=True)
    passport = {
        "branch_info": {"branch_name": name},
        "citizenship": {"registry_id": registry_id},
    }
    (trinity / "passport.json").write_text(json.dumps(passport), encoding="utf-8")
    return agent_dir


def _make_registry(tmp_path: Path, branches: list, prefix: str = "TEST") -> Path:
    """Create a registry file."""
    reg = tmp_path / f"{prefix}_REGISTRY.json"
    reg.write_text(json.dumps({"branches": branches}), encoding="utf-8")
    return reg


# =============================================================================
# TestDetectProjectName
# =============================================================================


class TestDetectProjectName:
    def test_from_registry(self, tmp_path: Path) -> None:
        """Derives name from COMPASS_REGISTRY.json → compass."""
        _make_registry(tmp_path, [], prefix="COMPASS")
        result = detect_project_name(tmp_path)
        assert result == "compass"

    def test_fallback_to_dirname(self, tmp_path: Path) -> None:
        """Falls back to directory name when no registry."""
        no_reg = tmp_path / "empty_project"
        no_reg.mkdir()
        with patch(
            "aipass.aipass.apps.modules._doctor_fix._discover_registry",
            return_value=no_reg / "MISSING_REGISTRY.json",
        ):
            result = detect_project_name(no_reg)
        assert result == "empty_project"

    def test_registry_name_lowered(self, tmp_path: Path) -> None:
        """Registry name is lowercased."""
        _make_registry(tmp_path, [], prefix="AIPASS")
        result = detect_project_name(tmp_path)
        assert result == "aipass"


# =============================================================================
# TestGenerateRemediation
# =============================================================================


class TestGenerateRemediation:
    def test_clean_project_empty(self, tmp_path: Path) -> None:
        """Clean project produces no remediation items."""
        _make_agent(tmp_path, "agent1", "uuid-1")
        _make_registry(tmp_path, [{"name": "agent1", "path": str(tmp_path / "src" / "agent1")}])
        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
        items = generate_remediation(tmp_path)
        assert items == []

    def test_pollution_is_critical(self, tmp_path: Path) -> None:
        """Duplicate branch name produces critical severity."""
        _make_agent(tmp_path, "orig", "uuid-dup")
        _make_agent(tmp_path, "orig", "uuid-other", subdir="pkg")
        _make_registry(tmp_path, [])
        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
        items = generate_remediation(tmp_path)
        pollution = [i for i in items if i.category == "pollution"]
        assert len(pollution) == 1
        assert pollution[0].severity == "critical"

    def test_pollution_command_uses_clean(self, tmp_path: Path) -> None:
        """Pollution fix command uses --clean-pollution."""
        _make_agent(tmp_path, "orig", "uuid-dup")
        _make_agent(tmp_path, "orig", "uuid-other", subdir="pkg")
        _make_registry(tmp_path, [], prefix="COMPASS")
        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
        items = generate_remediation(tmp_path)
        pollution = [i for i in items if i.category == "pollution"]
        assert "--clean-pollution" in pollution[0].fix_command
        assert "@compass" in pollution[0].fix_command

    def test_placement_is_warning(self, tmp_path: Path) -> None:
        """Misplaced agent produces warning severity."""
        agent_dir = tmp_path / "stray" / "agent"
        trinity = agent_dir / ".trinity"
        trinity.mkdir(parents=True)
        passport = {"branch_info": {"branch_name": "stray"}, "citizenship": {"registry_id": "uuid-s"}}
        (trinity / "passport.json").write_text(json.dumps(passport), encoding="utf-8")
        _make_registry(tmp_path, [])
        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
        items = generate_remediation(tmp_path)
        placement = [i for i in items if i.category == "placement"]
        assert len(placement) >= 1
        assert placement[0].severity == "warning"

    def test_placement_command_uses_relocate(self, tmp_path: Path) -> None:
        """Placement fix command uses --relocate."""
        agent_dir = tmp_path / "other" / "agent"
        trinity = agent_dir / ".trinity"
        trinity.mkdir(parents=True)
        passport = {"branch_info": {"branch_name": "stray"}, "citizenship": {"registry_id": "uuid-s"}}
        (trinity / "passport.json").write_text(json.dumps(passport), encoding="utf-8")
        _make_registry(tmp_path, [], prefix="TEST")
        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
        items = generate_remediation(tmp_path)
        placement = [i for i in items if i.category == "placement"]
        assert any("--relocate" in i.fix_command for i in placement)

    def test_registry_missing_path_is_warning(self, tmp_path: Path) -> None:
        """Missing registry path produces warning severity."""
        _make_registry(tmp_path, [{"name": "ghost", "path": str(tmp_path / "src" / "ghost")}])
        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
        items = generate_remediation(tmp_path)
        registry = [i for i in items if i.category == "registry"]
        assert len(registry) >= 1
        assert registry[0].severity == "warning"

    def test_registry_command_uses_dedup(self, tmp_path: Path) -> None:
        """Registry fix command uses --dedup-registry."""
        _make_registry(tmp_path, [{"name": "ghost", "path": str(tmp_path / "src" / "ghost")}])
        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
        items = generate_remediation(tmp_path)
        registry = [i for i in items if i.category == "registry"]
        assert "--dedup-registry" in registry[0].fix_command

    def test_root_artifact_warn(self, tmp_path: Path) -> None:
        """Root artifact with warn severity produces warning remediation."""
        _make_agent(tmp_path, "agent1", "uuid-1")
        _make_registry(tmp_path, [{"name": "agent1", "path": str(tmp_path / "src" / "agent1")}])
        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
        (tmp_path / ".chroma").mkdir()
        items = generate_remediation(tmp_path)
        root_items = [i for i in items if i.category == "root_artifact"]
        assert len(root_items) == 1
        assert root_items[0].severity == "warning"
        assert ".chroma" in root_items[0].description

    def test_root_artifact_info(self, tmp_path: Path) -> None:
        """.venv root artifact maps to info severity."""
        _make_agent(tmp_path, "agent1", "uuid-1")
        _make_registry(tmp_path, [{"name": "agent1", "path": str(tmp_path / "src" / "agent1")}])
        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
        (tmp_path / ".venv").mkdir()
        items = generate_remediation(tmp_path)
        root_items = [i for i in items if i.category == "root_artifact"]
        assert len(root_items) == 1
        assert root_items[0].severity == "info"

    def test_root_artifact_command(self, tmp_path: Path) -> None:
        """Root artifact fix command uses --relocate-root."""
        _make_agent(tmp_path, "agent1", "uuid-1")
        _make_registry(tmp_path, [{"name": "agent1", "path": str(tmp_path / "src" / "agent1")}], prefix="TEST")
        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
        (tmp_path / "logs").mkdir()
        items = generate_remediation(tmp_path)
        root_items = [i for i in items if i.category == "root_artifact"]
        assert "--relocate-root logs" in root_items[0].fix_command
        assert "@test" in root_items[0].fix_command

    def test_missing_pyproject_is_info(self, tmp_path: Path) -> None:
        """Missing pyproject.toml produces info severity."""
        _make_agent(tmp_path, "agent1", "uuid-1")
        _make_registry(tmp_path, [{"name": "agent1", "path": str(tmp_path / "src" / "agent1")}])
        items = generate_remediation(tmp_path)
        pyproject = [i for i in items if i.category == "pyproject"]
        assert len(pyproject) == 1
        assert pyproject[0].severity == "info"

    def test_pyproject_command_uses_add(self, tmp_path: Path) -> None:
        """Pyproject fix command uses --add-pyproject."""
        _make_agent(tmp_path, "agent1", "uuid-1")
        _make_registry(tmp_path, [{"name": "agent1", "path": str(tmp_path / "src" / "agent1")}])
        items = generate_remediation(tmp_path)
        pyproject = [i for i in items if i.category == "pyproject"]
        assert "--add-pyproject" in pyproject[0].fix_command


# =============================================================================
# TestFormatTextReport
# =============================================================================


class TestFormatTextReport:
    def test_empty_items(self) -> None:
        """No items produces 'no issues' message."""
        result = format_text_report([], "compass")
        assert "No structure issues" in result
        assert "@compass" in result

    def test_header_shows_counts(self) -> None:
        """Header shows total and critical counts."""
        items = [
            RemediationItem("critical", "pollution", "dup", "fix1"),
            RemediationItem("warning", "placement", "bad", "fix2"),
        ]
        result = format_text_report(items, "test")
        assert "2 found" in result
        assert "1 critical" in result

    def test_severity_tags_present(self) -> None:
        """Each item has [SEVERITY] tag."""
        items = [
            RemediationItem("critical", "pollution", "dup", "fix1"),
            RemediationItem("warning", "placement", "bad", "fix2"),
            RemediationItem("info", "pyproject", "missing", "fix3"),
        ]
        result = format_text_report(items, "test")
        assert "[CRITICAL]" in result
        assert "[WARNING]" in result
        assert "[INFO]" in result

    def test_fix_commands_present(self) -> None:
        """Fix commands appear in output."""
        items = [RemediationItem("warning", "placement", "bad", "drone @spawn repair @test --relocate a b")]
        result = format_text_report(items, "test")
        assert "drone @spawn repair @test --relocate a b" in result

    def test_dry_run_hint(self) -> None:
        """Report shows preview (dry-run default) and explicit --apply hints."""
        items = [RemediationItem("info", "pyproject", "missing", "fix")]
        result = format_text_report(items, "myproj")
        # Repair is dry-run by default now: preview form has no flag, apply form is explicit
        assert "Preview all fixes:" in result
        assert "drone @spawn repair @myproj" in result
        assert "drone @spawn repair @myproj --apply" in result

    def test_critical_sorted_first(self) -> None:
        """Critical items appear before warning and info."""
        items = [
            RemediationItem("info", "pyproject", "missing", "fix3"),
            RemediationItem("critical", "pollution", "dup", "fix1"),
            RemediationItem("warning", "placement", "bad", "fix2"),
        ]
        result = format_text_report(items, "test")
        crit_pos = result.index("[CRITICAL]")
        warn_pos = result.index("[WARNING]")
        info_pos = result.index("[INFO]")
        assert crit_pos < warn_pos < info_pos


# =============================================================================
# TestFormatJsonReport
# =============================================================================


class TestFormatJsonReport:
    def test_valid_json(self) -> None:
        """Output is valid parseable JSON."""
        items = [RemediationItem("critical", "pollution", "dup", "fix1")]
        result = format_json_report(items, "test")
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_json_structure(self) -> None:
        """JSON has expected top-level keys."""
        items = [
            RemediationItem("critical", "pollution", "dup", "fix1"),
            RemediationItem("warning", "placement", "bad", "fix2"),
        ]
        result = json.loads(format_json_report(items, "compass"))
        assert result["project"] == "compass"
        assert result["total_issues"] == 2
        assert result["critical_count"] == 1
        assert result["warning_count"] == 1
        assert result["info_count"] == 0

    def test_json_issues_array(self) -> None:
        """JSON issues array has correct fields per item."""
        items = [RemediationItem("info", "pyproject", "missing toml", "drone @spawn repair @t --add-pyproject")]
        result = json.loads(format_json_report(items, "t"))
        issue = result["issues"][0]
        assert issue["severity"] == "info"
        assert issue["category"] == "pyproject"
        assert issue["description"] == "missing toml"
        assert issue["fix_command"] == "drone @spawn repair @t --add-pyproject"

    def test_empty_report(self) -> None:
        """Empty items produces valid JSON with zero counts."""
        result = json.loads(format_json_report([], "test"))
        assert result["total_issues"] == 0
        assert result["issues"] == []

    def test_spawn_commands_in_json(self) -> None:
        """Fix commands in JSON match spawn's CLI interface."""
        items = [
            RemediationItem("critical", "pollution", "dup", "drone @spawn repair @p --clean-pollution"),
            RemediationItem("warning", "registry", "miss", "drone @spawn repair @p --dedup-registry"),
            RemediationItem("warning", "placement", "bad", "drone @spawn repair @p --relocate a b"),
        ]
        result = json.loads(format_json_report(items, "p"))
        commands = [i["fix_command"] for i in result["issues"]]
        assert all(cmd.startswith("drone @spawn repair @p") for cmd in commands)


# =============================================================================
# TestPrintFunctions
# =============================================================================


class TestPrintFunctions:
    def test_print_remediation_returns_count(self, tmp_path: Path) -> None:
        """print_remediation_report returns issue count."""
        _make_agent(tmp_path, "orig", "uuid-dup")
        _make_agent(tmp_path, "copy", "uuid-dup", subdir="pkg")
        _make_registry(tmp_path, [])
        count = print_remediation_report(tmp_path)
        assert count >= 1

    def test_print_remediation_clean_returns_zero(self, tmp_path: Path) -> None:
        """Clean project returns 0."""
        _make_agent(tmp_path, "agent1", "uuid-1")
        _make_registry(tmp_path, [{"name": "agent1", "path": str(tmp_path / "src" / "agent1")}])
        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
        count = print_remediation_report(tmp_path)
        assert count == 0

    def test_print_json_returns_count(self, tmp_path: Path) -> None:
        """print_json_report returns issue count."""
        _make_agent(tmp_path, "agent1", "uuid-1")
        _make_registry(tmp_path, [{"name": "agent1", "path": str(tmp_path / "src" / "agent1")}])
        count = print_json_report(tmp_path)
        assert count >= 1


# =============================================================================
# TestDoctorFixHandleCommand
# =============================================================================


class TestDoctorFixHandleCommand:
    def test_wrong_command(self) -> None:
        """Non-doctor_fix commands are not handled."""
        from aipass.aipass.apps.modules._doctor_fix import handle_command

        assert handle_command("doctor", []) is False
        assert handle_command("help", []) is False

    def test_no_args_shows_usage(self) -> None:
        """No args shows usage message (not introspection banner)."""
        from aipass.aipass.apps.modules._doctor_fix import handle_command

        with patch("aipass.aipass.apps.modules._doctor_fix.console") as mock_console:
            result = handle_command("doctor_fix", [])
        assert result is True
        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "aipass doctor --fix" in printed

    def test_info_flag(self) -> None:
        """--info triggers print_introspection."""
        from aipass.aipass.apps.modules._doctor_fix import handle_command

        with patch("aipass.aipass.apps.modules._doctor_fix.print_introspection") as mock:
            result = handle_command("doctor_fix", ["--info"])
        assert result is True
        mock.assert_called_once()
