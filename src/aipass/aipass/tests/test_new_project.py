# =================== AIPass ====================
# Name: test_new_project.py
# Description: Tests for aipass new — project creation handler
# Version: 1.1.7
# Created: 2026-07-17
# Modified: 2026-09-28
# =============================================

"""Tests for apps/handlers/new_project/__init__.py and apps/modules/new_project.py."""

# All file operations use tmp_path to stay fully isolated from the live
# filesystem. Tests mock subprocess calls to avoid real git/drone invocations.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — spawn_agent's own behavior; @spawn's function, mocked here

import functools
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps import aipass as entry
from aipass.aipass.apps.handlers.init.bootstrap import init_project, is_projects_child
from aipass.aipass.apps.handlers.new_project import (
    _git_init,
    create_project,
    find_host_root,
)
from aipass.aipass.apps.handlers.new_project.adopt import adopt_project
from aipass.aipass.shared.registry_discovery import registries_in
from aipass.aipass.apps.modules.new_project import (
    _prompt_agent,
    _prompt_template,
    handle_command,
)
from aipass.spawn.apps.handlers.class_registry import (
    LEGACY_CLASSES,
    refuse_retired_or_forbidden,
)


# ---------------------------------------------------------------------------
# find_host_root
# ---------------------------------------------------------------------------


def test_find_host_root_finds_registry(tmp_path):
    """Finds directory containing *_REGISTRY.json."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    sub = tmp_path / "projects" / "myapp"
    sub.mkdir(parents=True)
    assert find_host_root(sub) == tmp_path


def test_find_host_root_returns_none_without_registry(tmp_path):
    """Returns None when no registry exists above start."""
    assert find_host_root(tmp_path) is None


def test_find_host_root_finds_closest_registry(tmp_path):
    """Walks up and finds the closest *_REGISTRY.json."""
    (tmp_path / "HOST_REGISTRY.json").write_text("{}", encoding="utf-8")
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert find_host_root(sub) == tmp_path


# ---------------------------------------------------------------------------
# _validate_name
# ---------------------------------------------------------------------------


# Read through create_project, the name check's one caller (fleet green leg 3). The
# check runs first; from a directory with no host above it, a name it accepts goes on
# to "Not inside an AIPass installation", so nothing is ever written.


def _name_answer(tmp_path, monkeypatch, name: str) -> str:
    """create_project's refusal for *name* from a host-less tmp_path: which check stopped it."""
    assert find_host_root(tmp_path) is None  # premise: no host, so no project can be built
    monkeypatch.chdir(tmp_path)
    with pytest.raises((ValueError, RuntimeError)) as refused:
        create_project(name, no_agent=True)
    return str(refused.value)


def test_validate_name_accepts_valid(tmp_path, monkeypatch):
    """Mutant (fleet green leg 3): the pattern `^[a-zA-Z][a-zA-Z0-9_-]*$` -> `^[a-z][a-z0-9]*$` -> red."""
    assert "Not inside an AIPass" in _name_answer(tmp_path, monkeypatch, "myapp")
    assert "Not inside an AIPass" in _name_answer(tmp_path, monkeypatch, "My-App_2")


def test_validate_name_rejects_empty(tmp_path, monkeypatch):
    """Mutant (fleet green leg 3): `if not name:` -> `if False:` -> red."""
    assert "cannot be empty" in _name_answer(tmp_path, monkeypatch, "")


def test_validate_name_rejects_leading_digit(tmp_path, monkeypatch):
    """Mutant (fleet green leg 3): the pattern's first class `[a-zA-Z]` -> `[a-zA-Z0-9]` -> red."""
    assert "Must start with a letter" in _name_answer(tmp_path, monkeypatch, "2fast")


def test_validate_name_rejects_special_chars(tmp_path, monkeypatch):
    """Mutant (fleet green leg 3): the pattern's anchor `*$"` -> `*"` -> red."""
    assert "Must start with a letter" in _name_answer(tmp_path, monkeypatch, "my app!")


# ---------------------------------------------------------------------------
# _registry_name
# ---------------------------------------------------------------------------


def _built(host_env, monkeypatch, name: str, template: str = "empty") -> dict:
    """create_project's answer for *name* under the tmp_path host (git stubbed, no agent, no enrolment)."""
    monkeypatch.chdir(host_env)
    with (
        patch("subprocess.run", side_effect=_mock_git_run),
        patch("aipass.aipass.shared.project_home._detect_aipass_home", return_value=None),
        patch("aipass.aipass.shared.project_home._enroll_project"),
    ):
        return create_project(name, template=template, no_agent=True)


def _registry_file(host_env, monkeypatch, name: str) -> str:
    """The registry file create_project mints for *name* under the tmp_path host."""
    return _built(host_env, monkeypatch, name)["registry_file"]


def test_registry_name_uppercases(host_env, monkeypatch):
    """Read through create_project's registry file (fleet green leg 3).

    Mutant (fleet green leg 3): `name.upper()` -> `name` in _registry_name -> red.
    """
    assert _registry_file(host_env, monkeypatch, "myapp") == "MYAPP_REGISTRY.json"


