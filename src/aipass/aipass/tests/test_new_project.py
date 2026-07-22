# =================== AIPass ====================
# Name: test_new_project.py
# Description: Tests for aipass new — project creation handler
# Version: 1.0.0
# Created: 2026-07-17
# Modified: 2026-07-17
# =============================================

"""Tests for the new_project handler and module.

All file operations use tmp_path to stay fully isolated from the live
filesystem. Tests mock subprocess calls to avoid real git/drone invocations.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.handlers.new_project import (
    _agent_home,
    _registry_name,
    _spawn_project_agent,
    _validate_name,
    _write_registry,
    _write_template,
    create_project,
    find_host_root,
)


# ---------------------------------------------------------------------------
# find_host_root
# ---------------------------------------------------------------------------


def test_find_host_root_finds_registry(tmp_path):
    """Finds directory containing *_REGISTRY.json."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}")
    sub = tmp_path / "projects" / "myapp"
    sub.mkdir(parents=True)
    assert find_host_root(sub) == tmp_path


def test_find_host_root_returns_none_without_registry(tmp_path):
    """Returns None when no registry exists above start."""
    assert find_host_root(tmp_path) is None


def test_find_host_root_finds_closest_registry(tmp_path):
    """Walks up and finds the closest *_REGISTRY.json."""
    (tmp_path / "HOST_REGISTRY.json").write_text("{}")
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert find_host_root(sub) == tmp_path


# ---------------------------------------------------------------------------
# _validate_name
# ---------------------------------------------------------------------------


def test_validate_name_accepts_valid():
    assert _validate_name("myapp") == "myapp"
    assert _validate_name("My-App_2") == "My-App_2"


def test_validate_name_rejects_empty():
    with pytest.raises(ValueError, match="cannot be empty"):
        _validate_name("")


def test_validate_name_rejects_leading_digit():
    with pytest.raises(ValueError, match="Must start with a letter"):
        _validate_name("2fast")


def test_validate_name_rejects_special_chars():
    with pytest.raises(ValueError, match="Must start with a letter"):
        _validate_name("my app!")


# ---------------------------------------------------------------------------
# _registry_name
# ---------------------------------------------------------------------------


def test_registry_name_uppercases():
    assert _registry_name("myapp") == "MYAPP"


def test_registry_name_replaces_special():
    assert _registry_name("my.app") == "MY_APP"


def test_registry_name_preserves_hyphens():
    assert _registry_name("my-app") == "MY-APP"


# ---------------------------------------------------------------------------
# _write_registry
# ---------------------------------------------------------------------------


def test_write_registry_creates_file(tmp_path):
    rid, fname = _write_registry(tmp_path, "demo")
    path = tmp_path / fname
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["metadata"]["id"] == rid
    assert data["metadata"]["name"] == "DEMO"
    assert fname == "DEMO_REGISTRY.json"
    assert data["branches"] == []


# ---------------------------------------------------------------------------
# _write_template — empty
# ---------------------------------------------------------------------------


def test_write_template_empty(tmp_path):
    created = _write_template(tmp_path, "demo", "empty")
    assert "README.md" in created
    assert ".gitignore" in created
    assert (tmp_path / "README.md").exists()
    assert (tmp_path / ".gitignore").exists()
    assert not (tmp_path / "pyproject.toml").exists()
    assert not (tmp_path / "src").exists()
    gitignore = (tmp_path / ".gitignore").read_text()
    assert ".venv\n" in gitignore
    assert ".venv/\n" not in gitignore
    assert "*_REGISTRY.lock" in gitignore


# ---------------------------------------------------------------------------
# _write_template — python
# ---------------------------------------------------------------------------


def test_write_template_python(tmp_path):
    created = _write_template(tmp_path, "demo", "python")
    assert "pyproject.toml" in created
    assert "src/demo/__init__.py" in created
    assert (tmp_path / "pyproject.toml").exists()
    assert (tmp_path / "src" / "demo" / "__init__.py").exists()
    pyproject = (tmp_path / "pyproject.toml").read_text()
    assert 'name = "demo"' in pyproject


