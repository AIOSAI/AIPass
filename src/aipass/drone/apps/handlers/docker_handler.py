# =================== AIPass ====================
# Name: docker_handler.py
# Description: drone docker: the base Dockerfile, the docker argv per verb, names, the box ledger
# Version: 1.0.0
# Created: 2026-11-24
# Modified: 2026-11-24
# =============================================

"""The pieces behind ``drone docker``: docs/docker.md.

Pure builders (Dockerfile text, argv, script, names) plus the few docker and ledger calls.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.deletion_log import append_ledger_line, ledger_beside
from aipass.drone.apps.handlers.git.gh_chores import ChoreRefusal, repo_slug
from aipass.drone.apps.handlers.json import json_handler

LEDGER_NAME = "docker_boxes.jsonl"
LABEL = "aipass.box"
APT_BASES = ("ubuntu", "debian")
BOX_HOME = "/home/aipass"
CLONE_DIR = "~/AIPass-src"
DOCKER_TIMEOUT = 60
OS_RELEASE = Path("/etc/os-release")

# One copy of the three vendor installers, mirroring aipass's provider_choice (its apps/ is not ours to import).
INSTALLERS = {
    "claude": "curl -fsSL https://claude.ai/install.sh | bash",
    "codex": "npm install -g @openai/codex",
    "opencode": "curl -fsSL https://opencode.ai/v2/install | bash",
}

# Box-side config dirs, each carried by its own named volume under --login.
LOGIN_DIRS = {"claude": ".claude", "codex": ".codex", "opencode": ".config/opencode"}

# Host dirs that hold sign-ins or keys: never mounted into a box, nor any dir inside or above them.
CREDENTIAL_DIRS = (".claude", ".codex", ".config/opencode", ".secrets", ".ssh")

USERMOD_LINE = "Add yourself to the docker group, then log in again: sudo usermod -aG docker $USER"


class BoxRefusal(Exception):
    """The request is refused; the message is printed exactly."""


def host_image_ref() -> str:
    """``ID:VERSION_ID`` of this machine, e.g. ``ubuntu:26.04``."""
    fields = {}
    for line in OS_RELEASE.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        fields[key.strip()] = value.strip().strip('"')
    return f"{fields.get('ID', '')}:{fields.get('VERSION_ID', 'latest')}"


def check_apt_base(image_ref: str) -> None:
    """Refuse a base whose repo name is not ubuntu or debian: the image installs with apt."""
    repo = image_ref.rsplit("/", 1)[-1].split("@")[0].split(":")[0]
    if repo not in APT_BASES:
        raise BoxRefusal(f"base {image_ref} refused: the image installs with apt, so the base must be ubuntu or debian")


def base_tag(image_ref: str) -> str:
    """The cached image's tag for one base ref."""
    return "aipass-base:" + image_ref.replace("/", "-").replace(":", "-")


def dockerfile_text(image_ref: str) -> str:
    """The base image: tools, user aipass, no AIPass and no CLI."""
    config_dirs = " ".join(f"{BOX_HOME}/{d}" for d in LOGIN_DIRS.values())
    return f"""FROM {image_ref}
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \\
      python3 python3-venv python3-pip git curl ca-certificates nodejs npm tmux ripgrep jq \\
    && rm -rf /var/lib/apt/lists/* \\
    && useradd -m -s /bin/bash aipass \\
    && git config --system --add safe.directory '*'
USER aipass
WORKDIR {BOX_HOME}
RUN mkdir -p {config_dirs}
ENV NPM_CONFIG_PREFIX={BOX_HOME}/.local
ENV PATH={BOX_HOME}/.local/bin:{BOX_HOME}/aipass-venv/bin:{BOX_HOME}/.opencode/bin:$PATH
"""


def check_mount(path_str: str, home: Path | None = None) -> Path:
    """The resolved host path to bind read-only; refuse a missing path or a credential dir."""
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        raise BoxRefusal(f"--mount {path_str} refused: no such path")
    home = (home or Path.home()).resolve()
    for rel in CREDENTIAL_DIRS:
        cred = home / rel
        if path == cred or cred in path.parents or path in cred.parents:
            raise BoxRefusal(
                f"--mount {path_str} refused: it is, holds or sits in ~/{rel}; host credentials never enter a box"
            )
    return path


def box_script(verb: str, with_clis: list[str], clone_url: str | None, command: str | None) -> str:
    """What runs inside: installers, the verb's clone, the next commands, then a shell or the one command."""
    lines = []
    for cli in with_clis:
        lines.append(f"echo {shlex.quote('== installing ' + cli + ': ' + INSTALLERS[cli])}")
        lines.append(f"{INSTALLERS[cli]} || echo {shlex.quote('install of ' + cli + ' failed')}")
    if verb != "bare":
        source = "/src" if verb == "local" else CLONE_DIR
        branch = "" if verb == "local" else f"--branch {verb} "
        lines.append(f"git clone -q {branch}{shlex.quote(clone_url or '')} {CLONE_DIR}")
        lines.append(f"git -C {CLONE_DIR} log -1 --oneline")
        lines.append("echo 'Next:'")
        lines.append(f"echo '  python3 -m venv ~/aipass-venv && ~/aipass-venv/bin/pip install {CLONE_DIR}'")
        lines.append(f"echo '  aipass install --source {source}'")
    lines.append(command if command else "exec bash -l")
    return "\n".join(lines)