def test_registry_name_replaces_special(host_env):
    """A dot reaches the registry name only through adopt (create_project's name check refuses it).

    Read through a dry-run adopt_project of <host>/projects/my.app: dry run writes nothing,
    and with no AIPass home detected no live template is read (fleet green leg 3).
    Mutant (fleet green leg 3): `"_", name.upper()` -> `"", name.upper()` in _registry_name -> red.
    """
    target = host_env / "projects" / "my.app"
    target.mkdir()
    with patch("aipass.aipass.apps.handlers.new_project.adopt._detect_aipass_home", return_value=None):
        planned = adopt_project(target, no_agent=True, dry_run=True)
    assert planned["registry_file"] == "MY_APP_REGISTRY.json"
    assert list(target.iterdir()) == []


def test_registry_name_preserves_hyphens(host_env, monkeypatch):
    """Mutant (fleet green leg 3): the kept class `[^A-Z0-9_-]` -> `[^A-Z0-9_]` -> red."""
    assert _registry_file(host_env, monkeypatch, "my-app") == "MY-APP_REGISTRY.json"


# ---------------------------------------------------------------------------
# _write_registry
# ---------------------------------------------------------------------------


def test_write_registry_creates_file(host_env, monkeypatch):
    """Read through create_project's minted registry (fleet green leg 3).

    Mutant (fleet green leg 3): the registry's `"name": reg,` -> `"name": name,` -> red.
    """
    result = _built(host_env, monkeypatch, "demo")
    fname = result["registry_file"]
    path = Path(result["target"]) / fname
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["metadata"]["id"] == result["registry_id"]
    assert data["metadata"]["name"] == "DEMO"
    assert fname == "DEMO_REGISTRY.json"
    assert data["branches"] == []


# ---------------------------------------------------------------------------
# _write_template — empty
# ---------------------------------------------------------------------------


def test_write_template_empty(host_env, monkeypatch):
    """Read through create_project's files and target (fleet green leg 3).

    Mutant (fleet green leg 3): _write_template's `created.append(".gitignore")` -> `pass` -> red.
    """
    result = _built(host_env, monkeypatch, "demo")
    created = result["files"]
    target = Path(result["target"])
    assert "README.md" in created
    assert ".gitignore" in created
    assert (target / "README.md").exists()
    assert (target / ".gitignore").exists()
    assert not (target / "pyproject.toml").exists()
    assert not (target / "src").exists()
    gitignore = (target / ".gitignore").read_text(encoding="utf-8")
    assert ".venv\n" in gitignore
    assert ".venv/\n" not in gitignore
    assert "*_REGISTRY.lock" in gitignore


# ---------------------------------------------------------------------------
# _write_template — python
# ---------------------------------------------------------------------------


def test_write_template_python(host_env, monkeypatch):
    """Mutant (fleet green leg 3): the pyproject line f'name = "{name}"' -> 'name = "x"' -> red."""
    result = _built(host_env, monkeypatch, "demo", template="python")
    created = result["files"]
    target = Path(result["target"])
    assert "pyproject.toml" in created
    assert "src/demo/__init__.py" in created
    assert (target / "pyproject.toml").exists()
    assert (target / "src" / "demo" / "__init__.py").exists()
    pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "demo"' in pyproject


def test_write_template_python_hyphen_name(host_env, monkeypatch):
    """Mutant (fleet green leg 3): python branch `pkg = name.replace("-", "_").lower()` -> `name.lower()` -> red."""
    result = _built(host_env, monkeypatch, "my-app", template="python")
    assert (Path(result["target"]) / "src" / "my_app" / "__init__.py").exists()


# ---------------------------------------------------------------------------
# create_project — integration (mocked subprocess)
# ---------------------------------------------------------------------------


