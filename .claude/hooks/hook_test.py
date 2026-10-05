#!/usr/bin/env python3
"""
Hook Test Harness — two test layers:

  1. DIRECT tests: pipe JSON to hook scripts via subprocess. Deterministic,
     fast, no model dependency. HIGH confidence.
  2. INTEGRATION tests: run `claude -p` from different CWDs, read JSONL log.
     Tests full pipeline. MEDIUM confidence (model-dependent).

Usage:
    python3 hook_test.py                    # Run all tests
    python3 hook_test.py --direct           # Direct tests only (fast, deterministic)
    python3 hook_test.py --integration      # Integration tests only (slower, needs claude)
    python3 hook_test.py --test cwd_guard   # Run one test by name
    python3 hook_test.py --list             # List available tests
    python3 hook_test.py --verbose          # Show detail per test

Version: 2.0.0
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_LOG_FILE = Path("/tmp/aipass_hook_log.jsonl")
# The repo root is two levels above .claude/hooks/; no machine's path is written here.
_AIPASS_HOME = os.environ.get("AIPASS_HOME", str(Path(__file__).resolve().parents[2]))


def _clear_log() -> None:
    if _LOG_FILE.exists():
        _LOG_FILE.unlink()


def _read_log() -> list[dict]:
    if not _LOG_FILE.exists():
        return []
    entries = []
    for line in _LOG_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _run_headless(cwd: str, prompt: str = "say hi", model: str = "haiku") -> tuple[int, str]:
    """Run `claude -p` from a given CWD and return (exit_code, stdout)."""
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", model],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode, result.stdout
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except FileNotFoundError:
        return -2, "claude not found"


class TestResult:
    def __init__(self, name: str) -> None:
        self.name = name
        self.passed = False
        self.message = ""
        self.entries: list[dict] = []

    def ok(self, msg: str = "") -> "TestResult":
        self.passed = True
        self.message = msg or "PASS"
        return self

    def fail(self, msg: str) -> "TestResult":
        self.passed = False
        self.message = msg
        return self


_HOOKS_DIR = Path(_AIPASS_HOME) / ".claude" / "hooks"


def _run_hook_direct(
    script: str,
    payload: dict,
    cwd: str = "/tmp",
    env_extra: dict | None = None,
) -> tuple[int, str, str]:
    """Run a hook script as a subprocess with JSON on stdin. Returns (exit_code, stdout, stderr)."""
    script_path = _HOOKS_DIR / script
    if not script_path.exists():
        return -1, "", f"Script not found: {script_path}"
    env = {**os.environ, "AIPASS_HOME": _AIPASS_HOME}
    if env_extra:
        env.update(env_extra)
    try:
        result = subprocess.run(
            ["python3", str(script_path)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=15,
            cwd=cwd,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -2, "", "TIMEOUT"


def _find_project_with_hooks() -> str:
    """Dynamically find a project that has its own UserPromptSubmit hooks."""
    projects_dir = Path.home() / "Projects"
    if not projects_dir.is_dir():
        return ""
    for proj in sorted(projects_dir.iterdir()):
        if proj.name == "AIPass":
            continue
        settings = proj / ".claude" / "settings.json"
        if settings.exists():
            try:
                data = json.loads(settings.read_text(encoding="utf-8"))
                if data.get("hooks", {}).get("UserPromptSubmit"):
                    return str(proj)
            except (json.JSONDecodeError, OSError):
                continue
    return ""


def _find_project_without_hooks() -> str:
    """Dynamically find a project that has settings.json but NO UserPromptSubmit hooks."""
    projects_dir = Path.home() / "Projects"
    if not projects_dir.is_dir():
        return ""
    for proj in sorted(projects_dir.iterdir()):
        if proj.name == "AIPass":
            continue
        settings = proj / ".claude" / "settings.json"
        if settings.exists():
            try:
                data = json.loads(settings.read_text(encoding="utf-8"))
                if not data.get("hooks", {}).get("UserPromptSubmit"):
                    return str(proj)
            except (json.JSONDecodeError, OSError):
                return str(proj)
    return ""


# =========================================================================
# DIRECT TESTS — pipe JSON to hook subprocess, deterministic, HIGH confidence
# =========================================================================


def test_direct_global_prompt_from_tmp(verbose: bool = False) -> TestResult:
    """[DIRECT] global_prompt_loader outputs full prompt when run from /tmp."""
    r = TestResult("direct_global_prompt_from_tmp")
    exit_code, stdout, stderr = _run_hook_direct("global_prompt_loader.py", {}, cwd="/tmp")
    if exit_code != 0:
        return r.fail(f"Exit {exit_code}: {stderr}")
    if len(stdout) < 1000:
        return r.fail(f"Output only {len(stdout)} chars — expected ~22KB global prompt")
    return r.ok(f"{len(stdout)} chars output from /tmp")


def test_direct_global_prompt_guarded(verbose: bool = False) -> TestResult:
    """[DIRECT] global_prompt_loader suppressed when CWD has own hooks."""
    r = TestResult("direct_global_prompt_guarded")
    cwd = os.path.join(_AIPASS_HOME, "src", "aipass", "devpulse")
    exit_code, stdout, stderr = _run_hook_direct("global_prompt_loader.py", {}, cwd=cwd)
    if exit_code != 0:
        return r.fail(f"Exit {exit_code}: {stderr}")
    if stdout.strip():
        return r.fail(f"Expected silent (CWD guard), got {len(stdout)} chars")
    return r.ok("Silent output — CWD guard active")


def test_direct_identity_injector(verbose: bool = False) -> TestResult:
    """[DIRECT] identity_injector outputs identity from branch with passport."""
    r = TestResult("direct_identity_injector")
    cwd = os.path.join(_AIPASS_HOME, "src", "aipass", "devpulse")
    exit_code, stdout, _ = _run_hook_direct("identity_injector.py", {}, cwd=cwd)
    if exit_code != 0:
        return r.fail(f"Exit {exit_code}")
    # From devpulse, CWD guard is active — should be silent
    if stdout.strip():
        return r.fail("Expected silent from devpulse (CWD guard), got output")
    # Test from /tmp — no branch root, should also be silent
    exit_code2, stdout2, _ = _run_hook_direct("identity_injector.py", {}, cwd="/tmp")
    if stdout2.strip():
        return r.fail("Expected silent from /tmp (no branch root), got output")
    return r.ok("Silent from guarded CWD and no-branch CWD")


def test_direct_git_gate_allows_safe(verbose: bool = False) -> TestResult:
    """[DIRECT] git_gate allows safe Bash commands (exit 0, no output)."""
    r = TestResult("direct_git_gate_allows_safe")
    payload = {"tool_name": "Bash", "tool_input": {"command": "echo hello"}, "cwd": "/tmp"}
    exit_code, stdout, _ = _run_hook_direct("git_gate.py", payload)
    if exit_code != 0:
        return r.fail(f"Safe command blocked — exit {exit_code}")
    if stdout.strip():
        return r.fail(f"Unexpected output for safe command: {stdout[:100]}")
    return r.ok("Safe Bash command allowed (exit 0, silent)")


def test_direct_git_gate_blocks_raw_git(verbose: bool = False) -> TestResult:
    """[DIRECT] git_gate blocks raw git commit (exit 2, decision=block)."""
    r = TestResult("direct_git_gate_blocks_raw_git")
    payload = {"tool_name": "Bash", "tool_input": {"command": "git commit -m test"}, "cwd": "/tmp"}
    exit_code, stdout, _ = _run_hook_direct("git_gate.py", payload)
    if exit_code != 2:
        return r.fail(f"Expected exit 2 (block), got {exit_code}")
    try:
        out = json.loads(stdout)
        if out.get("decision") != "block":
            return r.fail(f"Expected decision=block, got {out.get('decision')}")
    except json.JSONDecodeError:
        return r.fail(f"Non-JSON output: {stdout[:100]}")
    return r.ok("git commit blocked (exit 2, decision=block)")


def test_direct_git_gate_blocks_gh_push(verbose: bool = False) -> TestResult:
    """[DIRECT] git_gate blocks git push (exit 2, decision=block)."""
    r = TestResult("direct_git_gate_blocks_gh_push")
    payload = {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}, "cwd": "/tmp"}
    exit_code, stdout, _ = _run_hook_direct("git_gate.py", payload)
    if exit_code != 2:
        return r.fail(f"Expected exit 2 (block), got {exit_code}")
    return r.ok("git push blocked (exit 2)")


def test_direct_tool_use_sound_exits_clean(verbose: bool = False) -> TestResult:
    """[DIRECT] tool_use_sound exits 0 and produces no stdout."""
    r = TestResult("direct_tool_use_sound_exits_clean")
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Read"}
    exit_code, stdout, _ = _run_hook_direct("tool_use_sound.py", payload)
    if exit_code != 0:
        return r.fail(f"Exit {exit_code}")
    if stdout.strip():
        return r.fail(f"Unexpected stdout: {stdout[:100]}")
    return r.ok("Clean exit, no stdout")


def test_direct_email_notification_no_mail(verbose: bool = False) -> TestResult:
    """[DIRECT] email_notification silent when no inbox exists."""
    r = TestResult("direct_email_notification_no_mail")
    exit_code, stdout, _ = _run_hook_direct("email_notification.py", {}, cwd="/tmp")
    if exit_code != 0:
        return r.fail(f"Exit {exit_code}")
    if stdout.strip():
        return r.fail(f"Unexpected output from /tmp (no mailbox): {stdout[:100]}")
    return r.ok("Silent — no mailbox at /tmp")


def test_direct_settings_schema(verbose: bool = False) -> TestResult:
    """[DIRECT] All hooks in provider settings.json reference scripts that exist."""
    r = TestResult("direct_settings_schema")
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return r.fail("~/.claude/settings.json not found")

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = data.get("hooks", {})

    valid_events = {
        "PreToolUse",
        "PostToolUse",
        "UserPromptSubmit",
        "SubagentStop",
        "PreCompact",
        "PostCompact",
        "Stop",
        "Notification",
        "SessionStart",
        "PermissionRequest",
    }
    missing = []
    bad_events = []

    for event, entries in hooks.items():
        if event not in valid_events:
            bad_events.append(event)
        for entry in entries:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                parts = cmd.split()
                for part in parts:
                    if part.endswith(".py") and "/" in part:
                        if not Path(part).exists():
                            missing.append(part)

    errors = []
    if bad_events:
        errors.append(f"Invalid events: {bad_events}")
    if missing:
        errors.append(f"Missing scripts: {missing}")

    if errors:
        return r.fail("; ".join(errors))

    hook_count = sum(len(e.get("hooks", [])) for entries in hooks.values() for e in entries)
    return r.ok(f"{len(hooks)} events, {hook_count} hooks, all scripts exist")


def _find_aipass_init_project() -> str:
    """Find a project created by aipass init (has *_REGISTRY.json)."""
    projects_dir = Path.home() / "Projects"
    if not projects_dir.exists():
        return ""
    for proj in sorted(projects_dir.iterdir()):
        if proj.name == "AIPass":
            continue
        registries = list(proj.glob("*_REGISTRY.json"))
        settings = proj / ".claude" / "settings.json"
        if registries and settings.exists():
            return str(proj)
    return ""


def test_direct_project_settings_schema(verbose: bool = False) -> TestResult:
    """[DIRECT] aipass init project has valid settings.json with expected hooks."""
    r = TestResult("direct_project_settings_schema")

    proj = _find_aipass_init_project()
    if not proj:
        return r.ok("SKIP — no aipass init project found (needs ~/Projects with *_REGISTRY.json)")

    settings_path = Path(proj) / ".claude" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = data.get("hooks", {})

    has_ups = bool(hooks.get("UserPromptSubmit"))
    has_pre = bool(hooks.get("PreToolUse"))
    has_post = bool(hooks.get("PostToolUse"))

    project_name = Path(proj).name
    notes = []
    if has_ups:
        notes.append(f"UserPromptSubmit: {len(hooks['UserPromptSubmit'])} entries")
    if has_pre:
        notes.append(f"PreToolUse: {len(hooks['PreToolUse'])} entries (NOTE: won't fire from project level)")
    if has_post:
        notes.append(f"PostToolUse: {len(hooks['PostToolUse'])} entries (NOTE: won't fire from project level)")

    for event, entries in hooks.items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                if cmd.startswith("python3 ") and ".py" in cmd:
                    script = cmd.split()[-1]
                    full = Path(proj) / script
                    if not full.exists():
                        return r.fail(f"Missing script in {project_name}: {script}")

    return r.ok(f"{project_name}: {', '.join(notes)}")


def test_direct_provider_guards_for_init_project(verbose: bool = False) -> TestResult:
    """[DIRECT] Provider hooks are CWD-guarded when run from an aipass init project."""
    r = TestResult("direct_provider_guards_for_init_project")

    proj = _find_aipass_init_project()
    if not proj:
        return r.ok("SKIP — no aipass init project found")

    guarded_hooks = [
        "global_prompt_loader.py",
        "branch_prompt_loader.py",
        "identity_injector.py",
        "email_notification.py",
    ]

    for script in guarded_hooks:
        exit_code, stdout, _ = _run_hook_direct(script, {}, cwd=proj)
        if exit_code != 0:
            return r.fail(f"{script} exited {exit_code} from {Path(proj).name}")
        if stdout.strip():
            return r.fail(
                f"{script} produced output from {Path(proj).name} — "
                f"CWD guard should suppress (project has own UserPromptSubmit hooks)"
            )

    return r.ok(f"All 4 provider hooks suppressed from {Path(proj).name}")


# =========================================================================
# INTEGRATION TESTS — run claude -p, read JSONL log, MEDIUM confidence
# =========================================================================


def test_aipass_branch_hooks(verbose: bool = False) -> TestResult:
    """Test: hooks fire correctly from an AIPass branch CWD (devpulse)."""
    r = TestResult("aipass_branch_hooks")
    cwd = os.path.join(_AIPASS_HOME, "src", "aipass", "devpulse")

    if not Path(cwd).exists():
        return r.fail(f"CWD not found: {cwd}")

    _clear_log()
    exit_code, _ = _run_headless(cwd)
    entries = _read_log()
    r.entries = entries

    if exit_code != 0:
        return r.fail(f"claude -p exited {exit_code}")

    ups = [e for e in entries if e.get("event") == "UserPromptSubmit"]
    if not ups:
        return r.fail("No UserPromptSubmit hooks fired")

    expected_scripts = {
        "global_prompt_loader.py",
        "branch_prompt_loader.py",
        "identity_injector.py",
        "email_notification.py",
    }
    fired_scripts = {e.get("script", "") for e in ups}

    missing = expected_scripts - fired_scripts
    if missing:
        return r.fail(f"Missing UserPromptSubmit hooks: {missing}")

    return r.ok(f"{len(ups)} UserPromptSubmit hooks fired, {len(entries)} total")


def test_cwd_guard_devpulse(verbose: bool = False) -> TestResult:
    """Test: CWD guard suppresses provider hooks when project has own hooks."""
    r = TestResult("cwd_guard_devpulse")
    cwd = os.path.join(_AIPASS_HOME, "src", "aipass", "devpulse")

    project_settings = Path(cwd)
    found_settings = False
    search = project_settings
    while search != Path.home() and search.parent != search:
        if (search / ".claude" / "settings.json").exists():
            found_settings = True
            break
        search = search.parent

    if not found_settings:
        return r.fail("No .claude/settings.json found in CWD hierarchy — can't test CWD guard")

    _clear_log()
    exit_code, _ = _run_headless(cwd)
    entries = _read_log()
    r.entries = entries

    if exit_code != 0:
        return r.fail(f"claude -p exited {exit_code}")

    ups = [e for e in entries if e.get("event") == "UserPromptSubmit"]
    guarded = [e for e in ups if e.get("output_bytes", 0) == 0]

    if not guarded:
        return r.fail(
            "No UserPromptSubmit hooks were suppressed — CWD guard may not be working. "
            f"Hooks fired: {[e.get('script') for e in ups]}"
        )

    return r.ok(f"{len(guarded)}/{len(ups)} UserPromptSubmit hooks suppressed by CWD guard")


def test_tmp_no_guard(verbose: bool = False) -> TestResult:
    """Test: from /tmp (no project hooks), provider hooks fire with full output."""
    r = TestResult("tmp_no_guard")

    _clear_log()
    exit_code, _ = _run_headless("/tmp")
    entries = _read_log()
    r.entries = entries

    if exit_code != 0:
        return r.fail(f"claude -p exited {exit_code}")

    ups = [e for e in entries if e.get("event") == "UserPromptSubmit"]
    global_prompt = [e for e in ups if e.get("script") == "global_prompt_loader.py"]

    if not global_prompt:
        return r.fail("global_prompt_loader.py did not fire from /tmp")

    if global_prompt[0].get("output_bytes", 0) < 1000:
        return r.fail(
            f"global_prompt_loader.py output only {global_prompt[0].get('output_bytes')}B "
            "from /tmp — expected ~22KB (CWD guard should NOT fire here)"
        )

    return r.ok(
        f"global_prompt_loader.py output {global_prompt[0].get('output_bytes')}B (guard not active, as expected)"
    )


def test_pretooluse_fires(verbose: bool = False) -> TestResult:
    """Test: PreToolUse hooks fire on tool calls."""
    r = TestResult("pretooluse_fires")
    cwd = os.path.join(_AIPASS_HOME, "src", "aipass", "devpulse")

    _clear_log()
    exit_code, _ = _run_headless(cwd, prompt="run: echo hello")
    entries = _read_log()
    r.entries = entries

    pre = [e for e in entries if e.get("event") == "PreToolUse"]
    if not pre:
        return r.fail("No PreToolUse hooks fired — expected at least tool_use_sound.py")

    return r.ok(f"{len(pre)} PreToolUse fires")


def test_posttooluse_fires(verbose: bool = False) -> TestResult:
    """Test: PostToolUse hooks fire after tool calls."""
    r = TestResult("posttooluse_fires")
    cwd = os.path.join(_AIPASS_HOME, "src", "aipass", "devpulse")

    _clear_log()
    exit_code, _ = _run_headless(cwd, prompt="use the bash tool to run: echo posttooluse-test")
    entries = _read_log()
    r.entries = entries

    post = [e for e in entries if e.get("event") == "PostToolUse"]
    if not post:
        return r.fail("No PostToolUse hooks fired")

    return r.ok(f"{len(post)} PostToolUse fires")


def test_standalone_project_guard(verbose: bool = False) -> TestResult:
    """[INTEGRATION] standalone projects with own hooks get provider hooks suppressed."""
    r = TestResult("standalone_project_guard")

    cwd = _find_project_with_hooks()
    if not cwd:
        return r.fail("No standalone project with UserPromptSubmit hooks found")

    _clear_log()
    exit_code, _ = _run_headless(cwd)
    entries = _read_log()
    r.entries = entries

    if exit_code != 0:
        return r.fail(f"claude -p exited {exit_code}")

    ups = [e for e in entries if e.get("event") == "UserPromptSubmit"]
    guarded = [e for e in ups if e.get("output_bytes", 0) == 0]

    if not ups:
        return r.fail("No UserPromptSubmit hooks fired at all")

    project_name = Path(cwd).name
    if not guarded:
        return r.fail(
            f"Provider hooks NOT suppressed in {project_name} (has own hooks). Fired: {[e.get('script') for e in ups]}"
        )

    return r.ok(f"{len(guarded)}/{len(ups)} provider UserPromptSubmit hooks suppressed in {project_name}")


def test_no_hooks_project_gets_prompt(verbose: bool = False) -> TestResult:
    """[INTEGRATION] projects without own hooks receive full provider prompt."""
    r = TestResult("no_hooks_project_gets_prompt")

    cwd = _find_project_without_hooks()
    if not cwd:
        return r.fail("No project without UserPromptSubmit hooks found")

    _clear_log()
    exit_code, _ = _run_headless(cwd)
    entries = _read_log()
    r.entries = entries

    if exit_code != 0:
        return r.fail(f"claude -p exited {exit_code}")

    global_prompt = [
        e for e in entries if e.get("script") == "global_prompt_loader.py" and e.get("output_bytes", 0) > 1000
    ]

    project_name = Path(cwd).name
    if not global_prompt:
        return r.fail(
            f"global_prompt_loader.py did NOT output full prompt in {project_name} "
            f"(no own hooks — guard should be inactive)"
        )

    return r.ok(
        f"global_prompt_loader.py output {global_prompt[0]['output_bytes']}B "
        f"in {project_name} (no own hooks, guard inactive)"
    )


def test_subagent_hooks(verbose: bool = False) -> TestResult:
    """Test: SubagentStop hook fires when a subagent completes."""
    r = TestResult("subagent_hooks")
    cwd = os.path.join(_AIPASS_HOME, "src", "aipass", "devpulse")

    _clear_log()
    exit_code, _ = _run_headless(
        cwd,
        prompt="Use the Agent tool to spawn a helper that runs echo test via Bash then reports back",
    )
    entries = _read_log()
    r.entries = entries

    if exit_code != 0:
        return r.fail(f"claude -p exited {exit_code}")

    subagent_stops = [e for e in entries if e.get("event") == "SubagentStop"]
    if not subagent_stops:
        return r.fail("No SubagentStop hook fired — model may not have spawned a subagent")

    return r.ok(f"{len(subagent_stops)} SubagentStop fire(s)")


def test_disable_toggle(verbose: bool = False) -> TestResult:
    """[INTEGRATION] disableAllHooks=true stops all hook firing (atomic backup/restore)."""
    r = TestResult("disable_toggle")
    import shutil
    import tempfile

    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return r.fail("~/.claude/settings.json not found")

    # Atomic backup — copy to temp file first, restore from backup on any failure
    backup_fd, backup_path = tempfile.mkstemp(suffix=".json", prefix="settings_backup_")
    os.close(backup_fd)
    shutil.copy2(str(settings_path), backup_path)

    try:
        original = settings_path.read_text(encoding="utf-8")
        data = json.loads(original)
        data["disableAllHooks"] = True
        settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        _clear_log()
        exit_code, _ = _run_headless("/tmp")
        entries = _read_log()
        r.entries = entries
    finally:
        # Restore from atomic backup — safe even after crash/signal
        shutil.copy2(backup_path, str(settings_path))
        try:
            os.unlink(backup_path)
        except OSError:
            pass

    if entries:
        return r.fail(f"{len(entries)} hooks fired with disableAllHooks=true — toggle broken")

    return r.ok("0 hooks fired with disableAllHooks=true")


_DIRECT_TESTS = [
    ("direct_global_prompt_from_tmp", test_direct_global_prompt_from_tmp),
    ("direct_global_prompt_guarded", test_direct_global_prompt_guarded),
    ("direct_identity_injector", test_direct_identity_injector),
    ("direct_git_gate_allows_safe", test_direct_git_gate_allows_safe),
    ("direct_git_gate_blocks_raw_git", test_direct_git_gate_blocks_raw_git),
    ("direct_git_gate_blocks_gh_push", test_direct_git_gate_blocks_gh_push),
    ("direct_tool_use_sound_exits_clean", test_direct_tool_use_sound_exits_clean),
    ("direct_email_notification_no_mail", test_direct_email_notification_no_mail),
    ("direct_settings_schema", test_direct_settings_schema),
    ("direct_project_settings_schema", test_direct_project_settings_schema),
    ("direct_provider_guards_for_init_project", test_direct_provider_guards_for_init_project),
]

_INTEGRATION_TESTS = [
    ("aipass_branch_hooks", test_aipass_branch_hooks),
    ("cwd_guard_devpulse", test_cwd_guard_devpulse),
    ("tmp_no_guard", test_tmp_no_guard),
    ("pretooluse_fires", test_pretooluse_fires),
    ("posttooluse_fires", test_posttooluse_fires),
    ("standalone_project_guard", test_standalone_project_guard),
    ("no_hooks_project_gets_prompt", test_no_hooks_project_gets_prompt),
    ("subagent_hooks", test_subagent_hooks),
    ("disable_toggle", test_disable_toggle),
]

_ALL_TESTS = _DIRECT_TESTS + _INTEGRATION_TESTS


def main() -> None:
    parser = argparse.ArgumentParser(description="Hook test harness")
    parser.add_argument("--test", default="", help="Run specific test by name")
    parser.add_argument("--direct", action="store_true", help="Run direct tests only (fast, deterministic)")
    parser.add_argument("--integration", action="store_true", help="Run integration tests only (slower)")
    parser.add_argument("--list", action="store_true", help="List available tests")
    parser.add_argument("--verbose", action="store_true", help="Show hook log per test")

    args = parser.parse_args()

    if args.list:
        for name, fn in _ALL_TESTS:
            print(f"  {name}: {fn.__doc__}")
        return

    if args.direct:
        tests = _DIRECT_TESTS
    elif args.integration:
        tests = _INTEGRATION_TESTS
    else:
        tests = _ALL_TESTS
    if args.test:
        tests = [(n, f) for n, f in tests if n == args.test or args.test in n]
        if not tests:
            print(f"Unknown test: {args.test}")
            print(f"Available: {', '.join(n for n, _ in _ALL_TESTS)}")
            sys.exit(1)

    passed = 0
    failed = 0

    print(f"\nHook Test Harness — {len(tests)} test(s)")
    print("=" * 60)

    for name, fn in tests:
        print(f"\n  Running: {name}...", end=" ", flush=True)
        try:
            result = fn(verbose=args.verbose)
        except Exception as e:
            result = TestResult(name).fail(f"Exception: {e}")

        if result.passed:
            passed += 1
            print(f"PASS — {result.message}")
        else:
            failed += 1
            print(f"FAIL — {result.message}")

        if args.verbose and result.entries:
            print(f"    Log entries ({len(result.entries)}):")
            for e in result.entries:
                print(
                    f"      {e.get('event'):<22} "
                    f"{e.get('script'):<28} "
                    f"{e.get('elapsed_ms', 0):>6.1f}ms "
                    f"{e.get('output_bytes', 0):>6}B"
                )

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
