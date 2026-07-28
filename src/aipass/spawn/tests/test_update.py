# =================== META ====================
# Name: test_update.py
# Description: Tests for spawn update orchestrator
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""Tests for the spawn update module.

Tests update_branch(), update_all(), dry-run mode, .py skip behavior,
JSON deep merge, first-time adoption, and self-skip logic.
"""

import json
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def template_dir(tmp_path):
    """Create a minimal template directory with registry."""
    tpl = tmp_path / "template"
    tpl.mkdir()

    # Template files
    (tpl / "README.md").write_text("# {{BRANCHNAME}}\nTemplate readme\n")
    (tpl / "DASHBOARD.local.json").write_text(
        json.dumps({"status": "active", "branch": "{{branchname}}", "version": "1.0"}, indent=2)
    )
    (tpl / "apps").mkdir()
    (tpl / "apps" / "__init__.py").write_text('"""{{branchname}} apps"""')
    (tpl / "apps" / "branch.py").write_text('"""{{branchname}} entry point"""\ndef main(): pass\n')
    (tpl / "tests").mkdir()
    (tpl / "tests" / "__init__.py").write_text("")
    (tpl / ".archive").mkdir()
    (tpl / "docs").mkdir()

    # .spawn directory with template registry
    spawn_meta = tpl / ".spawn"
    spawn_meta.mkdir()

    registry = {
        "metadata": {
            "version": "1.0.0",
            "last_updated": "2026-03-07",
            "description": "Template file tracking registry",
        },
        "files": {
            "f001": {
                "current_name": "README.md",
                "path": "README.md",
                "content_hash": _hash_content("# {{BRANCHNAME}}\nTemplate readme\n"),
                "has_branch_placeholder": True,
            },
            "f002": {
                "current_name": "DASHBOARD.local.json",
                "path": "DASHBOARD.local.json",
                "content_hash": _hash_content(
                    json.dumps({"status": "active", "branch": "{{branchname}}", "version": "1.0"}, indent=2)
                ),
                "has_branch_placeholder": True,
            },
            "f003": {
                "current_name": "__init__.py",
                "path": "apps/__init__.py",
                "content_hash": _hash_content('"""{{branchname}} apps"""'),
                "has_branch_placeholder": True,
            },
            "f004": {
                "current_name": "branch.py",
                "path": "apps/branch.py",
                "content_hash": _hash_content('"""{{branchname}} entry point"""\ndef main(): pass\n'),
                "has_branch_placeholder": True,
            },
            "f005": {
                "current_name": "__init__.py",
                "path": "tests/__init__.py",
                "content_hash": _hash_content(""),
                "has_branch_placeholder": False,
            },
        },
        "directories": {
            "d001": {
                "current_name": "apps",
                "path": "apps",
                "has_branch_placeholder": False,
            },
            "d002": {
                "current_name": "tests",
                "path": "tests",
                "has_branch_placeholder": False,
            },
            "d003": {
                "current_name": ".archive",
                "path": ".archive",
                "has_branch_placeholder": False,
            },
            "d004": {
                "current_name": "docs",
                "path": "docs",
                "has_branch_placeholder": False,
            },
        },
    }

    (spawn_meta / ".template_registry.json").write_text(json.dumps(registry, indent=2) + "\n")

    return tpl


@pytest.fixture
def branch_dir(tmp_path):
    """Create a minimal existing branch directory (pre-update)."""
    branch = tmp_path / "test_branch"
    branch.mkdir()

    # Existing files in branch
    (branch / "README.md").write_text("# TEST_BRANCH\nCustom readme with user edits\n")
    (branch / "DASHBOARD.local.json").write_text(
        json.dumps({"status": "running", "branch": "test_branch", "custom_key": "preserved"}, indent=2)
    )
    (branch / "apps").mkdir()
    (branch / "apps" / "__init__.py").write_text('"""test_branch apps - modified"""')
    (branch / "apps" / "branch.py").write_text('"""test_branch entry"""\ndef main():\n    print("hello")\n')
    (branch / "tests").mkdir()
    (branch / "tests" / "__init__.py").write_text("")
    (branch / ".archive").mkdir()
    (branch / "docs").mkdir()
    (branch / ".spawn").mkdir()

    # passport.json — _read_citizen_class requires one (no fallback, DPLAN-0262).
    # Fully allowlist-complete so generic engine tests don't incidentally trigger
    # a passport heal diff; test_passport_drift.py and TestPassportHeal cover healing.
    (branch / ".trinity").mkdir()
    (branch / ".trinity" / "passport.json").write_text(
        json.dumps(
            {
                "branch_info": {
                    "branch_name": "test_branch",
                    "email": "@test_branch",
                    "git_branch": "work/test_branch",
                },
                "identity": {"citizen_class": "aipass_framework", "role": "test", "traits": ""},
            },
            indent=2,
        )
        + "\n"
    )

    return branch


@pytest.fixture
def mock_registry(tmp_path, branch_dir):
    """Create a mock AIPASS_REGISTRY.json pointing to our test branch."""
    # We need paths relative to some "repo root"
    repo_root = tmp_path
    rel_path = str(branch_dir.relative_to(repo_root))

    registry = {
        "metadata": {
            "version": "1.0.0",
            "last_updated": "2026-03-07",
            "total_branches": 2,
        },
        "branches": [
            {
                "name": "TEST_BRANCH",
                "path": rel_path,
                "profile": "library",
                "description": "Test branch",
                "email": "@test_branch",
                "status": "active",
            },
            {
                "name": "SPAWN",
                "path": "spawn",
                "profile": "library",
                "description": "Agent creation",
                "email": "@spawn",
                "status": "active",
            },
        ],
    }

    reg_path = repo_root / "AIPASS_REGISTRY.json"
    reg_path.write_text(json.dumps(registry, indent=2) + "\n")

    return reg_path


def _hash_content(content: str) -> str:
    """Compute SHA-256 hash (first 12 chars) of content string."""
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUpdateBranch:
    """Tests for update_branch()."""

    def test_first_time_adoption_generates_meta(self, tmp_path, template_dir, branch_dir, mock_registry):
        """Branch with no .branch_meta.json should get one generated."""
        from aipass.spawn.apps.handlers.update_ops import update_branch

        # Ensure no branch_meta exists
        meta_path = branch_dir / ".spawn" / ".branch_meta.json"
        assert not meta_path.exists()

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert result["success"] is True
        assert result["branch"] == "test_branch"
        # After update, branch_meta should exist
        assert meta_path.exists()

    def test_dry_run_does_not_modify(self, tmp_path, template_dir, branch_dir, mock_registry):
        """Dry run should report changes without modifying files."""
        from aipass.spawn.apps.handlers.update_ops import update_branch

        # Record original state
        readme_before = (branch_dir / "README.md").read_text()
        dashboard_before = (branch_dir / "DASHBOARD.local.json").read_text()

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch", dry_run=True)

        assert result["success"] is True
        assert result["dry_run"] is True

        # Files should be unchanged
        assert (branch_dir / "README.md").read_text() == readme_before
        assert (branch_dir / "DASHBOARD.local.json").read_text() == dashboard_before

        # No branch_meta created in dry-run on first adoption
        meta_path = branch_dir / ".spawn" / ".branch_meta.json"
        assert not meta_path.exists()

    def test_py_files_never_overwritten(self, tmp_path, template_dir, branch_dir, mock_registry):
        """Python files should be skipped even when template hash differs."""
        from aipass.spawn.apps.handlers.update_ops import update_branch

        # Create initial branch_meta with a matching .py file that has a different hash
        spawn_dir = branch_dir / ".spawn"
        spawn_dir.mkdir(exist_ok=True)

        branch_py_content = '"""test_branch entry"""\ndef main():\n    print("hello")\n'
        original_content = branch_py_content

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        # .py file should still have original content
        assert (branch_dir / "apps" / "branch.py").read_text() == original_content
        assert result["success"] is True

    def test_json_deep_merge_preserves_existing(self, tmp_path, template_dir, branch_dir, mock_registry):
        """JSON merge should add new template keys while preserving existing values."""
        from aipass.spawn.apps.handlers.update_ops import update_branch

        # Set up branch_meta so DASHBOARD.local.json shows as needing update
        spawn_dir = branch_dir / ".spawn"
        spawn_dir.mkdir(exist_ok=True)

        # Write template with a new key
        (template_dir / "DASHBOARD.local.json").write_text(
            json.dumps(
                {
                    "status": "active",
                    "branch": "{{branchname}}",
                    "version": "2.0",
                    "new_field": "from_template",
                },
                indent=2,
            )
        )

        # Update template registry hash to differ from branch
        reg_path = template_dir / ".spawn" / ".template_registry.json"
        reg = json.loads(reg_path.read_text())
        reg["files"]["f002"]["content_hash"] = "different_hash"
        reg_path.write_text(json.dumps(reg, indent=2) + "\n")

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert result["success"] is True

        # Read merged dashboard
        merged = json.loads((branch_dir / "DASHBOARD.local.json").read_text())

        # Existing values preserved
        assert merged["custom_key"] == "preserved"
        assert merged["status"] == "running"  # existing value kept over template
        assert merged["branch"] == "test_branch"  # existing value kept

    def test_branch_not_found(self, tmp_path, template_dir, mock_registry):
        """Non-existent branch should return failure."""
        from aipass.spawn.apps.handlers.update_ops import update_branch

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("nonexistent_branch")

        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_additions_from_template(self, tmp_path, template_dir, branch_dir, mock_registry):
        """New template files not in branch should be added."""
        from aipass.spawn.apps.handlers.update_ops import update_branch

        # Add a new file to template that doesn't exist in branch
        (template_dir / "docs" / "new_doc.md").write_text("# New doc for {{branchname}}")

        # Add it to template registry
        reg_path = template_dir / ".spawn" / ".template_registry.json"
        reg = json.loads(reg_path.read_text())
        reg["files"]["f099"] = {
            "current_name": "new_doc.md",
            "path": "docs/new_doc.md",
            "content_hash": _hash_content("# New doc for {{branchname}}"),
            "has_branch_placeholder": True,
        }
        reg_path.write_text(json.dumps(reg, indent=2) + "\n")

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert result["success"] is True
        assert result["additions"] >= 1

        # The new file should exist with placeholders replaced
        new_file = branch_dir / "docs" / "new_doc.md"
        assert new_file.exists()
        content = new_file.read_text()
        assert "{{branchname}}" not in content
        assert "test_branch" in content

    def test_extra_files_not_pruned(self, tmp_path, template_dir, branch_dir, mock_registry):
        """P1 engine never prunes — extra branch files are left untouched."""
        from aipass.spawn.apps.handlers.update_ops import update_branch

        extra_file = branch_dir / "old_config.json"
        extra_file.write_text(json.dumps({"old": True}))

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert result["success"] is True
        assert result["pruned"] == 0
        assert extra_file.exists()


class TestNeverUpdateGuard:
    """Tests for create-only file protection (P1 engine, TDPLAN-0006)."""

    def test_trinity_local_json_never_touched(self, tmp_path, template_dir, branch_dir, mock_registry):
        """Update must never modify .trinity/local.json even when template has it (create-only)."""
        from aipass.spawn.apps.handlers.update_ops import update_branch

        trinity_tpl = template_dir / ".trinity"
        trinity_tpl.mkdir(exist_ok=True)
        (trinity_tpl / "local.json").write_text('{"sessions": []}')

        trinity_branch = branch_dir / ".trinity"
        (trinity_branch / "local.json").write_text('{"sessions": [{"id": 1}]}')
        local_before = (trinity_branch / "local.json").read_text()

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert result["success"] is True
        assert (trinity_branch / "local.json").read_text() == local_before

    def test_passport_identity_content_never_touched_by_heal(self, tmp_path, template_dir, branch_dir, mock_registry):
        """passport.json heals allowlisted fields only — role/purpose/etc. stay create-only,
        even when the branch_dir fixture's passport is already allowlist-complete and the
        template disagrees on a non-allowlisted field (role) and on allowlisted ones (email,
        git_branch, traits) — existing always wins, template's differing values never land."""
        from aipass.spawn.apps.handlers.update_ops import update_branch

        trinity_tpl = template_dir / ".trinity"
        trinity_tpl.mkdir(exist_ok=True)
        (trinity_tpl / "passport.json").write_text(
            json.dumps(
                {
                    "branch_info": {"email": "@template_default", "git_branch": "work/template_default"},
                    "identity": {"role": "template_role_should_not_apply", "traits": "should_not_apply"},
                },
                indent=2,
            )
        )

        trinity_branch = branch_dir / ".trinity"
        passport_before = (trinity_branch / "passport.json").read_text()

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert result["success"] is True
        assert (trinity_branch / "passport.json").read_text() == passport_before

    def test_dashboard_never_touched(self, tmp_path, template_dir, branch_dir, mock_registry):
        """Update must never modify DASHBOARD.local.json even when template differs."""
        from aipass.spawn.apps.handlers.update_ops import update_branch

        dashboard = branch_dir / "DASHBOARD.local.json"
        dashboard_before = dashboard.read_text()

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert result["success"] is True
        assert dashboard.read_text() == dashboard_before

    def test_zero_renames_always(self, tmp_path, template_dir, branch_dir, mock_registry):
        """P1 engine never proposes renames."""
        from aipass.spawn.apps.handlers.update_ops import update_branch

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch", dry_run=True)

        assert result["renames"] == 0
        assert result.get("_renames_detail", []) == []

    def test_backup_lands_in_spawn_recovery(self, tmp_path, template_dir, branch_dir, mock_registry):
        """JSON merge backups should land in .spawn/.recovery/, not branch root .recovery/."""
        from aipass.spawn.apps.handlers.update_ops import update_branch

        config_tpl = template_dir / "config.json"
        config_tpl.write_text(json.dumps({"version": "2.0", "new_key": "added"}, indent=2))
        config_branch = branch_dir / "config.json"
        config_branch.write_text(json.dumps({"version": "1.0"}, indent=2))

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert result["updates"] >= 1
        spawn_recovery = branch_dir / ".spawn" / ".recovery"
        assert spawn_recovery.is_dir()
        backups = list(spawn_recovery.glob("config.json.*.backup"))
        assert len(backups) == 1
        root_recovery = branch_dir / ".recovery"
        assert not root_recovery.exists()

    def test_create_update_invariant(self, tmp_path, template_dir, branch_dir, mock_registry):
        """Fresh branch from template should show 0 changes on update."""
        from aipass.spawn.apps.handlers.update_ops import update_branch

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch", dry_run=True)

        assert result["success"] is True
        assert result["additions"] == 0
        assert result["renames"] == 0
        assert result["updates"] == 0
        assert result["pruned"] == 0


