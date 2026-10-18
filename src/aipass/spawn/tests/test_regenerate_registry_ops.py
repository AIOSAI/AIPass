# =================== AIPass ====================
# Name: test_regenerate_registry_ops.py
# Description: Tests for regenerate_registry_ops handler
# Version: 1.0.4
# Created: 2026-04-03
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/regenerate_registry_ops.py and apps/modules/regenerate_registry.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that regenerate_registry_ops.py and regenerate_registry.py parse and import
# seedgo: no-test-needed(documentation) — docstrings on the scan/regenerate helper functions

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.spawn.apps.handlers import regenerate_registry_ops
from aipass.spawn.apps.handlers.class_registry import get_available_classes, get_template_dir
from aipass.spawn.apps.handlers.regenerate_registry_ops import regenerate_template_registry
from aipass.spawn.apps.modules import regenerate_registry as regenerate_registry_module
from aipass.spawn.apps.modules.regenerate_registry import handle_regenerate_registry


def _make_template(tmp_path: Path, files: dict[str, str] | None = None, dirs: list[str] | None = None) -> Path:
    """Create a minimal template directory with given files and sub-directories."""
    tpl = tmp_path / "my_template"
    tpl.mkdir(parents=True, exist_ok=True)

    for rel, content in (files or {}).items():
        fp = tpl / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")

    for d in dirs or []:
        (tpl / d).mkdir(parents=True, exist_ok=True)

    return tpl


def _hash_for(_content: str) -> str:
    """Return a deterministic fake 12-char hex hash for the given content key."""
    import hashlib

    return hashlib.sha256(_content.encode()).hexdigest()[:12]


class TestRegenerateFreshTemplate:
    """Test 1 — create template dir with files+dirs, no existing registry."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_fresh_template(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = None
        mock_hash.return_value = "aabbccdd1122"

        tpl = _make_template(
            tmp_path,
            files={"main.py": "print('hi')", "apps/utils.py": "# util"},
            dirs=["apps", "apps/handlers"],
        )

        result = regenerate_template_registry(tpl)

        assert "files" in result
        assert "directories" in result
        assert "stats" in result
        assert "metadata" in result

        registry_path = tpl / ".spawn" / ".template_registry.json"
        assert registry_path.exists()

        persisted = json.loads(registry_path.read_text(encoding="utf-8"))
        assert "files" in persisted
        assert "directories" in persisted
        assert "metadata" in persisted


class TestPreservesIdsByHash:
    """Test 2 — existing registry with hash->ID, same content at different path."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_preserves_ids_by_hash(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = {
            "files": {
                "f001": {
                    "path": "old/main.py",
                    "name": "main.py",
                    "content_hash": "aabbccdd1122",
                },
            },
            "directories": {},
        }
        mock_hash.return_value = "aabbccdd1122"

        tpl = _make_template(tmp_path, files={"new_location/main.py": "print('hi')"})

        result = regenerate_template_registry(tpl)

        assert "f001" in result["files"]
        assert result["files"]["f001"]["path"] == "new_location/main.py"


class TestPreservesIdsByPath:
    """Test 3 — same path, different content -> ID preserved via path match."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_preserves_ids_by_path(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = {
            "files": {
                "f005": {
                    "path": "config.yaml",
                    "name": "config.yaml",
                    "content_hash": "oldoldhash12",
                },
            },
            "directories": {},
        }
        mock_hash.return_value = "newnewnew123"

        tpl = _make_template(tmp_path, files={"config.yaml": "new content here"})

        result = regenerate_template_registry(tpl)

        assert "f005" in result["files"]
        assert result["files"]["f005"]["content_hash"] == "newnewnew123"


class TestAssignsNewIds:
    """Test 4 — file matching neither hash nor path gets a new sequential ID."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_assigns_new_ids(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = {
            "files": {
                "f001": {
                    "path": "existing.py",
                    "name": "existing.py",
                    "content_hash": "existhash123",
                },
            },
            "directories": {},
        }
        mock_hash.return_value = "brandnew1234"

        tpl = _make_template(tmp_path, files={"totally_new.py": "new stuff"})

        result = regenerate_template_registry(tpl)

        # An unmatched old entry claims nothing, so f001 is the first free id.
        file_ids = list(result["files"].keys())
        assert len(file_ids) == 1
        assert file_ids[0] == "f001"


