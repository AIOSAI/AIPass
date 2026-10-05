# =================== AIPass ====================
# Name: engine_closure.py
# Version: 1.0.0
# Description: The hook engine's import closure, and the edit check that keeps a NameError out of it
# Branch: hooks
# Layer: apps/modules
# Created: 2026-10-04
# Modified: 2026-10-04
# =============================================

"""Which files the hook engine imports, and a refusal for an edit that would crash one of them.

The 10-03 incident (14:58 to 15:45): a module the engine imports used a name one
edit before its import. The engine crashed with a NameError and, failing closed,
refused every tool fleet-wide, Read included. Two layers already stood: the
promoted copy (the engine runs from .live-current, not the source tree) and the
fail-closed crash refusal. Neither covers another branch's module the engine
imports live, which is where 10-03 struck. This is the third layer, the edit
gate's (fleet green leg 5, item 2, the owner's question):

  - :func:`closure` is COMPUTED, never a hand list: the roots are the engine, the
    loader, the bridges and every handler wired in the root ``.aipass/hooks.json``;
    from each, the ``aipass.*`` imports at module level are followed, with every
    package ``__init__`` on the way. Files are read and parsed (``ast``), never
    imported: importing would run them.
  - :func:`crash_refusal` runs ruff with F821 (undefined name) on the text an edit
    WOULD leave, before it lands, for a closure file only. Syntax errors come with
    it: the dispatch named E999, which ruff removed (see CRASH_RULES).

What it cannot see: an import made inside a function, or by importlib at run
time. The engine's own handler imports are of that kind, which is why the wired
handlers are roots rather than discovered.
"""

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.handlers.config.loader import aipass_home
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

#: The engine's own entry points; the wired handlers are added from hooks.json.
ROOT_MODULES = (
    "aipass.hooks.apps.modules.engine",
    "aipass.hooks.apps.handlers.config.loader",
    "aipass.hooks.apps.handlers.bridges.claude",
    "aipass.hooks.apps.handlers.bridges.codex",
    "aipass.hooks.apps.handlers.bridges.mount",
)

#: The rule that turns a module into a crash at import: an undefined name. A syntax error needs no rule:
#: ruff removed E999 and reports every syntax error as ``invalid-syntax`` (0.15.x refuses ``--select E999``).
CRASH_RULES = "F821"

REFUSED = (
    "{name} is imported by the hook engine, and this edit would leave it crashing at import:\n{hits}\n"
    "A crash there refuses every tool for every seat (the 10-03 incident). Land the import in the same "
    "edit as its first use, then retry."
)


def _wired_handlers(home: Path) -> list[str]:
    """The module of every handler the root hooks.json wires (``aipass.x.y.handle`` -> ``aipass.x.y``)."""
    config = home / ".aipass" / "hooks.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("[HOOKS] engine_closure: %s unreadable, closure from the engine's own roots: %s", config, exc)
        data = {}
    found: list[str] = []
    stack: list[object] = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            handler = node.get("handler")
            if isinstance(handler, str) and handler.startswith("aipass.") and "." in handler:
                found.append(handler.rsplit(".", 1)[0])
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return found


def _files_of(name: str, src: Path) -> list[Path]:
    """The files importing *name* runs: each package ``__init__`` on the way, then the module itself."""
    parts = name.split(".")
    files = [src.joinpath(*parts[:i], "__init__.py") for i in range(1, len(parts) + 1)]
    files.append(src.joinpath(*parts).with_suffix(".py"))
    return [f for f in files if f.is_file()]


def _top_level(body: list) -> list:
    """Statements that run at import: the module body, and the bodies of its top-level if and try."""
    found = []
    for node in body:
        found.append(node)
        if isinstance(node, ast.If):
            found.extend(_top_level(node.body) + _top_level(node.orelse))
        elif isinstance(node, ast.Try):
            for block in (node.body, node.orelse, node.finalbody, *[h.body for h in node.handlers]):
                found.extend(_top_level(block))
    return found


