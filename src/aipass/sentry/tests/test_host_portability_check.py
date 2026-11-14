# =================== META ====================
# Name: test_host_portability_check.py
# Description: host_portability_check — arms B and D to H over minimised fleet sites, and its branch score
# Version: 1.0.0
# Created: 2026-11-01
# Modified: 2026-11-14
# =============================================

"""Tests for apps/handlers/aipass_standards/host_portability_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(stdlib) — ast.parse's parsing; the checker only walks the tree it returns
# sentry: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py

import pytest
from unittest.mock import MagicMock

from aipass.sentry.apps.handlers.aipass_standards import host_portability_check
from aipass.sentry.apps.handlers.bypass import utils as _bypass_utils


@pytest.fixture(autouse=True)
def _pin_bypass_log(monkeypatch):
    """Point is_bypassed's json_handler at a mock: it appends to a tracked log, and xdist races corrupt it."""
    mock_handler = MagicMock()
    mock_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(_bypass_utils, "json_handler", mock_handler)


# host_portability_check: fixtures are minimised copies of real fleet sites, never live file:line pins,
# which go red whenever the file grows; the live list lives in host_portability.md.


def _scan_source(tmp_path, source, name="sample.py"):
    """Write *source* to a file and return (violations, acquitted_binary_sites)."""
    target = tmp_path / name
    target.write_text(source, encoding="utf-8")
    return host_portability_check.scan_file(str(target))


def _lines(violations):
    """Just the line numbers, which is what every pin below actually claims."""
    return [lineno for lineno, _ in violations]


def test_host_portability_declares_the_branch_level_contract():
    """AUDIT_SCOPE and the entry point the audit pipeline dispatches on."""
    assert host_portability_check.AUDIT_SCOPE == "branch_level"
    assert callable(host_portability_check.check_branch)


def test_a_clean_branch_scores_100_and_reports_the_file_count(tmp_path):
    """check_branch returns the pack's dict shape: passed/checks/score/standard."""
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "clean.py").write_text("import os\n\n\ndef where():\n    return os.getcwd()\n", encoding="utf-8")

    result = host_portability_check.check_branch(str(tmp_path))

    assert result["standard"] == "HOST_PORTABILITY"
    assert result["score"] == 100
    assert result["passed"] is True
    assert all(check["passed"] for check in result["checks"])


def test_a_branch_with_one_dirty_file_scores_by_clean_file_share(tmp_path):
    """Score is clean/total x 100 -- the number the all_files lane averages to."""
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "clean.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    (apps / "dirty.py").write_text(
        'import subprocess\n\n\ndef kill(name):\n    subprocess.run(["tmux", "kill-session", "-t", name])\n',
        encoding="utf-8",
    )

    result = host_portability_check.check_branch(str(tmp_path))

    assert result["score"] == 50
    failing = [c for c in result["checks"] if not c["passed"]]
    assert len(failing) == 1
    assert failing[0]["violations"][0]["file"] == "apps/dirty.py"


def test_tmux_kill_session_with_check_false_is_convicted(tmp_path):
    """hooks session_boot.py:248, :313 and :1078 -- the fleet's three tmux bugs."""
    source = (
        "import subprocess\n"
        "\n"
        "\n"
        "def stop(session):\n"
        '    subprocess.run(["tmux", "kill-session", "-t", session], check=False)\n'
    )

    violations, acquitted = _scan_source(tmp_path, source)

    assert _lines(violations) == [5]
    assert "tmux" in violations[0][1]
    assert acquitted == 0


def test_systemctl_enable_with_no_guard_is_convicted(tmp_path):
    """trigger service_control.py:82 -- systemctl --user enable, bare."""
    source = (
        "import subprocess\n"
        "\n"
        "\n"
        "def install(unit):\n"
        '    subprocess.run(["systemctl", "--user", "enable", unit], timeout=10)\n'
    )

    violations, _ = _scan_source(tmp_path, source)

    assert _lines(violations) == [5]
    assert "systemctl" in violations[0][1]


def test_a_which_probe_in_the_same_function_acquits_the_binary(tmp_path):
    """aipass handoff_platform launch_tmux -- shutil.which('tmux') then run it."""
    source = (
        "import shutil\n"
        "import subprocess\n"
        "\n"
        "\n"
        "def launch(session):\n"
        '    if not shutil.which("tmux"):\n'
        "        return False\n"
        '    subprocess.run(["tmux", "new-session", "-d", "-s", session])\n'
        "    return True\n"
    )

    violations, acquitted = _scan_source(tmp_path, source)

    assert violations == []
    assert acquitted == 1


