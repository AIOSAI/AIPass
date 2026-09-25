# =================== META ====================
# Name: test_ceiling_guard.py
# Description: Tests for the per-run size/file-count ceiling (runaway guard)
# Version: 1.0.4
# Created: 2026-08-20
# Modified: 2026-09-25
# =============================================

"""Tests for src/aipass/backup/apps/handlers/scan/ceiling.py and the per-run size/file-count ceiling."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that scan/ceiling and modules/snapshot, versioned, all parse and import
# seedgo: no-test-needed(documentation) — that check_ceiling and breach methods carry docstrings
# seedgo: no-test-needed(constant) — DEFAULT_MAX_TOTAL_GB and DEFAULT_MAX_FILES values (the latter tested as the limit)
# seedgo: no-test-needed(stdlib) — the byte count os.path.getsize() returns; its OSError skip is tested here

import json
from pathlib import Path
from unittest.mock import patch

from aipass.backup.apps.handlers.path.builder import build_snapshot_path, build_versioned_store
from aipass.backup.apps.handlers.scan import ceiling
from aipass.backup.apps.handlers.scan.ceiling import DEFAULT_MAX_FILES, check_ceiling
from aipass.backup.apps.modules import all as all_mod
from aipass.backup.apps.modules.all import handle_command
from aipass.backup.apps.modules.snapshot import run_snapshot
from aipass.backup.apps.modules.versioned import run_versioned


def _files(tmp_path: Path, rel_paths: list[str], size: int = 8) -> list[tuple[str, str]]:
    """Create real files under tmp_path and return (abs, rel) tuples."""
    out = []
    for rel in rel_paths:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
        out.append((str(p), rel))
    return out


# --- measurement ---


class TestCheckCeiling:
    """check_ceiling measures the filtered set and records each refusal in the audit trail."""

    def test_under_both_limits_returns_none(self, tmp_path: Path) -> None:
        """A normal project passes and the run proceeds."""
        files = _files(tmp_path, ["src/a.py", "src/b.py"])
        assert check_ceiling(files, {"max_backup_files": 10, "max_backup_size_gb": 10}) is None

    def test_file_count_breach(self, tmp_path: Path) -> None:
        """More files than the ceiling refuses the run."""
        files = _files(tmp_path, [f"t/{i}.o" for i in range(6)])
        breach = check_ceiling(files, {"max_backup_files": 5, "max_backup_size_gb": 10})
        assert breach is not None
        assert breach.reason == "file_count"
        assert breach.measured == 6
        assert breach.limit == 5
        assert breach.config_key == "max_backup_files"

    def test_breach_is_recorded_in_the_audit_trail(self, tmp_path: Path, mock_infrastructure: Path) -> None:
        """A refusal lands in backup's own operations stream inside the mock_infrastructure sandbox."""
        files = _files(tmp_path, [f"t/{i}.o" for i in range(6)])
        breach = check_ceiling(files, {"max_backup_files": 5, "max_backup_size_gb": 10})
        assert breach is not None

        stream = ceiling.trail.log_path()
        assert stream.parent.parent == mock_infrastructure.parent
        entries = [json.loads(line) for line in stream.read_text(encoding="utf-8").splitlines() if line.strip()]
        refusals = [entry for entry in entries if entry.get("operation") == "ceiling_breach"]
        assert len(refusals) == 1
        assert refusals[0]["reason"] == "file_count"
        assert refusals[0]["measured"] == 6
        assert refusals[0]["limit"] == 5
        # A list, not a tuple: the row has been through JSON. breach.offenders itself holds tuples.
        assert refusals[0]["offenders"] == [["t", 6, 0]]

    def test_equal_to_limit_is_allowed(self, tmp_path: Path) -> None:
        """The ceiling is a maximum, not an exclusive bound."""
        files = _files(tmp_path, [f"t/{i}.o" for i in range(5)])
        assert check_ceiling(files, {"max_backup_files": 5, "max_backup_size_gb": 10}) is None

    def test_total_size_breach(self, tmp_path: Path) -> None:
        """Total bytes over the ceiling refuses even when the file count is small."""
        files = _files(tmp_path, ["big/blob.bin"], size=4096)
        breach = check_ceiling(
            files,
            {"max_backup_files": 1000, "max_backup_size_gb": 0.000001},
        )
        assert breach is not None
        assert breach.reason == "total_size"
        assert breach.config_key == "max_backup_size_gb"
        assert breach.measured == 4096

    def test_zero_disables_file_ceiling(self, tmp_path: Path) -> None:
        """max_backup_files=0 means unlimited, for a project that really is huge."""
        files = _files(tmp_path, [f"t/{i}.o" for i in range(20)])
        assert check_ceiling(files, {"max_backup_files": 0, "max_backup_size_gb": 0}) is None

    def test_zero_disables_size_ceiling(self, tmp_path: Path) -> None:
        """max_backup_size_gb=0 skips the byte pass entirely."""
        files = _files(tmp_path, ["big/blob.bin"], size=4096)
        assert check_ceiling(files, {"max_backup_files": 1000, "max_backup_size_gb": 0}) is None

    def test_count_breach_skips_the_stat_pass(self, tmp_path: Path) -> None:
        """A count breach never stats: the ghost entry logs no "Ceiling measure skipped" line."""
        files = _files(tmp_path, [f"t/{i}.o" for i in range(6)])
        files.append((str(tmp_path / "t" / "ghost.o"), "t/ghost.o"))

        measured: list[str] = []
        recorder = patch.object(
            ceiling.logger,
            "info",
            side_effect=lambda message, *args, **kwargs: measured.append(str(message)),
        )
        with recorder:
            breach = ceiling.check_ceiling(files, {"max_backup_files": 5, "max_backup_size_gb": 10})

        assert breach is not None
        assert breach.reason == "file_count"
        assert breach.measured == 7
        # Anchored to the log literal at apps/handlers/scan/ceiling.py:149; reword it and this goes vacuous.
        assert [line for line in measured if "Ceiling measure skipped" in line] == []

    def test_vanished_file_does_not_abort_measurement(self, tmp_path: Path) -> None:
        """A file gone between filter and measure contributes nothing, never raises."""
        files = _files(tmp_path, ["src/a.py"])
        files.append((str(tmp_path / "src" / "ghost.py"), "src/ghost.py"))
        assert check_ceiling(files, {"max_backup_files": 100, "max_backup_size_gb": 10}) is None

    def test_absent_max_backup_files_uses_default_limit(self, tmp_path: Path) -> None:
        """Without max_backup_files a small set passes and one file past DEFAULT_MAX_FILES refuses."""
        files = _files(tmp_path, ["src/a.py"])
        assert check_ceiling(files, {}) is None

        over = [(str(tmp_path / "t" / f"{i}.o"), f"t/{i}.o") for i in range(DEFAULT_MAX_FILES + 1)]
        breach = check_ceiling(over, {"max_backup_size_gb": 0})
        assert breach is not None
        assert breach.reason == "file_count"
        assert breach.measured == DEFAULT_MAX_FILES + 1
        assert breach.limit == DEFAULT_MAX_FILES