class TestSkipsPycache:
    """Test 5 — __pycache__ directory and its contents should be excluded."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_skips_pycache(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = None
        mock_hash.return_value = "abc123def456"

        tpl = _make_template(
            tmp_path,
            files={
                "main.py": "print(1)",
                "__pycache__/main.cpython-312.pyc": "bytecode",
            },
        )

        result = regenerate_template_registry(tpl)

        all_paths = [f["path"] for f in result["files"].values()]
        assert not any("__pycache__" in p for p in all_paths)

        all_dir_paths = [d["path"] for d in result["directories"].values()]
        assert not any("__pycache__" in p for p in all_dir_paths)


class TestSkipsSpawnTrackingFiles:
    """Test 6 — .template_registry.json and .branch_meta.json inside .spawn/ are skipped."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_skips_spawn_tracking_files(self, mock_hash, mock_load, tmp_path):
        # {} not None: None beside an existing manifest means unreadable, which refuses.
        mock_load.return_value = {}
        mock_hash.return_value = "aabb11223344"

        tpl = _make_template(
            tmp_path,
            files={
                "main.py": "print(1)",
                ".spawn/.template_registry.json": "{}",
                ".spawn/.branch_meta.json": "{}",
            },
        )

        result = regenerate_template_registry(tpl)

        all_paths = [f["path"] for f in result["files"].values()]
        assert ".spawn/.template_registry.json" not in all_paths
        assert ".spawn/.branch_meta.json" not in all_paths


class TestAllowsSpawnReadme:
    """Test 7 — .spawn/README.md is NOT a tracking file and should be included."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_allows_spawn_readme(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = None
        mock_hash.return_value = "readmehash12"

        tpl = _make_template(
            tmp_path,
            files={
                ".spawn/README.md": "# Spawn docs",
            },
        )

        result = regenerate_template_registry(tpl)

        all_paths = [f["path"] for f in result["files"].values()]
        assert ".spawn/README.md" in all_paths


class TestNonexistentDir:
    """Test 8 — pass nonexistent path, verify returns error dict."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    def test_regenerate_nonexistent_dir(self, mock_load, tmp_path):
        bogus = tmp_path / "does_not_exist"

        result = regenerate_template_registry(bogus)

        assert "error" in result
        mock_load.assert_not_called()


class TestUnreadableManifestIsRefused:
    """A manifest that is there but cannot be read is named and refused (never read as absent)."""

    def test_an_unreadable_manifest_refuses_and_writes_nothing(self, tmp_path):
        tpl = _make_template(tmp_path, files={"README.md": "# hi", "apps/a.py": "x"})
        manifest = tpl / ".spawn" / ".template_registry.json"
        manifest.parent.mkdir()
        manifest.write_bytes(b'{"files": {"f007": ')
        before = {p.relative_to(tpl): (p.read_bytes() if p.is_file() else None) for p in tpl.rglob("*")}

        result = regenerate_template_registry(tpl)

        assert list(result) == ["error"]
        assert str(manifest) in result["error"]
        assert {p.relative_to(tpl): (p.read_bytes() if p.is_file() else None) for p in tpl.rglob("*")} == before


class TestDetectsPlaceholderFilenames:
    """Test 9 — file named {{BRANCH}}.py should have has_branch_placeholder=True."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_detects_placeholder_filenames(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = None
        mock_hash.return_value = "placeholder12"

        tpl = _make_template(
            tmp_path,
            files={
                "{{BRANCH}}.py": "# branch-specific file",
                "normal.py": "# regular file",
            },
        )

        result = regenerate_template_registry(tpl)

        placeholder_entry = None
        normal_entry = None
        for entry in result["files"].values():
            if "{{BRANCH}}" in entry["path"]:
                placeholder_entry = entry
            elif entry["path"] == "normal.py":
                normal_entry = entry

        assert placeholder_entry is not None
        assert placeholder_entry["has_branch_placeholder"] is True

        assert normal_entry is not None
        assert normal_entry["has_branch_placeholder"] is False


class TestDirectoryIdPreservation:
    """Test 10 — existing dir IDs preserved by path match."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_directory_id_preservation(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = {
            "files": {},
            "directories": {
                "d010": {
                    "path": "apps/handlers",
                    "name": "handlers",
                    "has_branch_placeholder": False,
                },
            },
        }
        mock_hash.return_value = "filehash1234"

        tpl = _make_template(
            tmp_path,
            files={"apps/handlers/main.py": "code"},
            dirs=["apps", "apps/handlers"],
        )

        result = regenerate_template_registry(tpl)

        assert "d010" in result["directories"]
        assert result["directories"]["d010"]["path"] == "apps/handlers"