@pytest.fixture()
def host_env(tmp_path):
    """Set up a minimal AIPass host installation in tmp_path."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text(
        json.dumps({"metadata": {"id": "host-id"}, "branches": []}), encoding="utf-8"
    )
    (tmp_path / "projects").mkdir()
    (tmp_path / ".aipass").mkdir()
    return tmp_path


def _mock_git_run(args, **kwargs):
    """Stub subprocess.run for git commands — always succeeds."""
    from unittest.mock import MagicMock

    result = MagicMock()
    result.returncode = 0
    result.stdout = ""
    result.stderr = ""
    return result


def test_create_project_empty_template(host_env, monkeypatch):
    monkeypatch.chdir(host_env)
    with (
        patch("subprocess.run", side_effect=_mock_git_run),
        patch(
            "aipass.aipass.shared.project_home._detect_aipass_home",
            return_value=None,
        ),
        patch(
            "aipass.aipass.shared.project_home._enroll_project",
        ),
    ):
        result = create_project("testproj", template="empty", no_agent=True)

    target = Path(result["target"])
    assert target.exists()
    assert result["name"] == "testproj"
    assert result["template"] == "empty"
    assert result["registry_file"] == "TESTPROJ_REGISTRY.json"
    assert (target / "TESTPROJ_REGISTRY.json").exists()
    assert (target / "README.md").exists()
    assert (target / ".gitignore").exists()
    assert not (target / "pyproject.toml").exists()

    # `aipass new` is the fourth project-minting door and was the only one not
    # stamping a manifest, so a project born here met its first `init update`
    # as unknown provenance and collected sidecars for files nobody edited.
    manifest = target / ".aipass" / "scaffold_manifest.json"
    assert manifest.is_file()
    stamped = json.loads(manifest.read_text(encoding="utf-8"))
    assert stamped["files"], "manifest stamped with no files"
    for rel, digest in stamped["files"].items():
        assert hashlib.sha256((target / rel).read_bytes()).hexdigest() == digest, rel


def test_create_project_python_template(host_env, monkeypatch):
    monkeypatch.chdir(host_env)
    with (
        patch("subprocess.run", side_effect=_mock_git_run),
        patch(
            "aipass.aipass.shared.project_home._detect_aipass_home",
            return_value=None,
        ),
        patch(
            "aipass.aipass.shared.project_home._enroll_project",
        ),
    ):
        result = create_project("pyapp", template="python", no_agent=True)

    target = Path(result["target"])
    assert (target / "pyproject.toml").exists()
    assert (target / "src" / "pyapp" / "__init__.py").exists()


def test_create_project_gets_claude_md_excludes_fence(host_env, monkeypatch):
    """aipass new always creates under <host>/projects/<name> — nested fence must be written."""
    monkeypatch.chdir(host_env)
    with (
        patch("subprocess.run", side_effect=_mock_git_run),
        patch(
            "aipass.aipass.shared.project_home._detect_aipass_home",
            return_value=str(host_env),
        ),
        patch("aipass.aipass.shared.project_home._enroll_project"),
        patch("aipass.aipass.shared.project_home.is_throwaway_path", return_value=False),
    ):
        result = create_project("fenced", template="empty", no_agent=True)

    target = Path(result["target"])
    local_settings = json.loads((target / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert local_settings["claudeMdExcludes"] == [
        (host_env / "CLAUDE.md").as_posix(),
        (host_env / ".claude" / "CLAUDE.md").as_posix(),
    ]


def test_create_project_rejects_existing(host_env, monkeypatch):
    monkeypatch.chdir(host_env)
    (host_env / "projects" / "taken").mkdir()
    with pytest.raises(RuntimeError, match="already exists"):
        create_project("taken", no_agent=True)


def test_create_project_rejects_invalid_name(host_env, monkeypatch):
    monkeypatch.chdir(host_env)
    with pytest.raises(ValueError, match="Must start with a letter"):
        create_project("123bad", no_agent=True)


def test_create_project_rejects_bad_template(host_env, monkeypatch):
    monkeypatch.chdir(host_env)
    with pytest.raises(ValueError, match="Unknown template"):
        create_project("foo", template="rust", no_agent=True)


def test_create_project_no_host(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError, match="Not inside an AIPass"):
        create_project("foo", no_agent=True)


def test_create_project_cleans_up_on_failure(host_env, monkeypatch):
    monkeypatch.chdir(host_env)

    def _fail_git(args, **kwargs):
        from unittest.mock import MagicMock

        result = MagicMock()
        result.returncode = 1
        result.stderr = "simulated failure"
        return result

    with (
        patch("subprocess.run", side_effect=_fail_git),
        patch(
            "aipass.aipass.shared.project_home._detect_aipass_home",
            return_value=None,
        ),
        patch("aipass.aipass.shared.project_home._enroll_project"),
        pytest.raises(RuntimeError, match="simulated failure"),
    ):
        create_project("failproj", no_agent=True)

    assert not (host_env / "projects" / "failproj").exists()


def test_create_project_registry_before_scaffold(host_env, monkeypatch):
    """Registry file must exist before scaffold runs (order invariant).

    Mutant (fleet green leg 3): _write_template moved above _write_registry in create_project -> red.
    """
    monkeypatch.chdir(host_env)
    registry_seen_by_template = []

    def track_template(target, name, template):
        """Stands in for the template writer: records whether the registry is already on disk."""
        registry_seen_by_template.append(bool(registries_in(target)))
        return []

    with (
        patch("subprocess.run", side_effect=_mock_git_run),
        patch(
            "aipass.aipass.apps.handlers.new_project._write_template",
            side_effect=track_template,
        ),
        patch(
            "aipass.aipass.shared.project_home._detect_aipass_home",
            return_value=None,
        ),
        patch("aipass.aipass.shared.project_home._enroll_project"),
    ):
        create_project("ordertest", no_agent=True)

    assert registry_seen_by_template == [True]


# ---------------------------------------------------------------------------
# _spawn_project_agent (delegates to spawn_agent)
# ---------------------------------------------------------------------------

_SPAWN_SUCCESS = {
    "success": True,
    "branch_name": "DEMO",
    # Never touched by the filesystem — it is the mock's payload. Built from
    # tempfile so the literal stays portable (windows_compat).
    "path": str(Path(tempfile.gettempdir()) / "demo"),
    "files_copied": 12,
    "registry_updated": True,
    "validation_issues": [],
}


def _built_with_agent(host_env, monkeypatch, name: str, spawn_answer: dict):
    """create_project with an agent under the tmp_path host; spawn_agent is a recording stub.

    Returns (result, spawn stub). The agent code is read through create_project,
    its one caller (fleet green leg 3); spawn itself never runs.
    """
    monkeypatch.chdir(host_env)
    with (
        patch("subprocess.run", side_effect=_mock_git_run),
        patch("aipass.aipass.shared.project_home._detect_aipass_home", return_value=None),
        patch("aipass.aipass.shared.project_home._enroll_project"),
        patch("aipass.aipass.apps.handlers.new_project.spawn_agent", return_value=spawn_answer) as mock_spawn,
    ):
        return create_project(name, no_agent=False), mock_spawn


def test_agent_home_simple(host_env, monkeypatch):
    """Agent home is src/<pkg>/<pkg>/.

    Mutant (fleet green leg 3): _agent_home's `project_root / "src" / pkg / pkg` -> `project_root / "src" / pkg` -> red.
    """
    result, _spawn = _built_with_agent(host_env, monkeypatch, "demo", _SPAWN_SUCCESS)
    assert result["agent_home"] == str(host_env / "projects" / "demo" / "src" / "demo" / "demo")


def test_agent_home_hyphenated(host_env, monkeypatch):
    """Hyphens normalized to underscores, matching python template.

    Mutant (fleet green leg 3): _agent_home's `pkg = name.replace("-", "_").lower()` -> `pkg = name.lower()` -> red.
    """
    result, _spawn = _built_with_agent(host_env, monkeypatch, "my-app", _SPAWN_SUCCESS)
    assert result["agent_home"] == str(host_env / "projects" / "my-app" / "src" / "my_app" / "my_app")


def test_spawn_project_agent_calls_spawn(host_env, monkeypatch):
    """Calls spawn_agent with the agent_home path, role and purpose — and no class.

    Mutant (fleet green leg 3): `role="project_manager",` -> `role="project_agent",` -> red.
    """
    result, mock_spawn = _built_with_agent(host_env, monkeypatch, "demo", _SPAWN_SUCCESS)
    expected_home = str(host_env / "projects" / "demo" / "src" / "demo" / "demo")
    mock_spawn.assert_called_once_with(
        target_path=expected_home,
        role="project_manager",
        purpose="Resident agent of the demo project.",
    )
    assert result["spawn_result"]["success"] is True
    assert result["spawn_result"]["branch_name"] == "DEMO"


def test_spawn_project_agent_raises_on_failure(host_env, monkeypatch):
    """Raises RuntimeError when spawn_agent returns success=False.

    Mutant (fleet green leg 3): `if not result.get("success"):` -> `if False:` -> red.
    """
    with pytest.raises(RuntimeError, match="spawn_agent failed.*template missing"):
        _built_with_agent(host_env, monkeypatch, "broken", {"success": False, "error": "template missing"})


def test_spawn_project_agent_returns_spawn_result(host_env, monkeypatch):
    """Returns the full result dict from spawn_agent.

    Mutant (fleet green leg 3): _spawn_project_agent's `return result` -> `return dict(result, files_copied=0)` -> red.
    """
    result, _spawn = _built_with_agent(host_env, monkeypatch, "demo", {**_SPAWN_SUCCESS, "citizen_number": 1})
    assert result["spawn_result"]["files_copied"] == 12
    assert result["spawn_result"]["citizen_number"] == 1


# ---------------------------------------------------------------------------
# create_project — WITH agent
# ---------------------------------------------------------------------------


def test_create_project_with_agent(host_env, monkeypatch):
    """WITH-agent path: spawn_agent called, result propagated."""
    monkeypatch.chdir(host_env)
    spawn_ok = {
        "success": True,
        "branch_name": "WITHAGENT",
        "path": str(host_env / "projects" / "withagent"),
        "files_copied": 15,
        "registry_updated": True,
        "validation_issues": [],
    }
    with (
        patch("subprocess.run", side_effect=_mock_git_run),
        patch(
            "aipass.aipass.shared.project_home._detect_aipass_home",
            return_value=None,
        ),
        patch("aipass.aipass.shared.project_home._enroll_project"),
        patch(
            "aipass.aipass.apps.handlers.new_project.spawn_agent",
            return_value=spawn_ok,
        ) as mock_spawn,
    ):
        result = create_project("withagent", template="empty", no_agent=False)

    assert result["agent_created"] is True
    assert result["spawn_result"] == spawn_ok
    expected_home = str(host_env / "projects" / "withagent" / "src" / "withagent" / "withagent")
    assert result["agent_home"] == expected_home
    mock_spawn.assert_called_once()
    call_kwargs = mock_spawn.call_args[1]
    assert call_kwargs["target_path"] == expected_home
    assert "citizen_class" not in call_kwargs


def test_create_project_spawn_failure_cleans_up(host_env, monkeypatch):
    """spawn_agent failure triggers cleanup — no partial project left."""
    monkeypatch.chdir(host_env)
    with (
        patch("subprocess.run", side_effect=_mock_git_run),
        patch(
            "aipass.aipass.shared.project_home._detect_aipass_home",
            return_value=None,
        ),
        patch("aipass.aipass.shared.project_home._enroll_project"),
        patch(
            "aipass.aipass.apps.handlers.new_project.spawn_agent",
            return_value={"success": False, "error": "template missing"},
        ),
        pytest.raises(RuntimeError, match="spawn_agent failed"),
    ):
        create_project("failspawn", template="empty", no_agent=False)

    assert not (host_env / "projects" / "failspawn").exists()


def test_create_project_no_agent_next_steps(host_env, monkeypatch, capsys: pytest.CaptureFixture[str]):
    """Mutant: agent next-step printed for --no-agent -> red."""
    monkeypatch.chdir(host_env)
    with (
        patch("subprocess.run", side_effect=_mock_git_run),
        patch(
            "aipass.aipass.shared.project_home._detect_aipass_home",
            return_value=None,
        ),
        patch("aipass.aipass.shared.project_home._enroll_project"),
    ):
        handle_command("new", ["cosmtest", "--template", "empty", "--no-agent"])
    out, _err = capsys.readouterr()
    assert "Next steps:" in out
    assert "meet your project agent" not in out


def test_create_project_no_agent_flag(host_env, monkeypatch):
    """no_agent=True skips passport and registry seating."""
    monkeypatch.chdir(host_env)
    with (
        patch("subprocess.run", side_effect=_mock_git_run),
        patch(
            "aipass.aipass.shared.project_home._detect_aipass_home",
            return_value=None,
        ),
        patch("aipass.aipass.shared.project_home._enroll_project"),
    ):
        result = create_project("noagent", template="empty", no_agent=True)

    assert result["agent_created"] is False
    assert result["agent_home"] is None
    target = Path(result["target"])
    assert not (target / "src" / "noagent" / "noagent").exists()
    reg = json.loads((target / result["registry_file"]).read_text(encoding="utf-8"))
    assert reg["metadata"]["total_branches"] == 0


# ---------------------------------------------------------------------------
# is_projects_child (guard relaxation)
# ---------------------------------------------------------------------------


def test_is_projects_child_valid(tmp_path):
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "projects" / "myapp"
    target.mkdir(parents=True)
    assert is_projects_child(target) is True


def test_is_projects_child_not_in_projects(tmp_path):
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "elsewhere" / "myapp"
    target.mkdir(parents=True)
    assert is_projects_child(target) is False


def test_is_projects_child_no_host_registry(tmp_path):
    target = tmp_path / "projects" / "myapp"
    target.mkdir(parents=True)
    assert is_projects_child(target) is False


# ---------------------------------------------------------------------------
# _guard_init relaxation
# ---------------------------------------------------------------------------


# Read through init_project, the guard's one caller (fleet green leg 3). Every call
# names the project "!!!", which sanitizes to nothing: a target the guard lets through
# stops at init_project's ValueError before any file is written, so even a broken
# guard never scaffolds a project.
_NO_NAME = "!!!"


def test_guard_init_blocks_nested_by_default(tmp_path):
    """The refusal names the host it found and the marker file that proved it.

    Mutant: `(has {f.name})` dropped from the BLOCKED message -> red.
    """
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "projects" / "nested"
    target.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="inside AIPass project") as exc_info:
        init_project(target, _NO_NAME)
    assert f"at '{tmp_path}' (has AIPASS_REGISTRY.json)" in str(exc_info.value)


def test_guard_init_allows_nested_with_flag(tmp_path):
    """The flag is the ONLY difference between the refusal and the pass.

    Both halves stand in one unit on purpose (v5 no_oracle, 2026-09-08): the
    old body called the allowed form and asserted nothing, so a _guard_init
    that had stopped refusing anything at all would have kept it green.
    Passing the guard shows as reaching init_project's own name check.
    Mutant (fleet green leg 3): the nested-project `if allow_projects_child and is_projects_child(target):
    return` -> `if False: return` -> red.
    """
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "projects" / "nested"
    target.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="inside AIPass project"):
        init_project(target, _NO_NAME)
    with pytest.raises(ValueError, match="Cannot derive project name"):
        init_project(target, _NO_NAME, allow_projects_child=True)
    assert list(target.iterdir()) == []


def test_guard_init_still_blocks_non_projects_nested(tmp_path):
    """Mutant (fleet green leg 3): `raise RuntimeError(` for the inside-project block -> `return (` -> red."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "elsewhere" / "nested"
    target.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="inside AIPass project"):
        init_project(target, _NO_NAME, allow_projects_child=True)


