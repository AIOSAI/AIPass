# =================== AIPass ====================
# Name: scaffold_manifest.py
# Description: Scaffold manifest + the conffile rule that decides what an update may overwrite
# Version: 1.0.0
# Created: 2026-09-09
# Modified: 2026-09-09
# =============================================

"""Scaffold manifest — which AIPass version wrote which file, and its hash.

WHY THIS FILE EXISTS. ``update_project`` used to overwrite every managed file
whose content differed from the template, which cannot tell "the template moved
on" from "the project edited this file". The live case that forced it: Vera
replaced Vera-Studio's ``tier1_navmap.md`` with the studio's own map, and an
update would have silently put AIPass's roster map back (DPLAN-0334/0335).

THE CONFFILE RULE, named after dpkg's. A managed file is overwritten only when
nobody has touched it since AIPass wrote it -- proven by its hash still matching
the manifest -- or when it is absent. Otherwise it is KEPT and the template is
written beside it as ``<name>.aipass-new`` for the manager to diff.

THE MANIFEST IS A CONTRACT, NOT A CACHE. ``@hooks``' ``release_notice`` handler
reads ``aipass_version`` out of it to decide whether a project is behind, so the
three keys below are fixed by DPLAN-0335 and may not be renamed without telling
them. Anything else in the document is ignored by both readers.

RULES (inherited from bootstrap.py): pure Python, no module/prax/cli imports.
"""

import fnmatch
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

#: Where the manifest lives inside a project. Tracked on purpose -- it is the
#: record of what AIPass wrote, so it belongs in the project's history.
MANIFEST_REL: Path = Path(".aipass") / "scaffold_manifest.json"

#: Suffix for the template written beside a file the project has edited.
NEW_SUFFIX: str = ".aipass-new"

#: Backup root inside the project. One timestamped directory per apply.
BACKUP_REL: Path = Path(".aipass") / ".backup"

#: Files created once and NEVER rewritten. They exist to be filled in by the
#: project, so a template refresh would delete the manager's actual content.
#: Deliberately NOT the same list as the managed files -- a seed is scaffolding
#: that stops being ours the moment it is written.
SEED_FILES: tuple = ("CLAUDE.md", "AGENTS.md")

#: Hook handlers retired from the framework. The union merge in
#: ``_merge_hooks_json`` can add a handler but never remove one, so a handler
#: dropped from the template lives on in every project that already had it.
#: This list is the removal side, applied on update and reported.
RETIRED_HOOK_HANDLERS: tuple = ("auto_watchdog",)

#: Owner-owned ignore file at the project root. AIPass never creates or edits
#: it -- it exists so a project can say "this file is mine now" up front,
#: rather than discovering after the fact that an update wanted it.
IGNORE_NAME: str = ".updateignore"

#: Plan verdicts. A file carries exactly one.
ACTION_CREATE: str = "create"
ACTION_UPDATE: str = "update"
ACTION_CURRENT: str = "current"
ACTION_KEPT_LOCAL: str = "kept-local"
ACTION_RETIRE: str = "retire"
ACTION_SKIPPED: str = "skipped"

#: Verdicts that mean "something would be written". ``current`` and ``skipped``
#: are the two that are not pending; ``kept-local`` IS pending, because the
#: apply writes a ``.aipass-new`` sidecar the manager has to look at.
PENDING_ACTIONS: frozenset = frozenset({ACTION_CREATE, ACTION_UPDATE, ACTION_KEPT_LOCAL, ACTION_RETIRE})


# =============================================================================
# HASHING
# =============================================================================


def sha256_text(text: str) -> str:
    """Hash text as UTF-8 bytes.

    THE MANIFEST HASHES BYTES WRITTEN, NOT STRINGS COMPARED. Every managed file
    is written with ``encoding="utf-8"``, so hashing the encoded form is the
    only spelling that matches what lands on disk.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_file(path: Path) -> str | None:
    """Hash a file's bytes, or None when it is absent or unreadable.

    UNREADABLE READS AS ABSENT ON PURPOSE. The caller's next move for both is
    the same -- it cannot prove the project left the file alone -- and a raise
    here would turn a permissions oddity into a failed update.
    """
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError) as exc:
        logger.info("[scaffold] unreadable, treating as absent: %s (%s)", path, exc)
        return None


# =============================================================================
# VERSION
# =============================================================================


def installed_version() -> str:
    """The AIPass version running right now, or 'unknown' if it cannot be read.

    Imported lazily: this handler is stdlib-only by contract, and a scaffold
    plan must still compute on a tree where the package will not import.
    """
    try:
        import aipass

        return str(getattr(aipass, "__version__", "unknown"))
    except Exception as exc:  # pragma: no cover - defensive, package always imports here
        logger.info("[scaffold] version unreadable: %s", exc)
        return "unknown"


# =============================================================================
# MANIFEST I/O
# =============================================================================


def manifest_path(target: Path) -> Path:
    """Absolute path to *target*'s scaffold manifest."""
    return Path(target) / MANIFEST_REL