class TestDirectoryNameFallback:
    """Test 11 — dir ID preserved by name when path changes."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_directory_name_fallback(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = {
            "files": {},
            "directories": {
                "d007": {
                    "path": "old_location/utils",
                    "name": "utils",
                    "has_branch_placeholder": False,
                },
            },
        }
        mock_hash.return_value = "filehash1234"

        tpl = _make_template(
            tmp_path,
            files={"new_location/utils/helper.py": "code"},
            dirs=["new_location", "new_location/utils"],
        )

        result = regenerate_template_registry(tpl)

        assert "d007" in result["directories"]
        assert result["directories"]["d007"]["name"] == "utils"


class TestStatsAccuracy:
    """Test 12 — verify stats dict has correct file/dir counts and template_name."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_stats_accuracy(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = {
            "files": {
                "f001": {"path": "old.py", "name": "old.py", "content_hash": "oldhash12345"},
                "f002": {"path": "old2.py", "name": "old2.py", "content_hash": "oldhash22222"},
            },
            "directories": {
                "d001": {"path": "olddir", "name": "olddir"},
            },
        }
        mock_hash.return_value = "newhash12345"

        tpl = _make_template(
            tmp_path,
            files={
                "a.py": "aaa",
                "b.py": "bbb",
                "c.py": "ccc",
            },
            dirs=["subdir1", "subdir2"],
        )

        result = regenerate_template_registry(tpl)
        stats = result["stats"]

        assert stats["files_tracked"] == 3
        assert stats["directories_tracked"] == 2
        assert stats["previous_files"] == 2
        assert stats["previous_directories"] == 1
        assert stats["template_name"] == "my_template"