# ---------------------------------------------------------------------------
# Module handle_command
# ---------------------------------------------------------------------------


def test_module_handles_new_command():
    assert handle_command("notmine", []) is False


def test_module_handles_help(capsys: pytest.CaptureFixture[str]):
    """Mutant: print_help() dropped from the --help branch -> red."""
    assert handle_command("new", ["--help"]) is True
    out, err = capsys.readouterr()
    assert "USAGE:" in out
    assert "--template python" in out


def test_module_handles_no_args(capsys: pytest.CaptureFixture[str]):
    """Mutant: print_introspection() dropped from the bare branch -> red."""
    assert handle_command("new", []) is True
    out, err = capsys.readouterr()
    assert "project creator" in out


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------


def _eof(prompt: str) -> str:
    """Stand-in for input() at a closed stdin."""
    raise EOFError


def test_prompt_template_default():
    assert _prompt_template(["empty", "python"], ask=lambda prompt: "") == "empty"


def test_prompt_template_by_number():
    """Mutant: `return templates[int(choice) - 1]` -> `return templates[0]` -> red."""
    assert _prompt_template(["empty", "python"], ask=lambda prompt: "2") == "python"


def test_prompt_template_by_name():
    assert _prompt_template(["empty", "python"], ask=lambda prompt: "python") == "python"


