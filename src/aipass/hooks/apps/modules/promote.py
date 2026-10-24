# =================== AIPass ====================
# Name: promote.py
# Version: 1.1.0
# Description: The one step that makes edited hook code live: check, copy, smoke, then point (drone @hooks promote)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-09-30
# Modified: 2026-10-24
# =============================================

"""Hook code goes live through one explicit step, never by being saved (DPLAN-0356 item 3).

Every hook process imports ``aipass.hooks.apps`` from a promoted copy
(handlers/bridges/mount.py), so saving the source changes no seat. Any failed
check leaves the last promoted copy live.
"""

import compileall
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.handlers.json import json_handler
from aipass.hooks.apps.handlers.module_root import module_file
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

HELP_COMMANDS = [
    ("promote", "Check the hook source (ruff, compile, suite), copy it, smoke it, then make it live"),
    ("promote status", "Show which promoted copy every hook process is running"),
]

BRANCH_ROOT = module_file(__file__).parent.parent.parent
# Spelled again in handlers/bridges/mount.py, which must stay stdlib-only and
# cannot import this module; the pins in test_engine hold the two equal.
POINTER = ".live-current"
PREFIX = ".live-"
OVERRIDE_ENV = "AIPASS_HOOKS_LIVE"
KEEP = 3
RUFF_RULES = "F821,F823,E9"
SUITE_TIMEOUT_S = 900
SMOKE_TIMEOUT_S = 60
_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".archive")


def live_name(root: Path = BRANCH_ROOT) -> str | None:
    """The snapshot ``.live-current`` names, or None when nothing was ever promoted."""
    pointer = root / POINTER
    if not pointer.is_file():
        return None
    name = pointer.read_text(encoding="utf-8").strip()
    return name or None


def _hook_env(**extra: str) -> dict:
    """This process's environment minus drone's caller stamps (AIPASS_CALLER_*).

    A hook process never carries them; inherited, they make the admin-seat pin read hooks' cwd and fail.
    """
    env = {key: value for key, value in os.environ.items() if not key.startswith("AIPASS_CALLER_")}
    env.update(extra)
    return env


def _ruff() -> str | None:
    """ruff beside this interpreter (the project venv), else on PATH."""
    beside = Path(sys.executable).parent / ("ruff.exe" if os.name == "nt" else "ruff")
    return str(beside) if beside.is_file() else shutil.which("ruff")


def check_lint(root: Path) -> tuple[bool, str]:
    """ruff's undefined-name and syntax rules over apps/. Missing ruff is a refusal, never a skip."""
    ruff = _ruff()
    if ruff is None:
        return False, "ruff not found beside the interpreter or on PATH"
    done = subprocess.run(
        [ruff, "check", "--no-cache", "--select", RUFF_RULES, str(root / "apps")],
        capture_output=True,
        text=True,
        timeout=SMOKE_TIMEOUT_S,
    )
    return done.returncode == 0, (done.stdout or done.stderr).strip()[-2000:]


def check_compile(root: Path) -> tuple[bool, str]:
    """Every source file under apps/ compiles."""
    ok = compileall.compile_dir(str(root / "apps"), quiet=1, force=True)
    return bool(ok), "compiled" if ok else "a file under apps/ does not compile (see the output above)"


def check_suite(root: Path) -> tuple[bool, str]:
    """The branch's whole suite, against the source tree, stopping at the first failure."""
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q", "-x", "-p", "no:cacheprovider"],
        cwd=root,
        env=_hook_env(),
        capture_output=True,
        text=True,
        timeout=SUITE_TIMEOUT_S,
    )
    tail = done.stdout.strip().splitlines()[-1:] or [done.stderr.strip()[-300:]]
    return done.returncode == 0, tail[0]


def _stamp(root: Path) -> str:
    base = f"{PREFIX}{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    name, n = base, 1
    while (root / name).exists():
        n += 1
        name = f"{base}-{n}"
    return name


def copy_source(root: Path) -> str:
    """Copy apps/ to a new ``.live-<stamp>`` sibling of apps/ and return its name.

    A sibling, so each module's ``__file__`` arithmetic still lands in this branch.
    """
    name = _stamp(root)
    shutil.copytree(root / "apps", root / name, ignore=_SKIP)
    return name


