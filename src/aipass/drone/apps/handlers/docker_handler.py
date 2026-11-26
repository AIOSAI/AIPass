# =================== AIPass ====================
# Name: docker_handler.py
# Description: drone docker: the base Dockerfile, the docker argv per verb, names, the box ledger
# Version: 1.2.0
# Created: 2026-11-24
# Modified: 2026-11-25
# =============================================

"""The pieces behind ``drone docker``: docs/docker.md.

Pure builders (Dockerfile text, argv, script, names) plus the few docker and ledger calls.
"""

from __future__ import annotations

import hashlib
import json
import re
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
STAMP_LABEL = "aipass.base"
REF_LABEL = "aipass.base.ref"
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
CREDENTIAL_DIRS = (
    ".claude",
    ".codex",
    ".config/opencode",
    ".secrets",
    ".ssh",
    ".config/gh",
    ".git-credentials",
    ".netrc",
    ".aws",
    ".gnupg",
    ".docker",
    ".kube",
)

# Docker's own rule for a container name.
NAME_RULE = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$"
LOGIN_VOLUMES = tuple(f"aipass-login-{cli}" for cli in LOGIN_DIRS)
EXIT_USAGE = 2

USERMOD_LINE = "Add yourself to the docker group, then log in again: sudo usermod -aG docker $USER"


class BoxRefusal(Exception):
    """The request is refused; the message is printed exactly and ``code`` is the exit code."""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


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
    return "aipass-base:" + re.sub(r"[^a-zA-Z0-9_.-]", "-", image_ref)


def dockerfile_text(image_ref: str) -> str:
    """The base image: tools, user aipass, no AIPass and no CLI."""
    config_dirs = " ".join(f"{BOX_HOME}/{d}" for d in LOGIN_DIRS.values())
    path = f"{BOX_HOME}/.local/bin:{BOX_HOME}/aipass-venv/bin:{BOX_HOME}/.opencode/bin:$PATH"
    return f"""FROM {image_ref}
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \\
      python3 python3-venv python3-pip pipx git curl ca-certificates nodejs npm tmux ripgrep jq \\
    && rm -rf /var/lib/apt/lists/* \\
    && useradd -m -s /bin/bash aipass \\
    && git config --system --add safe.directory '*'
USER aipass
WORKDIR {BOX_HOME}
RUN mkdir -p {config_dirs} && python3 -m venv {BOX_HOME}/aipass-venv \\
    && echo 'export PATH={path}' >> {BOX_HOME}/.profile
ENV NPM_CONFIG_PREFIX={BOX_HOME}/.local
ENV PATH={path}
"""


def base_stamp(image_ref: str) -> str:
    """A digest of the Dockerfile text, labelled on the image so a changed Dockerfile rebuilds a cached base."""
    return hashlib.sha256(dockerfile_text(image_ref).encode("utf-8")).hexdigest()[:12]


def check_mount(path_str: str, home: Path | None = None) -> Path:
    """The resolved host path to bind read-only; refuse a missing path or a credential dir."""
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        raise BoxRefusal(f"--mount {path_str} refused: no such path")
    home = (home or Path.home()).resolve()
    for rel in CREDENTIAL_DIRS:
        cred = (home / rel).resolve()
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
        branch = "" if verb == "local" else f"--branch {verb} "
        lines.append(f"git clone -q {branch}{shlex.quote(clone_url or '')} {CLONE_DIR}")
        lines.append(f"git -C {CLONE_DIR} log -1 --oneline")
        lines.append(f"~/aipass-venv/bin/pip install -q {CLONE_DIR} || echo 'pip install of {CLONE_DIR} failed'")
        lines.append("echo 'Next:'")
        lines.append(f"echo '  aipass install --source {CLONE_DIR}'")
    lines.append(command if command else "exec bash -l")
    return "\n".join(lines)


def run_argv(
    *,
    verb: str,
    name: str,
    image: str,
    keep: bool,
    mounts: list[Path],
    login: bool,
    repo_root: Path | None,
) -> list[str]:
    """``docker run -d`` for one box; sleep keeps it up, so a kept box can always be started and entered."""
    argv = ["docker", "run", "-d", "--init"]
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
    return argv + [image, "sleep", "infinity"]


def exec_argv(name: str, script: str, tty: bool) -> list[str]:
    """``docker exec`` of the box script, attached to this terminal."""
    return ["docker", "exec"] + (["-it"] if tty else []) + [name, "bash", "-lc", script]


def check_name(name: str) -> None:
    """Refuse a name docker would refuse, before any docker call or ledger row."""
    if not re.match(NAME_RULE, name):
        raise BoxRefusal(f"--name {name} refused: a box name must match {NAME_RULE}", EXIT_USAGE)