def test_prompt_template_eof():
    assert _prompt_template(["empty", "python"], ask=_eof) == "empty"


def test_prompt_agent_default_yes():
    assert _prompt_agent(ask=lambda prompt: "") is False


def test_prompt_agent_no():
    """Mutant: the `("n", "no")` branch's `return True` -> `return False` -> red."""
    assert _prompt_agent(ask=lambda prompt: "n") is True


def test_prompt_agent_eof():
    assert _prompt_agent(ask=_eof) is False


def _ctrl_c(prompt: str) -> str:
    """Stand-in for input() when the user presses Ctrl-C."""
    raise KeyboardInterrupt


def test_ctrl_c_at_the_agent_prompt_creates_nothing(host_env, monkeypatch):
    """Ctrl-C is a cancel, never a yes: no project is created and the command exits 130.

    Red before the cure: _prompt_agent answered Ctrl-C like Enter and the project was built.
    The host is tmp_path and create_project is a recording stub answering "no agent", so even
    a broken prompt writes no project and launches nothing.
    Mutant (fleet green leg 3): `except EOFError:` -> `except (EOFError, KeyboardInterrupt):` -> red.
    """
    monkeypatch.chdir(host_env)
    built = {
        "target": str(host_env / "projects" / "cancelled"),
        "registry_file": str(host_env / "projects" / "cancelled" / "CANCELLED_REGISTRY.json"),
        "template": "empty",
        "agent_created": False,
    }
    with (
        patch(
            "aipass.aipass.apps.modules.new_project._prompt_agent",
            functools.partial(_prompt_agent, ask=_ctrl_c),
        ),
        patch("aipass.aipass.apps.handlers.new_project.create_project", return_value=built) as mock_create,
        pytest.raises(SystemExit) as exited,
    ):
        handle_command("new", ["cancelled", "--template", "empty"])
    assert exited.value.code == 130
    mock_create.assert_not_called()