# --- offender naming ---


class TestOffenderReporting:
    """The refusal must name the directory to add to .backupignore."""

    def test_names_the_rust_target_dir(self, tmp_path: Path) -> None:
        """baud's shape: the offender is app/src-tauri/target, not the deps leaf."""
        rels = [f"app/src-tauri/target/debug/deps/o{i}.rcgu.o" for i in range(10)]
        rels += ["app/src/main.rs", "README.md"]
        breach = check_ceiling(_files(tmp_path, rels), {"max_backup_files": 5, "max_backup_size_gb": 10})
        assert breach is not None
        top_dir = breach.offenders[0][0]
        assert top_dir == "app/src-tauri/target"

    def test_offender_row_does_not_miscount_its_directory(self, tmp_path: Path) -> None:
        """The reported count matches the files under that directory."""
        rels = [f"target/debug/o{i}.o" for i in range(7)]
        breach = check_ceiling(_files(tmp_path, rels), {"max_backup_files": 3, "max_backup_size_gb": 10})
        assert breach is not None
        assert breach.offenders[0] == ("target/debug", 7, 0)

    def test_root_level_files_group_under_dot(self, tmp_path: Path) -> None:
        """Files at the project root have no directory to blame."""
        breach = check_ceiling(
            _files(tmp_path, ["a.txt", "b.txt", "c.txt"]), {"max_backup_files": 2, "max_backup_size_gb": 10}
        )
        assert breach is not None
        assert breach.offenders[0][0] == "."

    def test_detail_lines_name_the_config_escape_hatch(self, tmp_path: Path) -> None:
        """The refusal names the offender row, .backupignore, and the max_backup_files escape hatch."""
        breach = check_ceiling(
            _files(tmp_path, [f"t/{i}.o" for i in range(6)]), {"max_backup_files": 5, "max_backup_size_gb": 10}
        )
        assert breach is not None
        lines = breach.detail_lines()
        assert len(lines) == 4
        assert lines[0] == "Largest directories in this run:"
        assert lines[1] == "  t  —  6 files"
        assert lines[2] == "Add the build-artifact directories above to .backupignore, then re-run."
        assert lines[3].startswith("If the project really is this large, raise 'max_backup_files'")

    def test_summary_reads_as_a_refusal(self, tmp_path: Path) -> None:
        """summary() states the measurement, then the ceiling, as one exact sentence."""
        breach = check_ceiling(
            _files(tmp_path, [f"t/{i}.o" for i in range(6)]), {"max_backup_files": 5, "max_backup_size_gb": 10}
        )
        assert breach is not None
        assert breach.summary() == "6 files exceeds the 5-file ceiling"


# --- refusal is enforced end-to-end ---


