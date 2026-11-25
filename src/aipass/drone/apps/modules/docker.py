# =================== AIPass ====================
# Name: docker.py
# Description: Module orchestrator for drone docker: disposable test boxes it names, lists and removes
# Version: 1.0.0
# Created: 2026-11-24
# Modified: 2026-11-24
# =============================================

"""Disposable docker boxes for testing AIPass: bare, local, dev, main; list, shell, rm.

Every box is ``aipass-<verb>-<n>``, labelled and recorded; drone docker never touches another container.
"""

from __future__ import annotations

import sys
import time

from aipass.prax import logger
from aipass.cli import console, error
from aipass.drone.apps.handlers import docker_handler as box
from aipass.drone.apps.handlers.help_flags import wants_help
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.rm_handler import format_age
from aipass.drone.apps.handlers.router_handler import find_project_root

DRONE_MODULE = {
    "name": "docker",
    "version": "1.0.0",
    "description": "Disposable docker boxes: bare, local, dev, main; list, shell, rm",
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
        return EXIT_REFUSED


def _parse(args: list[str]) -> dict:
    """The create options; raise BoxRefusal on an unknown flag or a missing value."""
    opts: dict = {"keep": False, "login": False, "rebuild": False, "with": [], "mount": [], "image": None, "name": None}
    opts["command"] = " ".join(args[args.index("--") + 1 :]) if "--" in args else None
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
    """Build the base if needed, record the box, run it attached to this terminal."""
    opts = _parse(args)
    image_ref = opts["image"] or box.host_image_ref()
    box.check_apt_base(image_ref)
    mounts = [box.check_mount(p) for p in opts["mount"]]
    if _ready():
        return EXIT_NO_DOCKER
    repo_root = find_project_root() if verb != "bare" else None
    if verb != "bare" and repo_root is None:
        raise box.BoxRefusal(f"drone docker {verb} needs the AIPass project root, and none was found from here")
    url = box.clone_url(verb, repo_root) if repo_root is not None else None
    built = box.ensure_base(image_ref, opts["rebuild"])
    if built:
        error(f"docker build of {box.base_tag(image_ref)} failed (exit {built})")
        return built
    name = opts["name"] or box.next_name(verb, box.read_rows())
    console.print(f"{name}  ({verb}, {image_ref}{', kept' if opts['keep'] else ''})", markup=False, highlight=False)
    return box.launch(verb, name, image_ref, opts, mounts, repo_root, url, tty=sys.stdin.isatty())


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
    return 0


def shell(name: str) -> int:
    """Start a stopped box if needed and open a login shell in it."""
    if _ready():
        return EXIT_NO_DOCKER
    state = box.own_box(name)
    if state != "running" and box.docker(["start", name]).returncode != 0:
        error(f"docker start {name} failed")
        return EXIT_REFUSED
    return box.attach(["docker", "exec", "-it", name, "bash", "-l"])


def remove(args: list[str]) -> int:
    """Stop then remove named boxes, or every live one with --all; record each removal."""
    if _ready():
        return EXIT_NO_DOCKER
    if args == ["--all"]:
        states = box.live_states()
        names = [n for n in box.boxes(box.read_rows()) if n in states]
    else:
        names = args
        for name in names:
            box.own_box(name)
    failed = 0
    for name in names:
        box.docker(["stop", name])
        result = box.docker(["rm", name])
        if result.returncode != 0:
            error(f"docker rm {name} failed: {(result.stderr or result.stdout).strip()}")
            failed += 1
            continue
        box.record({"event": "removed", "name": name})
        logger.info("docker: removed %s", name)
        console.print(f"removed {name}", markup=False)
    if not names:
        console.print("no drone docker boxes to remove", markup=False)
    return EXIT_REFUSED if failed else 0


def print_introspection() -> None:
    """Display module overview (no args)."""
    console.print()
    console.print("[bold cyan]docker — Disposable Test Boxes[/bold cyan]")
    console.print()
    console.print("[dim]Containers that match this machine: bare, local, dev, main; list, shell, rm.[/dim]")
    console.print()
    console.print("Run [green]'drone docker --help'[/green] for usage information")
    console.print()


def print_help() -> None:
    """Display help (--help flag)."""
    for line in HELP.splitlines():
        console.print(line, markup=False, highlight=False, soft_wrap=True)


HELP = """Usage: drone docker <verb> [options] [-- <command>]

Disposable boxes that match this machine. Every box is named aipass-<verb>-<n>, carries the
label aipass.box and a row in .ai_central/docker_boxes.jsonl. drone docker lists, enters and
removes only those; never any other container.

Verbs:
  bare                 fresh image of this machine's OS, base tools, no AIPass, a shell
  local                bare + a clone of this repo's committed HEAD (repo mounted read-only at /src)
  dev | main           bare + a clone of that branch from origin on github
  list                 its boxes: name, verb, age, running or stopped, kept or rm on exit
  shell <name>         start a kept box if stopped and open a shell in it
  rm <name>... | --all stop and remove its boxes; a name it did not make is refused

Options for bare, local, dev, main:
  --keep               do not remove on exit (default: removed on exit)
  --with <cli>         install claude, codex or opencode with its vendor installer (repeatable)
  --mount <path>       bind a host directory read-only at /mnt/<basename> (repeatable)
  --login              named volumes for ~/.claude, ~/.codex, ~/.config/opencode in the box
  --image <ref>        base image (default: this machine's ID:VERSION_ID; ubuntu or debian only)
  --rebuild            rebuild the cached base image (--no-cache)
  --name <name>        instead of aipass-<verb>-<n>
  -- <command>         run this one command in the box instead of a shell

Rules:
  Host credential dirs (~/.claude, ~/.codex, ~/.config/opencode, ~/.secrets, ~/.ssh) never
  mount, nor any directory inside or holding one. --login is the only state carried between boxes.
  Docker absent or its daemon down: one line, exit 2.

Examples:
  drone docker bare
  drone docker local --with claude --login
  drone docker dev --keep
  drone docker bare -- 'cat /etc/os-release'
  drone docker rm aipass-dev-1"""
