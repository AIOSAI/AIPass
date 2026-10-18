# =================== AIPass ====================
# Name: loader.py
# Version: 2.1.0
# Description: Hook config loader — the AIPass config from AIPASS_HOME, a project's own behind trust, gates always
# Branch: hooks
# Layer: apps/handlers/config
# Created: 2026-05-19
# Modified: 2026-10-17
# =============================================

"""Which hook config a session runs. Security never depends on trust (DPLAN-0356 item 1).

Reference: docs/project_config.md
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from aipass.hooks.apps.handlers.config import gates
from aipass.hooks.apps.handlers.module_root import module_file
from aipass.prax.apps.modules.logger import system_logger as logger

_GUARD_DIR = Path(tempfile.gettempdir())
_CONFIG = Path(".aipass") / "hooks.json"
_PROJECT_MARKER = "*_REGISTRY.json"

AIPASS = "aipass"
EXTERNAL = "external"
NONE = "none"


def _search_bounds() -> tuple[Path, Path]:
    """Where the walk for .aipass/hooks.json starts (the working directory) and stops (home).

    A seam: tests replace it by name instead of patching Path.cwd and Path.home process-wide.
    """
    return Path.cwd(), Path.home()


def _absolute(raw: str) -> Path:
    path = Path(raw)
    try:
        return path.resolve()
    except OSError as exc:  # resolve() reads the cwd on Windows; the spelling is still the place
        logger.info("[HOOKS] loader: cannot resolve %s, using it as spelled: %s", raw, exc)
        return path


def aipass_home() -> Path | None:
    """The AIPass install: $AIPASS_HOME, else the repo this code was loaded from, else None.

    Read per call so a test's environment patch is honoured.
    """
    raw = os.environ.get("AIPASS_HOME", "")
    if raw:
        return _absolute(raw)
    here = module_file(__file__)
    if len(here.parents) > 6:
        root = here.parents[6]
        if (root / _CONFIG).is_file() and (root / "src" / "aipass").is_dir():
            return root
    return None


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _is_project_root(directory: Path) -> bool:
    """A nested project marks its root with a registry, as write_ownership and @ai_mail read it."""
    try:
        return any(directory.glob(_PROJECT_MARKER))
    except OSError as exc:
        logger.info("[HOOKS] loader: project marker scan failed at %s: %s", directory, exc)
        return False


def locate_config() -> tuple[str, Path | None]:
    """Where this session's config comes from: (AIPASS | EXTERNAL | NONE, the directory holding .aipass/)."""
    home = aipass_home()
    # One canonical form, like home and the trust registry's keys: a symlinked walk (macOS /var) reads as external.
    search, stop = (_absolute(str(bound)) for bound in _search_bounds())
    start = search
    while search != stop and search.parent != search:
        if (search / _CONFIG).exists():
            if home is not None and search == home:
                return AIPASS, home
            if home is not None and _inside(search, home) and not _is_project_root(search):
                logger.warning(
                    "[HOOKS] loader: IGNORED %s — inside AIPass only %s configures hooks",
                    search / _CONFIG,
                    home / _CONFIG,
                )
            else:
                return EXTERNAL, search
        search = search.parent
    if home is not None and _inside(start, home) and (home / _CONFIG).exists():
        return AIPASS, home
    return NONE, None


def _read_config(config_file: Path) -> dict:
    """Parse one hooks.json, $AIPASS_HOME substituted."""
    raw = config_file.read_text(encoding="utf-8")
    home = os.environ.get("AIPASS_HOME", "")
    if home:
        raw = raw.replace("$AIPASS_HOME", home)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"{config_file} is not a JSON object")
    parsed["_source"] = "project"
    return parsed


def gate_set() -> dict:
    """The AIPass gate set: the gate entries of AIPASS_HOME's config, else the built-in set, loudly."""
    home = aipass_home()
    if home is not None:
        try:
            found = gates.gate_config(_read_config(home / _CONFIG))
            if gates.has_gates(found):
                found["_source"] = "project"
                return found
            logger.error("[HOOKS] loader: %s names no gate — the built-in gate set runs", home / _CONFIG)
        except (OSError, ValueError) as exc:
            logger.error("[HOOKS] loader: AIPass config unreadable (%s) — the built-in gate set runs", exc)
    return gates.builtin_config()


