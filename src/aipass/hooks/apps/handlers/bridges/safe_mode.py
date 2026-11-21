# =================== AIPass ====================
# Name: safe_mode.py
# Version: 1.0.0
# Description: Safe mode — the one recovery command the admin seat may run while the hook engine is broken
# Branch: hooks
# Layer: apps/handlers/bridges
# Created: 2026-11-19
# Modified: 2026-11-19
# =============================================

"""Safe mode: while the hook engine cannot run, the admin seat may still put broken code back.

Standard library only, and no aipass import: this file must load when everything it would import is what broke.
The Claude bridge asks `allows` before it refuses a call. The command it lets through is this file, run as a script:

    python3 -I <this file> diagnose        why the engine cannot run, and which uncommitted code is suspect
    python3 -I <this file> park <path>     move the uncommitted changes under one branch's apps/ into a git stash
    python3 -I <this file> rollback        serve the promoted hooks copy before the live one

Nothing here deletes, edits code, commits or pushes. `park` and `rollback` refuse while the engine is healthy.
"""

import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "safe_mode.py")

ADMIN_HOLDER = "devpulse"
KEY_PATH = os.path.join(os.path.expanduser("~"), ".aipass", "admin_grant.key")
#: Outside the tree, so no park can move the record of a park.
RECOVERY_DIR = os.path.join(os.path.expanduser("~"), ".aipass", "recovery")

#: What the bridge lets through and what the help prints: one spelling, so the printed command always passes.
INVOKE = " ".join(("python3", "-I", SCRIPT))
#: The whole command, start to end: no second command, no redirect, no substitution can ride along.
_COMMAND = re.compile(re.escape(INVOKE) + r" (diagnose|rollback|park [A-Za-z0-9_./-]+)")

#: main() of the Claude bridge, step for step, on a harmless call: what breaks there breaks here.
_PROBE = """
import importlib.util, json, os, sys, traceback
here, payload = sys.argv[1], sys.argv[2]
try:
    spec = importlib.util.spec_from_file_location("_aipass_hooks_mount", os.path.join(here, "mount.py"))
    mount = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mount)
    mount.mount_or_source(os.path.join(here, "claude.py"), "claude")
    from aipass.hooks.apps.handlers.json import json_handler
    from aipass.hooks.apps.modules.engine import run_event
    _, exit_code = run_event("PreToolUse", payload)
    json_handler.log_operation("bridge", {"event": "PreToolUse", "exit_code": exit_code})
except BaseException:
    traceback.print_exc()
    sys.exit(1)
"""


def _holds_git(path: str) -> bool:
    """A .git file (a worktree) or a .git directory with something in it: a sandbox mounts an empty one."""
    marker = os.path.join(path, ".git")
    return os.path.isfile(marker) or (os.path.isdir(marker) and bool(os.listdir(marker)))


def repo_root() -> str:
    """The checkout this file sits in, links resolved: the nearest directory above it that holds .git."""
    path = os.path.realpath(HERE)
    while not _holds_git(path):
        parent = os.path.dirname(path)
        if parent == path:
            raise FileNotFoundError(f"no .git above {HERE}")
        path = parent
    return path


def hooks_root() -> str:
    """The hooks branch, from this file's own place: bridges -> handlers -> apps -> branch."""
    path = HERE
    for _ in range(3):
        path = os.path.dirname(path)
    return path


def _seat_root(cwd: str) -> str | None:
    """The directory holding the nearest passport above *cwd*, or None."""
    path = os.path.realpath(cwd) if cwd else ""
    while path:
        if os.path.isfile(os.path.join(path, ".trinity", "passport.json")):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
    return None


def is_admin_seat(cwd: str) -> bool:
    """True when *cwd* sits in this checkout's admin branch and its birth certificate carries a signed admin grant.

    The registry is not read: it is one of the things that can be what broke. The place is fixed instead,
    so a copy of the certificate in another branch proves nothing.
    """
    root = _seat_root(cwd)
    if root is None or root != os.path.join(repo_root(), "src", "aipass", ADMIN_HOLDER):
        return False
    cert_path = os.path.join(root, "artifacts", "birth_certificate.json")
    if not os.path.isfile(cert_path):
        return False
    with open(cert_path, encoding="utf-8") as handle:
        cert = json.load(handle)
    if cert.get("owner") != ADMIN_HOLDER or cert.get("type") != "birth_certificate":
        return False
    if cert.get("privileges", {}).get("admin") is not True:
        return False
    signature = cert.get("signature", {})
    if signature.get("algo") != "hmac-sha256" or not isinstance(signature.get("value"), str):
        return False
    with open(KEY_PATH, encoding="utf-8") as handle:
        key = bytes.fromhex(handle.read().strip())
    unsigned = {k: v for k, v in cert.items() if k != "signature"}
    payload = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hmac.compare_digest(signature["value"], hmac.new(key, payload, hashlib.sha256).hexdigest())


