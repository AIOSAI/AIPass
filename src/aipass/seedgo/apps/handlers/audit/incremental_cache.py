# =================== AIPass ====================
# Name: incremental_cache.py
# Description: Audit Fingerprint Cache Handler
# Version: 1.3.0
# Created: 2026-07-31
# Modified: 2026-09-21
# =============================================

"""
Audit Fingerprint Cache Handler

Backup-style (mtime_ns, size) fingerprint cache so audit_branch_incremental()
can skip re-scanning unchanged files/branches. Machine-local state only —
never git-tracked (seedgo_json/ is gitignored like every branch's *_json/).

ONE FILE PER CACHE KEY, under seedgo_json/audit_cache/:

    {
        "schema_version": 2,
        "cache_key": "memory",          # "memory::no-bypass", "memory::pack=x"
        "entry": {
            "stamp": "<shared-pack + machinery + bypass/ignore + bypass-state + cache-version fingerprint>",
            "checker_stamps": {"<checker>": "<that checker file's own fingerprint>"},
            "files": {
                "<relpath>": {"fp": [mtime_ns, size], "results": {"<checker>": {...}}}
            },
            "output": {...last audit_branch() output dict, for the clean fast path...}
        }
    }

WHY ONE FILE EACH, and it is not about speed. Every entry used to live in one
flat doc. audit_branch_incremental loaded the WHOLE doc (47.7 MB, 67 keys),
audited for 30 to 450 seconds, then saved the WHOLE doc back — so each save
reverted every entry another process had written in that window to the stale
snapshot the saver read on the way in. The owner met it on 2026-09-21: a fleet
run immediately after a cold one re-scanned 14 of 18 branches, 1,149 s, because
three overlapping processes kept clobbering each other's work. The cache itself
was sound; the container was the bug.

A save can now only race a save for the SAME key, where both processes did the
same work over the same branch and last-writer-wins is a correct outcome.
Nothing a run does to @memory's entry can touch @drone's. Load and save are
O(one branch): the median entry is 226 KB against a 47.7 MB doc.

Fail-open by construction: any read/schema problem here returns an empty
entry, which the caller (branch_audit.audit_branch_incremental) treats as
"no cache" and runs a full audit — never a skipped one. Still no locking, and
none is needed now — accepted per DPLAN-0275.

See branch_audit.audit_branch_incremental()'s docstring for the accepted
diagnostics/pyright cross-branch staleness divergence (DPLAN-0275 §8 HIGH).
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

# Bump when the fingerprint/stamp ALGORITHM changes (belt-and-braces bust).
# "2": the pack stamp stopped covering the checker files themselves, which now
# carry one stamp each. Every entry written under "1" must bust once, because
# its single stamp claims a coverage the new one deliberately no longer has.
# "3": the audit's CORPUS grew to include tests/ (owner ruling 2026-09-21
# 21:20). Nothing else would have caught this. The branch stamp already
# fingerprinted tests/ through _collect_watch_files, so an unchanged branch
# hits the fast path and serves results computed from an apps/-only corpus --
# a stale 100% with no test row in it. The corpus is defined in branch_audit,
# which neither the pack stamp nor the per-checker stamps cover, so the version
# is the only thing that can bust it.
CACHE_VERSION = "3"
# Bump when the on-disk DOC SHAPE changes — checked separately from the
# checker/bypass/version stamp so schema churn during development doesn't
# piggyback on version bumps. Deliberately NOT bumped for checker_stamps: the
# key is additive, and an entry without it reads as "every checker stale",
# which re-runs rather than serves. Bumping would discard 39MB of still-valid
# per-file results to gain nothing CACHE_VERSION does not already do.
#
# 2: one file per cache key. The CONTAINER changed, not the entry — stamp,
# checker_stamps, files and output are byte-identical to what schema 1 held, so
# migrate_legacy_cache() rewraps them rather than discarding them, and
# CACHE_VERSION does NOT move: no fingerprint or stamp algorithm changed, and
# bumping it would throw away 47.7 MB of still-valid results to prove a point.
SCHEMA_VERSION = 2
# Asked of the service rather than spelled out: the shim binds the fleet json
# service (DPLAN-0325) and no longer carries a JSON_DIR of its own.
# The directory is asked for through a bound name rather than reached for on
# the handle: get_json_path is the only public way to name it, and the cache
# doc is not one of the three declared json_types.
_JSON_DIR = json_handler.get_json_path("audit", "data").parent

# One file per cache key lives here.
CACHE_DIR = _JSON_DIR / "audit_cache"

# The single flat doc every entry shared until 2026-09-21. Read once by
# migrate_legacy_cache(), then retired by rename beside itself — never deleted,
# because a cache is cheap to rebuild and evidence is not.
LEGACY_CACHE_FILE = _JSON_DIR / "audit_cache.json"

# Packages that decide audit OUTPUT without living in the checker pack: bypass/
# decides whether a violation counts, audit/ decides which files a checker ever
# sees. Both are inputs exactly as much as a checker is, and neither was
# fingerprinted — so when FPLAN-0382 changed is_bypassed's matching semantics,
# every branch kept serving results computed under the old rules. The fleet read
# 17/17 cached green while CI, which has no cache, showed the real 99%. A stale
# green is worse than a slow audit.
MACHINERY_DIRS: Tuple[Path, ...] = (
    module_file(__file__).parent,
    module_file(__file__).parent.parent / "bypass",
)


# Presence-only entries share one constant fingerprint: see collect_fingerprints().
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

    Expects dicts shaped like _collect_py_files()'s output ({'file', 'rel'}).
    Reusing the caller's own 'rel' keeps cache keys identical to the ones
    branch_audit uses for per-file result lookups.

    An entry flagged ``presence_only`` gets a CONSTANT fingerprint: its
    existence is the signal, its bytes are not. diff_fileset() derives added
    and deleted from the key sets, so both still bust the cache while content
    churn stays invisible -- which is what a checker scoring "does this file
    exist" actually depends on.
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


# Pack files the audit can never read: a standard's prose page and its
# queryable *_content.py are consumed by standards_query, a separate command
# with no cache. Checked against the live 39MB cache doc rather than assumed —
# every ".md" and "_content" string in a cached output names a file in the
# AUDITED branch, never a page of the pack's own. Fingerprinting them turned
# every wording fix into a full fleet re-scan for a result that cannot move.
_UNREAD_BY_AUDIT: Tuple[str, ...] = ("*.md", "*_content.py")


def _is_unread_by_audit(path: Path) -> bool:
    """True for a pack file whose bytes cannot reach audit output."""
    return any(path.match(pattern) for pattern in _UNREAD_BY_AUDIT)


def compute_pack_stamp(pack_path: Path, diag_path: Path | None = None) -> str:
    """Fingerprint the pack's SHARED inputs — everything except the checkers themselves.

    Each checker now carries its own stamp (compute_checker_stamps), so editing
    one no longer throws away the other fifty's results. What stays here is what
    every checker answers THROUGH, and so still busts the whole branch: the
    shared helpers (applicability, skip_dirs, trinity_groups, ...), the runner
    config (diagnostics.json), and diagnostics_check.py, which lives outside the
    pack and has no per-checker slot. Prose pages and *_content.py are excluded
    (_is_unread_by_audit). __pycache__ is skipped — bytecode churn isn't a real
    input change. A shared pack asset added or removed still changes this stamp.
    """
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

    The key is the file stem minus ``_check`` — exactly the key
    branch_audit.discover_checkers() uses — so a stale entry names the checker
    whose cached results must be dropped, and nothing else's. A checker added
    or removed shows up as a key appearing or disappearing, which
    stale_checkers() reports as stale too.
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

    A name is stale when its stamp moved, when it is new (nothing cached for
    it), or when the pack no longer has it. The removed case is named
    deliberately: a checker that leaves and later comes back under the same
    filename must not be handed the results its predecessor computed. An entry
    written before checker_stamps existed has an empty cached map, so every
    checker reads stale and the branch re-runs whole — the safe direction.
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
    """Fingerprint the bypass/ and audit/ packages — the code that decides results.

    compute_pack_stamp() covers the checkers; this covers everything the
    checkers' answers are filtered through afterwards. Machine-local paths, so
    the stamp is per-install, which is what the cache is too.
    """
    entries = []
    for directory in MACHINERY_DIRS:
        if not directory.exists():
            continue
        for f in sorted(directory.rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            fp = fingerprint_file(f)
            entries.append([f"{directory.name}/{f.relative_to(directory).as_posix()}", fp[0], fp[1]])
    return hashlib.sha1(json.dumps(entries).encode("utf-8")).hexdigest()


def current_stamp(branch_path: Path, pack_path: Path, diag_path: Path | None = None, no_bypass: bool = False) -> str:
    """Combined whole-branch stamp: cache version + shared pack + audit machinery + bypass/ignore rules.

    Everything here busts the entire branch entry. The checkers themselves are
    no longer in it — they are stamped one by one (compute_checker_stamps) so a
    single checker's edit re-runs that checker and leaves the rest cached.

    no_bypass records that the rules were SUPPRESSED for this run (--no-bypass),
    which nothing else in the stamp can see: compute_bypass_stamp() fingerprints
    the bypass.json FILE, and that file is byte-identical whether or not its
    rules were applied. Without it, a normal run and a --no-bypass run over an
    unchanged tree agree on every input, so whichever runs second is served the
    other one's score — the honest number published as the normal one, or the
    bypassed number published as honest.
    """
    combined = (
        f"{CACHE_VERSION}:{compute_pack_stamp(pack_path, diag_path)}"
        f":{compute_machinery_stamp()}:{compute_bypass_stamp(branch_path)}"
        f":{'rules-suppressed' if no_bypass else 'rules-applied'}"
    )
    return hashlib.sha1(combined.encode("utf-8")).hexdigest()


#: Everything a filename may not carry. Cache keys hold "::" and "=", and ":"
#: is illegal on Windows outright.
_UNSAFE_IN_FILENAME = re.compile(r"[^A-Za-z0-9._-]")

#: Names Windows reserves for devices, matched on the segment before the first
#: dot and regardless of extension — a branch called `con` would otherwise
#: produce a file that cannot be created there.
_WINDOWS_RESERVED_STEMS: frozenset[str] = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{n}" for n in range(1, 10)} | {f"LPT{n}" for n in range(1, 10)}
)


def entry_filename(cache_key: str) -> str:
    """The file one cache key lives in, spelled safely for every host.

    Readable stem plus a digest of the EXACT key, and both halves earn their
    place. The stem is what a human greps for. The digest is what keeps two
    different keys apart after the stem has been flattened:

        "memory::no-bypass" and "memory=no-bypass"  ->  same stem
        "BACKUP" and "backup"                       ->  same file on Windows
                                                        and macOS, which are
                                                        case-insensitive

    Both pairs are real: the fleet has `BACKUP` and lowercase branch names in
    one cache, and every key carries "::". A collision would serve one branch
    another branch's audit, so the digest is not decoration.
    """
    stem = _UNSAFE_IN_FILENAME.sub("_", cache_key)
    if stem.split(".")[0].upper() in _WINDOWS_RESERVED_STEMS:
        stem = f"_{stem}"
    return f"{stem}.{hashlib.sha1(cache_key.encode('utf-8')).hexdigest()[:10]}.json"


def entry_path(cache_key: str) -> Path:
    """Where one cache key's entry is stored."""
    return CACHE_DIR / entry_filename(cache_key)


