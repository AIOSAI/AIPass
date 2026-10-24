# =================== META ====================
# Name: test_update.py
# Description: Tests for spawn update orchestrator
# Version: 1.2.4
# Created: 2026-03-07
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/update_ops.py — the spawn update orchestrator."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that update_ops.py, update_ignore.py, and modules/update.py parse and import cleanly
# seedgo: no-test-needed(documentation) — that the public functions in those modules carry docstrings

import json
from unittest.mock import patch

import pytest

from aipass.spawn.apps.handlers.update_ignore import UpdateIgnoreUnreadable, read_ignore
from aipass.spawn.apps.handlers.update_ops import update_all, update_branch
from aipass.spawn.apps.modules.update import handle_update


@pytest.fixture
def template_dir(tmp_path):
    """Create a minimal template directory with registry."""
    tpl = tmp_path / "template"
    tpl.mkdir()

    (tpl / "README.md").write_text("# {{BRANCHNAME}}\nTemplate readme\n", encoding="utf-8")
    (tpl / "DASHBOARD.local.json").write_text(
        json.dumps({"status": "active", "branch": "{{branchname}}", "version": "1.0"}, indent=2),
        encoding="utf-8",
    )
    (tpl / "apps").mkdir()
    (tpl / "apps" / "__init__.py").write_text('"""{{branchname}} apps"""', encoding="utf-8")
    (tpl / "apps" / "branch.py").write_text('"""{{branchname}} entry point"""\ndef main(): pass\n', encoding="utf-8")
    (tpl / "tests").mkdir()
    (tpl / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (tpl / ".archive").mkdir()
    (tpl / "docs").mkdir()

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

    (spawn_meta / ".template_registry.json").write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

    return tpl


@pytest.fixture
def branch_dir(tmp_path):
    """Create a minimal existing branch directory (pre-update)."""
    branch = tmp_path / "test_branch"
    branch.mkdir()

    (branch / "README.md").write_text("# TEST_BRANCH\nCustom readme with user edits\n", encoding="utf-8")
    (branch / "DASHBOARD.local.json").write_text(
        json.dumps({"status": "running", "branch": "test_branch", "custom_key": "preserved"}, indent=2),
        encoding="utf-8",
    )
    (branch / "apps").mkdir()
    (branch / "apps" / "__init__.py").write_text('"""test_branch apps - modified"""', encoding="utf-8")
    (branch / "apps" / "branch.py").write_text(
        '"""test_branch entry"""\ndef main():\n    print("hello")\n', encoding="utf-8"
    )
    (branch / "tests").mkdir()
    (branch / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (branch / ".archive").mkdir()
    (branch / "docs").mkdir()
    (branch / ".spawn").mkdir()

    # Update reads the class from the passport (no fallback); allowlist-complete so no heal diff fires.
    (branch / ".trinity").mkdir()
    (branch / ".trinity" / "passport.json").write_text(
        json.dumps(
            {
                "branch_info": {
                    "branch_name": "test_branch",
                    "email": "@test_branch",
                    "git_branch": "dev",
                },
                "identity": {"citizen_class": "specialist", "role": "test", "traits": []},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return branch


@pytest.fixture
def mock_registry(tmp_path, branch_dir):
    """Create a mock AIPASS_REGISTRY.json pointing to our test branch."""
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
    reg_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

    return reg_path


def _hash_content(content: str) -> str:
    """Compute SHA-256 hash (first 12 chars) of content string."""
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


class TestUpdateBranch:
    """Tests for update_branch()."""

    def test_first_time_adoption_generates_meta(self, tmp_path, template_dir, branch_dir, mock_registry):
        """Branch with no .branch_meta.json should get one generated."""
        meta_path = branch_dir / ".spawn" / ".branch_meta.json"
        assert not meta_path.exists()

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert result["success"] is True
        assert result["branch"] == "test_branch"
        assert meta_path.exists()

    def test_dry_run_does_not_modify(self, tmp_path, template_dir, branch_dir, mock_registry):
        """Dry run should report changes without modifying files."""
        readme_before = (branch_dir / "README.md").read_text(encoding="utf-8")
        dashboard_before = (branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8")

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch", dry_run=True)

        assert result["success"] is True
        assert result["dry_run"] is True

        assert (branch_dir / "README.md").read_text(encoding="utf-8") == readme_before
        assert (branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8") == dashboard_before

        meta_path = branch_dir / ".spawn" / ".branch_meta.json"
        assert not meta_path.exists()

    def test_py_files_never_overwritten(self, tmp_path, template_dir, branch_dir, mock_registry):
        """Python files should be skipped even when template hash differs."""
        spawn_dir = branch_dir / ".spawn"
        spawn_dir.mkdir(exist_ok=True)

        branch_py_content = '"""test_branch entry"""\ndef main():\n    print("hello")\n'
        original_content = branch_py_content

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert (branch_dir / "apps" / "branch.py").read_text(encoding="utf-8") == original_content
        assert result["success"] is True

    def test_json_deep_merge_preserves_existing(self, tmp_path, template_dir, branch_dir, mock_registry):
        """JSON merge should add new template keys while preserving existing values."""
        spawn_dir = branch_dir / ".spawn"
        spawn_dir.mkdir(exist_ok=True)

        (template_dir / "DASHBOARD.local.json").write_text(
            json.dumps(
                {
                    "status": "active",
                    "branch": "{{branchname}}",
                    "version": "2.0",
                    "new_field": "from_template",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        reg_path = template_dir / ".spawn" / ".template_registry.json"
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        reg["files"]["f002"]["content_hash"] = "different_hash"
        reg_path.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert result["success"] is True

        merged = json.loads((branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8"))

        assert merged["custom_key"] == "preserved"
        assert merged["status"] == "running"  # existing value kept over template
        assert merged["branch"] == "test_branch"  # existing value kept

    def test_branch_not_found(self, tmp_path, template_dir, mock_registry):
        """Non-existent branch should return failure."""
        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("nonexistent_branch")

        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_additions_from_template(self, tmp_path, template_dir, branch_dir, mock_registry):
        """New template files not in branch should be added."""
        (template_dir / "docs" / "new_doc.md").write_text("# New doc for {{branchname}}", encoding="utf-8")

        reg_path = template_dir / ".spawn" / ".template_registry.json"
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        reg["files"]["f099"] = {
            "current_name": "new_doc.md",
            "path": "docs/new_doc.md",
            "content_hash": _hash_content("# New doc for {{branchname}}"),
            "has_branch_placeholder": True,
        }
        reg_path.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert result["success"] is True
        assert result["additions"] >= 1

        new_file = branch_dir / "docs" / "new_doc.md"
        assert new_file.exists()
        content = new_file.read_text(encoding="utf-8")
        assert "{{branchname}}" not in content
        assert "test_branch" in content

    def test_extra_files_not_pruned(self, tmp_path, template_dir, branch_dir, mock_registry):
        """P1 engine never prunes — extra branch files are left untouched."""
        extra_file = branch_dir / "old_config.json"
        extra_file.write_text(json.dumps({"old": True}), encoding="utf-8")

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
        trinity_tpl = template_dir / ".trinity"
        trinity_tpl.mkdir(exist_ok=True)
        (trinity_tpl / "local.json").write_text('{"sessions": []}', encoding="utf-8")

        trinity_branch = branch_dir / ".trinity"
        (trinity_branch / "local.json").write_text('{"sessions": [{"id": 1}]}', encoding="utf-8")
        local_before = (trinity_branch / "local.json").read_text(encoding="utf-8")

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert result["success"] is True
        assert (trinity_branch / "local.json").read_text(encoding="utf-8") == local_before

    def test_passport_identity_content_never_touched_by_heal(self, tmp_path, template_dir, branch_dir, mock_registry):
        """passport.json heals allowlisted fields only — role/purpose/etc. stay create-only,
        and on a complete passport existing always wins, even on allowlisted fields."""
        trinity_tpl = template_dir / ".trinity"
        trinity_tpl.mkdir(exist_ok=True)
        (trinity_tpl / "passport.json").write_text(
            json.dumps(
                {
                    "branch_info": {"email": "@template_default", "git_branch": "work/template_default"},
                    "identity": {"role": "template_role_should_not_apply", "traits": "should_not_apply"},
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        trinity_branch = branch_dir / ".trinity"
        passport_before = (trinity_branch / "passport.json").read_text(encoding="utf-8")

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert result["success"] is True
        assert (trinity_branch / "passport.json").read_text(encoding="utf-8") == passport_before

    def test_dashboard_never_touched(self, tmp_path, template_dir, branch_dir, mock_registry):
        """Update must never modify DASHBOARD.local.json even when template differs."""
        dashboard = branch_dir / "DASHBOARD.local.json"
        dashboard_before = dashboard.read_text(encoding="utf-8")

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert result["success"] is True
        assert dashboard.read_text(encoding="utf-8") == dashboard_before

    def test_ai_mail_local_inbox_never_touched(self, tmp_path, template_dir, branch_dir, mock_registry):
        """Update must never merge into .ai_mail.local/inbox.json — it is a branch's
        live mailbox; the template's new key makes any deep-merge touch detectable."""
        mail_tpl = template_dir / ".ai_mail.local"
        mail_tpl.mkdir(exist_ok=True)
        (mail_tpl / "inbox.json").write_text(
            json.dumps(
                {"mailbox": "inbox", "total_messages": 0, "unread_count": 0, "messages": [], "schema_version": 2},
                indent=2,
            ),
            encoding="utf-8",
        )

        mail_branch = branch_dir / ".ai_mail.local"
        mail_branch.mkdir(exist_ok=True)
        inbox = mail_branch / "inbox.json"
        inbox.write_text(
            json.dumps(
                {
                    "mailbox": "inbox",
                    "total_messages": 3,
                    "unread_count": 1,
                    "messages": [{"id": "m1", "from": "@someone", "subject": "hi"}],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        inbox_before = inbox.read_text(encoding="utf-8")

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert result["success"] is True
        assert inbox.read_text(encoding="utf-8") == inbox_before

    def test_scaffold_test_never_re_added(self, tmp_path, template_dir, branch_dir, mock_registry):
        """tests/test_scaffold.py is create-only — a branch that deleted it never gets it back.

        The .py skip only guards existing files; a re-added scaffold would be a permanently inert test.
        """
        tests_tpl = template_dir / "tests"
        tests_tpl.mkdir(exist_ok=True)
        (tests_tpl / "test_scaffold.py").write_text("def test_scaffold(): pass\n", encoding="utf-8")

        branch_tests = branch_dir / "tests"
        branch_tests.mkdir(exist_ok=True)
        (branch_tests / "test_real_suite.py").write_text("def test_real(): pass\n", encoding="utf-8")

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch")

        assert result["success"] is True
        assert not (branch_tests / "test_scaffold.py").exists()
        added = [a["template_path"] for a in result.get("additions_detail", [])]
        assert "tests/test_scaffold.py" not in added

    def test_zero_renames_always(self, tmp_path, template_dir, branch_dir, mock_registry):
        """P1 engine never proposes renames."""
        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = update_branch("test_branch", dry_run=True)

        assert result["renames"] == 0
        assert result.get("_renames_detail", []) == []

    def test_backup_lands_in_spawn_recovery(self, tmp_path, template_dir, branch_dir, mock_registry):
        """JSON merge backups should land in .spawn/.recovery/, not branch root .recovery/."""
        config_tpl = template_dir / "config.json"
        config_tpl.write_text(json.dumps({"version": "2.0", "new_key": "added"}, indent=2), encoding="utf-8")
        config_branch = branch_dir / "config.json"
        config_branch.write_text(json.dumps({"version": "1.0"}, indent=2), encoding="utf-8")

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


class TestMarkdownIsReportedAndNeverWritten:
    """`.md` drift: update says what it sees and writes nothing (DPLAN-0347).

    A report, not a write: README content is the owner's judgment, and an unguarded overwrite is a known bug."""

    def _update(self, template_dir, mock_registry, dry_run=True):
        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            return update_branch("test_branch", dry_run=dry_run)

    def _states(self, result):
        return {entry["branch_path"]: entry["state"] for entry in result["_md_detail"]}

    def test_an_edited_readme_reports_as_differs(self, template_dir, branch_dir, mock_registry):
        """The branch fixture's README is hand-edited — the fleet's own condition."""
        result = self._update(template_dir, mock_registry)

        assert self._states(result)["README.md"] == "differs"
        assert result["md_differs"] == 1

    def test_a_readme_still_as_the_template_renders_it_reports_as_matches(
        self, template_dir, branch_dir, mock_registry
    ):
        """Rendered, not raw: the comparison resolves placeholders first."""
        (branch_dir / "README.md").write_text("# TEST_BRANCH\nTemplate readme\n", encoding="utf-8")

        result = self._update(template_dir, mock_registry)

        assert self._states(result)["README.md"] == "matches"
        assert result["md_differs"] == 0
        assert result["md_matches"] == 1

    def test_a_missing_md_is_added_and_reports_as_absent(self, template_dir, branch_dir, mock_registry):
        """A missing file is still an addition — the report names why it was written."""
        (branch_dir / "README.md").unlink()

        result = self._update(template_dir, mock_registry, dry_run=False)

        assert self._states(result)["README.md"] == "absent"
        assert (branch_dir / "README.md").read_text(encoding="utf-8") == "# TEST_BRANCH\nTemplate readme\n"

    def test_an_apply_never_rewrites_an_existing_md(self, template_dir, branch_dir, mock_registry):
        """--apply is the dangerous world, so the pin lives there: byte-identical after."""
        before = (branch_dir / "README.md").read_text(encoding="utf-8")

        result = self._update(template_dir, mock_registry, dry_run=False)

        assert (branch_dir / "README.md").read_text(encoding="utf-8") == before
        assert result["md_differs"] == 1
        assert not list(branch_dir.glob("README.md.*backup*")), "a .md was backed up, which means it was written"

    def test_an_unreadable_md_is_reported_as_unreadable_not_guessed(self, template_dir, branch_dir, mock_registry):
        """Undecodable bytes are their own answer — never reported as drift."""
        (branch_dir / "README.md").write_bytes(b"\xff\xfe\x00broken")

        result = self._update(template_dir, mock_registry)

        assert self._states(result)["README.md"] == "unreadable"
        assert result["md_unreadable"] == 1
        assert result["md_differs"] == 0

    def test_an_owner_protected_md_is_not_even_compared(self, template_dir, branch_dir, mock_registry):
        """`.updateignore` still runs first: protected means unseen, not reported."""
        (branch_dir / ".updateignore").write_text("README.md\n", encoding="utf-8")

        result = self._update(template_dir, mock_registry)

        assert result["owner_protected"] == 1
        assert "README.md" not in self._states(result)


class TestUpdateIgnoreIsTheOwnersDecision:
    """`.updateignore` at a branch root — the owner decides what update skips.

    Same contract as `aipass init update` at project roots, so an owner learns it once."""

    def _ignore(self, branch_dir, text):
        (branch_dir / ".updateignore").write_text(text, encoding="utf-8")

    def _update(self, template_dir, mock_registry, dry_run=True):
        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            return update_branch("test_branch", dry_run=dry_run)

    def test_absent_file_protects_nothing(self, tmp_path, template_dir, branch_dir, mock_registry):
        """No `.updateignore` is the world every branch is in today — nothing protected."""
        assert not (branch_dir / ".updateignore").exists()

        result = self._update(template_dir, mock_registry)

        assert result["owner_protected"] == 0
        assert result["_ignored_detail"] == []

    def test_a_named_file_moves_from_written_to_owner_protected(
        self, tmp_path, template_dir, branch_dir, mock_registry
    ):
        """The whole point, measured as a MOVE: the same file, both worlds.

        The unprotected run is the control: the template must be offering the file at all."""
        (branch_dir / "README.md").unlink()
        before = self._update(template_dir, mock_registry)
        offered = [a["template_path"] for a in before["_additions_detail"]]
        assert "README.md" in offered, "control: the template must be offering this file"
        assert before["owner_protected"] == 0

        self._ignore(branch_dir, "README.md\n")
        after = self._update(template_dir, mock_registry)

        assert after["owner_protected"] == 1
        assert [g["branch_path"] for g in after["_ignored_detail"]] == ["README.md"]
        assert "README.md" not in [a["template_path"] for a in after["_additions_detail"]]

    def test_a_protected_file_is_never_written(self, tmp_path, template_dir, branch_dir, mock_registry):
        """--apply must not create it either. Byte-for-byte, the file stays absent."""
        (branch_dir / "README.md").unlink()
        self._ignore(branch_dir, "README.md\n")

        result = self._update(template_dir, mock_registry, dry_run=False)

        assert result["success"] is True
        assert result["owner_protected"] == 1
        assert not (branch_dir / "README.md").exists(), "an owner-protected file was written by --apply"

    def test_a_protected_json_is_never_merged_and_never_backed_up(
        self, tmp_path, template_dir, branch_dir, mock_registry
    ):
        """Never written, never merged, never backed up — the third clause has its own pin."""
        dashboard = branch_dir / "DASHBOARD.local.json"
        before = dashboard.read_text(encoding="utf-8")
        self._ignore(branch_dir, "DASHBOARD.local.json\n")

        result = self._update(template_dir, mock_registry, dry_run=False)

        assert result["owner_protected"] == 1
        assert dashboard.read_text(encoding="utf-8") == before
        recovery = branch_dir / ".spawn" / ".recovery"
        copies = list(recovery.rglob("*DASHBOARD*")) if recovery.exists() else []
        assert copies == [], f"an owner-protected file was backed up: {copies}"

    def test_the_passport_is_protected_before_the_heal_can_reach_it(
        self, tmp_path, template_dir, branch_dir, mock_registry
    ):
        """@vera's case. The heal runs BEFORE the create-only guard, so ignore must run before both."""
        template_passport = template_dir / ".trinity"
        template_passport.mkdir()
        (template_passport / "passport.json").write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "{{branchname}}", "email": "@{{branchname}}", "git_branch": "dev"},
                    "identity": {"citizen_class": "specialist", "role": "template", "traits": ["generic"]},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        passport = branch_dir / ".trinity" / "passport.json"
        document = json.loads(passport.read_text(encoding="utf-8"))
        del document["branch_info"]["email"]
        passport.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        before = passport.read_text(encoding="utf-8")

        control = self._update(template_dir, mock_registry)
        assert ".trinity/passport.json" in [u["branch_path"] for u in control["_updates_detail"]], (
            "control: the heal must be proposing a merge, or this pin proves nothing"
        )

        self._ignore(branch_dir, ".trinity/passport.json\n")
        result = self._update(template_dir, mock_registry, dry_run=False)

        assert result["owner_protected"] == 1
        assert [g["branch_path"] for g in result["_ignored_detail"]] == [".trinity/passport.json"]
        assert passport.read_text(encoding="utf-8") == before, "the heal reached an owner-protected passport"

    def test_a_directory_pattern_takes_everything_under_it(self, tmp_path, template_dir, branch_dir, mock_registry):
        """A trailing slash means the directory and everything below it, at any depth."""
        nested = template_dir / "docs" / "sub"
        nested.mkdir(parents=True)
        (template_dir / "docs" / "guide.md").write_text("# guide\n", encoding="utf-8")
        (nested / "deep.md").write_text("# deep\n", encoding="utf-8")

        self._ignore(branch_dir, "docs/\n")
        result = self._update(template_dir, mock_registry)

        protected = sorted(g["branch_path"] for g in result["_ignored_detail"])
        assert protected == ["docs/guide.md", "docs/sub/deep.md"]
        assert not any(a["template_path"].startswith("docs/") for a in result["_additions_detail"])

    def test_comments_and_blank_lines_are_not_patterns(self, tmp_path, template_dir, branch_dir, mock_registry):
        """The parsed PATTERN LIST, not just its downstream effect.

        A `#` is a literal to fnmatch, so a comment kept as a pattern never matches and hides one layer down.
        """
        self._ignore(
            branch_dir,
            "# README.md is the owner's, or would be\n\n   \n  DASHBOARD.local.json  \n\t\n# trailing note\n",
        )

        assert read_ignore(branch_dir) == ["DASHBOARD.local.json"]

        result = self._update(template_dir, mock_registry)

        assert result["owner_protected"] == 1
        assert [g["branch_path"] for g in result["_ignored_detail"]] == ["DASHBOARD.local.json"]

    def test_a_bare_name_matches_at_any_depth(self, tmp_path, template_dir, branch_dir, mock_registry):
        """A pattern with no slash claims that filename wherever it sits.

        Removing this arm leaves every other pin in the class green, so the target here sits at depth."""
        nested = template_dir / "docs" / "deep"
        nested.mkdir(parents=True)
        (nested / "notes.md").write_text("# nested\n", encoding="utf-8")
        (template_dir / "notes.md").write_text("# root\n", encoding="utf-8")

        self._ignore(branch_dir, "notes.md\n")
        result = self._update(template_dir, mock_registry)

        protected = sorted(g["branch_path"] for g in result["_ignored_detail"])
        assert protected == ["docs/deep/notes.md", "notes.md"], (
            "a bare name must claim the nested copy as well as the root one"
        )
        assert not any(a["template_path"].endswith("notes.md") for a in result["_additions_detail"])

    def test_a_pattern_with_a_slash_claims_only_that_path(self, tmp_path, template_dir, branch_dir, mock_registry):
        """The other half of the depth rule: naming a path must not widen to a basename."""
        nested = template_dir / "docs" / "deep"
        nested.mkdir(parents=True)
        (nested / "notes.md").write_text("# nested\n", encoding="utf-8")
        (template_dir / "notes.md").write_text("# root\n", encoding="utf-8")

        self._ignore(branch_dir, "docs/deep/notes.md\n")
        result = self._update(template_dir, mock_registry)

        assert [g["branch_path"] for g in result["_ignored_detail"]] == ["docs/deep/notes.md"]
        assert "notes.md" in [a["template_path"] for a in result["_additions_detail"]], (
            "the root copy shares a basename and was never named — it must still be written"
        )

    def test_a_commented_out_name_is_still_written(self, tmp_path, template_dir, branch_dir, mock_registry):
        """The owner's escape hatch: comment the line out and the file comes back."""
        (branch_dir / "README.md").unlink()
        self._ignore(branch_dir, "# README.md\n")

        result = self._update(template_dir, mock_registry)

        assert result["owner_protected"] == 0
        assert "README.md" in [a["template_path"] for a in result["_additions_detail"]]

    def test_spawn_never_creates_or_modifies_the_ignore_file(self, tmp_path, template_dir, branch_dir, mock_registry):
        """It is the owner's file. An update must leave it exactly as it found it."""
        self._ignore(branch_dir, "README.md\n")
        path = branch_dir / ".updateignore"
        before = path.read_text(encoding="utf-8")

        self._update(template_dir, mock_registry, dry_run=False)

        assert path.read_text(encoding="utf-8") == before

    @staticmethod
    def _tree(root):
        return {p.relative_to(root): (p.read_bytes() if p.is_file() else None) for p in root.rglob("*")}

    def test_an_unreadable_ignore_file_refuses_the_update_and_writes_nothing(
        self, tmp_path, template_dir, branch_dir, mock_registry
    ):
        """A claim that cannot be read protects nothing, so the update refuses whole."""
        (branch_dir / "README.md").unlink()
        (branch_dir / ".updateignore").write_bytes(b"\xff\xfe README.md")
        before = self._tree(branch_dir)
        registry_before = mock_registry.read_bytes()

        with pytest.raises(UpdateIgnoreUnreadable, match=r"\.updateignore"):
            self._update(template_dir, mock_registry, dry_run=False)

        assert self._tree(branch_dir) == before
        assert mock_registry.read_bytes() == registry_before

    def test_update_all_goes_on_past_a_branch_whose_ignore_file_is_unreadable(
        self, tmp_path, template_dir, branch_dir, mock_registry
    ):
        """One refused branch is a failed row; the next branch is still updated."""
        (branch_dir / ".updateignore").write_bytes(b"\xff\xfe README.md")
        other = tmp_path / "other_branch"
        (other / ".trinity").mkdir(parents=True)
        (other / ".trinity" / "passport.json").write_bytes((branch_dir / ".trinity" / "passport.json").read_bytes())
        reg = json.loads(mock_registry.read_text(encoding="utf-8"))
        reg["branches"].append({"name": "OTHER_BRANCH", "path": "other_branch", "status": "active"})
        mock_registry.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")
        before = self._tree(branch_dir)

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            results = {r["branch"]: r for r in update_all(dry_run=False)}

        assert results["test_branch"]["success"] is False
        assert ".updateignore" in results["test_branch"]["errors"][0]
        assert self._tree(branch_dir) == before
        assert results["other_branch"]["success"] is True
        assert (other / "README.md").is_file()


class TestUpdateNeverJudgesASandbox:
    """A living branch's dropbox and .archive are never read, compared or merged.

    What the template ships there is still handed in when absent. The world sits under a dir
    named dropbox because the skip must read only the parts below the branch root."""

    _TEMPLATE = {
        "README.md": "# {{BRANCHNAME}}\nTemplate readme\n",
        "dropbox/README.md": "# Dropbox\nHanded in here.\n",
        ".archive/README.md": "# Archive\nRetired things.\n",
        ".archive/notes.json": json.dumps({"kept": 1, "template_key": 2}),
        "docs/.archive/old.md": "# Old\nShipped retired page.\n",
    }

    def _world(self, tmp_path):
        """A template and a living branch under tmp_path/dropbox, with a registry."""
        root = tmp_path / "dropbox"
        tpl = root / "template"
        for rel, text in self._TEMPLATE.items():
            (tpl / rel).parent.mkdir(parents=True, exist_ok=True)
            (tpl / rel).write_text(text, encoding="utf-8")
        branch = root / "test_branch"
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".spawn").mkdir()
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps({"identity": {"citizen_class": "specialist", "role": "test", "traits": []}}), encoding="utf-8"
        )
        registry = root / "AIPASS_REGISTRY.json"
        entry = {"name": "TEST_BRANCH", "path": "test_branch", "email": "@test_branch", "status": "active"}
        registry.write_text(json.dumps({"metadata": {}, "branches": [entry]}), encoding="utf-8")
        return tpl, branch, registry

    def _update(self, tpl, registry):
        with patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=tpl):
            return update_branch("test_branch", dry_run=False, registry_path=registry)

    def test_a_present_dropbox_or_archive_file_is_neither_reported_nor_merged(self, tmp_path):
        """Both READMEs must not report as differs, nor notes.json merge."""
        tpl, branch, registry = self._world(tmp_path)
        planted = {
            "README.md": "# TEST_BRANCH\nEdited by its owner\n",
            "dropbox/README.md": "# Dropbox\nChanged by the branch\n",
            ".archive/README.md": "# Archive\nChanged too\n",
            ".archive/notes.json": json.dumps({"kept": 1}),
            "docs/.archive/old.md": "# Old\nA nested archive, changed\n",
        }
        for rel, text in planted.items():
            (branch / rel).parent.mkdir(parents=True, exist_ok=True)
            (branch / rel).write_text(text, encoding="utf-8")

        result = self._update(tpl, registry)

        assert result["success"] is True, result
        # The control: the live README beside them is still judged.
        assert [(e["branch_path"], e["state"]) for e in result["_md_detail"]] == [("README.md", "differs")]
        assert result["updates"] == 0
        for rel, text in planted.items():
            assert (branch / rel).read_text(encoding="utf-8") == text, rel

    def test_an_absent_dropbox_is_created_with_its_shipped_readme(self, tmp_path):
        """Handing a file in is what the place is for: directory absent, both land."""
        tpl, branch, registry = self._world(tmp_path)

        self._update(tpl, registry)

        assert (branch / "dropbox" / "README.md").read_text(encoding="utf-8") == self._TEMPLATE["dropbox/README.md"]

    def test_an_absent_shipped_file_in_a_present_archive_is_written(self, tmp_path):
        """The directory is there, the shipped README is not: it is written, nothing else is touched."""
        tpl, branch, registry = self._world(tmp_path)
        (branch / ".archive").mkdir()
        (branch / ".archive" / "notes.json").write_text(json.dumps({"kept": 1}), encoding="utf-8")

        self._update(tpl, registry)

        assert (branch / ".archive" / "README.md").read_text(encoding="utf-8") == self._TEMPLATE[".archive/README.md"]
        assert json.loads((branch / ".archive" / "notes.json").read_text(encoding="utf-8")) == {"kept": 1}


class TestUpdateAll:
    """Tests for update_all()."""

    def test_update_all_skips_spawn(self, tmp_path, template_dir, branch_dir, mock_registry):
        """update_all should skip spawn itself."""
        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            results = update_all()

        branch_names = [r["branch"] for r in results]
        assert "spawn" not in branch_names
        assert "test_branch" in branch_names

    def test_update_all_processes_all_branches(self, tmp_path, template_dir, mock_registry):
        """update_all should process each registered branch."""
        branch2 = tmp_path / "other_branch"
        branch2.mkdir()
        (branch2 / "README.md").write_text("# Other", encoding="utf-8")
        (branch2 / "apps").mkdir()
        (branch2 / "tests").mkdir()

        reg = json.loads(mock_registry.read_text(encoding="utf-8"))
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
        mock_registry.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            results = update_all()

        branch_names = [r["branch"] for r in results]
        assert "test_branch" in branch_names
        assert "other_branch" in branch_names
        assert "spawn" not in branch_names

    def test_a_class_filtered_run_turns_an_unreadable_passport_into_a_failed_row(
        self, tmp_path, template_dir, branch_dir, mock_registry
    ):
        """Pins the abort: the class read sat outside the per-branch try, so one bad passport ended the run."""
        broken = tmp_path / "broken_branch"
        (broken / ".trinity").mkdir(parents=True)
        (broken / ".trinity" / "passport.json").write_text("{not json", encoding="utf-8")
        reg = json.loads(mock_registry.read_text(encoding="utf-8"))
        reg["branches"].insert(0, {"name": "BROKEN_BRANCH", "path": "broken_branch", "status": "active"})
        mock_registry.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")

        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            results = {r["branch"]: r for r in update_all(citizen_class="specialist")}

        assert results["broken_branch"]["success"] is False
        assert "passport.json" in results["broken_branch"]["errors"][0]
        assert results["test_branch"]["success"] is True


class TestHandleUpdate:
    """Tests for handle_update() CLI parsing."""

    def test_no_args_shows_usage(self):
        """No args should show usage and return 1."""
        result = handle_update([])
        assert result == 1

    def test_failed_dry_run_prints_no_raw_markup(self, capsys, tmp_path, template_dir, mock_registry):
        """The failure line must not leak literal Rich tags.

        error() writes plain text, so a marker built for console.print() would leak its tags.
        """
        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            handle_update(["@no_such_branch"])

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "Update FAILED" in combined
        assert "[dim]" not in combined
        assert "[/dim]" not in combined
        assert "(dry-run)" in combined

    def test_single_branch_arg(self, tmp_path, template_dir, branch_dir, mock_registry):
        """@branch arg should call update_branch."""
        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = handle_update(["@test_branch"])

        assert result == 0

    def test_dry_run_flag(self, tmp_path, template_dir, branch_dir, mock_registry):
        """--dry-run flag should be parsed and passed through."""
        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = handle_update(["--dry-run", "@test_branch"])

        assert result == 0
        meta_path = branch_dir / ".spawn" / ".branch_meta.json"
        assert not meta_path.exists()

    def test_all_flag_requires_class(self, tmp_path, template_dir, branch_dir, mock_registry):
        """--all without a citizen class should be blocked."""
        result = handle_update(["--all"])
        assert result == 1

    def test_all_flag_with_class(self, tmp_path, template_dir, branch_dir, mock_registry):
        """--all with a citizen class should trigger update_all."""
        with (
            patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=template_dir),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=mock_registry),
        ):
            result = handle_update(["specialist", "--all"])

        assert result == 0


def _one_file_world(tmp_path, rel, template_text, existing_text):
    """A template holding ONE file at *rel*, and a branch holding its own copy.

    Adds a minimal passport when *rel* is not it (update reads the class first). Returns (registry, dest).
    """
    (tmp_path / "template" / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "template" / rel).write_text(template_text, encoding="utf-8")
    dest = tmp_path / "test_branch" / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(existing_text, encoding="utf-8")
    passport = tmp_path / "test_branch" / ".trinity" / "passport.json"
    if not passport.exists():
        passport.parent.mkdir(parents=True, exist_ok=True)
        passport.write_text(json.dumps({"identity": {"citizen_class": "specialist"}}), encoding="utf-8")
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text(json.dumps({"branches": [{"name": "TEST_BRANCH", "path": "test_branch"}]}), encoding="utf-8")
    return registry, dest


def _update_verdict(tmp_path, registry, rel):
    """Run the public update once; answer what it did to *rel*: updated, unchanged or error."""
    with patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=tmp_path / "template"):
        result = update_branch("test_branch", dry_run=False, registry_path=registry)
    if result["errors"]:
        return "error"
    return "updated" if rel in [d["branch_path"] for d in result["_updates_detail"]] else "unchanged"


class TestPassportHealIsNotAMigration:
    """FPLAN-0492: the heal repairs three derived fields; it never changes schema.

    All three allowlisted fields exist in schema 1.0.0 and 2.0.0; a 2.0-only field added to the
    allowlist would half-migrate every 1.0 passport. Migration is ``migrate-passports``' job.
    """

    SCHEMA_1_PASSPORT = {
        "document_metadata": {"schema_version": "1.0.0", "version": "1.0.0"},
        "branch_info": {"branch_name": "legacy", "email": "@legacy", "git_branch": "main"},
        "identity": {"citizen_class": "manager", "role": "archivist", "traits": ["careful"]},
        "principles": ["Top-level, the 1.0 shape", "Seven of these in the real thing"],
    }

    def _heal(self, tmp_path, template_passport, existing_passport):
        rel = ".trinity/passport.json"
        registry, dest = _one_file_world(
            tmp_path, rel, json.dumps(template_passport, indent=2), json.dumps(existing_passport, indent=2) + "\n"
        )
        result = _update_verdict(tmp_path, registry, rel)
        return result, json.loads(dest.read_text(encoding="utf-8"))

    def test_a_schema_1_passport_gains_no_2_0_fields_and_no_bump(self, tmp_path):
        """The whole half-migration claim, as a pin: no new keys, no schema change."""
        template = {
            "document_metadata": {"schema_version": "2.0.0", "version": "2.0.0"},
            "branch_info": {"email": "@template", "git_branch": "dev"},
            "citizenship": {"residency": "resident", "citizen_id": ""},
            "identity": {"traits": [], "principles": ["Code is truth - fail honestly"]},
        }

        result, healed = self._heal(tmp_path, template, self.SCHEMA_1_PASSPORT)

        assert result == "unchanged"
        assert healed["document_metadata"]["schema_version"] == "1.0.0"
        assert "principles" not in healed["identity"]
        assert "citizenship" not in healed
        assert healed == self.SCHEMA_1_PASSPORT

    # Carries 2.0-only fields too, so a heal reaching past the allowlist shows as an added path.
    TEMPLATE_2_0 = {
        "document_metadata": {"schema_version": "2.0.0", "version": "2.0.0"},
        "branch_info": {"email": "@template", "git_branch": "dev"},
        "citizenship": {"residency": "resident", "citizen_id": ""},
        "identity": {"traits": ["templated"], "principles": ["Code is truth - fail honestly"]},
    }

    def _without(self, missing):
        """SCHEMA_1_PASSPORT with each (section, key) in *missing* removed."""
        return {
            section: {k: v for k, v in body.items() if (section, k) not in missing} if isinstance(body, dict) else body
            for section, body in self.SCHEMA_1_PASSPORT.items()
        }

    @staticmethod
    def _paths(document):
        """Every (section, key) a document holds; a non-dict top-level value is (section,)."""
        paths = set()
        for section, body in document.items():
            if isinstance(body, dict):
                paths.update((section, key) for key in body)
            else:
                paths.add((section,))
        return paths

    @pytest.mark.parametrize("field", [("branch_info", "email"), ("branch_info", "git_branch"), ("identity", "traits")])
    def test_a_missing_allowlisted_field_is_healed_and_nothing_else(self, tmp_path, field):
        """Each field the heal allowlist names is one a schema-1.0.0 passport has, and heals alone.

        Pinned through update_branch, not the allowlist tuple: a dropped field leaves this case red.
        """
        existing = self._without({field})

        result, healed = self._heal(tmp_path, self.TEMPLATE_2_0, existing)

        assert result == "updated"
        section, key = field
        assert healed[section][key] == self.TEMPLATE_2_0[section][key]
        assert healed["document_metadata"]["schema_version"] == "1.0.0"
        assert self._paths(healed) - self._paths(existing) == {field}

    def test_the_heal_adds_exactly_the_three_allowlisted_fields(self, tmp_path):
        """The floor: with all three missing, the heal adds those three paths and no other.

        An allowlist that grew adds a 2.0-only path; one that shrank adds fewer. Either way red.
        """
        three = {("branch_info", "email"), ("branch_info", "git_branch"), ("identity", "traits")}
        existing = self._without(three)

        result, healed = self._heal(tmp_path, self.TEMPLATE_2_0, existing)

        assert result == "updated"
        assert self._paths(healed) - self._paths(existing) == three
        assert healed["document_metadata"]["schema_version"] == "1.0.0"

    def test_a_passport_written_with_escapes_is_left_alone(self, tmp_path):
        """An untouched document must not be rewritten because it is SPELLED differently.

        Compares documents, not text: ``ensure_ascii=True`` output differs in spelling, not in fields.
        """
        rel = ".trinity/passport.json"
        template = {"branch_info": {"email": "@t", "git_branch": "dev"}, "identity": {"traits": []}}
        existing = {
            "document_metadata": {"schema_version": "2.0.0"},
            "branch_info": {"email": "@legacy", "git_branch": "main"},
            "identity": {"citizen_class": "specialist", "traits": ["Radical specificity — exact numbers"]},
        }
        registry, dest = _one_file_world(
            tmp_path, rel, json.dumps(template, indent=2), json.dumps(existing, indent=2, ensure_ascii=True) + "\n"
        )
        before = dest.read_bytes()
        assert b"\\u2014" in before, "fixture must carry an escaped character for this to mean anything"

        result = _update_verdict(tmp_path, registry, rel)

        assert result == "unchanged"
        assert dest.read_bytes() == before


class TestTemplateOwnedListsGrow:
    """FPLAN-0492: declared template-owned lists are additive; every other list is not.

    deep_merge keeps a non-empty existing list whole, so later template entries would never arrive."""

    TEMPLATE_IGNORE = {
        "metadata": {"version": "1.3.0"},
        "ignore_files": [".template_registry.json", ".registry_ignore.json", "test_cli_routing.py"],
        "ignore_patterns": ["__pycache__", "*.pyc"],
    }
    BRANCH_IGNORE = {
        "metadata": {"version": "1.1.0"},
        "ignore_files": [".template_registry.json", ".registry_ignore.json"],
        "ignore_patterns": ["__pycache__", "*.pyc"],
    }

    def _merge(self, tmp_path, resolved_path, template_data, existing_data):
        registry, dest = _one_file_world(
            tmp_path, resolved_path, json.dumps(template_data, indent=2), json.dumps(existing_data, indent=2) + "\n"
        )
        result = _update_verdict(tmp_path, registry, resolved_path)
        return result, json.loads(dest.read_text(encoding="utf-8"))

    def test_a_declared_list_receives_the_templates_additions(self, tmp_path):
        result, merged = self._merge(tmp_path, ".spawn/.registry_ignore.json", self.TEMPLATE_IGNORE, self.BRANCH_IGNORE)

        assert result == "updated"
        assert merged["ignore_files"] == [
            ".template_registry.json",
            ".registry_ignore.json",
            "test_cli_routing.py",
        ]

    def test_the_branchs_own_entries_and_their_order_survive(self, tmp_path):
        existing = dict(self.BRANCH_IGNORE, ignore_files=["branch_only.json", ".template_registry.json"])

        _result, merged = self._merge(tmp_path, ".spawn/.registry_ignore.json", self.TEMPLATE_IGNORE, existing)

        assert merged["ignore_files"][:2] == ["branch_only.json", ".template_registry.json"]
        assert set(merged["ignore_files"]) == set(self.TEMPLATE_IGNORE["ignore_files"]) | {"branch_only.json"}
        assert len(merged["ignore_files"]) == len(set(merged["ignore_files"])), "no duplicates"

    def test_a_second_pass_changes_nothing(self, tmp_path):
        rel = ".spawn/.registry_ignore.json"
        registry, _dest = _one_file_world(
            tmp_path, rel, json.dumps(self.TEMPLATE_IGNORE, indent=2), json.dumps(self.BRANCH_IGNORE, indent=2) + "\n"
        )

        first = _update_verdict(tmp_path, registry, rel)
        second = _update_verdict(tmp_path, registry, rel)

        assert (first, second) == ("updated", "unchanged")

    def test_an_undeclared_file_keeps_existing_wins(self, tmp_path):
        """Permissions are NOT additive: a blanket union would re-deny @devpulse's publishing lane."""
        template = {"permissions": {"deny": ["Bash(rm -rf*)", "Bash(commit-ish*)"], "allow": []}}
        existing = {"permissions": {"deny": ["Bash(rm -rf*)"], "allow": ["Bash(ls*)"]}}

        result, merged = self._merge(tmp_path, ".claude/settings.local.json", template, existing)

        assert result == "unchanged"
        assert merged["permissions"]["deny"] == ["Bash(rm -rf*)"]


class TestAuditFixes:
    """ponytail audit 2026-10-24: findings 16, 17 and the update leftovers."""

    def test_a_json_differing_only_in_key_order_is_unchanged_and_not_backed_up(self, tmp_path):
        """Documents, not text: a reordered file once read as "updated" and grew .spawn/.recovery every run."""
        rel = "config.json"
        registry, dest = _one_file_world(
            tmp_path, rel, json.dumps({"a": 1, "b": 2}, indent=2), json.dumps({"b": 2, "a": 1}, indent=2) + "\n"
        )
        before = dest.read_bytes()

        assert _update_verdict(tmp_path, registry, rel) == "unchanged"
        assert dest.read_bytes() == before
        assert not (tmp_path / "test_branch" / ".spawn" / ".recovery").exists()

    @pytest.mark.parametrize("cache", [".pytest_cache", ".ruff_cache", ".mypy_cache"])
    def test_a_template_tool_cache_never_reaches_the_branch(self, tmp_path, cache):
        """The skip set is file_ops.SKIP_NAMES: a cache create never copies, update must not copy either."""
        registry, _dest = _one_file_world(tmp_path, "README.md", "x\n", "x\n")
        (tmp_path / "template" / cache).mkdir()
        (tmp_path / "template" / cache / "CACHEDIR.TAG").write_text("tag\n", encoding="utf-8")

        _update_verdict(tmp_path, registry, cache)

        assert not (tmp_path / "test_branch" / cache).exists()

    def test_the_readme_preview_renders_the_passports_purpose_and_class(self, tmp_path):
        """A README as create rendered it matches: purpose and class come from the passport, not defaults."""
        registry, _dest = _one_file_world(
            tmp_path,
            "README.md",
            "Purpose: {{PURPOSE_BRIEF}}\nClass: {{CITIZEN_CLASS}}\n",
            "Purpose: Ships widgets\nClass: manager\n",
        )
        passport = tmp_path / "test_branch" / ".trinity" / "passport.json"
        passport.write_text(
            json.dumps({"identity": {"citizen_class": "manager", "purpose": "Ships widgets"}}), encoding="utf-8"
        )

        with patch("aipass.spawn.apps.handlers.update_ops.get_template_dir", return_value=tmp_path / "template"):
            result = update_branch("test_branch", dry_run=True, registry_path=registry)

        assert result["_md_detail"] == [{"branch_path": "README.md", "state": "matches"}]

    def test_a_quoted_purpose_never_breaks_the_passport_heal(self, tmp_path):
        """Purpose is free text: rendered into the template passport, a quote would make it unparseable."""
        rel = ".trinity/passport.json"
        existing = {"identity": {"citizen_class": "specialist", "purpose": 'Ships "widgets"', "traits": []}}
        registry, _dest = _one_file_world(
            tmp_path, rel, json.dumps({"identity": {"purpose": "{{PURPOSE_BRIEF}}"}}), json.dumps(existing)
        )

        assert _update_verdict(tmp_path, registry, rel) != "error"

    def test_class_all_with_no_registry_is_an_error_exit(self, tmp_path, monkeypatch, capsys):
        """No registry is not "0 branches, all fine": it exits 1 and says why."""
        monkeypatch.chdir(tmp_path)

        assert handle_update(["specialist", "--all", "--apply"]) == 1
        captured = capsys.readouterr()
        assert "REGISTRY" in captured.out + captured.err