def allows(stdin_data: str) -> bool:
    """True for exactly one call: the admin seat running this file's own command through Bash."""
    payload = json.loads(stdin_data)
    if payload.get("tool_name") != "Bash":
        return False
    command = payload.get("tool_input", {}).get("command")
    if not isinstance(command, str) or _COMMAND.fullmatch(command) is None:
        return False
    return is_admin_seat(payload.get("cwd", ""))


def engine_error() -> str:
    """ "" when the engine runs a harmless call the way the bridge runs it, else the traceback."""
    repo = repo_root()
    python = os.path.join(repo, ".venv", "bin", "python3")
    if not os.path.isfile(python):
        raise FileNotFoundError(f"no interpreter at {python}: the engine cannot be probed")
    call = {"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": SCRIPT}}
    payload = json.dumps({**call, "cwd": repo, "session_id": "safe-mode-probe"})
    done = subprocess.run(
        [python, "-c", _PROBE, HERE, payload],
        capture_output=True,
        encoding="utf-8",
        errors="backslashreplace",
        timeout=120,
        cwd=repo,
        check=False,
    )
    return "" if done.returncode == 0 else (done.stderr.strip() or f"the probe exited {done.returncode}")


def _git(*args: str) -> subprocess.CompletedProcess:
    # No timeout: a git killed halfway through a stash leaves a lock and a half-moved tree.
    return subprocess.run(["git", "-C", repo_root(), *args], capture_output=True, check=False)


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


def _log(entry: dict) -> None:
    """One line per command in the recovery log; a command that cannot be logged does not run."""
    os.makedirs(RECOVERY_DIR, exist_ok=True)
    with open(os.path.join(RECOVERY_DIR, "log.jsonl"), "a", encoding="utf-8") as handle:
        stamp = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "checkout": repo_root(), "cwd": os.getcwd()}
        handle.write(json.dumps({**stamp, **entry}) + "\n")


def _suspects() -> list[str]:
    """Uncommitted paths under some branch's apps/: the code the engine may be loading."""
    done = _git("status", "--porcelain", "--", "src/aipass")
    lines = done.stdout.decode("utf-8", "backslashreplace").splitlines()
    return [line for line in lines if "/apps/" in line]


def diagnose() -> int:
    """Say whether the engine runs; when it does not, show why and what is uncommitted."""
    error = engine_error()
    _log({"verb": "diagnose", "broken": bool(error)})
    if not error:
        _say("The hook engine runs. Nothing to recover.")
        return 0
    _say("THE HOOK ENGINE IS BROKEN. Its error:\n")
    _say(error)
    suspects = _suspects()
    _say("\nUncommitted code (git status), the suspects:\n")
    _say("\n".join(suspects) if suspects else "  none")
    _say("\nThe LAST File line of the traceback names the code that failed.")
    _say("Under src/aipass/<branch>/apps, and uncommitted: park the apps/ folder of that branch, nothing wider:")
    _say(f"  {INVOKE} park src/aipass/<branch>/apps")
    _say("Under src/aipass/hooks/.live-<stamp>: serve the promoted copy before it (undone by itself if no cure):")
    _say(f"  {INVOKE} rollback")
    _say("Neither: the break is committed, or it is not code. Stop here and follow the recovery guide.")
    return 1


def _parkable(arg: str) -> str:
    """*arg* as a path relative to the checkout, or a ValueError: only code under one branch's apps/ parks."""
    repo = repo_root()
    target = os.path.abspath(arg if os.path.isabs(arg) else os.path.join(repo, arg))
    if os.path.realpath(target) != target:
        raise ValueError(f"{arg} passes through a symbolic link")
    rel = os.path.relpath(target, repo)
    parts = rel.split(os.sep)
    if len(parts) < 4 or parts[:2] != ["src", "aipass"] or parts[3] != "apps":
        raise ValueError(f"{arg} is not inside a branch's apps/ folder (src/aipass/<branch>/apps)")
    return rel