def test_ctrl_c_at_the_template_prompt_creates_nothing(host_env, monkeypatch):
    """Ctrl-C at the template prompt is a cancel, never "use the default": nothing is created, exit 130.

    Red before the cure: _prompt_template answered Ctrl-C with templates[0] and went on to the build.
    The host is tmp_path and create_project is a recording stub answering "no agent", so even
    a broken prompt writes no project and launches nothing.
    Mutant (fleet green leg 3): template prompt `except EOFError:` -> `except (EOFError, KeyboardInterrupt):` -> red.
    """
    monkeypatch.chdir(host_env)
    built = {
        "target": str(host_env / "projects" / "cancelled"),
        "registry_file": str(host_env / "projects" / "cancelled" / "CANCELLED_REGISTRY.json"),
        "template": "empty",
        "agent_created": False,
    }
    with (
        patch(
            "aipass.aipass.apps.modules.new_project._prompt_template",
            functools.partial(_prompt_template, ask=_ctrl_c),
        ),
        patch("aipass.aipass.apps.handlers.new_project.create_project", return_value=built) as mock_create,
        pytest.raises(SystemExit) as exited,
    ):
        handle_command("new", ["cancelled", "--no-agent"])
    assert exited.value.code == 130
    mock_create.assert_not_called()
    assert not (host_env / "projects" / "cancelled").exists()


# ---------------------------------------------------------------------------
# TTY auto-launch (FIX 3: aipass new auto-launches on TTY)
# ---------------------------------------------------------------------------


def test_tty_auto_launches_agent(host_env, monkeypatch):
    """On a TTY with an agent created, launch_inline is called.

    Mutant: the launch_inline command `"claude",` -> `"codex",` -> red.
    """
    monkeypatch.chdir(host_env)
    spawn_ok = {
        "success": True,
        "branch_name": "LAUNCH",
        "path": str(host_env / "projects" / "launch"),
        "files_copied": 12,
        "registry_updated": True,
        "validation_issues": [],
    }
    with (
        patch("subprocess.run", side_effect=_mock_git_run),
        # The real agent prompt, answered Enter through its own ask seam (never builtins.input).
        patch(
            "aipass.aipass.apps.modules.new_project._prompt_agent",
            functools.partial(_prompt_agent, ask=lambda prompt: ""),
        ),
        patch(
            "aipass.aipass.shared.project_home._detect_aipass_home",
            return_value=None,
        ),
        patch("aipass.aipass.shared.project_home._enroll_project"),
        patch(
            "aipass.aipass.apps.handlers.new_project.spawn_agent",
            return_value=spawn_ok,
        ),
        patch("aipass.aipass.apps.modules.new_project.sys.stdin") as mock_stdin,
        patch("aipass.aipass.apps.handlers.handoff_platform.launch_inline") as mock_launch,
    ):
        mock_stdin.isatty.return_value = True
        handle_command("new", ["launch", "--template", "empty"])
    mock_launch.assert_called_once()
    assert mock_launch.call_args[0][0] == "claude"
    assert "launch" in mock_launch.call_args[0][2]


def test_no_tty_skips_auto_launch(host_env, monkeypatch, capsys: pytest.CaptureFixture[str]):
    """On a non-TTY, launch_inline is NOT called — fallback to printed instructions.

    Mutant: 'claude' next-step line not printed -> red.
    """
    monkeypatch.chdir(host_env)
    spawn_ok = {
        "success": True,
        "branch_name": "PIPED",
        "path": str(host_env / "projects" / "piped"),
        "files_copied": 12,
        "registry_updated": True,
        "validation_issues": [],
    }
    with (
        patch("subprocess.run", side_effect=_mock_git_run),
        # The real agent prompt, answered Enter through its own ask seam (never builtins.input).
        patch(
            "aipass.aipass.apps.modules.new_project._prompt_agent",
            functools.partial(_prompt_agent, ask=lambda prompt: ""),
        ),
        patch(
            "aipass.aipass.shared.project_home._detect_aipass_home",
            return_value=None,
        ),
        patch("aipass.aipass.shared.project_home._enroll_project"),
        patch(
            "aipass.aipass.apps.handlers.new_project.spawn_agent",
            return_value=spawn_ok,
        ),
        patch("aipass.aipass.apps.modules.new_project.sys.stdin") as mock_stdin,
        patch("aipass.aipass.apps.handlers.handoff_platform.launch_inline") as mock_launch,
    ):
        mock_stdin.isatty.return_value = False
        handle_command("new", ["piped", "--template", "empty"])
    mock_launch.assert_not_called()
    out, _err = capsys.readouterr()
    assert "cd " in out
    assert "# meet your project agent" in out