class TestRunRefusal:
    """A breach must stop the run before a single byte is copied."""

    def _project(self, tmp_path: Path, n: int = 40, max_files: int = 5) -> Path:
        """Build a project whose heavy dir is NOT covered by .backupignore.

        Not named target/ or build/: those are seeded into every .backupignore.
        """
        root = tmp_path / "proj"
        heavy = root / "artifacts" / "obj" / "cache"
        heavy.mkdir(parents=True)
        for i in range(n):
            (heavy / f"o{i}.blob").write_bytes(b"x" * 16)
        (root / "main.rs").write_text("fn main() {}", encoding="utf-8")

        # Written before the run: create_backup_dir seeds config.json only when
        # absent, and a saved config wins over the module DEFAULTS.
        backup_dir = root / ".backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / "config.json").write_text(
            json.dumps({"max_backup_files": max_files, "max_backup_size_gb": 10}),
            encoding="utf-8",
        )
        return root

    def test_snapshot_refuses_and_copies_nothing(self, tmp_path: Path) -> None:
        """run_snapshot refuses over-ceiling and copies no artifact file."""

        root = self._project(tmp_path)
        result = run_snapshot(str(root), show_panels=False)

        assert result.success is False
        assert result.files_copied == 0
        assert "refused" in result.errors[0].lower()

        # Measured 2026-09-08 on a fresh tree: the refusal DOES leave the
        # snapshot directory behind (setup scaffolds .backup/snapshots before
        # the ceiling is read) and leaves it completely empty.
        dest = build_snapshot_path(str(root))
        assert dest.exists() is True
        assert list(dest.rglob("*")) == []

    def test_versioned_refuses_and_writes_no_store(self, tmp_path: Path) -> None:
        """run_versioned refuses over-ceiling and creates no versioned content."""

        root = self._project(tmp_path)
        result = run_versioned(str(root), show_panels=False)

        assert result.success is False
        assert result.files_copied == 0

        # Measured: versioned refuses BEFORE it scaffolds, so unlike snapshot
        # the store directory is never created at all.
        store = build_versioned_store(str(root))
        assert store.exists() is False

    def test_versioned_refuses_a_pre_scanned_set(self, tmp_path: Path) -> None:
        """The 'all' path hands versioned a pre-scanned list — still measured."""

        root = self._project(tmp_path)
        pre = [(str(p), str(p.relative_to(root))) for p in root.rglob("*") if p.is_file() and ".backup" not in p.parts]
        result = run_versioned(str(root), show_panels=False, pre_scanned=pre)

        assert result.success is False

        # Same world as the un-scanned call: nothing scaffolded, nothing written.
        store = build_versioned_store(str(root))
        assert store.exists() is False

    def test_all_refuses_before_either_store_is_written(self, tmp_path: Path) -> None:
        """'all' writes nothing on breach — belt and braces with the sub-guards."""

        root = self._project(tmp_path)
        assert handle_command("all", [str(root), "--quiet"]) is True

        # Measured on a fresh tree, both worlds named rather than or-ed:
        # 'all' refuses on its own shared scan, so versioned is never even
        # scaffolded, while the snapshot directory exists and is empty.
        store = build_versioned_store(str(root))
        dest = build_snapshot_path(str(root))
        assert store.exists() is False
        assert dest.exists() is True
        assert list(dest.rglob("*")) == []

    def test_all_refuses_without_re_walking_the_tree(self, tmp_path: Path) -> None:
        """'all' refuses on its own shared scan and never calls run_snapshot or run_versioned."""
        root = self._project(tmp_path)
        with patch.object(all_mod, "run_snapshot") as snap, patch.object(all_mod, "run_versioned") as ver:
            assert all_mod.handle_command("all", [str(root), "--quiet"]) is True

        snap.assert_not_called()
        ver.assert_not_called()

    def test_under_ceiling_still_backs_up(self, tmp_path: Path) -> None:
        """The guard refuses runaways, not ordinary projects."""

        root = self._project(tmp_path, n=3, max_files=100)
        result = run_snapshot(str(root), show_panels=False)

        assert result.success is True
        assert result.files_copied >= 1


class TestSharedScanSeeding:
    """The 'all' shared scan must run against a seeded .backupignore."""

    def test_first_run_seeds_ignore_before_the_shared_scan(self, tmp_path: Path) -> None:
        """A project's FIRST 'all' run keeps seed-excluded artifacts out of the versioned store."""

        root = tmp_path / "rustproj"
        (root / "app" / "src-tauri" / "target" / "debug" / "deps").mkdir(parents=True)
        (root / "app" / "src-tauri" / "target" / "debug" / "deps" / "big.rcgu.o").write_bytes(b"x" * 64)
        (root / "src").mkdir()
        (root / "src" / "main.rs").write_text("fn main() {}", encoding="utf-8")

        assert not (root / ".backupignore").exists()
        # Under the ceiling, 'all' goes on to run_drive_sync — keep the suite off the network.
        with patch("aipass.backup.apps.modules.drive_sync.run_drive_sync", return_value={}):
            assert handle_command("all", [str(root), "--quiet"]) is True

        store = build_versioned_store(str(root))
        leaked = list(store.rglob("*rcgu*")) if store.exists() else []
        assert leaked == [], f"seed-excluded artifacts reached the versioned store: {leaked}"


# =============================================
