# =================== AIPass ====================
# Name: docker.py
# Description: Module orchestrator for drone docker: disposable test boxes it names, lists and removes
# Version: 1.1.0
# Created: 2026-11-24
# Modified: 2026-11-25
# =============================================

"""Disposable docker boxes for testing AIPass: bare, local, dev, main; list, shell, rm.

Every box is ``aipass-<verb>-<n>``, labelled and recorded; drone docker never touches another container.
"""

from __future__ import annotations

import shlex
import sys
import time

from aipass.prax import logger
from aipass.cli import console, err_console, error, escape
from aipass.drone.apps.handlers import docker_handler as box
from aipass.drone.apps.handlers.help_flags import wants_help
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.rm_handler import format_age
from aipass.drone.apps.handlers.router_handler import find_project_root

DRONE_MODULE = {
    "name": "docker",
    "version": "1.0.0",
    "description": "Disposable docker boxes: bare, local, dev, main; build, list, shell, rm",
}

CREATE_VERBS = ("bare", "local", "dev", "main")
EXIT_REFUSED = 1
EXIT_NO_DOCKER = 2


def handle_command(command: str | None = None, args: list[str] | None = None) -> bool:
    """Module-routing entry point; drone's built-in route calls run() for the exit code."""
    if not args:
        if command is None:
            print_introspection()
            return True
    if wants_help(command, args):
        print_help()
        return True
    return run(command, args) == 0


def run(command: str | None = None, args: list[str] | None = None) -> int:
    """``drone docker <verb> [options]``; returns the exit code (2 when docker is absent or down)."""
    args = list(args or [])
    if command is None:
        print_introspection()
        return 0
    if wants_help(command, args):
        print_help()
        return 0
    json_handler.log_operation("docker_command", {"verb": command, "args": args})
    try:
        if command in CREATE_VERBS:
            return create(command, args)
        if command == "build":
            return build(args)
        if command == "list" and not args:
            return list_boxes()
        if command == "shell" and len(args) == 1:
            return shell(args[0])
        if command == "rm" and args:
            return remove(args)
        usage = " ".join([command, *args])
        raise box.BoxRefusal(f"unknown or incomplete docker command: {usage} (drone docker --help)")
    except box.BoxRefusal as exc:
        logger.warning("docker: refused: %s", exc)
        error(str(exc))
        return exc.code


def _parse(args: list[str]) -> dict:
    """The create options; raise BoxRefusal on an unknown flag or a missing value."""
    opts: dict = {"keep": False, "login": False, "rebuild": False, "with": [], "mount": [], "image": None, "name": None}
    command = args[args.index("--") + 1 :] if "--" in args else []
    opts["command"] = command[0] if len(command) == 1 else shlex.join(command) if command else None
    rest = args[: args.index("--")] if "--" in args else list(args)
    while rest:
        flag = rest.pop(0)
        if flag in ("--keep", "--login", "--rebuild"):
            opts[flag[2:]] = True
            continue
        if flag not in ("--with", "--mount", "--image", "--name"):
            raise box.BoxRefusal(f"unknown option {flag} (drone docker --help)")
        if not rest:
            raise box.BoxRefusal(f"{flag} needs a value")
        value = rest.pop(0)
        if flag == "--with" and value not in box.INSTALLERS:
            raise box.BoxRefusal(f"--with {value} refused: one of {', '.join(box.INSTALLERS)}")
        if flag in ("--with", "--mount"):
            opts[flag[2:]].append(value)
        else:
            opts[flag[2:]] = value
    return opts


def _ready() -> int:
    """0 when docker answers, else the line said and exit 2."""
    ok, message = box.docker_ready()
    if ok:
        return 0
    error(message)
    return EXIT_NO_DOCKER


def create(verb: str, args: list[str]) -> int:
    """Check the name, build the base if needed, then start, record, enter and stop the box."""
    opts = _parse(args)
    if opts["name"] is not None:
        box.check_name(opts["name"])
    image_ref = opts["image"] or box.host_image_ref()
    box.check_apt_base(image_ref)
    mounts = [box.check_mount(p) for p in opts["mount"]]
    if _ready():
        return EXIT_NO_DOCKER
    repo_root = find_project_root() if verb != "bare" else None
    if verb != "bare" and repo_root is None:
        raise box.BoxRefusal(f"drone docker {verb} needs the AIPass project root, and none was found from here")
    if repo_root is not None:
        box.check_aipass_checkout(repo_root)
    url = box.clone_url(verb, repo_root) if repo_root is not None else None
    state = "rebuild" if opts["rebuild"] else box.base_state(image_ref)
    built = _build(image_ref, state) if state != "current" else 0
    if built:
        return built
    name = opts["name"] or box.next_name(verb, box.read_rows())
    box.check_free(name)
    console.print(f"{name}  ({verb}, {image_ref}{', kept' if opts['keep'] else ''})", markup=False, highlight=False)
    return box.launch(verb, name, image_ref, opts, mounts, repo_root, url, tty=sys.stdin.isatty())