def fingerprint(folder: Path) -> str:
    """One hash over every file the copy keeps (its path and bytes), so two trees compare in one string."""
    digest = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        relative = path.relative_to(folder)
        if any(_SKIP("", [part]) for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _bridge_says(root: Path, name: str, payload: dict) -> tuple[int, str]:
    env = _hook_env(**{OVERRIDE_ENV: name})
    bridge = root / "apps" / "handlers" / "bridges" / "claude.py"
    done = subprocess.run(
        [sys.executable, str(bridge), "PreToolUse"],
        input=json.dumps(payload),
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=SMOKE_TIMEOUT_S,
    )
    return done.returncode, done.stdout


def check_smoke(root: Path, name: str) -> tuple[bool, str]:
    """The real bridge, serving the candidate: a raw rm is refused and a Read passes.

    Decision only: the hook never runs the command it is asked about.
    """
    base = {"session_id": "promote-smoke", "cwd": str(root), "hook_event_name": "PreToolUse"}
    code, out = _bridge_says(
        root, name, {**base, "tool_name": "Bash", "tool_input": {"command": "rm promote-smoke-canary.txt"}}
    )
    try:
        refused = code == 2 and json.loads(out).get("decision") == "block"
    except (json.JSONDecodeError, AttributeError) as exc:
        logger.info("[HOOKS] promote: smoke refusal unreadable: %s", exc)
        refused = False
    if not refused:
        return False, f"raw rm was not refused through the candidate (exit {code}): {out[:300]}"
    code, out = _bridge_says(root, name, {**base, "tool_name": "Read", "tool_input": {"file_path": str(root)}})
    if code != 0:
        return False, f"a Read was refused through the candidate (exit {code}): {out[:300]}"
    return True, "raw rm refused, Read allowed"


def point_at(root: Path, name: str) -> None:
    """Rewrite the pointer in one rename: a hook process reads the old name or the new, never half."""
    scratch = root / f"{POINTER}.{os.getpid()}.tmp"
    scratch.write_text(name + "\n", encoding="utf-8")
    os.replace(scratch, root / POINTER)


def rotate(root: Path, keep: int = KEEP) -> list[str]:
    """Rotate out all but the newest *keep* copies; the live one is never touched."""
    live = live_name(root)
    copies = sorted(p.name for p in root.iterdir() if p.is_dir() and p.name.startswith(PREFIX))
    gone = [name for name in copies[:-keep] if name != live] if keep > 0 else []
    for name in gone:
        shutil.rmtree(root / name)
        logger.info("[HOOKS] promote: rotated out %s", name)
    return gone


def _discard(root: Path, name: str) -> None:
    """A refused candidate never stays beside the live copies."""
    shutil.rmtree(root / name, ignore_errors=True)


def promote(
    root: Path = BRANCH_ROOT, checks: tuple = (check_lint, check_compile, check_suite)
) -> tuple[bool, list[str]]:
    """Check, copy, smoke, point. Returns (promoted, report lines); refuses on the first failure.

    *checks* is a seam: the tests cannot run the suite from inside the suite.
    """
    report: list[str] = []
    checked = fingerprint(root / "apps")
    for check in checks:
        ok, detail = check(root)
        report.append(f"{check.__name__}: {'ok' if ok else 'FAILED'} — {detail}")
        if not ok:
            logger.warning("[HOOKS] promote refused at %s: %s", check.__name__, detail[:300])
            return False, report
    name = copy_source(root)
    if fingerprint(root / name) != checked:
        _discard(root, name)
        report.append("copy: FAILED — apps/ changed while the checks ran; the copy is not what was checked")
        logger.warning("[HOOKS] promote refused: apps/ changed while the checks ran")
        return False, report
    ok, detail = check_smoke(root, name)
    report.append(f"check_smoke: {'ok' if ok else 'FAILED'} — {detail}")
    if not ok:
        _discard(root, name)
        logger.warning("[HOOKS] promote refused at check_smoke: %s", detail[:300])
        return False, report
    before = live_name(root)
    point_at(root, name)
    report.append(f"live: {name} (was {before or 'the source tree'})")
    report.extend(f"rotated out: {gone}" for gone in rotate(root))
    json_handler.log_operation("promote", {"live": name, "was": before or ""})
    logger.info("[HOOKS] promote: %s is live (was %s)", name, before or "the source tree")
    return True, report


def print_introspection():
    """Print module structure for drone routing."""
    CONSOLE.print("[bold cyan]promote[/bold cyan] — edited hook code goes live only through this step")
    CONSOLE.print(f"[dim]Live copy: {live_name() or 'none promoted — the source tree serves'}[/dim]")


def _print_help() -> None:
    CONSOLE.print("[bold cyan]promote[/bold cyan] — make edited hook code live")
    CONSOLE.print()
    CONSOLE.print("  drone @hooks promote          ruff + compile + suite, copy, smoke through the bridge, point")
    CONSOLE.print("  drone @hooks promote status   which copy every hook process runs")
    CONSOLE.print()
    CONSOLE.print("Workflow: edit, test, promote. Saving a file changes no seat; promote does.")


def handle_command(command: str, args: list) -> bool:
    """Route promote commands from drone @hooks."""
    if command != "promote":
        return False
    if wants_help(args):
        _print_help()
        return True
    if args and args[0] == "status":
        CONSOLE.print(f"live: {live_name() or 'none promoted — the source tree serves'}")
        return True
    if args:
        _print_help()
        sys.exit(1)
    ok, report = promote()
    for line in report:
        CONSOLE.print(line)
    if not ok:
        CONSOLE.print("[red]Refused — the last promoted copy stays live.[/red]")
        sys.exit(1)
    return True