def _atomic_write(path: Path, doc: Dict[str, Any]) -> None:
    """Write one JSON doc through a staging file (write-tmp-then-os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, default=str)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        # finally, not `except Exception`: KeyboardInterrupt and SystemExit are
        # BaseExceptions and walked straight past the old clause, leaving the
        # staging file on disk. os.replace consumes tmp on the success path, so
        # absence is the normal case and must not raise.
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
        # Another process migrated first and the file is already gone, or the
        # rename target exists. Either way the split is done; say so and move on.
        logger.info("[incremental_cache] Legacy cache not retired (%s): %s", LEGACY_CACHE_FILE, exc)
        return
    logger.info("[incremental_cache] Legacy cache retired to %s", retired.name)
    json_handler.log_operation("audit_cache_legacy_retired", {"file": retired.name})


def migrate_legacy_cache() -> int:
    """Split the flat doc into one file per key, then retire it. Returns the count.

    Runs at most once per install: the first load or save after this lands does
    the split, and every call after that costs one ``exists()`` on a path that
    is no longer there. The entry payload is carried across UNCHANGED — schema 2
    rewrapped the container, it did not reshape what is inside — so a fleet's
    worth of still-valid results survives the upgrade instead of being rebuilt
    over twenty-five minutes of cold scanning.

    An entry whose per-key file ALREADY exists is left alone: that file was
    written by a run under the new shape and is newer than anything the flat
    doc remembers. A corrupt or unreadable flat doc migrates nothing and is
    still retired — it has already failed open to a full audit.
    """
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
            _atomic_write(entry_path(cache_key), _wrap(cache_key, entry))
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
        # The key is recorded inside the file as well as spelled into its name,
        # so a digest collision or a hand-moved file reads as a miss rather than
        # as another branch's audit.
        logger.warning("[incremental_cache] %s holds key %r, wanted %r", path.name, doc.get("cache_key"), cache_key)
        return {}
    entry = doc.get("entry")
    if not isinstance(entry, dict):
        return {}
    json_handler.log_operation("audit_cache_loaded", {"cache_key": cache_key})
    return entry


def save_branch_entry(cache_key: str, entry: Dict[str, Any]) -> None:
    """Atomically write one key's entry to its own file.

    A save can only ever race a save for the SAME key — two runs auditing the
    same branch under the same pack and bypass mode, which did the same work
    and where last-writer-wins is a correct outcome. No other branch's entry is
    reachable from here, which is the whole point of the split.
    """
    migrate_legacy_cache()
    _atomic_write(entry_path(cache_key), _wrap(cache_key, entry))
    json_handler.log_operation("audit_cache_saved", {"cache_key": cache_key})