class TestUpdateAll:
    """Tests for update_all()."""

    def test_update_all_skips_spawn(self, tmp_path, template_dir, branch_dir, mock_registry):
        """update_all should skip spawn itself."""
        from aipass.spawn.apps.handlers.update_ops import update_all

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            results = update_all()

        # Should have results for test_branch but NOT for spawn
        branch_names = [r["branch"] for r in results]
        assert "spawn" not in branch_names
        # test_branch should be present
        assert "test_branch" in branch_names

    def test_update_all_processes_all_branches(self, tmp_path, template_dir, mock_registry):
        """update_all should process each registered branch."""
        from aipass.spawn.apps.handlers.update_ops import update_all

        # Create a second branch
        branch2 = tmp_path / "other_branch"
        branch2.mkdir()
        (branch2 / "README.md").write_text("# Other")
        (branch2 / "apps").mkdir()
        (branch2 / "tests").mkdir()

        # Add it to registry
        reg = json.loads(mock_registry.read_text())
        rel_path = str(branch2.relative_to(tmp_path))
        reg["branches"].append(
            {
                "name": "OTHER_BRANCH",
                "path": rel_path,
                "profile": "library",
                "description": "Other branch",
                "email": "@other_branch",
                "status": "active",
            }
        )
        mock_registry.write_text(json.dumps(reg, indent=2) + "\n")

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            results = update_all()

        branch_names = [r["branch"] for r in results]
        assert "test_branch" in branch_names
        assert "other_branch" in branch_names
        assert "spawn" not in branch_names


