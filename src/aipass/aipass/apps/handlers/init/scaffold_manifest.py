# =================== AIPass ====================
# Name: scaffold_manifest.py
# Description: Scaffold manifest + the conffile rule that decides what an update may overwrite
# Version: 1.1.0
# Created: 2026-09-09
# Modified: 2026-10-27
# =============================================

"""Scaffold manifest: which AIPass version wrote which file, and its hash. Conffile rule (dpkg's):
overwrite a managed file only when absent or unedited, else write ``<name>.aipass-new`` beside it.
Keys are a contract (@hooks release_notice reads ``aipass_version``); pure Python, bootstrap imports it."""

import fnmatch
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

MANIFEST_REL: Path = Path(".aipass") / "scaffold_manifest.json"

NEW_SUFFIX: str = ".aipass-new"

BACKUP_REL: Path = Path(".aipass") / ".backup"

#: Set by every writer since AGENTS.md left the seeds: before it, an update adopted an edited AGENTS.md's
#: hash, so a manifest without it holds no AGENTS.md hash an overwrite may trust.
AGENTS_MANAGED_KEY: str = "agents_md_managed"

#: ``_merge_hooks_json`` only adds handlers; this list is the removal side.
RETIRED_HOOK_HANDLERS: tuple = ("auto_watchdog",)

IGNORE_NAME: str = ".updateignore"


class UpdateIgnoreUnreadable(Exception):
    """The project's ``.updateignore`` is there but cannot be read.

    Not the same as no file: reading the claim as empty would overwrite claimed files."""


ACTION_CREATE: str = "create"
ACTION_UPDATE: str = "update"
ACTION_CURRENT: str = "current"
ACTION_KEPT_LOCAL: str = "kept-local"
ACTION_RETIRE: str = "retire"
ACTION_SKIPPED: str = "skipped"

# No PENDING_ACTIONS set: a kept-local verdict may write nothing; count queued writes.


def sha256_text(text: str) -> str:
    """Hash text as UTF-8 bytes."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_text_lf(path: Path, content: str) -> None:
    """Write a scaffold file with LF endings on every platform.

    The one writer for managed files: Windows' default CRLF makes the manifest hash never match."""
    path.write_text(content, encoding="utf-8", newline="\n")


def hash_file(path: Path) -> str | None:
    """Hash a file's bytes, or None when it is absent or unreadable."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError) as exc:
        logger.info("[scaffold] unreadable, treating as absent: %s (%s)", path, exc)
        return None


def installed_version() -> str:
    """The AIPass version running right now, or 'unknown' if it cannot be read.

    Imported lazily: the plan must still compute where the package will not import."""
    try:
        import aipass

        return str(getattr(aipass, "__version__", "unknown"))
    except Exception as exc:  # pragma: no cover - defensive, package always imports here
        logger.info("[scaffold] version unreadable: %s", exc)
        return "unknown"


def manifest_path(target: Path) -> Path:
    """Absolute path to *target*'s scaffold manifest."""
    return Path(target) / MANIFEST_REL


def read_manifest(target: Path) -> dict:
    """Read the manifest, or an empty document when absent or unparseable.

    Corrupt reads as absent: with no recorded hash, a differing file is kept, never overwritten."""
    path = manifest_path(target)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.info("[scaffold] manifest unreadable, treating as absent: %s (%s)", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def manifest_hashes(target: Path) -> dict:
    """The recorded ``rel path -> sha256`` map, empty when there is no manifest."""
    files = read_manifest(target).get("files")
    return files if isinstance(files, dict) else {}


def trusted_hashes(target: Path) -> dict:
    """``manifest_hashes`` minus an AGENTS.md hash a pre-managed manifest recorded, which may be the owner's edit."""
    files = dict(manifest_hashes(target))
    if not read_manifest(target).get(AGENTS_MANAGED_KEY):
        files.pop("AGENTS.md", None)
    return files


def stamped_version(target: Path) -> str | None:
    """The AIPass version recorded in *target*'s manifest, or None."""
    version = read_manifest(target).get("aipass_version")
    return str(version) if isinstance(version, str) else None


def write_manifest(target: Path, files: dict, version: str | None = None) -> Path:
    """Write the manifest recording *files* and the version that wrote them."""
    path = manifest_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "aipass_version": version or installed_version(),
        "stamped_at": datetime.now(timezone.utc).isoformat(),
        AGENTS_MANAGED_KEY: True,
        "files": {key: files[key] for key in sorted(files)},
    }
    write_text_lf(path, json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    return path


def decide(current: str | None, template: str | None, recorded: str | None) -> tuple:
    """Decide what an update may do to one managed file.

    Arm order is the rule: absent, provenance, content; swapping the last two overwrites edits."""
    if template is None:
        return ACTION_CURRENT, "no template available - nothing to compare"
    if current is None:
        return ACTION_CREATE, "absent"
    if recorded is not None:
        if current == recorded:
            if current == template:
                return ACTION_CURRENT, "matches template"
            return ACTION_UPDATE, "unmodified since AIPass wrote it"
        return ACTION_KEPT_LOCAL, "local edits"
    if current == template:
        return ACTION_CURRENT, "matches template (adopted into manifest)"
    return ACTION_KEPT_LOCAL, "unknown provenance"


def read_ignore(target: Path) -> list:
    """Patterns from *target*'s ``.updateignore``, or [] when it is absent."""
    path = Path(target) / IGNORE_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("[scaffold] %s is there but cannot be read: %s", path, exc)
        raise UpdateIgnoreUnreadable(f"{path} is there but cannot be read ({exc}); fix or remove it") from exc
    patterns = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            patterns.append(stripped)
    return patterns


def is_ignored(rel: str, patterns: list) -> bool:
    """True when *rel* (a posix path relative to the project root) is owner-protected.

    A slashless pattern matches a bare filename at any depth, as a manager means it."""
    name = rel.rsplit("/", 1)[-1]
    for pattern in patterns:
        if pattern.endswith("/"):
            prefix = pattern.rstrip("/")
            if rel == prefix or rel.startswith(prefix + "/") or fnmatch.fnmatch(rel, prefix + "/*"):
                return True
            continue
        if fnmatch.fnmatch(rel, pattern):
            return True
        if "/" not in pattern and fnmatch.fnmatch(name, pattern):
            return True
    return False


def sidecar_path(path: Path) -> Path:
    """Where the template goes when a file is kept because it was edited."""
    return path.with_name(path.name + NEW_SUFFIX)


def disabled_path(path: Path) -> Path:
    """Where a retired managed file is renamed to.

    Rename, never unlink: a retired file the manager can still see is reversible."""
    return path.with_name(f"{path.stem}(disabled){path.suffix}")


def retired_handlers_in(hooks: dict) -> list:
    """Retired handler names present in a project's hooks document, sorted."""
    found: list = []
    for event, handlers in hooks.items():
        if not isinstance(handlers, dict):
            continue
        for name in handlers:
            if name in RETIRED_HOOK_HANDLERS:
                found.append(f"{event}.{name}")
    return sorted(found)


def prune_retired(hooks: dict) -> dict:
    """Return *hooks* without any retired handler. Events left empty are dropped."""
    pruned: dict = {}
    for event, handlers in hooks.items():
        if not isinstance(handlers, dict):
            pruned[event] = handlers
            continue
        kept = {name: data for name, data in handlers.items() if name not in RETIRED_HOOK_HANDLERS}
        if kept:
            pruned[event] = kept
    return pruned
