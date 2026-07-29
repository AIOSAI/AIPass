# =================== AIPass ====================
# Name: test_wiring.py
# Description: Cross-OS end-to-end WIRING tests against the installed wheel
# Version: 1.0.0
# Created: 2026-06-03
# =============================================

"""Cross-OS end-to-end WIRING tests (FPLAN-0239, P1 of DPLAN-0194).

This proves AIPass *wiring* — not units-with-mocks — by building the wheel,
installing it into a clean venv (see ``conftest.py``), and asserting a 4-tier
ladder against the real installed package:

    T0  install + console scripts exist and run
    T1  ``aipass init`` scaffolds a project correctly
    T2a a hook actually fires, blocks, and leaves a sentinel record
    T3  ``drone`` resolves a real branch and executes it via subprocess

It is RED-FIRST: it is expected to fail on Windows in known places (symlink
init, bin-vs-Scripts, /tmp). The harness itself is written to be cross-OS so
those reds reflect AIPass bugs, not harness bugs.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from conftest import REPO_ROOT, CleanVenv


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a subprocess capturing text output with a bounded timeout."""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("timeout", 60)
    return subprocess.run(cmd, **kwargs)


# ===========================================================================
# TIER 0 — clean-venv wheel install + binaries
# ===========================================================================


def test_t0_wheel_built(wheel: Path) -> None:
    """The wheel built and is named for aipass."""
    assert wheel.exists()
    assert wheel.suffix == ".whl"
    assert wheel.name.startswith("aipass-")


def test_t0_venv_has_pip(clean_venv: CleanVenv) -> None:
    """Clean venv has a working pip — not a silently-broken venv (ref #495)."""
    result = _run([str(clean_venv.python), "-m", "pip", "--version"])
    assert result.returncode == 0, result.stderr


def test_t0_console_scripts_exist(clean_venv: CleanVenv) -> None:
    """Both ``aipass`` and ``drone`` console scripts are installed."""
    assert clean_venv.aipass.exists(), f"missing aipass at {clean_venv.aipass}"
    assert clean_venv.drone.exists(), f"missing drone at {clean_venv.drone}"


def test_t0_drone_version_runs(clean_venv: CleanVenv) -> None:
    """``drone --version`` runs (entry point imports cleanly)."""
    result = _run([str(clean_venv.drone), "--version"])
    assert result.returncode == 0, result.stderr


def test_t0_aipass_init_help_runs(clean_venv: CleanVenv) -> None:
    """``aipass init --help`` runs (the init entry point imports cleanly)."""
    result = _run([str(clean_venv.aipass), "init", "--help"])
    assert result.returncode == 0, result.stderr


# ===========================================================================
# TIER 1 — aipass init scaffolds correctly
# ===========================================================================