class TestHandleUpdate:
    """Tests for handle_update() CLI parsing."""

    def test_no_args_shows_usage(self):
        """No args should show usage and return 1."""
        from aipass.spawn.apps.modules.update import handle_update

        result = handle_update([])
        assert result == 1

    def test_single_branch_arg(self, tmp_path, template_dir, branch_dir, mock_registry):
        """@branch arg should call update_branch."""
        from aipass.spawn.apps.modules.update import handle_update

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = handle_update(["@test_branch"])

        assert result == 0

    def test_dry_run_flag(self, tmp_path, template_dir, branch_dir, mock_registry):
        """--dry-run flag should be parsed and passed through."""
        from aipass.spawn.apps.modules.update import handle_update

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = handle_update(["--dry-run", "@test_branch"])

        # dry-run should succeed (exit 0) and not create branch_meta
        assert result == 0
        meta_path = branch_dir / ".spawn" / ".branch_meta.json"
        assert not meta_path.exists()

    def test_all_flag_requires_class(self, tmp_path, template_dir, branch_dir, mock_registry):
        """--all without a citizen class should be blocked."""
        from aipass.spawn.apps.modules.update import handle_update

        result = handle_update(["--all"])
        assert result == 1

    def test_all_flag_with_class(self, tmp_path, template_dir, branch_dir, mock_registry):
        """--all with a citizen class should trigger update_all."""
        from aipass.spawn.apps.modules.update import handle_update

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = handle_update(["aipass_framework", "--all"])

        assert result == 0