def run_argv(
    *,
    verb: str,
    name: str,
    image: str,
    script: str,
    keep: bool,
    tty: bool,
    mounts: list[Path],
    login: bool,
    repo_root: Path | None,
) -> list[str]:
    """``docker run`` for one box."""
    argv = ["docker", "run"] + (["-it"] if tty else [])
    if not keep:
        argv.append("--rm")
    argv += ["--name", name, "--label", f"{LABEL}={verb}"]
    if verb == "local":
        argv += ["-v", f"{repo_root}:/src:ro"]
    for path in mounts:
        argv += ["-v", f"{path}:/mnt/{path.name}:ro"]
    if login:
        for cli, rel in LOGIN_DIRS.items():
            argv += ["-v", f"aipass-login-{cli}:{BOX_HOME}/{rel}"]
    return argv + [image, "bash", "-lc", script]


def launch(
    verb: str,
    name: str,
    image_ref: str,
    opts: dict,
    mounts: list[Path],
    repo_root: Path | None,
    url: str | None,
    *,
    tty: bool,
) -> int:
    """Record the box, then run it attached to this terminal; docker run's exit code."""
    argv = run_argv(
        verb=verb,
        name=name,
        image=base_tag(image_ref),
        script=box_script(verb, opts["with"], url, opts["command"]),
        keep=opts["keep"],
        tty=tty,
        mounts=mounts,
        login=opts["login"],
        repo_root=repo_root,
    )
    record(
        {
            "event": "created",
            "name": name,
            "verb": verb,
            "image": image_ref,
            "created": time.time(),
            "kept": opts["keep"],
            "mounts": [str(m) for m in mounts],
        }
    )
    logger.info("docker: running %s from %s", name, image_ref)
    return attach(argv)


def attach(argv: list[str]) -> int:
    """Run a docker command on this terminal, uncaptured, so an interactive shell works."""
    return subprocess.run(argv).returncode


def clone_url(verb: str, repo_root: Path) -> str:
    """``file:///src`` for local, else origin's github https URL."""
    if verb == "local":
        return "file:///src"
    try:
        return f"https://github.com/{repo_slug(repo_root, 'docker')}"
    except ChoreRefusal as exc:
        raise BoxRefusal(str(exc)) from exc


def docker(argv: list[str]) -> subprocess.CompletedProcess:
    """One captured docker call."""
    return subprocess.run(["docker", *argv], capture_output=True, text=True, timeout=DOCKER_TIMEOUT)


def docker_ready() -> tuple[bool, str]:
    """``(True, "")``, or ``(False, the lines to print)`` when docker is absent, down or forbidden."""
    if shutil.which("docker") is None:
        return False, "docker is not installed here (no docker on PATH)"
    try:
        result = docker(["info", "--format", "{{.ServerVersion}}"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("docker: info failed: %s", exc)
        return False, f"the docker daemon did not answer: {exc}"
    if result.returncode == 0:
        return True, ""
    reason = (result.stderr or result.stdout).strip()
    if "permission denied" in reason.lower():
        return False, f"{reason}\n{USERMOD_LINE}"
    logger.warning("docker: daemon down: %s", reason)
    return False, "the docker daemon is not running (docker info failed)"


def ensure_base(image_ref: str, rebuild: bool) -> int:
    """Build the base image when it is missing or ``--rebuild``; docker build's own exit code, 0 when cached."""
    tag = base_tag(image_ref)
    if not rebuild and docker(["image", "inspect", tag]).returncode == 0:
        return 0
    with tempfile.TemporaryDirectory(prefix="aipass_docker_") as tmp:
        Path(tmp, "Dockerfile").write_text(dockerfile_text(image_ref), encoding="utf-8")
        argv = ["docker", "build"] + (["--no-cache"] if rebuild else []) + ["-t", tag, tmp]
        logger.info("docker: building %s", tag)
        return subprocess.run(argv).returncode


def ledger_path() -> Path:
    """The box ledger, beside drone's deletion record."""
    return ledger_beside(LEDGER_NAME)


def read_rows() -> list[dict]:
    """Every ledger row, oldest first; an unreadable line is skipped and logged."""
    path = ledger_path()
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("docker: unreadable ledger line in %s", path)
    return rows


def record(row: dict) -> None:
    """Append one row to the ledger."""
    append_ledger_line({"ts": time.time(), **row}, ledger_path())
    json_handler.log_operation("docker_box", row)


def boxes(rows: list[dict]) -> dict[str, dict]:
    """Name -> its creation row, for boxes not yet removed through drone."""
    made: dict[str, dict] = {}
    for row in rows:
        if row.get("event") == "created":
            made[row["name"]] = row
        elif row.get("event") == "removed":
            made.pop(str(row.get("name")), None)
    return made


def live_states() -> dict[str, str]:
    """Name -> docker State for every container carrying our label."""
    result = docker(["ps", "-a", "--filter", f"label={LABEL}", "--format", "{{.Names}}\t{{.State}}"])
    states = {}
    for line in result.stdout.splitlines():
        name, _, state = line.partition("\t")
        states[name] = state
    return states


def next_name(verb: str, rows: list[dict]) -> str:
    """``aipass-<verb>-<n>``, n one past the highest recorded or live for that verb."""
    prefix = f"aipass-{verb}-"
    live = docker(["ps", "-a", "--filter", f"name=^{prefix}", "--format", "{{.Names}}"]).stdout.split()
    taken = [r.get("name", "") for r in rows] + live
    numbers = [int(n[len(prefix) :]) for n in taken if n.startswith(prefix) and n[len(prefix) :].isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1}"


def own_box(name: str) -> str:
    """The live state of a box drone docker made; refuse a name with no ledger row or no labelled container."""
    if name not in boxes(read_rows()):
        raise BoxRefusal(f"drone docker did not make {name}")
    state = live_states().get(name)
    if state is None:
        raise BoxRefusal(f"{name} is gone: no container with that name carries the {LABEL} label")
    return state