def test_write_template_python_hyphen_name(tmp_path):
    _write_template(tmp_path, "my-app", "python")
    assert (tmp_path / "src" / "my_app" / "__init__.py").exists()


# ---------------------------------------------------------------------------
# create_project — integration (mocked subprocess)
# ---------------------------------------------------------------------------


@pytest.fixture()
def host_env(tmp_path):
    """Set up a minimal AIPass host installation in tmp_path."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps({"metadata": {"id": "host-id"}, "branches": []}))
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
    """Registry file must exist before scaffold runs (order invariant)."""
    monkeypatch.chdir(host_env)
    creation_order = []

    original_write_registry = _write_registry
    original_write_template = _write_template

    def track_registry(target, name):
        creation_order.append("registry")
        return original_write_registry(target, name)

    def track_template(target, name, template):
        creation_order.append("template")
        return original_write_template(target, name, template)

    with (
        patch("subprocess.run", side_effect=_mock_git_run),
        patch(
            "aipass.aipass.apps.handlers.new_project._write_registry",
            side_effect=track_registry,
        ),
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

    assert creation_order.index("registry") < creation_order.index("template")


# ---------------------------------------------------------------------------
# _spawn_project_agent (delegates to spawn_agent)
# ---------------------------------------------------------------------------

_SPAWN_SUCCESS = {
    "success": True,
    "branch_name": "DEMO",
    "path": "/tmp/demo",
    "files_copied": 12,
    "registry_updated": True,
    "validation_issues": [],
}


def test_agent_home_simple():
    """Agent home is src/<pkg>/<pkg>/."""
    from pathlib import Path

    home = _agent_home(Path("/proj"), "demo")
    assert home == Path("/proj/src/demo/demo")


def test_agent_home_hyphenated():
    """Hyphens normalized to underscores, matching python template."""
    from pathlib import Path

    home = _agent_home(Path("/proj"), "my-app")
    assert home == Path("/proj/src/my_app/my_app")


def test_spawn_project_agent_calls_spawn(tmp_path):
    """Calls spawn_agent with correct citizen_class, purpose, and agent_home path."""
    with patch(
        "aipass.aipass.apps.handlers.new_project.spawn_agent",
        return_value=_SPAWN_SUCCESS,
    ) as mock_spawn:
        result = _spawn_project_agent(tmp_path, "demo")
    expected_home = str(tmp_path / "src" / "demo" / "demo")
    mock_spawn.assert_called_once_with(
        target_path=expected_home,
        role="project_agent",
        purpose="Resident agent of the demo project.",
        citizen_class="project_agent",
    )
    assert result["success"] is True
    assert result["branch_name"] == "DEMO"


def test_spawn_project_agent_raises_on_failure(tmp_path):
    """Raises RuntimeError when spawn_agent returns success=False."""
    with (
        patch(
            "aipass.aipass.apps.handlers.new_project.spawn_agent",
            return_value={"success": False, "error": "template missing"},
        ),
        pytest.raises(RuntimeError, match="spawn_agent failed.*template missing"),
    ):
        _spawn_project_agent(tmp_path, "broken")


def test_spawn_project_agent_returns_spawn_result(tmp_path):
    """Returns the full result dict from spawn_agent."""
    with patch(
        "aipass.aipass.apps.handlers.new_project.spawn_agent",
        return_value={**_SPAWN_SUCCESS, "citizen_number": 1},
    ):
        result = _spawn_project_agent(tmp_path, "demo")
    assert result["files_copied"] == 12
    assert result["citizen_number"] == 1


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
    assert call_kwargs["citizen_class"] == "project_agent"


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


def test_create_project_no_agent_next_steps(host_env, monkeypatch):
    """no_agent output omits 'meet your project agent' line."""
    from aipass.aipass.apps.modules.new_project import handle_command

    monkeypatch.chdir(host_env)
    with (
        patch("subprocess.run", side_effect=_mock_git_run),
        patch(
            "aipass.aipass.shared.project_home._detect_aipass_home",
            return_value=None,
        ),
        patch("aipass.aipass.shared.project_home._enroll_project"),
        patch("aipass.aipass.apps.modules.new_project.console") as mock_con,
    ):
        handle_command("new", ["cosmtest", "--template", "empty", "--no-agent"])
    printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
    assert "meet your project agent" not in printed


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
    reg = json.loads((target / result["registry_file"]).read_text())
    assert reg["metadata"]["total_branches"] == 0


# ---------------------------------------------------------------------------
# is_projects_child (guard relaxation)
# ---------------------------------------------------------------------------


def test_is_projects_child_valid(tmp_path):
    from aipass.aipass.apps.handlers.init.bootstrap import is_projects_child

    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}")
    target = tmp_path / "projects" / "myapp"
    target.mkdir(parents=True)
    assert is_projects_child(target) is True


def test_is_projects_child_not_in_projects(tmp_path):
    from aipass.aipass.apps.handlers.init.bootstrap import is_projects_child

    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}")
    target = tmp_path / "elsewhere" / "myapp"
    target.mkdir(parents=True)
    assert is_projects_child(target) is False


def test_is_projects_child_no_host_registry(tmp_path):
    from aipass.aipass.apps.handlers.init.bootstrap import is_projects_child

    target = tmp_path / "projects" / "myapp"
    target.mkdir(parents=True)
    assert is_projects_child(target) is False


# ---------------------------------------------------------------------------
# _guard_init relaxation
# ---------------------------------------------------------------------------


def test_guard_init_blocks_nested_by_default(tmp_path):
    from aipass.aipass.apps.handlers.init.bootstrap import _guard_init

    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}")
    target = tmp_path / "projects" / "nested"
    target.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="inside AIPass project"):
        _guard_init(target)


def test_guard_init_allows_nested_with_flag(tmp_path):
    from aipass.aipass.apps.handlers.init.bootstrap import _guard_init

    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}")
    target = tmp_path / "projects" / "nested"
    target.mkdir(parents=True)
    _guard_init(target, allow_projects_child=True)


def test_guard_init_still_blocks_non_projects_nested(tmp_path):
    from aipass.aipass.apps.handlers.init.bootstrap import _guard_init

    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}")
    target = tmp_path / "elsewhere" / "nested"
    target.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="inside AIPass project"):
        _guard_init(target, allow_projects_child=True)


# ---------------------------------------------------------------------------
# Module handle_command
# ---------------------------------------------------------------------------


def test_module_handles_new_command():
    from aipass.aipass.apps.modules.new_project import handle_command

    assert handle_command("notmine", []) is False


def test_module_handles_help():
    from aipass.aipass.apps.modules.new_project import handle_command

    assert handle_command("new", ["--help"]) is True


def test_module_handles_no_args():
    from aipass.aipass.apps.modules.new_project import handle_command

    assert handle_command("new", []) is True


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------


def test_prompt_template_default():
    from aipass.aipass.apps.modules.new_project import _prompt_template

    with patch("builtins.input", return_value=""):
        assert _prompt_template(["empty", "python"]) == "empty"


def test_prompt_template_by_number():
    from aipass.aipass.apps.modules.new_project import _prompt_template

    with patch("builtins.input", return_value="2"):
        assert _prompt_template(["empty", "python"]) == "python"


def test_prompt_template_by_name():
    from aipass.aipass.apps.modules.new_project import _prompt_template

    with patch("builtins.input", return_value="python"):
        assert _prompt_template(["empty", "python"]) == "python"


def test_prompt_template_eof():
    from aipass.aipass.apps.modules.new_project import _prompt_template

    with patch("builtins.input", side_effect=EOFError):
        assert _prompt_template(["empty", "python"]) == "empty"


def test_prompt_agent_default_yes():
    from aipass.aipass.apps.modules.new_project import _prompt_agent

    with patch("builtins.input", return_value=""):
        assert _prompt_agent() is False


def test_prompt_agent_no():
    from aipass.aipass.apps.modules.new_project import _prompt_agent

    with patch("builtins.input", return_value="n"):
        assert _prompt_agent() is True


def test_prompt_agent_eof():
    from aipass.aipass.apps.modules.new_project import _prompt_agent

    with patch("builtins.input", side_effect=EOFError):
        assert _prompt_agent() is False


# ---------------------------------------------------------------------------
# TTY auto-launch (FIX 3: aipass new auto-launches on TTY)
# ---------------------------------------------------------------------------


def test_tty_auto_launches_agent(host_env, monkeypatch):
    """On a TTY with an agent created, launch_inline is called."""
    from aipass.aipass.apps.modules.new_project import handle_command

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
        patch("builtins.input", return_value=""),
        patch(
            "aipass.aipass.shared.project_home._detect_aipass_home",
            return_value=None,
        ),
        patch("aipass.aipass.shared.project_home._enroll_project"),
        patch(
            "aipass.aipass.apps.handlers.new_project.spawn_agent",
            return_value=spawn_ok,
        ),
        patch("aipass.aipass.apps.modules.new_project.console"),
        patch("aipass.aipass.apps.modules.new_project.sys") as mock_sys,
        patch("aipass.aipass.apps.handlers.handoff_platform.launch_inline") as mock_launch,
    ):
        mock_sys.stdin.isatty.return_value = True
        handle_command("new", ["launch", "--template", "empty"])
    mock_launch.assert_called_once()
    assert "launch" in mock_launch.call_args[0][2]


def test_no_tty_skips_auto_launch(host_env, monkeypatch):
    """On a non-TTY, launch_inline is NOT called — fallback to printed instructions."""
    from aipass.aipass.apps.modules.new_project import handle_command

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
        patch("builtins.input", return_value=""),
        patch(
            "aipass.aipass.shared.project_home._detect_aipass_home",
            return_value=None,
        ),
        patch("aipass.aipass.shared.project_home._enroll_project"),
        patch(
            "aipass.aipass.apps.handlers.new_project.spawn_agent",
            return_value=spawn_ok,
        ),
        patch("aipass.aipass.apps.modules.new_project.console") as mock_con,
        patch("aipass.aipass.apps.modules.new_project.sys") as mock_sys,
        patch("aipass.aipass.apps.handlers.handoff_platform.launch_inline") as mock_launch,
    ):
        mock_sys.stdin.isatty.return_value = False
        handle_command("new", ["piped", "--template", "empty"])
    mock_launch.assert_not_called()
    printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
    assert "cd" in printed
    assert "claude" in printed


def test_no_agent_skips_auto_launch(host_env, monkeypatch):
    """With --no-agent, launch_inline is not called even on TTY."""
    from aipass.aipass.apps.modules.new_project import handle_command

    monkeypatch.chdir(host_env)
    with (
        patch("subprocess.run", side_effect=_mock_git_run),
        patch(
            "aipass.aipass.shared.project_home._detect_aipass_home",
            return_value=None,
        ),
        patch("aipass.aipass.shared.project_home._enroll_project"),
        patch("aipass.aipass.apps.modules.new_project.console"),
        patch("aipass.aipass.apps.modules.new_project.sys") as mock_sys,
        patch("aipass.aipass.apps.handlers.handoff_platform.launch_inline") as mock_launch,
    ):
        mock_sys.stdin.isatty.return_value = True
        handle_command("new", ["nolaunch", "--template", "empty", "--no-agent"])
    mock_launch.assert_not_called()


# ---------------------------------------------------------------------------
# aipass.py entry point help (cli_ux)
# ---------------------------------------------------------------------------


def test_aipass_print_introspection():
    from aipass.aipass.apps.aipass import print_introspection

    print_introspection([])


def test_aipass_print_help():
    from aipass.aipass.apps.aipass import print_help

    print_help([])