def test_a_filenotfounderror_handler_acquits_the_binary(tmp_path):
    """daemon tests/conftest.py:90 -- systemctl inside except FileNotFoundError."""
    source = (
        "import subprocess\n"
        "\n"
        "\n"
        "def ask(*args):\n"
        "    try:\n"
        '        return subprocess.run(["systemctl", "--user", *args], timeout=15)\n'
        "    except (FileNotFoundError, OSError):\n"
        "        return None\n"
    )

    violations, acquitted = _scan_source(tmp_path, source)

    assert violations == []
    assert acquitted == 1


#: A test that runs tmux inside a pytest.raises of the given exception.
_RAISES_TMUX = (
    "import subprocess\n"
    "import pytest\n"
    "\n"
    "\n"
    "def test_no_tmux():\n"
    "    with pytest.raises({expected}):\n"
    '        subprocess.run(["tmux", "kill-session", "-t", "x"])\n'
)


@pytest.mark.parametrize("expected", ["FileNotFoundError", "OSError", "(FileNotFoundError, PermissionError)"])
def test_a_missing_file_raises_around_the_binary_acquits_it(tmp_path, expected):
    """Where tmux is absent the call raises exactly what the test expects, so it passes on every host."""
    violations, acquitted = _scan_source(tmp_path, _RAISES_TMUX.format(expected=expected))

    assert violations == []
    assert acquitted == 1


@pytest.mark.parametrize("expected", ["ValueError", "subprocess.CalledProcessError"])
def test_a_raises_of_another_error_still_convicts_the_binary(tmp_path, expected):
    """The control: a host without tmux raises FileNotFoundError, which this test does not expect."""
    violations, _acquitted = _scan_source(tmp_path, _RAISES_TMUX.format(expected=expected))

    assert _lines(violations) == [7]


def test_a_direct_pathlib_path_subclass_is_convicted_below_3_12(tmp_path):
    """trigger tests/test_error_registry.py:1477 class _RefusingPath(Path) (PR #774)."""
    source = "from pathlib import Path, PurePath\n\n\nclass _RefusingPath(Path):\n    pass\n"
    source += "\n\nclass _Pure(PurePath):\n    pass\n"
    violations, _acquitted = _scan_source(tmp_path, source)
    assert _lines(violations) == [4, 8]
    assert "_flavour" in violations[0][1]


def test_a_concrete_flavour_or_a_carried_flavour_is_acquitted(tmp_path):
    """A concrete flavour (PurePosixPath) carries _flavour; so does a class body that sets it."""
    source = (
        "import pathlib\nfrom pathlib import Path, PurePosixPath\n\n\n"
        "class _PosixFlavour(PurePosixPath):\n    pass\n\n\n"
        "class _Carried(pathlib.Path):\n    _flavour = type(Path())._flavour\n"
    )
    assert _scan_source(tmp_path, source)[0] == []


_DEGRADED_TOMLLIB = """def read(path):
    try:
        import tomllib
    except ModuleNotFoundError:
        return {}, "reading config.toml needs Python 3.11+"
    return tomllib.loads(path.read_text(encoding="utf-8")), ""
"""


def _floored_branch(tmp_path, floor, files):
    """A branch under a pyproject declaring *floor*; returns check_branch's violations."""
    (tmp_path / "pyproject.toml").write_text(f'[project]\nrequires-python = ">={floor}"\n', encoding="utf-8")
    apps = tmp_path / "apps"
    apps.mkdir()
    for name, source in files.items():
        (apps / name).write_text(source, encoding="utf-8")
    result = host_portability_check.check_branch(str(tmp_path))
    return [(v["file"], v["line"]) for check in result["checks"] for v in check.get("violations", [])]


def test_a_tomllib_import_with_a_degraded_except_and_no_tomli_is_convicted_below_its_floor(tmp_path):
    """aipass provider_wire.py before 1.9.1: fourteen tests red on CI's 3.10 lane only."""
    assert _floored_branch(tmp_path, "3.10", {"wire.py": _DEGRADED_TOMLLIB}) == [("apps/wire.py", 3)]


def test_a_tomli_fallback_in_the_same_guard_is_acquitted(tmp_path):
    """provider_wire 1.9.1 inside a function; aipass.py at module level, its tomli one try deeper."""
    in_function = _DEGRADED_TOMLLIB.replace(
        '        return {}, "reading config.toml needs Python 3.11+"\n',
        "        try:\n            import tomli as tomllib\n        except ImportError:\n"
        '            return {}, "needs tomli"\n',
    )
    module_level = """try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None
"""
    assert _floored_branch(tmp_path, "3.10", {"wire.py": in_function, "cli.py": module_level}) == []


def test_the_floor_comes_from_pyproject_so_a_311_floor_acquits_tomllib(tmp_path):
    assert _floored_branch(tmp_path, "3.11", {"wire.py": _DEGRADED_TOMLLIB}) == []