class TestHashLengthCompat:
    """Test 13 — existing 16-char hashes match against new 12-char hashes by prefix."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_hash_length_compat(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = {
            "files": {
                "f042": {
                    "path": "legacy.py",
                    "name": "legacy.py",
                    "content_hash": "aabbccdd11223344",  # 16 chars
                },
            },
            "directories": {},
        }
        mock_hash.return_value = "aabbccdd1122"  # 12 chars

        tpl = _make_template(tmp_path, files={"moved/legacy.py": "content"})

        result = regenerate_template_registry(tpl)

        assert "f042" in result["files"]
        assert result["files"]["f042"]["path"] == "moved/legacy.py"


def _seed_registry(tpl: Path, files: dict | None = None, directories: dict | None = None) -> None:
    """Write an existing .spawn/.template_registry.json into a tmp_path template."""
    spawn_dir = tpl / ".spawn"
    spawn_dir.mkdir(parents=True, exist_ok=True)
    registry = {"metadata": {"last_updated": "2026-01-01"}, "files": files or {}, "directories": directories or {}}
    (spawn_dir / ".template_registry.json").write_text(json.dumps(registry), encoding="utf-8")


def _file_entry(path: str) -> dict:
    return {"path": path, "name": path, "content_hash": _hash_for(path)}


def _id_of(entries: dict, path: str) -> str:
    return next(eid for eid, entry in entries.items() if entry["path"] == path)


class TestNextId:
    """Tests 14-16 — new-ID assignment, observed through regenerate_template_registry."""

    def test_next_id_basic(self, tmp_path):
        """Test 14 — nothing claimed yet: the first file gets prefix + 001.

        Mutant: new IDs numbered from 0 -> red."""
        tpl = _make_template(tmp_path, files={"only.py": "x"})

        result = regenerate_template_registry(tpl)

        assert list(result["files"]) == ["f001"]

    def test_next_id_skips_claimed(self, tmp_path):
        """Test 15 — skips past consecutively claimed IDs."""
        tpl = _make_template(tmp_path, files={"a.py": "a", "b.py": "b", "c.py": "c"})
        _seed_registry(tpl, files={"f001": _file_entry("a.py"), "f002": _file_entry("b.py")})

        result = regenerate_template_registry(tpl)

        assert _id_of(result["files"], "c.py") == "f003"

    def test_next_id_fills_gaps(self, tmp_path):
        """Test 16 — fills gaps in the sequence.

        Mutant: the next ID counts past the highest claimed instead of filling the first gap -> red."""
        tpl = _make_template(tmp_path, files={"a.py": "a", "c.py": "c", "new.py": "n"})
        _seed_registry(tpl, files={"f001": _file_entry("a.py"), "f003": _file_entry("c.py")})

        result = regenerate_template_registry(tpl)

        assert _id_of(result["files"], "new.py") == "f002"

    def test_next_id_directory_prefix(self, tmp_path):
        """Bonus — directories draw from the 'd' prefix."""
        fresh = _make_template(tmp_path / "fresh", dirs=["x"])
        assert list(regenerate_template_registry(fresh)["directories"]) == ["d001"]

        tpl = _make_template(tmp_path / "seeded", dirs=["x", "y"])
        _seed_registry(tpl, directories={"d001": {"path": ".spawn", "name": ".spawn"}})

        result = regenerate_template_registry(tpl)

        assert sorted(result["directories"]) == ["d001", "d002", "d003"]
        assert _id_of(result["directories"], ".spawn") == "d001"


class TestScanTemplateDirectoryOrdering:
    """Test 17 — files and dirs come from sorted rglob, verify consistent output."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_scan_template_directory_ordering(self, mock_hash, tmp_path):
        call_count = 0

        def _sequential_hash(_path):
            nonlocal call_count
            call_count += 1
            return f"{call_count:012d}"

        mock_hash.side_effect = _sequential_hash

        tpl = _make_template(
            tmp_path,
            files={
                "z_last.py": "z",
                "a_first.py": "a",
                "m_middle.py": "m",
            },
            dirs=["z_dir", "a_dir"],
        )

        result = regenerate_template_registry(tpl)
        files, directories = result["files"], result["directories"]

        file_paths = [entry["path"] for entry in files.values()]
        assert file_paths == sorted(file_paths)

        dir_paths = [entry["path"] for entry in directories.values()]
        assert dir_paths == sorted(dir_paths)


SPAWN_BRANCH_ROOT = Path(__file__).resolve().parents[1]

# Every template lookup regenerate_registry.py binds at import; the fixture must redirect all.
_TEMPLATE_LOOKUPS = {"get_template_dir", "get_template_dirs"}


def _shipped_registry_path() -> Path:
    """Path to the real citizen template registry that spawn ships (via the class registry, not a name)."""
    return get_template_dir() / ".spawn" / ".template_registry.json"


class TestRegistryDateSeam:
    """The clock seam itself, unpatched: every other date test replaces it."""

    def test_the_seam_answers_an_iso_day(self, tmp_path):
        """The real clock stamps a ten-character day that date.fromisoformat takes.

        No second clock is compared, so midnight cannot redden it.
        Mutant: the body formats day/month/year with slashes -> red."""
        tpl = _make_template(tmp_path, files={"main.py": "print('hi')"}, dirs=["apps"])

        answer = regenerate_template_registry(tpl)["metadata"]["last_updated"]

        assert len(answer) == 10
        assert date.fromisoformat(answer).isoformat() == answer