def park(arg: str) -> int:
    """Move the uncommitted changes under *arg* into a named stash, a readable patch beside the log.

    0 cured, 1 parked nothing or still broken, 2 refused because the engine runs, 3 refused path.
    """
    try:
        rel = _parkable(arg)
    except ValueError as exc:
        _say(f"REFUSED: {exc}. Memory, plans, mail and config are never parked.")
        return 3
    if not engine_error():
        _say("REFUSED: the hook engine runs. park exists only to cure a broken engine.")
        return 2
    if not _git("status", "--porcelain", "--", rel).stdout.strip():
        _say(f"Nothing uncommitted under {rel}: nothing to park.")
        return 1
    stamp = time.strftime("%Y%m%dT%H%M%S")
    os.makedirs(RECOVERY_DIR, exist_ok=True)
    patch = os.path.join(RECOVERY_DIR, f"{stamp}_{rel.replace(os.sep, '_')}.patch")
    with open(patch, "wb") as handle:
        handle.write(_git("diff", "HEAD", "--binary", "--", rel).stdout)
    name = f"safe mode {stamp}: {rel}"
    _log({"verb": "park", "path": rel, "stash": name, "patch": patch})
    done = _git("stash", "push", "--include-untracked", "-m", name, "--", rel)
    if done.returncode:
        _say(f"git stash failed ({done.returncode}). Read git status before anything else; the patch is at {patch}:")
        _say(done.stderr.decode("utf-8", "backslashreplace"))
        return 1
    _say(f"PARKED: the uncommitted changes under {rel} are in the git stash named")
    _say(f'  "{name}"')
    _say(f"and readable as a patch (new files are in the stash only): {patch}")
    _say("That path is now as it was at the last commit. Nothing was deleted.")
    error = engine_error()
    _log({"verb": "park-result", "path": rel, "broken": bool(error)})
    if error:
        _say("\nThe engine is STILL broken:\n")
        _say(error)
        return 1
    _say("\nThe hook engine runs again. Safe mode is over.")
    _say("Tell the owner what was parked; the parked work is rebuilt in a staged copy, never edited in place.")
    return 0


def rollback() -> int:
    """Serve the promoted hooks copy before the live one; the pointer goes back when that is no cure.

    0 cured, 1 no older copy or still broken (pointer restored), 2 refused because the engine runs.
    """
    if not engine_error():
        _say("REFUSED: the hook engine runs. rollback exists only to cure a broken engine.")
        return 2
    hooks = hooks_root()
    pointer = os.path.join(hooks, ".live-current")
    with open(pointer, encoding="utf-8") as handle:
        live = handle.read().strip()
    kept = (name for name in os.listdir(hooks) if name.startswith(".live-2") and name < live)
    older = sorted(name for name in kept if os.path.isfile(os.path.join(hooks, name, "__init__.py")))
    if not older:
        _say(f"No promoted copy older than {live} is kept: nothing to roll back to.")
        return 1
    _log({"verb": "rollback", "was": live, "now": older[-1]})
    with open(pointer, "w", encoding="utf-8") as handle:
        handle.write(older[-1] + "\n")
    error = engine_error()
    if error:
        with open(pointer, "w", encoding="utf-8") as handle:
            handle.write(live + "\n")
        _log({"verb": "rollback-result", "broken": True, "restored": live})
        _say(f"{older[-1]} does not run either, so {live} is live again, as it was. The engine is STILL broken:\n")
        _say(error)
        return 1
    _log({"verb": "rollback-result", "broken": False})
    _say(f"ROLLED BACK: {older[-1]} is served (was {live}). No copy was deleted.")
    _say("\nThe hook engine runs again. Safe mode is over.")
    _say(f"Tell the owner: {live} is broken and must not be promoted again as it is.")
    return 0


def main(argv: list[str]) -> int:
    """diagnose | park <path> | rollback."""
    if argv == ["diagnose"]:
        return diagnose()
    if argv == ["rollback"]:
        return rollback()
    if len(argv) == 2 and argv[0] == "park":
        return park(argv[1])
    _say(__doc__ or "")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