def read_manifest(target: Path) -> dict:
    """Read the manifest, or an empty document when absent or unparseable.

    A CORRUPT MANIFEST MUST READ AS ABSENT, NOT AS EMPTY-BUT-VALID. Both return
    ``{}`` here, and that is the safe direction: with no recorded hash every
    managed file falls to the backfill arm, where anything differing from the
    template is KEPT rather than overwritten.
    """
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


def stamped_version(target: Path) -> str | None:
    """The AIPass version recorded in *target*'s manifest, or None."""
    version = read_manifest(target).get("aipass_version")
    return str(version) if isinstance(version, str) else None


def write_manifest(target: Path, files: dict, version: str | None = None) -> Path:
    """Write the manifest recording *files* and the version that wrote them.

    Args:
        target: Project root.
        files: ``rel path (posix) -> sha256`` for every managed file ON DISK.
        version: Override for the stamped version; defaults to the installed one.

    Returns:
        The manifest path.
    """
    path = manifest_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "aipass_version": version or installed_version(),
        "stamped_at": datetime.now(timezone.utc).isoformat(),
        "files": {key: files[key] for key in sorted(files)},
    }
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# =============================================================================
# THE CONFFILE RULE
# =============================================================================


def decide(rel: str, current: str | None, template: str | None, recorded: str | None) -> tuple:
    """Decide what an update may do to one managed file.

    Args:
        rel: Path relative to the project root, for the reason string.
        current: sha256 of the file on disk, or None when absent.
        template: sha256 of the content the template would write, or None when
            the template is unavailable (no AIPASS_HOME, missing source file).
        recorded: sha256 the manifest says AIPass last wrote, or None.

    Returns:
        ``(action, reason)``.

    THE ORDER OF THE ARMS IS THE RULE. Absent is decided before provenance,
    because a file that is not there cannot have been edited. Provenance is
    decided before content, because "the project changed it" outranks "the
    template moved on" -- getting those two the other way round is exactly the
    bug that would have overwritten Vera's navmap.
    """
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
    # Backfill: no manifest entry, so provenance is unknown.
    if current == template:
        return ACTION_CURRENT, "matches template (adopted into manifest)"
    return ACTION_KEPT_LOCAL, "unknown provenance"


def read_ignore(target: Path) -> list:
    """Patterns from *target*'s ``.updateignore``, or [] when it is absent.

    Same fashion as ``.gitignore`` and ``.backupignore``: one pattern per line,
    ``#`` comments, blank lines ignored. Negation (``!``) is deliberately not in
    v1 -- an ignore file whose meaning depends on line order is a support
    burden, and nobody has asked for it yet.
    """
    path = Path(target) / IGNORE_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("[scaffold] %s unreadable, ignoring: %s", path, exc)
        return []
    patterns = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            patterns.append(stripped)
    return patterns


def is_ignored(rel: str, patterns: list) -> bool:
    """True when *rel* (a posix path relative to the project root) is owner-protected.

    A trailing slash means a directory and everything under it. A pattern with
    no slash also matches a bare filename at any depth, which is what a manager
    writing ``tier1_navmap.md`` means -- requiring the full ``.aipass/`` prefix
    for the common case would make the file a trap.
    """
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

    RENAME, NEVER UNLINK (Patrick, DPLAN-0264): a retired file the manager can
    still see is a decision they can reverse; a deleted one is a surprise.
    """
    return path.with_name(f"{path.stem}(disabled){path.suffix}")


def retired_handlers_in(hooks: dict) -> list:
    """Retired handler names present in a project's hooks document, sorted.

    Returns ``event.handler`` strings so a report names where each one sits --
    one handler can be wired under more than one event.
    """
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