def check_free(name: str) -> None:
    """Refuse a name that is a container or a box on record, so no other box's row is overwritten."""
    live = docker(["ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"]).stdout.split()
    if name in live or name in boxes(read_rows()):
        raise BoxRefusal(
            f"{name} is taken: a box by that name exists; pick another --name or drone docker rm it", EXIT_USAGE
        )


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
    """Start the box, record it, exec its script on this terminal, stop it; the exec's exit code."""
    argv = run_argv(
        verb=verb,
        name=name,
        image=base_tag(image_ref),
        keep=opts["keep"],
        mounts=mounts,
        login=opts["login"],
        repo_root=repo_root,
    )
    started = docker(argv[1:])
    if started.returncode != 0:
        raise BoxRefusal((started.stderr or started.stdout).strip(), started.returncode)
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
    try:
        return attach(exec_argv(name, box_script(verb, opts["with"], url, opts["command"]), tty))
    finally:
        # shortcut: the creating session owns the box lifetime; shared sessions need a separate contract.
        if stop(name) and not opts["keep"]:
            record({"event": "removed", "name": name})


def stop(name: str) -> bool:
    """Stop a box; return whether docker confirmed it, so a failed stop cannot close its record."""
    try:
        result = docker(["stop", "-t", "1", name])
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("docker: stop %s failed: %s", name, exc)
        return False
    if result.returncode != 0:
        logger.warning("docker: stop %s failed: %s", name, (result.stderr or result.stdout).strip())
    return result.returncode == 0


def attach(argv: list[str]) -> int:
    """Run a docker command on this terminal, uncaptured, so an interactive shell works."""
    return subprocess.run(argv).returncode


def check_aipass_checkout(root: Path) -> None:
    """Refuse a project root that is not an AIPass checkout: its pyproject.toml must name the aipass package.

    A hosted project (projects/<p>) is its own git repo and project root; cloning it gives a box with no aipass.
    """
    try:
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
    except OSError as exc:
        logger.info("docker: %s has no readable pyproject.toml: %s", root, exc)
        text = ""
    # tomllib is 3.11+ and the floor is 3.10: read the one key, name = "aipass", inside the [project] table.
    if not re.search(r"""^\[project\][^\[]*?^name\s*=\s*["']aipass["']\s*$""", text, re.MULTILINE):
        raise BoxRefusal(f"cwd is inside {root}, a project, not an AIPass checkout; run from inside the AIPass repo")


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


def _labels(tag: str, *labels: str) -> subprocess.CompletedProcess:
    """docker image inspect of *tag*, printing each label's value, tab-separated."""
    fmt = "\t".join(f'{{{{index .Config.Labels "{label}"}}}}' for label in labels)
    return docker(["image", "inspect", "--format", fmt, tag])


def base_state(image_ref: str) -> str:
    """``current`` (built from today's Dockerfile text), ``stale`` (from other text) or ``missing``."""
    seen = _labels(base_tag(image_ref), STAMP_LABEL)
    if seen.returncode != 0:
        return "missing"
    return "current" if seen.stdout.strip() == base_stamp(image_ref) else "stale"


def build_base(image_ref: str, no_cache: bool) -> int:
    """docker build the base, labelled with its stamp and ref; a success records its wall time. Build's exit code."""
    tag = base_tag(image_ref)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="aipass_docker_") as tmp:
        Path(tmp, "Dockerfile").write_text(dockerfile_text(image_ref), encoding="utf-8")
        flags = ["--no-cache"] if no_cache else []
        flags += ["--label", f"{STAMP_LABEL}={base_stamp(image_ref)}", "--label", f"{REF_LABEL}={image_ref}"]
        logger.info("docker: building %s", tag)
        returncode = subprocess.run(["docker", "build", *flags, "-t", tag, tmp]).returncode
    if returncode == 0:
        record({"event": "base_built", "tag": tag, "seconds": round(time.monotonic() - started)})
    return returncode


def last_build_seconds(tag: str) -> int | None:
    """How long the last recorded build of *tag* took, or None when none is recorded."""
    built = [r for r in read_rows() if r.get("event") == "base_built" and r.get("tag") == tag]
    return built[-1].get("seconds") if built else None


def base_images() -> list[tuple[str, str, str]]:
    """``(tag, age, state)`` per aipass-base image; state is current, stale, or unknown when no ref is labelled."""
    listing = docker(
        ["image", "ls", "--filter", "reference=aipass-base", "--format", "{{.Repository}}:{{.Tag}}\t{{.CreatedSince}}"]
    )
    host = host_image_ref()
    images = []
    for line in listing.stdout.splitlines():
        tag, _, age = line.partition("\t")
        stamp, _, ref = _labels(tag, STAMP_LABEL, REF_LABEL).stdout.strip().partition("\t")
        # An image built before the ref label was added: only the host's own base can be judged.
        if ref in ("", "<no value>"):
            ref = host if base_tag(host) == tag else ""
        state = "unknown (no base ref labelled)" if not ref else "current" if stamp == base_stamp(ref) else "stale"
        images.append((tag, age, state))
    return images


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


def login_volumes() -> list[str]:
    """The ``aipass-login-*`` volumes docker holds."""
    return docker(["volume", "ls", "--filter", "name=^aipass-login-", "--format", "{{.Name}}"]).stdout.split()


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
