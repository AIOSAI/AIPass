# =================== AIPass ====================
# Name: adopt.py
# Description: aipass adopt — bring an existing directory anywhere on disk into AIPass
# Version: 2.0.0
# Created: 2026-07-20
# Modified: 2026-11-08
# =============================================

"""
Adopt Handler — PRIVATE implementation

Two modes. framework: the AIPass layout, additive only, with .gitignore patched so AIPass local
state never leaks into a commit. contractor: the project keeps its own stack, and AIPass writes
no tracked file and never .gitignore; every local path it writes goes to .git/info/exclude.
Every path either mode considers comes back as a row: create, append, skip or clash, with a reason.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.new_project import (
    _agent_home,
    _registry_name,
    _spawn_project_agent,
    _write_registry,
)
from aipass.aipass.apps.handlers.init import scaffold_manifest as sm
from aipass.aipass.apps.handlers.init.bootstrap import (
    LINK_STATE_MISSING,
    NAVMAP_REL,
    OWNER_SEEDS,
    PREP_SKILL_REL,
    SKILLS_LINK_REL,
    SWITCH_PAIR,
    _link_venv,
    _managed_manifest_entries,
    link_skills,
    navmap_stub,
    shared_skills_state,
)
from aipass.aipass.shared import scaffold_content as sc
from aipass.aipass.shared.project_home import (
    claude_local_settings,
    _claude_settings,
    _detect_aipass_home,
    _enroll_project,
    agents_md_seed,
    is_projects_child,
    is_throwaway_path,
)
from aipass.prax import logger

GITIGNORE_MARKER = "# AIPass local state"
MODES = ("framework", "contractor")
CREATE, APPEND, SKIP, CLASH = "create", "append", "skip", "clash"
_CITIZEN_RE = re.compile(r"^@[A-Za-z0-9_-]+$")
_TRACKED = "tracked by the project: contractor mode never writes a tracked file"
_run_drone = subprocess.run  # the seam tests replace: @spawn's door is another branch


def _row(path: str, action: str, reason: str) -> dict:
    return {"path": path, "action": action, "reason": reason}


def _gitignore_safety(target: Path, *, dry_run: bool) -> str:
    """Ensure AIPass-managed paths are gitignored. Returns 'created', 'appended', or 'already-safe'."""
    gitignore_path = target / ".gitignore"
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8")
        if GITIGNORE_MARKER in existing:
            return "already-safe"
        if not dry_run:
            separator = "" if existing.endswith("\n") else "\n"
            sm.write_text_lf(gitignore_path, existing + separator + "\n" + sc.gitignore())
        return "appended"
    if not dry_run:
        sm.write_text_lf(gitignore_path, sc.gitignore())
    return "created"


def _write_if_missing(target: Path, rel: str, content: str, *, dry_run: bool, planned: list, rows: list) -> None:
    """Write *content* at *target*/*rel* unless something is there; either way the path gets a row."""
    path = target / rel
    if path.exists() or path.is_symlink():
        rows.append(_row(rel, SKIP, "present: the project's own copy is kept"))
        return
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        sm.write_text_lf(path, content)
    planned.append(str(path))
    rows.append(_row(rel, CREATE, "absent"))


def _spawn_adopt_citizen(citizen: str, target: Path, *, apply: bool) -> dict:
    """Call @spawn's adopt-citizen door; its stdout is kept verbatim for the caller to embed."""
    args = ["drone", "@spawn", "adopt-citizen", citizen, str(target)] + (["--apply"] if apply else [])
    try:
        proc = _run_drone(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("[AIPASS] adopt: %s failed: %s", " ".join(args), exc)
        return {"name": citizen, "ok": False, "output": "", "reason": f"could not run @spawn adopt-citizen: {exc}"}
    output = (proc.stdout or "").rstrip()
    ok = proc.returncode == 0
    reason = "" if ok else ((proc.stderr or "").strip() or output or f"exit {proc.returncode}")
    return {"name": citizen, "ok": ok, "output": output, "reason": reason}


def _check_citizen(citizen: str | None, no_agent: bool) -> None:
    if citizen is None:
        return
    if not _CITIZEN_RE.match(citizen):
        raise RuntimeError(f"--citizen takes @name (letters, digits, _ or -), got '{citizen}'.")
    if no_agent:
        raise RuntimeError("--citizen and --no-agent exclude each other: one brings a citizen, the other none.")


def adopt_project(
    target: Path,
    *,
    no_agent: bool = False,
    dry_run: bool = False,
    mode: str = "framework",
    citizen: str | None = None,
) -> dict:
    """Adopt an existing directory anywhere on disk as an AIPass project.

    ``citizen`` (``@name``) brings an existing citizen through @spawn instead of minting a resident;
    @spawn then seats the registry. ``dry_run`` writes nothing and asks @spawn only for its preview.
    """
    if mode not in MODES:
        raise RuntimeError(f"Unknown mode '{mode}': choose framework or contractor.")
    _check_citizen(citizen, no_agent)
    target = target.resolve()
    if not target.is_dir():
        raise RuntimeError(f"'{target}' does not exist. `aipass adopt` brings in an EXISTING directory.")

    existing_registry = [f for f in target.iterdir() if f.is_file() and f.name.endswith("_REGISTRY.json")]
    if existing_registry:
        raise RuntimeError(f"'{target}' is already adopted (has {existing_registry[0].name}).")

    if mode == "contractor":
        result = _adopt_contractor(target, no_agent=no_agent, dry_run=dry_run, citizen=citizen)
    else:
        result = _adopt_framework(target, no_agent=no_agent, dry_run=dry_run, citizen=citizen)
    json_handler.log_operation(
        "adopt_project",
        {"name": result["name"], "target": str(target), "mode": mode, "dry_run": dry_run},
        "adopt",
    )
    return result


def _adopt_framework(target: Path, *, no_agent: bool, dry_run: bool, citizen: str | None) -> dict:
    """The AIPass layout at any path: scaffold, .gitignore lines, and a fresh resident or *citizen*."""
    name = target.name
    reg = _registry_name(name)
    mint = not no_agent and citizen is None

    agent_home = _agent_home(target, name)
    if mint and agent_home.exists() and any(agent_home.iterdir()):
        raise RuntimeError(
            f"Name collision: '{agent_home}' already exists and is non-empty — "
            "cannot seat a resident agent there. Retry with --no-agent or --citizen @name."
        )

    citizen_result = None
    if citizen:
        # Preview first: a refusal stops the run before adopt writes anything.
        citizen_result = _spawn_adopt_citizen(citizen, target, apply=False)
        if not citizen_result["ok"] and not dry_run:
            raise RuntimeError(f"@spawn adopt-citizen {citizen} refused: {citizen_result['reason']}")

    aipass_home = _detect_aipass_home()
    files: list[str] = []
    rows: list[dict] = []
    notes: list[str] = []

    # First: the target may be a public repo, so nothing AIPass-managed lands before it is ignored.
    gitignore_action = _gitignore_safety(target, dry_run=dry_run)
    gitignore_rows = {
        "created": (CREATE, "absent"),
        "appended": (APPEND, "adds the AIPass local-state block"),
        "already-safe": (SKIP, "already holds the AIPass local-state block"),
    }
    rows.append(_row(".gitignore", *gitignore_rows[gitignore_action]))

    # Minted before spawn: registry-first.
    registry_id = None
    registry_filename = f"{reg}_REGISTRY.json"
    if citizen:
        rows.append(_row(registry_filename, SKIP, f"@spawn adopt-citizen seats it with {citizen}'s ids"))
    else:
        if not dry_run:
            registry_id, registry_filename = _write_registry(target, name)
        files.append(registry_filename)
        rows.append(_row(registry_filename, CREATE, "absent: makes the directory a project"))

    # A half-adopted tree keeps no registry, so a rerun is not refused as already adopted.
    try:
        write = {"dry_run": dry_run, "planned": files, "rows": rows}
        _write_if_missing(target, NAVMAP_REL, navmap_stub(target, reg), **write)
        for rel, content in OWNER_SEEDS:
            _write_if_missing(target, rel, content(), **write)
        hooks_created = False
        if aipass_home:
            kernel_src = Path(aipass_home) / ".aipass" / "tier0_kernel.md"
            if kernel_src.is_file():
                _write_if_missing(target, ".aipass/tier0_kernel.md", kernel_src.read_text(encoding="utf-8"), **write)

            hooks_template = Path(aipass_home) / ".aipass" / "project_hooks.json"
            if hooks_template.is_file():
                hooks_created = not (target / ".aipass" / "hooks.json").exists()
                _write_if_missing(target, ".aipass/hooks.json", hooks_template.read_text(encoding="utf-8"), **write)
                if hooks_created and not dry_run:
                    _enroll_project(target)
        rows.append(_trust_row(hooks_created))

        _write_if_missing(target, "AGENTS.md", agents_md_seed(reg, aipass_home), **write)
        _write_if_missing(target, ".claude/settings.json", _claude_settings(), **write)
        _settings_local(target, aipass_home, write)

        _write_if_missing(target, PREP_SKILL_REL, sc.prep_skill_md(), **write)
        for rel, content in SWITCH_PAIR:
            _write_if_missing(target, rel, content(), **write)
        if shared_skills_state(target)["link"] == LINK_STATE_MISSING:
            note = None if dry_run else link_skills(target)
            notes.extend([note] if note else [])
            files.append(str(target / SKILLS_LINK_REL))
            rows.append(_row(SKILLS_LINK_REL, CREATE, "link to .agents/skills"))

        if aipass_home:
            venv = Path(aipass_home) / ".venv"
            venv_link = target / ".venv"
            if venv.is_dir() and not venv_link.exists():
                if not dry_run:
                    _link_venv(venv_link, venv)
                files.append(str(venv_link))
                rows.append(_row(".venv", CREATE, "link to AIPASS_HOME's venv"))

        # The manifest lets `init update` tell a template change from a project edit; adopt
        # stamps only what it wrote, since the tree's pre-existing files are the project's.
        manifest_file = sm.manifest_path(target)
        if not dry_run:
            written = {rel: h for rel, h in _managed_manifest_entries(target).items() if str(target / rel) in files}
            manifest_file = sm.write_manifest(target, written)
        files.append(str(manifest_file))
        rows.append(_row(manifest_file.relative_to(target).as_posix(), CREATE, "stamps the files adopt wrote"))

        spawn_result = None
        agent_created = False
        if citizen and not dry_run:
            citizen_result = _spawn_adopt_citizen(citizen, target, apply=True)
            if not citizen_result["ok"]:
                raise RuntimeError(f"@spawn adopt-citizen {citizen} --apply refused: {citizen_result['reason']}")
        elif mint and not dry_run:
            spawn_result = _spawn_project_agent(target, name)
            agent_created = True
        elif mint:
            files.append(f"{agent_home} (resident agent — planned)")
        if mint:
            rows.append(_row(agent_home.relative_to(target).as_posix(), CREATE, "fresh resident agent (spawn_agent)"))
    except BaseException:
        if not dry_run and registry_id is not None:
            (target / registry_filename).unlink(missing_ok=True)
        raise

    return {
        "name": name,
        "mode": "framework",
        "target": str(target),
        "dry_run": dry_run,
        "registry_id": registry_id,
        "registry_file": registry_filename,
        "files": files,
        "rows": rows,
        "gitignore_action": gitignore_action,
        "agent_created": agent_created,
        "agent_home": str(agent_home) if mint else None,
        "spawn_result": spawn_result,
        "citizen": citizen_result,
        "notes": notes,
    }


def _settings_local(target: Path, aipass_home: str | None, write: dict) -> None:
    """settings.local.json carries AIPASS_HOME; under <host>/projects/ it also fences the host's AGENTS.md."""
    rel = ".claude/settings.local.json"
    if not aipass_home or is_throwaway_path(aipass_home):
        write["rows"].append(_row(rel, SKIP, "no installed AIPASS_HOME to point at"))
        return
    content = claude_local_settings(aipass_home, nested=is_projects_child(target))
    _write_if_missing(target, rel, content, **write)


def _trust_row(hooks_created: bool) -> dict:
    if hooks_created:
        return _row("trust registry", CREATE, "enrols the project: adopt writes its hooks.json")
    return _row("trust registry", SKIP, "unchanged: an existing hooks.json keeps its enrolment; re-trust after edits")


def _tracked_files(target: Path) -> set[str]:
    """Paths git tracks in *target*; contractor mode cannot tell what it may write without them."""
    git_dir = target / ".git"
    if not git_dir.is_dir() or not any(git_dir.iterdir()):
        raise RuntimeError(
            f"'{target}' has no git repo of its own: contractor mode records its local files in .git/info/exclude."
        )
    try:
        proc = subprocess.run(
            ["git", "-C", str(target), "ls-files", "-z"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Could not list {target}'s tracked files: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"Could not list {target}'s tracked files: {proc.stderr.strip()}")
    return {p for p in proc.stdout.split("\0") if p}


def _adopt_contractor(target: Path, *, no_agent: bool, dry_run: bool, citizen: str | None) -> dict:
    """Local state only: the registry and the hook scaffold, untracked, each listed in .git/info/exclude."""
    if citizen is None and not no_agent:
        raise RuntimeError(
            "Contractor mode seats an existing citizen (--citizen @name) or none (--no-agent): a fresh "
            "resident would land in src/<pkg>/<pkg>, inside the project's own source and image."
        )
    tracked = _tracked_files(target)
    aipass_home = _detect_aipass_home()
    name = target.name
    reg = _registry_name(name)
    registry_filename = f"{reg}_REGISTRY.json"
    rows: list[dict] = []
    writes: list[tuple[Path, str]] = []
    excludes: list[str] = []

    def plan(rel: str, content, why: str) -> None:
        """Row one local path: clash when tracked, skip when present, else create and exclude it."""
        if rel in tracked:
            rows.append(_row(rel, CLASH, _TRACKED))
        elif (target / rel).exists():
            rows.append(_row(rel, SKIP, "present, untracked: kept as it is"))
        else:
            rows.append(_row(rel, CREATE, why))
            writes.append((target / rel, content()))
            excludes.append(f"/{rel}")

    if citizen:
        rows.append(_row(registry_filename, SKIP, f"@spawn adopt-citizen seats it with {citizen}'s ids"))
    else:
        rows.append(_row(registry_filename, CREATE, "makes the directory a project: drone and the edit gate find it"))
        excludes += [f"/{registry_filename}", f"/.{reg}_REGISTRY.lock"]

    templates = Path(aipass_home) / ".aipass" if aipass_home else None
    kernel = templates / "tier0_kernel.md" if templates else None
    hooks = templates / "project_hooks.json" if templates else None
    if kernel and kernel.is_file():
        plan(".aipass/tier0_kernel.md", lambda: kernel.read_text(encoding="utf-8"), "the kernel the prompt hook reads")
    plan(NAVMAP_REL, lambda: navmap_stub(target, reg), "the roster the prompt hook injects")
    hooks_created = False
    if hooks and hooks.is_file():
        plan(".aipass/hooks.json", lambda: hooks.read_text(encoding="utf-8"), "the hook engine's project config")
        hooks_created = rows[-1]["action"] == CREATE
    if aipass_home and not is_throwaway_path(aipass_home):
        settings = claude_local_settings(aipass_home, nested=is_projects_child(target))
        plan(".claude/settings.local.json", lambda: settings, "AIPASS_HOME for sessions opened here")
    else:
        rows.append(_row(".claude/settings.local.json", SKIP, "no installed AIPASS_HOME to point at"))

    named = {row["path"] for row in rows}
    for rel in sorted(tracked - named):
        if rel.startswith(".aipass/") or rel.endswith("_REGISTRY.json") or rel == ".updateignore":
            rows.append(_row(rel, CLASH, "a tracked AIPass file: contractor mode leaves no AIPass file tracked"))
    rows.append(_trust_row(hooks_created))
    for rel in (".gitignore", "AGENTS.md"):
        state = "tracked, the project's own" if rel in tracked else "contractor mode does not write it"
        rows.append(_row(rel, SKIP, state))

    exclude = target / ".git" / "info" / "exclude"
    current = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    new_lines = [line for line in excludes if line not in current.splitlines()]
    if new_lines:
        rows.append(_row(".git/info/exclude", APPEND, "lists " + ", ".join(new_lines)))
    else:
        rows.append(_row(".git/info/exclude", SKIP, "nothing new to list"))

    citizen_result = _spawn_adopt_citizen(citizen, target, apply=False) if citizen else None
    clashes = [row["path"] for row in rows if row["action"] == CLASH]
    registry_id = None
    if not dry_run:
        if clashes:
            raise RuntimeError(
                f"Contractor mode refuses: {len(clashes)} tracked AIPass file(s) clash: {', '.join(clashes)}. "
                "Untrack them first; nothing was written."
            )
        if citizen_result and not citizen_result["ok"]:
            raise RuntimeError(f"@spawn adopt-citizen {citizen} refused: {citizen_result['reason']}")
        if not citizen:
            registry_id, registry_filename = _write_registry(target, name)
        for path, content in writes:
            path.parent.mkdir(parents=True, exist_ok=True)
            sm.write_text_lf(path, content)
        if new_lines:
            exclude.parent.mkdir(parents=True, exist_ok=True)
            head = current if current.endswith("\n") or not current else current + "\n"
            sm.write_text_lf(exclude, head + "".join(f"{line}\n" for line in new_lines))
        if hooks_created:
            _enroll_project(target)
        if citizen:
            citizen_result = _spawn_adopt_citizen(citizen, target, apply=True)
            if not citizen_result["ok"]:
                raise RuntimeError(
                    f"@spawn adopt-citizen {citizen} --apply refused after adopt's local writes: "
                    f"{citizen_result['reason']}"
                )

    return {
        "name": name,
        "mode": "contractor",
        "target": str(target),
        "dry_run": dry_run,
        "registry_id": registry_id,
        "registry_file": registry_filename,
        "files": [str(path) for path, _ in writes],
        "rows": rows,
        "gitignore_action": "untouched",
        "agent_created": False,
        "agent_home": None,
        "spawn_result": None,
        "citizen": citizen_result,
        "notes": [],
    }