class TestLastUpdatedTracksContentNotTheCalendar:
    """metadata.last_updated moves when the TEMPLATE moves, not when the day does."""

    _FIXED_DAY = "2031-06-15"

    @pytest.fixture(autouse=True)
    def _fixed_clock(self, monkeypatch):
        """Pin "today" at the product's clock seam, never at the stdlib (two clocks split at midnight)."""
        monkeypatch.setattr(regenerate_registry_ops, "_registry_date", lambda: self._FIXED_DAY)

    @staticmethod
    def _regenerate(template: Path) -> None:
        """Regenerate on the seam's fixed day; the old stamp is moved on disk."""
        regenerate_template_registry(template)

    def _today(self) -> str:
        return self._FIXED_DAY

    @staticmethod
    def _registry(template: Path) -> dict:
        return json.loads((template / ".spawn" / ".template_registry.json").read_text(encoding="utf-8"))

    def _settled(self, tmp_path: Path, date: str = "2026-01-01", newline: str = "\n") -> Path:
        """A template whose registry is already stable, stamped on a day that is not today.

        Settled twice: the first run creates .spawn/, which the second then tracks.
        newline is explicit: without it write_text writes os.linesep (CRLF on Windows)."""
        template = _make_template(tmp_path, files={"README.md": "hello"})
        self._regenerate(template)
        self._regenerate(template)
        registry = self._registry(template)
        registry["metadata"]["last_updated"] = date
        (template / ".spawn" / ".template_registry.json").write_text(
            json.dumps(registry, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline=newline
        )
        return template

    def test_no_change_regenerate_preserves_the_existing_date(self, tmp_path):
        """Mutant: a no-change regenerate stamps today's date -> red."""
        template = self._settled(tmp_path)

        self._regenerate(template)

        assert self._registry(template)["metadata"]["last_updated"] == "2026-01-01"

    @pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
    def test_no_change_regenerate_is_byte_identical(self, tmp_path, newline):
        """A no-op keeps every byte, line endings included (CRLF: a Windows checkout).

        Mutant: a no-change regenerate stamps today's date -> red, both endings.
        Mutant: the writer always writes LF -> red on crlf."""
        template = self._settled(tmp_path, newline=newline)
        registry_path = template / ".spawn" / ".template_registry.json"
        before = registry_path.read_bytes()

        self._regenerate(template)

        assert registry_path.read_bytes() == before

    def test_changed_content_does_bump_the_date(self, tmp_path):
        """The other half — preserving must never become freezing.

        Mutant: the existing date kept even when the content changed -> red.
        Mutant: the date read from datetime.now() past the _registry_date seam -> red."""
        template = self._settled(tmp_path)

        (template / "README.md").write_text("hello, world", encoding="utf-8")
        self._regenerate(template)

        assert self._registry(template)["metadata"]["last_updated"] == self._today()

    def test_a_new_file_bumps_the_date(self, tmp_path):
        template = self._settled(tmp_path)

        (template / "NEW.md").write_text("new", encoding="utf-8")
        self._regenerate(template)

        assert self._registry(template)["metadata"]["last_updated"] == self._today()

    def test_a_new_directory_bumps_the_date(self, tmp_path):
        template = self._settled(tmp_path)

        (template / "extra").mkdir()
        (template / "extra" / "README.md").write_text("x", encoding="utf-8")
        self._regenerate(template)

        assert self._registry(template)["metadata"]["last_updated"] == self._today()

    def test_a_removed_file_bumps_the_date(self, tmp_path):
        template = self._settled(tmp_path)

        (template / "README.md").unlink()
        self._regenerate(template)

        assert self._registry(template)["metadata"]["last_updated"] == self._today()

    def test_first_ever_regenerate_stamps_today(self, tmp_path):
        """No prior registry to preserve — today is the honest answer."""
        template = _make_template(tmp_path, files={"README.md": "hello"})

        self._regenerate(template)

        assert self._registry(template)["metadata"]["last_updated"] == self._today()


class TestHandleRegenerateRegistry:
    """Tests for handle_regenerate_registry() CLI handler.

    The real handler runs, so every template directory it can reach is redirected into tmp_path."""

    @pytest.fixture(autouse=True)
    def _isolate_templates(self, tmp_path):
        """Redirect EVERY template lookup the handler makes into tmp_path.

        Bound at import, so patched on THIS module by name; patching class_registry reaches nothing."""
        import shutil

        sandbox = tmp_path / "templates"
        sandbox.mkdir()
        for class_name in get_available_classes():
            shutil.copytree(get_template_dir(class_name), sandbox / class_name)

        def fake_template_dir(class_name: str = "specialist") -> Path:
            return sandbox / class_name

        def fake_template_dirs() -> list[Path]:
            return sorted({sandbox / class_name for class_name in get_available_classes()})

        with (
            patch("aipass.spawn.apps.modules.regenerate_registry.get_template_dir", side_effect=fake_template_dir),
            patch("aipass.spawn.apps.modules.regenerate_registry.get_template_dirs", side_effect=fake_template_dirs),
            patch(
                "aipass.spawn.apps.modules.regenerate_registry.get_available_classes",
                side_effect=get_available_classes,
            ),
        ):
            yield

    def test_every_template_lookup_is_redirected(self):
        """Guard the guard: a NEW template lookup on the module must be patched.

        On failure, redirect the new name in the fixture; never widen the list alone."""
        found = {
            name
            for name in dir(regenerate_registry_module)
            if name.startswith("get_template_dir") or name.endswith("_template_dirs")
        }

        assert found == _TEMPLATE_LOOKUPS, (
            f"template lookups on the module changed: {sorted(found)} != {sorted(_TEMPLATE_LOOKUPS)}. "
            "Every one of these must be redirected by _isolate_templates or a test run "
            "writes into the shipped template tree."
        )

    def test_shipped_template_registry_untouched(self):
        """Canary: running the CLI handler must not rewrite the registry spawn ships."""
        shipped = _shipped_registry_path()
        before = shipped.read_bytes()

        assert handle_regenerate_registry([]) == 0
        assert handle_regenerate_registry(["--all"]) == 0

        assert shipped.read_bytes() == before

    def test_shipped_registry_not_even_reopened_for_writing(self):
        """The canary, made date-proof: bytes are the wrong instrument alone.

        A same-day rewrite is byte-identical; mtime sees the write itself."""
        shipped = _shipped_registry_path()
        before_mtime = shipped.stat().st_mtime_ns

        assert handle_regenerate_registry([]) == 0
        assert handle_regenerate_registry(["--all"]) == 0

        assert shipped.stat().st_mtime_ns == before_mtime, (
            "the CLI handler reopened the SHIPPED template registry for writing — "
            "some template lookup escaped the _isolate_templates redirect"
        )

    def test_shipped_registry_untouched_on_a_different_calendar_day(self):
        """Reproduce the CI red locally: force the clock past the committed date."""
        shipped = _shipped_registry_path()
        before = shipped.read_bytes()

        with patch.object(regenerate_registry_ops, "_registry_date", return_value="2099-12-31"):
            assert handle_regenerate_registry([]) == 0
            assert handle_regenerate_registry(["--all"]) == 0

        assert shipped.read_bytes() == before

    def test_all_flag_writes_only_inside_the_sandbox(self):
        """Name the escape point directly: --all resolves dirs, not classes."""
        resolved = regenerate_registry_module.get_template_dirs()

        assert resolved, "get_template_dirs() returned nothing — the --all branch would be a silent no-op"
        for template_dir in resolved:
            assert not template_dir.is_relative_to(SPAWN_BRANCH_ROOT / "templates"), (
                f"--all resolved {template_dir}, which is inside the shipped tree"
            )

    def test_default_regenerates_the_default_class(self):
        result = handle_regenerate_registry([])
        assert result == 0

    def test_explicit_specialist(self):
        result = handle_regenerate_registry(["specialist"])
        assert result == 0

    def test_explicit_manager(self):
        result = handle_regenerate_registry(["manager"])
        assert result == 0

    def test_retired_class_returns_error(self):
        """A retired name is refused like any other unknown class — never mapped."""
        result = handle_regenerate_registry(["aipass_framework"])
        assert result == 1

    def test_all_flag(self):
        result = handle_regenerate_registry(["--all"])
        assert result == 0

    def test_help_flag(self):
        result = handle_regenerate_registry(["--help"])
        assert result == 0

    def test_unknown_class_returns_error(self):
        result = handle_regenerate_registry(["nonexistent_class"])
        assert result == 1