def build(args: list[str]) -> int:
    """Warm or refresh the cached base and exit, no box: the tag, cached or built, and the wall time."""
    rebuild = "--rebuild" in args
    rest = [a for a in args if a != "--rebuild"]
    if rest and (rest[0] != "--image" or len(rest) != 2):
        raise box.BoxRefusal("drone docker build takes only --image <ref> and --rebuild (drone docker --help)")
    image_ref = rest[1] if rest else box.host_image_ref()
    box.check_apt_base(image_ref)
    if _ready():
        return EXIT_NO_DOCKER
    started = time.monotonic()
    state = "rebuild" if rebuild else box.base_state(image_ref)
    if state != "current":
        built = _build(image_ref, state)
        if built:
            return built
    outcome = "cached" if state == "current" else "built"
    console.print(
        f"{box.base_tag(image_ref)}  {outcome}  {time.monotonic() - started:.1f}s", markup=False, highlight=False
    )
    return 0


def _build(image_ref: str, state: str) -> int:
    """Say why the base builds and how long it took last time, then build it; 0, or docker build's exit code."""
    tag = box.base_tag(image_ref)
    last = box.last_build_seconds(tag)
    took = "a few minutes" if not last else f"about {format_age(last) if last >= 60 else f'{last}s'} last time"
    why = {
        "stale": "is stale (Dockerfile changed)",
        "missing": "is not built yet",
        "rebuild": "rebuilds (--rebuild, no cache)",
    }
    err_console.print(
        f"base image {tag} {why[state]}: building, {took}; next time it is cached. To build ahead: drone docker build",
        markup=False,
        highlight=False,
        soft_wrap=True,
    )
    built = box.build_base(image_ref, state == "rebuild")
    if built:
        error(f"docker build of {tag} failed (exit {built})")
    return built


def list_boxes() -> int:
    """One line per box drone docker made and has not removed: name, verb, age, state, kept."""
    if _ready():
        return EXIT_NO_DOCKER
    states = box.live_states()
    made = box.boxes(box.read_rows())
    live = {n: r for n, r in made.items() if n in states}
    for name, row in live.items():
        state = "running" if states[name] == "running" else "stopped"
        age = format_age(time.time() - row.get("created", time.time()))
        kept = "kept" if row.get("kept") else "rm on exit"
        console.print(f"{name:<24} {row.get('verb', ''):<6} {age:>7}  {state:<8} {kept}", markup=False, highlight=False)
    gone = len(made) - len(live)
    if not live:
        console.print("no drone docker boxes on this machine", markup=False)
    if gone:
        console.print(f"{gone} earlier box(es) gone (ran with --rm, or removed outside drone)", markup=False)
    for tag, age, state in box.base_images():
        console.print(f"base image  {tag:<28} {age:<19} {state}", markup=False, highlight=False)
    for vol in box.login_volumes() or ["no login volumes"]:
        console.print(f"login volume  {vol}" if vol.startswith("aipass-") else vol, markup=False)
    return 0


def shell(name: str) -> int:
    """Start a stopped box, open a login shell in it, and stop it again so it is left as found."""
    if _ready():
        return EXIT_NO_DOCKER
    if box.own_box(name) == "running":
        return box.attach(["docker", "exec", "-it", name, "bash", "-l"])
    box.docker(["start", name])
    try:
        if box.live_states().get(name) != "running":
            raise box.BoxRefusal(
                f"{name} does not stay up when started (a box made before drone docker ran boxes on sleep); "
                f"drone docker rm {name} and make it again"
            )
        return box.attach(["docker", "exec", "-it", name, "bash", "-l"])
    finally:
        box.stop(name)


def remove(args: list[str]) -> int:
    """Force-remove named boxes, or every live one with --all; record each removal."""
    if _ready():
        return EXIT_NO_DOCKER
    if args == ["--login"]:
        return remove_login()
    if args == ["--all"]:
        states = box.live_states()
        names = [n for n in box.boxes(box.read_rows()) if n in states]
    else:
        names = args
        for name in names:
            box.own_box(name)
    failed = 0
    for name in names:
        result = box.docker(["rm", "-f", name])
        if result.returncode != 0 and "No such container:" not in result.stderr:
            error(f"docker rm {name} failed: {(result.stderr or result.stdout).strip()}")
            failed += 1
            continue
        box.record({"event": "removed", "name": name})
        logger.info("docker: removed %s", name)
        console.print(f"removed {name}", markup=False)
    if not names:
        console.print("no drone docker boxes to remove", markup=False)
    return EXIT_REFUSED if failed else 0


def remove_login() -> int:
    """Remove the aipass-login-* volumes, clearing every sign-in; docker's refusal of one in use passes through."""
    vols = [v for v in box.login_volumes() if v in box.LOGIN_VOLUMES]
    if not vols:
        console.print("no login volumes to remove", markup=False)
        return 0
    result = box.docker(["volume", "rm", *vols])
    removed = result.stdout.split()
    if removed:
        box.record({"event": "login_removed", "volumes": removed})
    for vol in removed:
        console.print(f"removed {vol}", markup=False)
    if result.returncode != 0:
        error(result.stderr.strip())
    return result.returncode


