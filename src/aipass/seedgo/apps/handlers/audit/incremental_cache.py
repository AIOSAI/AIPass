# =================== AIPass ====================
# Name: incremental_cache.py
# Description: Audit Fingerprint Cache Handler
# Version: 1.3.1
# Created: 2026-07-31
# Modified: 2026-10-24
# =============================================

"""
Audit Fingerprint Cache Handler

One file per cache key so concurrent runs on different branches cannot clobber each other.
Fail-open: any read/schema problem returns {} and the caller runs a full audit.
"""

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file

# Bump when the stamp algorithm or branch_audit's corpus changes: no stamp covers either.
CACHE_VERSION = "3"
# Bump when the on-disk doc shape changes; a container-only change migrates, not busts.
SCHEMA_VERSION = 2
_JSON_DIR = json_handler.get_json_path("audit", "data").parent

CACHE_DIR = _JSON_DIR / "audit_cache"

LEGACY_CACHE_FILE = _JSON_DIR / "audit_cache.json"

# Outside the pack yet decide audit output: unstamped, a semantics change serves stale green.
MACHINERY_DIRS: Tuple[Path, ...] = (
    module_file(__file__).parent,
    module_file(__file__).parent.parent / "bypass",
    module_file(__file__).parent.parent / "test_map",
)
# Inside the default pack (already stamped there) but they shape every other pack's output too.
MACHINERY_FILES: Tuple[Path, ...] = (
    module_file(__file__).parent.parent / "aipass_standards" / "applicability.py",
    module_file(__file__).parent.parent / "aipass_standards" / "skip_dirs.py",
)


_PRESENCE_FINGERPRINT: List[int] = [0, 0]


def fingerprint_file(path: Path) -> List[int]:
    """Return [mtime_ns, size] for a file. [-1, -1] if it can't be stat'd."""
    try:
        st = path.stat()
    except OSError as e:
        logger.info("[incremental_cache] Cannot stat %s: %s", path, e)
        return [-1, -1]
    return [st.st_mtime_ns, st.st_size]


def collect_fingerprints(files: List[Dict[str, str]]) -> Dict[str, List[int]]:
    """Map each file dict's 'rel' key to its fingerprint.

    ``presence_only`` entries get a constant fingerprint: add/delete still bust, content churn does not.
    """
    return {
        fi["rel"]: _PRESENCE_FINGERPRINT if fi.get("presence_only") else fingerprint_file(Path(fi["file"]))
        for fi in files
    }


def diff_fileset(cached: Dict[str, List[int]], current: Dict[str, List[int]]) -> Tuple[set, set, set, set]:
    """Return (added, changed, deleted, unchanged) relpath sets."""
    cached_keys, current_keys = set(cached), set(current)
    added = current_keys - cached_keys
    deleted = cached_keys - current_keys
    common = cached_keys & current_keys
    changed = {rel for rel in common if cached[rel] != current[rel]}
    unchanged = common - changed
    return added, changed, deleted, unchanged


# Consumed only by standards_query (no cache); fingerprinting them re-scans the fleet per wording fix.
_UNREAD_BY_AUDIT: Tuple[str, ...] = ("*.md", "*_content.py")


def _is_unread_by_audit(path: Path) -> bool:
    """True for a pack file whose bytes cannot reach audit output."""
    return any(path.match(pattern) for pattern in _UNREAD_BY_AUDIT)


def compute_pack_stamp(pack_path: Path, diag_path: Path | None = None) -> str:
    """Fingerprint the pack's SHARED inputs — everything except the checkers themselves."""
    entries = []
    if pack_path.exists():
        for cf in sorted(pack_path.rglob("*")):
            if not cf.is_file() or "__pycache__" in cf.parts:
                continue
            if cf.name.endswith("_check.py") or _is_unread_by_audit(cf):
                continue
            fp = fingerprint_file(cf)
            entries.append([cf.relative_to(pack_path).as_posix(), fp[0], fp[1]])
    if diag_path is not None and diag_path.exists():
        fp = fingerprint_file(diag_path)
        entries.append([diag_path.name, fp[0], fp[1]])
    return hashlib.sha1(json.dumps(entries).encode("utf-8")).hexdigest()