def _imports(path: Path, package: str) -> list[str]:
    """The ``aipass.*`` modules *path* imports at module level (a ``from x import y`` names x and x.y)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, ValueError) as exc:
        logger.warning("[HOOKS] engine_closure: %s not parsed, its imports are not followed: %s", path, exc)
        return []
    names: list[str] = []
    for node in _top_level(tree.body):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join([*anchor, base] if base else anchor)
            names.append(base)
            names.extend(f"{base}.{alias.name}" for alias in node.names)
    return [n for n in names if n == "aipass" or n.startswith("aipass.")]


def closure(home: Path) -> frozenset[Path]:
    """Every file the hook engine imports at module level, resolved, from its roots (see the module docstring).

    Args:
        home: The AIPass install root (holds src/aipass and .aipass/hooks.json).

    Returns:
        The resolved paths of the closure's files.
    """
    src = home / "src"
    queue = [*ROOT_MODULES, *_wired_handlers(home)]
    seen_names: set[str] = set()
    files: set[Path] = set()
    while queue:
        name = queue.pop()
        if name in seen_names:
            continue
        seen_names.add(name)
        for path in _files_of(name, src):
            if path in files:
                continue
            files.add(path)
            # The package a relative import counts from: an __init__'s own, a module's parent.
            queue.extend(_imports(path, ".".join(path.relative_to(src).parts[:-1])))
    return frozenset(p.resolve() for p in files)


def _ruff(ruff: str | None) -> str | None:
    """The ruff to run: the one handed in, else the one beside this interpreter, else PATH's."""
    if ruff:
        return ruff
    beside = Path(sys.executable).parent / ("ruff.exe" if os.name == "nt" else "ruff")
    return str(beside) if beside.is_file() else shutil.which("ruff")


def crash_hits(path: Path, text: str, ruff: str | None = None) -> list[str] | None:
    """F821 and syntax errors in *text* as ruff reads it for *path*: one line per hit, [] when clean.

    Args:
        path: The file the text is for (ruff's --stdin-filename).
        text: The text the edit would leave.
        ruff: The ruff executable; None finds it (a seam, so no test patches shutil).

    Returns:
        The hits, or None when ruff could not be run (logged: the promoted copy and
        the fail-closed engine still stand behind this layer).
    """
    exe = _ruff(ruff)
    if not exe:
        logger.warning("[HOOKS] engine_closure: no ruff found, %s is not pre-checked", path)
        return None
    command = [exe, "check", "--isolated", "--no-cache", "--select", CRASH_RULES, "--output-format", "json"]
    try:
        run = subprocess.run(
            [*command, "--stdin-filename", str(path), "-"],
            input=text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        if run.returncode not in (0, 1):  # 2 is ruff's own failure, with nothing on stdout: not a clean answer
            raise ValueError(run.stderr.strip() or f"ruff exited {run.returncode}")
        found = json.loads(run.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        logger.warning("[HOOKS] engine_closure: ruff did not answer for %s: %s", path, exc)
        return None
    return [f"  L{hit['location']['row']}: {hit.get('code') or 'syntax'} {hit['message']}" for hit in found]


def crash_refusal(path: Path, tool_name: str, tool_input: dict, after_text, home: Path | None) -> str | None:
    """The refusal for an edit that would leave a file of the engine's import closure crashing, or None.

    Args:
        path: The file being edited.
        tool_name: Write, Edit or MultiEdit.
        tool_input: The tool's input (content, or the edits).
        after_text: edit_gate's own reader of the text an Edit or MultiEdit leaves.
        home: The AIPass install root; None skips the check.

    Returns:
        The refusal text, or None (not a closure file, clean text, or ruff unavailable).
    """
    if home is None or path.suffix != ".py" or tool_name not in ("Write", "Edit", "MultiEdit"):
        return None
    target = path.resolve()
    if target not in closure(home):
        return None
    if tool_name == "Write":
        text = tool_input.get("content", "")
    else:
        text = after_text(tool_name, tool_input, target.read_text(encoding="utf-8")) if target.is_file() else None
    if text is None:
        return None
    hits = crash_hits(target, text)
    if not hits:
        return None
    logger.warning("[HOOKS] engine_closure: refused an edit leaving %s crashing at import", target)
    return REFUSED.format(name=target.name, hits="\n".join(hits))


def print_introspection() -> None:
    """Print module structure for drone routing: the roots and the rules."""
    CONSOLE.print("[bold cyan]engine_closure[/bold cyan] — the hook engine's import closure (fleet green leg 5)")
    CONSOLE.print(f"  roots: {', '.join(ROOT_MODULES)} + every handler in .aipass/hooks.json")
    CONSOLE.print(f"  an edit to a closure file is checked for {CRASH_RULES} before it lands")
    CONSOLE.print("  [dim]drone @hooks closure list[/dim] — list the closure, computed from this install")


def handle_command(command: str, args: list) -> bool:
    """Route ``closure list`` from drone @hooks: the closure's files, computed now, one per line."""
    if command != "closure":
        return False
    if not args:
        print_introspection()
        return True
    if args[0] != "list":
        print_introspection()
        return True
    home = aipass_home()
    if home is None:
        CONSOLE.print("[red]No AIPass install found (AIPASS_HOME unset, none above this file).[/red]")
        return True
    files = sorted(closure(home))
    for path in files:
        CONSOLE.print(f"  {path.relative_to(home) if path.is_relative_to(home) else path}")
    CONSOLE.print(f"[bold]{len(files)}[/bold] files in the hook engine's import closure under {home}")
    return True