def find_project_config() -> dict | None:
    """The config this session's own site supplies, or None when it supplies nothing usable.

    None means fall back to the gate set (:func:`resolve_config` does), never "no hooks".
    """
    from aipass.hooks.apps.handlers.config.trust_registry import (
        bootstrap,
        is_trusted,
        registry_path,
    )

    kind, where = locate_config()
    if where is None:
        return None
    config_file = where / _CONFIG
    if kind == EXTERNAL:
        if not registry_path().exists():
            bootstrap()
        if not is_trusted(str(where)):
            logger.warning(
                "[HOOKS] project not enrolled in trust registry: %s (its own hooks are off; the AIPass gates run)",
                where,
            )
            return None
    config: dict | None = None
    try:
        config = _read_config(config_file)
    except (OSError, ValueError) as exc:  # unreadable is "nothing usable": the gate set serves, loudly
        logger.error("[HOOKS] bad config %s: %s", config_file, exc)
    if config is None:
        return None
    home = aipass_home()
    if kind == EXTERNAL and home is not None and _inside(where, home):
        return gates.enforce(config, gate_set())
    if kind == AIPASS and not gates.has_gates(config):
        # A root edit that drops every gate must not run ungated.
        logger.error("[HOOKS] loader: %s names no gate — the built-in gates are forced over it", config_file)
        return gates.enforce(config, gates.builtin_config())
    return config


def resolve_config() -> dict:
    """The config a hook call runs: the site's own (find_project_config), else the gate set. Never empty of gates."""
    config = find_project_config()
    if config is not None:
        return config
    return gate_set()


def config_unavailable_reason() -> str:
    """Explain truthfully why find_project_config() returned None.

    find_project_config() returns the same bare None for every refusal, so a CLI surface asks here.
    """
    from aipass.hooks.apps.handlers.config.trust_registry import (
        is_hash_mismatch,
        is_unenrolled,
    )

    tail = " The AIPass gate set still runs."
    kind, where = locate_config()
    if where is None:
        return "No .aipass/hooks.json found — run from an AIPass project directory." + tail
    config_file = where / _CONFIG
    if kind == EXTERNAL and is_unenrolled(str(where)):
        return (
            f"{config_file} exists, but this project is not enrolled in the trust "
            f"registry — the trust gate refused its own hooks.{tail}\n"
            f"Fix: aipass trust {where}"
        )
    if kind == EXTERNAL and is_hash_mismatch(str(where)):
        return (
            f"{config_file} has changed since it was enrolled in the trust registry "
            f"— the trust gate refused its own hooks.{tail}\n"
            f"Fix (re-enroll): aipass trust {where}"
        )
    return f"{config_file} could not be read or parsed — see the [HOOKS] error in the engine log.{tail}"


def trust_break_banner() -> str | None:
    """Loud check for an external project whose enrolled config has changed since enrolment.

    Only an EXTERNAL project's config answers to trust; an AIPASS_HOME edit raises no banner.
    Never-enrolled returns None: normal first-run state, not a break.
    """
    from aipass.hooks.apps.handlers.config.trust_registry import is_hash_mismatch

    kind, where = locate_config()
    if kind != EXTERNAL or where is None or not is_hash_mismatch(str(where)):
        return None
    return (
        "# TRUST BREAK — THIS PROJECT'S OWN HOOKS ARE OFF\n\n"
        f"{where}/.aipass/hooks.json no longer matches its enrolled hash, so the hooks it "
        "configures are skipped until a human re-enrolls. The AIPass gate set still runs.\n\n"
        f"Fix (re-enroll): aipass trust {where}\n"
        "This does not auto-heal — re-enrollment is a deliberate human "
        "checkpoint, not a bug."
    )


def _nudge_guard_path(session_id: str, project_path: str) -> Path | None:
    """Guard-file path for the one-time never-enrolled nudge, keyed by session + project."""
    if not session_id:
        return None
    slug = hashlib.sha256(project_path.encode()).hexdigest()[:16]
    return _GUARD_DIR / f"aipass-never-enrolled-{session_id}-{slug}"


def _already_nudged(session_id: str, project_path: str) -> bool:
    path = _nudge_guard_path(session_id, project_path)
    return path is not None and path.exists()


def _mark_nudged(session_id: str, project_path: str) -> None:
    path = _nudge_guard_path(session_id, project_path)
    if path is not None:
        try:
            path.touch()
        except OSError as exc:
            logger.info("[HOOKS] never_enrolled_banner: guard write failed: %s", exc)


def never_enrolled_banner(session_id: str = "") -> str | None:
    """One-time-per-session nudge for an external project that was simply never enrolled.

    Never-enrolled is first-run state, not a break: one nudge per session, where trust_break_banner nags by design.
    """
    from aipass.hooks.apps.handlers.config.trust_registry import is_unenrolled

    kind, where = locate_config()
    if kind != EXTERNAL or where is None:
        return None
    project_path = str(where)
    if not is_unenrolled(project_path) or _already_nudged(session_id, project_path):
        return None
    _mark_nudged(session_id, project_path)
    return (
        "# THIS PROJECT'S OWN HOOKS ARE OFF — not yet enrolled\n\n"
        f"{project_path}/.aipass/hooks.json exists, but this project has never "
        "been enrolled in the trust registry, so the hooks it configures do not run "
        "(identity injection, prompts, and everything else it adds). The AIPass gate "
        "set still runs.\n\n"
        "Fix: aipass init update\n"
        "One-time nudge for this session — enrollment stays a deliberate "
        "human action, not something that auto-heals."
    )