def test_no_agent_skips_auto_launch(host_env, monkeypatch):
    """With --no-agent, launch_inline is not called even on TTY."""
    monkeypatch.chdir(host_env)
    with (
        patch("subprocess.run", side_effect=_mock_git_run),
        patch(
            "aipass.aipass.shared.project_home._detect_aipass_home",
            return_value=None,
        ),
        patch("aipass.aipass.shared.project_home._enroll_project"),
        patch("aipass.aipass.apps.modules.new_project.sys.stdin") as mock_stdin,
        patch("aipass.aipass.apps.handlers.handoff_platform.launch_inline") as mock_launch,
    ):
        mock_stdin.isatty.return_value = True
        handle_command("new", ["nolaunch", "--template", "empty", "--no-agent"])
    mock_launch.assert_not_called()


# ---------------------------------------------------------------------------
# aipass.py entry point help (cli_ux)
# ---------------------------------------------------------------------------


def test_aipass_print_introspection(capsys: pytest.CaptureFixture[str]):
    """Mutant: branch title not printed -> red."""
    entry.print_introspection([])
    out, _err = capsys.readouterr()
    printed = " ".join(out.split())
    assert "AIPASS \u2014 Concierge & Setup" in printed
    assert "--help" in printed


def test_aipass_print_help(capsys: pytest.CaptureFixture[str]):
    """Mutant: doctor command line not printed -> red."""
    entry.print_help([])
    out, _err = capsys.readouterr()
    printed = " ".join(out.split())
    assert "Usage:" in printed
    assert "aipass <command>" in printed
    assert "System health \u2014 structure, registry, hooks, tests" in printed


# ---------------------------------------------------------------------------
# _git_init — main + dev at mint (DPLAN-0319 R6)
#
# These run REAL git in a temp dir. subprocess.run is deliberately NOT mocked:
# the ordering claim ("dev is cut from the birth commit, HEAD lands on dev") is
# only provable against a real repo — a mocked subprocess would happily pass
# whatever argv it was handed.
# ---------------------------------------------------------------------------

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


def _git_env(monkeypatch):
    """Make commits work without any global git identity."""
    for var, value in (
        ("GIT_AUTHOR_NAME", "AIPass Test"),
        ("GIT_AUTHOR_EMAIL", "test@aipass.invalid"),
        ("GIT_COMMITTER_NAME", "AIPass Test"),
        ("GIT_COMMITTER_EMAIL", "test@aipass.invalid"),
    ):
        monkeypatch.setenv(var, value)


def _run_git(args: list[str], repo: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout.strip()


def _branches(repo: Path) -> list[str]:
    out = _run_git(["branch", "--format=%(refname:short)"], repo)
    return sorted(line.strip() for line in out.splitlines() if line.strip())


def _born(host_env, monkeypatch) -> Path:
    """A project born by create_project under the tmp_path host with REAL git; returns its repo.

    The git steps are read through create_project, their one caller (fleet green leg 3);
    only enrolment and home detection are stubbed, never subprocess.
    """
    _git_env(monkeypatch)
    monkeypatch.chdir(host_env)
    with (
        patch("aipass.aipass.shared.project_home._detect_aipass_home", return_value=None),
        patch("aipass.aipass.shared.project_home._enroll_project"),
    ):
        return Path(create_project("demo", no_agent=True)["target"])


@requires_git
def test_git_init_creates_main_and_dev(host_env, monkeypatch):
    """R6: a new project is born with BOTH branches, not just main.

    Mutant (fleet green leg 3): `_git(["checkout", "-b", "dev"], target)` -> `_git(["status"], target)` -> red.
    """
    repo = _born(host_env, monkeypatch)

    assert _branches(repo) == ["dev", "main"]


@requires_git
def test_git_init_leaves_head_on_dev(host_env, monkeypatch):
    """R6: the repo is LEFT on dev — agents default to dev, main trails.

    Mutant (fleet green leg 3): `["checkout", "-b", "dev"]` -> `["branch", "dev"]` -> red.
    """
    repo = _born(host_env, monkeypatch)

    assert _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo) == "dev"


@requires_git
def test_git_init_cuts_dev_from_the_birth_commit(host_env, monkeypatch):
    """dev and main share one root — dev is cut AFTER the birth commit.

    Cutting dev from an empty repo would give it no history in common with
    main, so the first merge back would be an unrelated-histories refusal.
    Mutant (fleet green leg 3): `["checkout", "-b", "dev"]` -> `["checkout", "--orphan", "dev"]` -> red.
    """
    repo = _born(host_env, monkeypatch)

    main = _run_git(["rev-parse", "main"], repo)
    dev = _run_git(["rev-parse", "dev"], repo)
    assert main and main == dev