def test_a_portable_binary_is_never_read(tmp_path):
    """git/bash/gh and nine more carry 134 fleet sites and zero known bugs."""
    source = (
        "import subprocess\n"
        "\n"
        "\n"
        "def head():\n"
        '    subprocess.run(["git", "rev-parse", "HEAD"])\n'
        '    subprocess.run(["gh", "pr", "list"])\n'
        '    subprocess.run(["bash", "-c", "echo hi"])\n'
    )

    violations, acquitted = _scan_source(tmp_path, source)

    assert violations == []
    assert acquitted == 0


def test_lib_is_in_the_corpus(tmp_path):
    """skills lib/ -- all seven built-in skills live there and were never scored."""
    handlers = tmp_path / "lib" / "telegram" / "apps" / "handlers"
    handlers.mkdir(parents=True)
    (handlers / "tmux_manager.py").write_text(
        'import subprocess\n\n\ndef has(name):\n    subprocess.run(["tmux", "has-session", "-t", name])\n',
        encoding="utf-8",
    )

    result = host_portability_check.check_branch(str(tmp_path))

    assert result["score"] == 0
    failing = [c for c in result["checks"] if not c["passed"]]
    assert failing[0]["violations"][0]["file"] == "lib/telegram/apps/handlers/tmux_manager.py"


_LOCATE_CONFIG = """import os
from pathlib import Path


def _search_bounds():
    return Path.cwd(), Path.home()


def _absolute(raw):
    path = Path(raw)
    try:
        return path.resolve()
    except OSError:
        return path


def aipass_home():
    raw = os.environ.get("AIPASS_HOME", "")
    if raw:
        return _absolute(raw)
    return None


def locate_config():
    home = aipass_home()
    BOUNDS
    while search != stop and search.parent != search:
        if search == home:
            return "aipass", home
        search = search.parent
    return "none", None
"""


def test_a_resolved_home_compared_with_an_unresolved_walk_is_convicted(tmp_path):
    """hooks apps/handlers/config/loader.py locate_config() before 2.1.0 (60d2af72, PR #774)."""
    source = _LOCATE_CONFIG.replace("BOUNDS", "search, stop = _search_bounds()")
    violations, _acquitted = _scan_source(tmp_path, source)
    assert _lines(violations) == [28]
    assert "search == home" in violations[0][1]
    assert "resolve" in violations[0][1]


def test_both_walk_bounds_resolved_like_home_are_acquitted(tmp_path):
    """The cure in loader.py 2.1.0: both bounds pass through the same _absolute() as home."""
    source = _LOCATE_CONFIG.replace("BOUNDS", "search, stop = (_absolute(str(bound)) for bound in _search_bounds())")
    assert _scan_source(tmp_path, source)[0] == []


def test_relative_to_and_startswith_across_the_two_spellings_are_convicted(tmp_path):
    """The other three comparisons the arm reads: relative_to, is_relative_to, startswith on str()."""
    source = (
        "import os\nimport tempfile\nfrom pathlib import Path\n\n\n"
        "def rel(target):\n"
        "    return Path(target).resolve().relative_to(Path.home())\n\n\n"
        "def inside(target):\n"
        "    where = Path(target).resolve()\n"
        "    return str(where).startswith(os.getcwd())\n\n\n"
        "def scratch(target):\n"
        "    return Path(tempfile.gettempdir()).is_relative_to(Path(target).resolve())\n"
    )
    violations, _acquitted = _scan_source(tmp_path, source)
    assert _lines(violations) == [7, 12, 16]


def test_two_unresolved_or_two_resolved_spellings_are_acquitted(tmp_path):
    """Same spelling on both sides compares equal on every host: nothing to convict."""
    source = (
        "from pathlib import Path\n\n\n"
        "def same_raw(target):\n"
        "    return Path(target) == Path.home() or Path.cwd() == Path.home()\n\n\n"
        "def same_resolved(target):\n"
        "    return Path(target).resolve().relative_to(Path.home().resolve())\n"
    )
    assert _scan_source(tmp_path, source)[0] == []


# Arm F: drone's aipass_github fixture (conftest 1.3.0 vs 1.3.1), minimised.
_EMPTIED_GIT = (
    "import pytest\n\n\n"
    "@pytest.fixture()\n"
    "def repo(tmp_path, monkeypatch):\n"
    '    (tmp_path / "gitconfig").write_text("", encoding="utf-8")\n'
    '    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))\n'
    '    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")\n'
    "IDENTITY"
    "    return tmp_path\n"
)


def test_emptied_git_config_with_no_commit_email_is_convicted_once_at_the_first_emptying_line(tmp_path):
    """The CI exit 128: a runner has no email git can auto-detect once the host config is gone."""
    violations, _acquitted = _scan_source(tmp_path, _EMPTIED_GIT.replace("IDENTITY", ""))
    assert _lines(violations) == [7]
    assert "GIT_AUTHOR_EMAIL" in violations[0][1] and "GIT_COMMITTER_EMAIL" in violations[0][1]