def print_introspection() -> None:
    """Display module overview (no args)."""
    console.print()
    console.print("[bold cyan]docker — Disposable Test Boxes[/bold cyan]")
    console.print()
    console.print("[dim]Containers that match this machine: bare, local, dev, main; build, list, shell, rm.[/dim]")
    console.print()
    console.print("Run [green]'drone docker --help'[/green] for usage information")
    console.print()


def print_help() -> None:
    """Display help (--help flag): headings and verbs styled, the text escaped so its brackets print."""
    console.print()
    console.print("[bold cyan]drone docker[/bold cyan] — Disposable Test Boxes")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print(escape("  drone docker <verb> [options] [-- <command>]"), highlight=False, soft_wrap=True)
    console.print()
    console.print(f"[dim]{escape(HELP['about'])}[/dim]", highlight=False, soft_wrap=True)
    console.print()
    console.print("[bold cyan]Verbs:[/bold cyan]")
    _print_rows(HELP["verbs"])
    console.print()
    console.print("[bold cyan]Options for bare, local, dev, main:[/bold cyan]")
    _print_rows(HELP["options"])
    console.print()
    console.print("[bold cyan]Rules:[/bold cyan]")
    console.print(f"[dim]{escape(HELP['rules'])}[/dim]", highlight=False, soft_wrap=True)
    console.print()
    console.print("[bold cyan]Examples:[/bold cyan]")
    for line in HELP["examples"].splitlines():
        console.print(f"  [green]{escape(line.strip())}[/green]", highlight=False, soft_wrap=True)
    console.print()


def _print_rows(block: str) -> None:
    """A verb or option row: the name cyan in its 21-column field, the text dim; a continuation line dim."""
    for line in block.splitlines():
        console.print(
            f"  [cyan]{escape(line[2:23])}[/cyan][dim]{escape(line[23:])}[/dim]", highlight=False, soft_wrap=True
        )


HELP = {
    "about": """Disposable boxes that match this machine. Every box is named aipass-<verb>-<n>, carries the
label aipass.box and a row in .ai_central/docker_boxes.jsonl. drone docker lists, enters and
removes only those; never any other container.""",
    "verbs": """  bare                 fresh image of this machine's OS, base tools, no AIPass, a shell
  local                bare + this checkout's committed HEAD, cloned and pip-installed (repo ro at /src)
  dev | main           bare + that branch cloned from origin on github (not this checkout), pip-installed
                       local, dev and main have aipass on PATH and nothing else set up; your first
                       command is: aipass install --source ~/AIPass-src
  build                warm or refresh the cached base (--image <ref>, --rebuild) and exit, no box:
                       the tag, cached or built, and the wall time. Run it after the Dockerfile changes
  list                 its boxes: name, verb, age, running or stopped, kept or rm on exit; then each
                       base image, current or stale against the Dockerfile text; then the
                       aipass-login-* volumes, or "no login volumes"
  shell <name>         start a kept box if stopped, open a shell in it, stop it again on exit
  rm <name>... | --all stop and remove its boxes; a name it did not make is refused
  rm --login           remove the aipass-login-* volumes: this is how a sign-in is cleared
                       (docker refuses a volume a container still uses; that refusal is shown)""",
    "options": """  --keep               do not remove on exit (default: removed on exit)
  --with <cli>         install claude, codex or opencode with its vendor installer (repeatable)
  --mount <path>       bind a host directory read-only at /mnt/<basename> (repeatable)
  --login              named volumes for ~/.claude, ~/.codex, ~/.config/opencode in the box
  --image <ref>        base image (default: this machine's ID:VERSION_ID; ubuntu or debian only)
  --rebuild            rebuild the cached base image (--no-cache)
  --name <name>        instead of aipass-<verb>-<n>; must match ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$
                       and not be a container or a recorded box already (else exit 2)
  -- <command>         one argument is a shell script; multiple arguments retain their quoting""",
    "rules": """  Host credential paths (~/.claude, ~/.codex, ~/.config/opencode, ~/.secrets, ~/.ssh, ~/.config/gh,
  ~/.git-credentials, ~/.netrc, ~/.aws, ~/.gnupg, ~/.docker, ~/.kube) never mount, nor any path
  inside or directory holding one. --login is the only state carried between boxes.
  Docker absent or its daemon down: one line, exit 2.
  Every box runs sleep under --init; the script or shell runs through docker exec, and the box is
  stopped after (a kept box stays, stopped, and can always be entered again with shell).
  A successful non-kept stop records removal, so its --name can be reused.
  bare, local, dev and main exit with the box command's exit code (docker's, if the box never starts).""",
    "examples": """  drone docker bare
  drone docker local --with claude --login
  drone docker dev --keep
  drone docker bare -- 'cat /etc/os-release'
  drone docker rm aipass-dev-1""",
}