@requires_git
def test_git_init_birth_commit_carries_the_project_files(host_env, monkeypatch):
    """The birth commit is real — dev's tree has the scaffolded file in it.

    Mutant (fleet green leg 3): `_git(["add", "-A"], target)` -> `_git(["add", ".gitignore"], target)` -> red.
    """
    repo = _born(host_env, monkeypatch)

    assert "README.md" in _run_git(["ls-tree", "--name-only", "dev"], repo).split()


def test_git_init_still_refuses_an_existing_repo(tmp_path):
    """The re-init guard survives the R6 change — no branch work on a live repo."""
    (tmp_path / ".git").mkdir()

    with pytest.raises(RuntimeError, match="already has a .git"):
        _git_init(tmp_path, "demo", "empty")


# ---------------------------------------------------------------------------
# first-agent class flows free (DPLAN-0319 R3)
# ---------------------------------------------------------------------------


def test_spawn_project_agent_passes_no_citizen_class(host_env, monkeypatch):
    """The class is spawn's to decide at mint — naming one here overrides R3.

    The project agent is always citizen #1 of a registry minted moments
    earlier, so spawn's first-agent rule mints ``manager`` on its own. Passing
    a class would replace that rule with a guess, and the value this used to
    pass ("project_agent") is a retired name spawn now refuses by name.
    Mutant (fleet green leg 3): `purpose=...,` gains `citizen_class="manager",` -> red.
    """
    _result, mock_spawn = _built_with_agent(
        host_env, monkeypatch, "demo", {"success": True, "branch_name": "DEMO", "files_copied": 1}
    )

    assert "citizen_class" not in mock_spawn.call_args.kwargs
    assert not mock_spawn.call_args.args


def test_spawn_project_agent_never_sends_a_retired_class(host_env, monkeypatch):
    """Guard the species, not the one string: no retired name reaches spawn.

    Mutant (fleet green leg 3): `role="project_manager",` -> `role="project_agent",` -> red.
    """
    _result, mock_spawn = _built_with_agent(
        host_env, monkeypatch, "demo", {"success": True, "branch_name": "DEMO", "files_copied": 1}
    )

    sent = {str(v) for v in mock_spawn.call_args.kwargs.values()}
    assert sent.isdisjoint(set(LEGACY_CLASSES) | {"admin"})


def test_spawn_still_refuses_the_class_this_used_to_pass():
    """Live proof the old value is a refusal, not a slow rename — red if spawn softens."""
    assert refuse_retired_or_forbidden("project_agent")
    assert not refuse_retired_or_forbidden("manager")


# ---------------------------------------------------------------------------
# END TO END — the real door (DPLAN-0319 wave 2)
#
# Nothing mocked but the host-enrolment side effects: real git, real @spawn,
# real template. This is the first proof of spawn's passport-2.0 mint path
# driven from `aipass new`, so mocking either half would prove nothing.
# ---------------------------------------------------------------------------


@pytest.fixture()
def _e2e_project(host_env, monkeypatch):
    """Run the real `aipass new` once; yield (result, project_root)."""
    _git_env(monkeypatch)
    monkeypatch.chdir(host_env)
    with (
        patch("aipass.aipass.shared.project_home._detect_aipass_home", return_value=None),
        patch("aipass.aipass.shared.project_home._enroll_project"),
    ):
        result = create_project("e2edemo", template="empty", no_agent=False)
    return result, Path(result["target"])


@requires_git
def test_e2e_new_project_is_born_on_dev_with_both_branches(_e2e_project):
    """R6 end to end: main AND dev exist, and the project is left on dev."""
    _result, project = _e2e_project

    assert _branches(project) == ["dev", "main"]
    assert _run_git(["rev-parse", "--abbrev-ref", "HEAD"], project) == "dev"


@requires_git
def test_e2e_project_agent_mints_manager_on_schema_2(_e2e_project):
    """R3 end to end: citizen #1 of a fresh registry mints manager, schema 2.0.0.

    Read off the passport spawn actually wrote — the class is never typed by
    this branch, so a `specialist` here would mean R3 did not fire at the door.
    """
    result, _project = _e2e_project
    passport = json.loads((Path(result["agent_home"]) / ".trinity" / "passport.json").read_text(encoding="utf-8"))

    assert passport["identity"]["citizen_class"] == "manager"
    assert passport["branch_info"]["git_branch"] == "dev"
    assert passport["document_metadata"]["schema_version"] == "2.0.0"


@requires_git
def test_e2e_minted_passport_carries_no_retired_or_dropped_fields(_e2e_project):
    """The 2.0 shape as this door produces it: no owner key, no legacy class."""
    result, _project = _e2e_project
    passport = json.loads((Path(result["agent_home"]) / ".trinity" / "passport.json").read_text(encoding="utf-8"))

    assert "owner" not in passport["citizenship"]
    assert passport["identity"]["citizen_class"] not in LEGACY_CLASSES
    assert "principles" in passport["identity"]


@requires_git
def test_e2e_agent_files_are_in_the_birth_commit(_e2e_project):
    """The agent is spawned BEFORE git init, so dev's tree already carries it."""
    result, project = _e2e_project
    tracked = _run_git(["ls-tree", "-r", "--name-only", "dev"], project).splitlines()
    rel = Path(result["agent_home"]).relative_to(project).as_posix()

    assert any(line.startswith(rel) for line in tracked)