def compute_checker_stamps(pack_path: Path) -> Dict[str, str]:
    """Fingerprint every checker file on its own: {checker name: stamp}.

    The key must match branch_audit.discover_checkers()'s key (stem minus ``_check``).
    """
    stamps: Dict[str, str] = {}
    if not pack_path.exists():
        return stamps
    for cf in sorted(pack_path.glob("*_check.py")):
        fp = fingerprint_file(cf)
        payload = json.dumps([cf.name, fp[0], fp[1]]).encode("utf-8")
        stamps[cf.stem.removesuffix("_check")] = hashlib.sha1(payload).hexdigest()
    return stamps


def stale_checkers(cached: Dict[str, str], current: Dict[str, str]) -> set:
    """Checker names whose cached results can no longer be served.

    Removed names are stale too, so a checker that returns is not served its predecessor's results.
    """
    return {name for name in set(cached) | set(current) if cached.get(name) != current.get(name)}


def compute_bypass_stamp(branch_path: Path) -> str:
    """Fingerprint .seedgo/bypass.json + every .seedgoignore file in the branch."""
    entries = []
    bypass_file = branch_path / ".seedgo" / "bypass.json"
    if bypass_file.exists():
        fp = fingerprint_file(bypass_file)
        entries.append(["bypass.json", fp[0], fp[1]])
    for ig in sorted(branch_path.rglob(".seedgoignore")):
        fp = fingerprint_file(ig)
        entries.append([ig.relative_to(branch_path).as_posix(), fp[0], fp[1]])
    return hashlib.sha1(json.dumps(entries).encode("utf-8")).hexdigest()


def compute_machinery_stamp() -> str:
    """Fingerprint the audit/, bypass/ and test_map/ packages plus MACHINERY_FILES — the code that decides results."""
    entries = []
    for directory in MACHINERY_DIRS:
        if not directory.exists():
            continue
        for f in sorted(directory.rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            fp = fingerprint_file(f)
            entries.append([f"{directory.name}/{f.relative_to(directory).as_posix()}", fp[0], fp[1]])
    for f in MACHINERY_FILES:
        fp = fingerprint_file(f)
        entries.append([f.name, fp[0], fp[1]])
    return hashlib.sha1(json.dumps(entries).encode("utf-8")).hexdigest()


def current_stamp(branch_path: Path, pack_path: Path, diag_path: Path | None = None, no_bypass: bool = False) -> str:
    """Combined whole-branch stamp: cache version + shared pack + audit machinery + bypass/ignore rules."""
    # no_bypass is stamped: bypass.json is unchanged by --no-bypass, so the two runs would share a score.
    combined = (
        f"{CACHE_VERSION}:{compute_pack_stamp(pack_path, diag_path)}"
        f":{compute_machinery_stamp()}:{compute_bypass_stamp(branch_path)}"
        f":{'rules-suppressed' if no_bypass else 'rules-applied'}"
    )
    return hashlib.sha1(combined.encode("utf-8")).hexdigest()


#: Cache keys hold "::" and "="; ":" is illegal in Windows filenames.
_UNSAFE_IN_FILENAME = re.compile(r"[^A-Za-z0-9._-]")

_WINDOWS_RESERVED_STEMS: frozenset[str] = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{n}" for n in range(1, 10)} | {f"LPT{n}" for n in range(1, 10)}
)


def entry_filename(cache_key: str) -> str:
    """The file one cache key lives in, spelled safely for every host."""
    # The exact-key digest separates "a::b"/"a=b" and "BACKUP"/"backup" (case-insensitive hosts).
    stem = _UNSAFE_IN_FILENAME.sub("_", cache_key)
    if stem.split(".")[0].upper() in _WINDOWS_RESERVED_STEMS:
        stem = f"_{stem}"
    return f"{stem}.{hashlib.sha1(cache_key.encode('utf-8')).hexdigest()[:10]}.json"