def test_both_emails_set_as_the_cured_fixture_does_are_acquitted(tmp_path):
    """conftest 1.3.1: the four GIT_AUTHOR_*/GIT_COMMITTER_* variables set through a loop."""
    identity = (
        '    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):\n'
        '        monkeypatch.setenv(name, "door@test.invalid")\n'
    )
    assert _scan_source(tmp_path, _EMPTIED_GIT.replace("IDENTITY", identity))[0] == []


def test_an_author_email_alone_is_convicted_because_git_resolves_the_committer_separately(tmp_path):
    """A half cure: git commit still asks for the committer's email and exits 128."""
    identity = '    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "a@test.invalid")\n'
    violations, _acquitted = _scan_source(tmp_path, _EMPTIED_GIT.replace("IDENTITY", identity))
    assert _lines(violations) == [7]
    assert "GIT_COMMITTER_EMAIL" in violations[0][1] and "GIT_AUTHOR_EMAIL" not in violations[0][1]


def test_a_user_email_written_to_git_config_is_acquitted(tmp_path):
    """`git config user.email` (or `-c user.email=`) answers both identities at once."""
    identity = '    subprocess.run(["git", "config", "--global", "user.email", "t@test.invalid"], check=True)\n'
    source = "import subprocess\n" + _EMPTIED_GIT.replace("IDENTITY", identity)
    assert _scan_source(tmp_path, source)[0] == []


# Arm H: a sandbox mounts an empty .git in each writable root, so a bare existence test calls it a repo.
_GIT_WALK = (
    "import os\n"
    "from pathlib import Path\n\n\n"
    "def repo_root(start):\n"
    "    for parent in (start, *start.parents):\n"
    "        if PROBE:\n"
    "            return parent\n"
    "    return None\n"
)


@pytest.mark.parametrize(
    "probe",
    [
        '(parent / ".git").exists()',
        '(parent / ".git").is_dir()',
        'os.path.exists(os.path.join(parent, ".git"))',
        'os.path.isdir(os.path.join(parent, ".git"))',
    ],
)
def test_an_existence_test_on_git_is_convicted_at_its_line(tmp_path, probe):
    """home_paths 1.0: the walk stopped at the empty /tmp/.git a Codex sandbox mounts."""
    violations, _acquitted = _scan_source(tmp_path, _GIT_WALK.replace("PROBE", probe))
    assert _lines(violations) == [7]
    assert "empty" in violations[0][1]


@pytest.mark.parametrize(
    "probe",
    [
        '(parent / ".git").is_file()',
        '(parent / "pyproject.toml").exists()',
        '_is_git_marker(parent / ".git")',
    ],
)
def test_a_probe_that_an_empty_directory_cannot_satisfy_is_acquitted(tmp_path, probe):
    """A .git FILE is a worktree's pointer; a sandbox mounts directories only."""
    assert _scan_source(tmp_path, _GIT_WALK.replace("PROBE", probe))[0] == []


def _walk_also(line):
    """The bare-exists walk with one more line in the same function."""
    return _GIT_WALK.replace("PROBE", '(parent / ".git").exists()').replace(
        "            return parent\n", "            return parent\n" + line
    )


@pytest.mark.parametrize(
    "reads_inside",
    [
        '        (parent / ".git" / "HEAD").is_file()\n',
        '        os.path.isfile(os.path.join(parent, ".git", "HEAD"))\n',
        '        any((parent / ".git").iterdir())\n',
        '        os.listdir(os.path.join(parent, ".git"))\n',
    ],
)
def test_a_function_that_also_reads_inside_the_marker_is_acquitted(tmp_path, reads_inside):
    """ignore_handler 1.1.2's cure: existence plus HEAD or a non-empty listing of .git itself."""
    assert _scan_source(tmp_path, _walk_also(reads_inside))[0] == []


@pytest.mark.parametrize("unrelated", ["        any(parent.iterdir())\n", '        (parent / "HEAD").exists()\n'])
def test_a_listing_or_head_elsewhere_does_not_acquit(tmp_path, unrelated):
    """aipass new_project 1.x: iterdir over the projects dir, beside a bare `.git` is_dir."""
    assert _lines(_scan_source(tmp_path, _walk_also(unrelated))[0]) == [7]


def test_a_git_existence_test_in_a_test_file_is_not_judged(tmp_path):
    """A fixture plants its own .git; only product code walks a host's tree."""
    (tmp_path / "tests").mkdir()
    source = _GIT_WALK.replace("PROBE", '(parent / ".git").exists()')
    assert _scan_source(tmp_path, source, name="tests/test_walk.py")[0] == []