@pytest.fixture(scope="module")
def init_project(clean_venv: CleanVenv, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run ``aipass init <proj> demo`` in a clean neutral dir, return the project.

    ``aipass init`` REFUSES when a ``*_REGISTRY.json`` sits in or above CWD
    (``_guard_init``), so we run it from a pristine tmp dir whose parents have
    no registry. ``AIPASS_HOME`` is left UNSET so the .venv-symlink step (a
    Windows-only failure tracked separately) is skipped — this test must pass
    on Linux.
    """
    neutral = tmp_path_factory.mktemp("neutral_init_cwd")
    proj = neutral / "proj"

    env = {
        "PATH": _path_env(),
        "HOME": str(neutral),
    }
    if sys.platform == "win32":
        # Windows needs a few base vars for subprocess/venv tooling to work.
        import os as _os

        for key in ("SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "PATHEXT", "COMSPEC"):
            if key in _os.environ:
                env[key] = _os.environ[key]

    result = subprocess.run(
        [str(clean_venv.aipass), "init", str(proj), "demo"],
        cwd=str(neutral),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"aipass init failed (exit {result.returncode}).\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return proj


def _path_env() -> str:
    """Minimal PATH for the init subprocess (portable across OSes)."""
    import os

    return os.environ.get("PATH", "")


def test_t1_registry_created_and_valid(init_project: Path) -> None:
    """DEMO_REGISTRY.json exists, is valid JSON, and names DEMO."""
    registry = init_project / "DEMO_REGISTRY.json"
    assert registry.is_file(), f"missing {registry}"
    data = json.loads(registry.read_text(encoding="utf-8"))
    assert data["metadata"]["name"] == "DEMO"


def test_t1_claude_settings_deny_enterplanmode(init_project: Path) -> None:
    """.claude/settings.json exists and its permissions.deny blocks EnterPlanMode."""
    settings = init_project / ".claude" / "settings.json"
    assert settings.is_file(), f"missing {settings}"
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "EnterPlanMode" in data["permissions"]["deny"]


def test_t1_src_package_scaffolded(init_project: Path) -> None:
    """src/demo/__init__.py is created."""
    assert (init_project / "src" / "demo" / "__init__.py").is_file()


def test_t1_gitignore_mentions_venv(init_project: Path) -> None:
    """.gitignore mentions .venv."""
    gitignore = init_project / ".gitignore"
    assert gitignore.is_file()
    assert ".venv" in gitignore.read_text(encoding="utf-8")


def test_t1_no_trinity_no_passport(init_project: Path) -> None:
    """Projects are NOT citizens: no .trinity/ dir and no passport.json."""
    assert not (init_project / ".trinity").exists()
    assert not (init_project / ".trinity" / "passport.json").exists()


# ===========================================================================
# TIER 2a — synthetic hook fire (module form, sentinel UUID, engine.jsonl)
# ===========================================================================

_RM_GATE_CONFIG = {
    "hooks_enabled": True,
    "PreToolUse": {
        "rm_gate": {
            "enabled": True,
            "handler": "aipass.hooks.apps.handlers.security.rm_gate.handle",
            "matcher": "Bash",
        }
    },
}


def _fire_hook(clean_venv: CleanVenv, work: Path, command: str, agent_id: str) -> subprocess.CompletedProcess:
    """Invoke the Claude bridge in MODULE form for a single PreToolUse event.

    Module form (``python -m aipass.hooks...``) is venv-portable and avoids the
    bin/Scripts split — the very bug this suite tests for.
    """
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "agent_id": agent_id,
        }
    )
    env = _hook_env(work)
    return subprocess.run(
        [
            str(clean_venv.python),
            "-m",
            "aipass.hooks.apps.handlers.bridges.claude",
            "PreToolUse:rm_gate",
        ],
        input=payload,
        cwd=str(work),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _hook_env(work: Path) -> dict:
    """Build a minimal env for the hook subprocess, with AIPASS_HOME isolated."""
    import os

    env = dict(os.environ)
    env["AIPASS_HOME"] = str(work)
    return env


def _engine_log(clean_venv: CleanVenv) -> Path | None:
    """Glob the installed package for aipass/hooks/logs/engine.jsonl."""
    hits = sorted(clean_venv.site_packages.glob("aipass/hooks/logs/engine.jsonl"))
    return hits[0] if hits else None


def _trust_registry(clean_venv: CleanVenv, op: str, work: Path) -> None:
    """Run trust_registry.enroll/revoke inside the clean venv.

    The harness python has no aipass installed on e2e-wheel runners (only the
    clean venv gets the wheel — that isolation is the point of this suite), so
    the trust call must go through the venv's own interpreter, never a
    harness-level import.
    """
    proc = subprocess.run(
        [
            str(clean_venv.python),
            "-c",
            f"from aipass.hooks.apps.handlers.config.trust_registry import {op}; {op}({str(work)!r})",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"trust_registry.{op} failed in clean venv:\n{proc.stdout}\n{proc.stderr}")


@pytest.fixture(scope="module")
def hook_workspace(clean_venv: CleanVenv, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """A tmp workspace holding an isolated .aipass/hooks.json with only rm_gate.

    Explicitly enrolled in the trust registry rather than relying on
    find_project_config()'s bootstrap() path: bootstrap() only auto-trusts
    AIPASS_HOME when ~/.aipass/trusted_projects.json doesn't exist yet. On a
    machine with a real, already-populated registry (any dev box with prior
    AIPass usage), bootstrap() never fires, this workspace is never enrolled,
    and the hook silently discovers zero handlers (fails open) instead of
    firing rm_gate — machine-dependent flakiness this fixture must not rely
    on (ref e2e rm_gate discovery-0-handlers, dispatch fc0ebf7d).
    """
    work = tmp_path_factory.mktemp("hook_ws")
    aipass_dir = work / ".aipass"
    aipass_dir.mkdir(parents=True, exist_ok=True)
    (aipass_dir / "hooks.json").write_text(json.dumps(_RM_GATE_CONFIG), encoding="utf-8")
    _trust_registry(clean_venv, "enroll", work)
    try:
        yield work
    finally:
        _trust_registry(clean_venv, "revoke", work)


def test_t2a_rm_gate_blocks(clean_venv: CleanVenv, hook_workspace: Path) -> None:
    """rm -rf is blocked via {"decision":"block"} on STDOUT with exit code 2.

    Block contract: every security gate (rm/git/edit/subagent/presence) returns
    exit_code 2 plus a block-JSON decision on stdout, and the bridge propagates
    that exit code. The non-zero exit is the cross-event block signal — it is
    what lets a UserPromptSubmit gate (presence_gate) actually cancel a prompt,
    not just PreToolUse. Claude Code surfaces the stdout decision reason either
    way. (Pre-FPLAN-0289 the bridge swallowed the exit code, so this test once
    pinned exit 0; beb048d corrected the bridge to propagate it.)
    """
    sentinel = f"e2e-block-{uuid.uuid4()}"
    proc = _fire_hook(clean_venv, hook_workspace, "rm -rf /tmp/x", sentinel)

    assert proc.returncode == 2, f"expected exit 2 (block), got {proc.returncode}. stderr:\n{proc.stderr}"
    decision = json.loads(proc.stdout)
    assert decision.get("decision") == "block", f"stdout was: {proc.stdout!r}"

    # Oracle: the engine log must hold a record with OUR sentinel AND hook==rm_gate.
    log = _engine_log(clean_venv)
    assert log is not None and log.is_file(), "engine.jsonl not found in installed package"
    assert _log_has_sentinel_for_hook(log, sentinel, "rm_gate"), (
        f"no engine.jsonl record found for sentinel {sentinel} + hook rm_gate"
    )


def _log_has_sentinel_for_hook(log: Path, sentinel: str, hook: str) -> bool:
    """Return True if any JSONL record has this agent_id AND this hook name.

    Asserts on the sentinel, never line counts — the log is shared with live
    sessions.
    """
    for line in log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("agent_id") == sentinel and rec.get("hook") == hook:
            return True
    return False


def test_t2a_rm_gate_allows_echo(clean_venv: CleanVenv, hook_workspace: Path) -> None:
    """A harmless command is allowed: exit 0 and decision is not "block"."""
    sentinel = f"e2e-allow-{uuid.uuid4()}"
    proc = _fire_hook(clean_venv, hook_workspace, "echo hi", sentinel)

    assert proc.returncode == 0, proc.stderr
    if proc.stdout.strip():
        try:
            decision = json.loads(proc.stdout)
            assert decision.get("decision") != "block", f"unexpected block: {proc.stdout!r}"
        except json.JSONDecodeError:
            # Non-JSON / empty output is also a valid "allow" signal.
            pass


# ===========================================================================
# TIER 3 — drone routing (real resolve -> subprocess -> execute)
# ===========================================================================


@pytest.fixture(scope="module")
def routing_root(clean_venv: CleanVenv) -> Iterator[Path]:
    """Generate a minimal registry at the repo root pointing at real branches.

    The repo's own AIPASS_REGISTRY.json is mode 0600 / host-absolute and won't
    relocate (its paths are the developer's home, absent in CI), so we GENERATE
    a minimal registry — faithful to what setup.sh produces — pointing at REAL
    branch dirs under this checkout.

    drone validates path containment against the registry's PARENT dir, so the
    registry must sit at the repo root for the ``src/aipass/*`` branch paths to
    validate. We back up any existing registry and restore it on teardown so a
    local run never mutates the working tree permanently.

    We target ``ai_mail`` — a real BRANCH (not an in-process drone module) — so
    ``drone @ai_mail --help`` exercises the full resolve -> subprocess ->
    execute path, the proof we never previously got green.
    """
    src = REPO_ROOT / "src" / "aipass"
    registry = {
        "metadata": {"name": "AIPASS", "version": "1.0.0", "total_branches": 3},
        "branches": [
            {"name": "ai_mail", "path": str(src / "ai_mail"), "status": "active"},
            {"name": "seedgo", "path": str(src / "seedgo"), "status": "active"},
            {"name": "drone", "path": str(src / "drone"), "status": "active"},
        ],
    }

    registry_path = REPO_ROOT / "AIPASS_REGISTRY.json"
    backup = registry_path.read_bytes() if registry_path.exists() else None
    try:
        registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
        yield REPO_ROOT
    finally:
        if backup is not None:
            registry_path.write_bytes(backup)
        elif registry_path.exists():
            registry_path.unlink()


def _drone_env() -> dict:
    """Env for drone subprocesses (inherits PATH etc.)."""
    import os

    return dict(os.environ)


def test_t3_drone_systems_lists_branch(clean_venv: CleanVenv, routing_root: Path) -> None:
    """``drone systems`` reads the registry and lists a known branch."""
    proc = _run(
        [str(clean_venv.drone), "systems"],
        cwd=str(routing_root),
        env=_drone_env(),
    )
    assert proc.returncode == 0, f"drone systems failed:\n{proc.stdout}\n{proc.stderr}"
    out = proc.stdout.lower()
    assert "seedgo" in out or "ai_mail" in out, f"no known branch listed:\n{proc.stdout}"


def test_t3_drone_routes_to_real_branch(clean_venv: CleanVenv, routing_root: Path) -> None:
    """``drone @ai_mail --help`` resolves -> subprocesses -> returns help text.

    This is the real integration proof: ai_mail is a registry branch (not an
    in-process drone module), so a non-empty help body proves drone resolved
    the @name, found apps/ai_mail.py, ran it in a subprocess, and captured its
    output.
    """
    proc = _run(
        [str(clean_venv.drone), "@ai_mail", "--help"],
        cwd=str(routing_root),
        env=_drone_env(),
    )
    combined = (proc.stdout + proc.stderr).lower()
    assert proc.returncode == 0, f"drone @ai_mail --help failed:\n{proc.stdout}\n{proc.stderr}"
    assert proc.stdout.strip(), f"no help text returned:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    assert "ai_mail" in combined or "mail" in combined, f"help text unexpected:\n{proc.stdout}"