def entry_path(cache_key: str) -> Path:
    """Where one cache key's entry is stored."""
    return CACHE_DIR / entry_filename(cache_key)


def atomic_write(path: Path, doc: Dict[str, Any]) -> None:
    """Write one JSON doc through a staging file (write-tmp-then-os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False, default=str)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        # finally, not except: KeyboardInterrupt must not leave the staging file.
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError as cleanup_err:
                logger.warning("[incremental_cache] Failed to clean up temp file %s: %s", tmp, cleanup_err)


def _retire_legacy_cache() -> None:
    """Rename the flat doc beside itself, timestamped. Never deleted."""
    retired = LEGACY_CACHE_FILE.with_name(f"audit_cache.retired-{time.strftime('%Y%m%d%H%M%S')}.json")
    try:
        LEGACY_CACHE_FILE.rename(retired)
    except OSError as exc:
        logger.info("[incremental_cache] Legacy cache not retired (%s): %s", LEGACY_CACHE_FILE, exc)
        return
    logger.info("[incremental_cache] Legacy cache retired to %s", retired.name)
    json_handler.log_operation("audit_cache_legacy_retired", {"file": retired.name})


def migrate_legacy_cache() -> int:
    """Split the flat doc into one file per key, then retire it. Returns the count."""
    if not LEGACY_CACHE_FILE.exists():
        return 0
    try:
        doc = json.loads(LEGACY_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[incremental_cache] Legacy cache unreadable, retiring without migrating: %s", exc)
        _retire_legacy_cache()
        return 0

    branches = doc.get("branches") if isinstance(doc, dict) else None
    migrated = 0
    if isinstance(branches, dict):
        for cache_key, entry in branches.items():
            if not isinstance(entry, dict) or entry_path(cache_key).exists():
                continue
            atomic_write(entry_path(cache_key), _wrap(cache_key, entry))
            migrated += 1
    _retire_legacy_cache()
    logger.info("[incremental_cache] Migrated %d cache entries to %s", migrated, CACHE_DIR.name)
    json_handler.log_operation("audit_cache_migrated", {"entries": migrated})
    return migrated


def _wrap(cache_key: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """The on-disk doc for one entry: its schema, its key, and the entry itself."""
    return {"schema_version": SCHEMA_VERSION, "cache_key": cache_key, "entry": entry}


def load_branch_entry(cache_key: str) -> Dict[str, Any]:
    """Load one key's cached entry. Missing/corrupt/mismatched -> {} (fail open to full)."""
    migrate_legacy_cache()
    path = entry_path(cache_key)
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.info("[incremental_cache] Cannot read %s: %s", path, e)
        return {}
    if not content.strip():
        return {}
    try:
        doc = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning("[incremental_cache] Corrupt cache entry at %s, renaming aside: %s", path, e)
        try:
            path.rename(path.with_suffix(path.suffix + ".corrupt"))
        except OSError as rename_err:
            logger.info("[incremental_cache] Could not rename corrupt entry: %s", rename_err)
        return {}
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION:
        return {}
    if doc.get("cache_key") != cache_key:
        # A digest collision or a hand-moved file reads as a miss, not another branch's audit.
        logger.warning("[incremental_cache] %s holds key %r, wanted %r", path.name, doc.get("cache_key"), cache_key)
        return {}
    entry = doc.get("entry")
    if not isinstance(entry, dict):
        return {}
    json_handler.log_operation("audit_cache_loaded", {"cache_key": cache_key})
    return entry


def save_branch_entry(cache_key: str, entry: Dict[str, Any]) -> None:
    """Atomically write one key's entry to its own file."""
    migrate_legacy_cache()
    atomic_write(entry_path(cache_key), _wrap(cache_key, entry))
    json_handler.log_operation("audit_cache_saved", {"cache_key": cache_key})
