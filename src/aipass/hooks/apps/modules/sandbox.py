# =================== AIPass ====================
# Name: sandbox.py
# Version: 1.0.0
# Description: Sandbox wrapper — launches commands inside srt (kernel FS boundary)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-06-09
# Modified: 2026-06-09
# =============================================

"""Sandbox wrapper — launches commands inside srt kernel filesystem boundary.

Accepts a policy (writable/RO path map) + command + cwd + env, resolves the
bwrap command via @anthropic-ai/sandbox-runtime, and spawns inside the sandbox.
Phase 1 of FPLAN-0250 / DPLAN-0202.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

_MODULE_DIR = Path(__file__).resolve().parent
_SRT_RESOLVE = _MODULE_DIR / "_srt_resolve.mjs"

_VAR_TMP = Path("/var/tmp")


def _srt_resolve_cwd() -> str:
    """Return a CWD for the srt resolver that is outside any allow_write path.

    srt auto-denies DANGEROUS_FILES (.bashrc, .gitconfig, …) resolved relative
    to process.cwd(). When the deny target doesn't exist and its ancestor IS in
    allow_write, bwrap creates 0-byte mount-point files that persist after exit.
    Running the resolver from /var/tmp (never in allow_write) makes srt skip
    those entries entirely — no bwrap args, no mount points, no pollution.
    """
    if _VAR_TMP.is_dir():
        return str(_VAR_TMP)
    return tempfile.gettempdir()


HELP_COMMANDS = [
    ("sandbox", "Launch a command inside the kernel sandbox"),
]


def _find_node() -> str:
    node = shutil.which("node")
    if node:
        return node
    msg = "node not found in PATH — required for srt sandbox"
    raise FileNotFoundError(msg)


def _find_rg() -> str:
    rg = shutil.which("rg")
    if rg:
        return rg
    fallback = Path.home() / ".local" / "bin" / "rg"
    if fallback.is_file():
        return str(fallback)
    msg = "ripgrep (rg) not found — required by srt for mandatory-deny scan"
    raise FileNotFoundError(msg)


def _find_repo_root(branch_path: Path) -> Path:
    """Walk up from branch_path to find the repo root (contains .git)."""
    current = branch_path.resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    msg = f"No .git found above {branch_path}"
    raise FileNotFoundError(msg)


def _is_devpulse(branch_path: Path) -> bool:
    """Check if a branch is devpulse (the only committer) via passport."""
    passport = branch_path / ".trinity" / "passport.json"
    if passport.is_file():
        try:
            data = json.loads(passport.read_text(encoding="utf-8"))
            return data.get("branch_info", {}).get("branch_name") == "devpulse"
        except (json.JSONDecodeError, OSError) as exc:
            logger.info("sandbox: failed to read passport for %s: %s", branch_path.name, exc)
    return branch_path.name == "devpulse"


def _claude_project_dir(branch_path: Path) -> Path:
    """Derive the ~/.claude/projects/ directory for a branch."""
    encoded = str(branch_path.resolve()).replace("/", "-")
    return Path.home() / ".claude" / "projects" / encoded


def _find_src_aipass(repo_root: Path) -> Path:
    """Locate the src/aipass/ directory within the repo."""
    return repo_root / "src" / "aipass"


def build_policy(branch_path: str | Path) -> dict:
    """Generate sandbox policy for a branch agent.

    Returns a policy dict compatible with sandbox_launch / build_srt_config:
        allow_write: list of writable paths
        deny_write: broker secret only (it sits inside the writable .ai_central)
        deny_read: broker secret only — agents must never read it, or a
            path-connected broker client could forge a devpulse identity.
            Everything else stays readable (shared live filesystem).
    """
    branch_path = Path(branch_path).resolve()
    repo_root = _find_repo_root(branch_path)
    src_aipass = _find_src_aipass(repo_root)
    branch_name = branch_path.name
    is_dp = _is_devpulse(branch_path)

    allow_write: list[str] = []

    allow_write.append(str(branch_path))

    system_tmp = tempfile.gettempdir()
    allow_write.append(system_tmp)
    tmpdir = os.environ.get("TMPDIR")
    if tmpdir and tmpdir != system_tmp:
        allow_write.append(tmpdir)

    allow_write.extend(
        [
            str(repo_root / "system_logs"),
            str(repo_root / ".ai_central"),
            str(src_aipass / "memory" / "memory_pool"),
            str(repo_root / "AIPASS_REGISTRY.json"),
            str(src_aipass / "flow" / "flow_json"),
        ]
    )

    for sibling in sorted(src_aipass.iterdir()):
        if not sibling.is_dir():
            continue
        if sibling.name == branch_name or sibling.name.startswith("_"):
            continue
        mail_dir = sibling / ".ai_mail.local"
        if mail_dir.is_dir():
            allow_write.append(str(mail_dir))
        dashboard = sibling / "DASHBOARD.local.json"
        if dashboard.is_file():
            allow_write.append(str(dashboard))

    if is_dp:
        allow_write.append(str(repo_root / ".git"))

    claude_proj = _claude_project_dir(branch_path)
    if claude_proj.is_dir():
        allow_write.append(str(claude_proj))

    broker_secret = repo_root / ".ai_central" / "broker_secret"
    return {
        "allow_write": allow_write,
        "deny_write": [str(broker_secret)],
        "deny_read": [str(broker_secret)],
    }


def build_srt_config(policy: dict) -> dict:
    """Convert a policy dict to srt config format.

    Policy keys:
        allow_write: list[str] — paths the sandboxed process may write to
        deny_write:  list[str] — paths to deny write within writable (optional)
        deny_read:   list[str] — paths to deny read (optional)
    """
    return {
        "network": {
            "allowAllUnixSockets": True,
        },
        "filesystem": {
            "denyRead": [str(p) for p in policy.get("deny_read", [])],
            "allowWrite": [str(p) for p in policy["allow_write"]],
            "denyWrite": [str(p) for p in policy.get("deny_write", [])],
        },
        "ripgrep": {
            "command": _find_rg(),
        },
    }


def resolve_bwrap_command(command: str, srt_config: dict) -> str:
    """Call the Node.js srt resolver to get the bwrap shell command."""
    node = _find_node()

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        prefix="srt-config-",
        delete=False,
        encoding="utf-8",
    ) as f:
        json.dump(srt_config, f)
        config_path = f.name

    try:
        result = subprocess.run(
            [node, str(_SRT_RESOLVE), config_path, command],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            cwd=_srt_resolve_cwd(),
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            msg = f"srt resolve failed (exit {result.returncode}): {stderr}"
            raise RuntimeError(msg)
        wrapped = result.stdout.strip()
        if not wrapped:
            msg = "srt resolve returned empty command"
            raise RuntimeError(msg)
        return wrapped
    finally:
        Path(config_path).unlink(missing_ok=True)


def sandbox_launch(
    command: str,
    *,
    cwd: str | Path | None = None,
    policy: dict,
    env: dict | None = None,
) -> subprocess.Popen:
    """Launch a command inside the srt kernel sandbox.

    Args:
        command: Shell command string to run inside the sandbox.
        cwd: Working directory for the sandboxed process.
        policy: Dict with allow_write (required), deny_write, deny_read (optional).
        env: Environment variables (defaults to current env).

    Returns:
        subprocess.Popen handle for the sandboxed process.
    """
    srt_config = build_srt_config(policy)
    bwrap_cmd = resolve_bwrap_command(command, srt_config)

    logger.info("sandbox_launch: wrapping command in srt sandbox")

    launch_env = env if env is not None else dict(os.environ)

    return subprocess.Popen(
        ["/bin/bash", "-c", bwrap_cmd],
        cwd=str(cwd) if cwd else None,
        env=launch_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def print_introspection() -> None:
    """Print module structure for drone routing."""
    CONSOLE.print("[bold cyan]sandbox[/bold cyan] — Kernel filesystem boundary via srt")
    CONSOLE.print("  Phase 1: wrapper module only (not yet wired into dispatch)")
    CONSOLE.print("  Use sandbox_launch() programmatically.")


def handle_command(command: str, args: list) -> bool:
    """Route sandbox commands from drone @hooks."""
    if command == "sandbox":
        if not args:
            print_introspection()
            return True

        if wants_help(args):
            CONSOLE.print("[bold cyan]sandbox[/bold cyan] — Kernel filesystem boundary via srt")
            CONSOLE.print()
            CONSOLE.print("  drone @hooks sandbox    Show sandbox module status")
            return True

    return False
