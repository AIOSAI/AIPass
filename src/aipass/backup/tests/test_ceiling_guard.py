# =================== AIPass ====================
# Name: test_ceiling_guard.py
# Description: Tests for the per-run size/file-count ceiling (runaway guard)
# Version: 1.0.0
# Created: 2026-08-20
# Modified: 2026-08-20
# =============================================

"""Tests for the per-run backup ceiling.

Regression origin: 'drone @backup all @baud' ran 01:14 -> 08:50 copying an
18GB Rust src-tauri/target tree that .backupignore did not cover, writing
50GB of build artifacts. Nothing measured the run, so nothing objected.
"""

from pathlib import Path
from unittest.mock import patch


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
    """check_ceiling measures the filtered set before any copying."""

    def test_under_both_limits_returns_none(self, tmp_path: Path) -> None:
        """A normal project passes and the run proceeds."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan.ceiling import check_ceiling

            files = _files(tmp_path, ["src/a.py", "src/b.py"])
            assert check_ceiling(files, {"max_backup_files": 10, "max_backup_size_gb": 10}) is None

    def test_file_count_breach(self, tmp_path: Path) -> None:
        """More files than the ceiling refuses the run."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan.ceiling import check_ceiling

            files = _files(tmp_path, [f"t/{i}.o" for i in range(6)])
            breach = check_ceiling(files, {"max_backup_files": 5, "max_backup_size_gb": 10})
            assert breach is not None
            assert breach.reason == "file_count"
            assert breach.measured == 6
            assert breach.limit == 5
            assert breach.config_key == "max_backup_files"

    def test_equal_to_limit_is_allowed(self, tmp_path: Path) -> None:
        """The ceiling is a maximum, not an exclusive bound."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan.ceiling import check_ceiling

            files = _files(tmp_path, [f"t/{i}.o" for i in range(5)])
            assert check_ceiling(files, {"max_backup_files": 5, "max_backup_size_gb": 10}) is None

    def test_total_size_breach(self, tmp_path: Path) -> None:
        """Total bytes over the ceiling refuses even when the file count is small."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan.ceiling import check_ceiling

            files = _files(tmp_path, ["big/blob.bin"], size=4096)
            breach = check_ceiling(
                files,
                {"max_backup_files": 1000, "max_backup_size_gb": 0.000001},
            )
            assert breach is not None
            assert breach.reason == "total_size"
            assert breach.config_key == "max_backup_size_gb"

    def test_zero_disables_file_ceiling(self, tmp_path: Path) -> None:
        """max_backup_files=0 means unlimited, for a project that really is huge."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan.ceiling import check_ceiling

            files = _files(tmp_path, [f"t/{i}.o" for i in range(20)])
            assert check_ceiling(files, {"max_backup_files": 0, "max_backup_size_gb": 0}) is None

    def test_zero_disables_size_ceiling(self, tmp_path: Path) -> None:
        """max_backup_size_gb=0 skips the byte pass entirely."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan.ceiling import check_ceiling

            files = _files(tmp_path, ["big/blob.bin"], size=4096)
            assert check_ceiling(files, {"max_backup_files": 1000, "max_backup_size_gb": 0}) is None

    def test_count_breach_skips_the_stat_pass(self, tmp_path: Path) -> None:
        """A count breach must not stat the tree it is refusing.

        The whole point is to fail fast: statting 300k files to confirm a
        refusal already decided is the grind we are preventing.
        """
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan import ceiling

            files = _files(tmp_path, [f"t/{i}.o" for i in range(6)])
            with patch.object(ceiling.os.path, "getsize", side_effect=AssertionError("statted")):
                breach = ceiling.check_ceiling(files, {"max_backup_files": 5, "max_backup_size_gb": 10})
            assert breach is not None

    def test_vanished_file_does_not_abort_measurement(self, tmp_path: Path) -> None:
        """A file gone between filter and measure contributes nothing, never raises."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan.ceiling import check_ceiling

            files = _files(tmp_path, ["src/a.py"])
            files.append((str(tmp_path / "src" / "ghost.py"), "src/ghost.py"))
            assert check_ceiling(files, {"max_backup_files": 100, "max_backup_size_gb": 10}) is None

    def test_defaults_apply_when_config_is_empty(self, tmp_path: Path) -> None:
        """A config with no ceiling keys still gets the default ceilings."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan.ceiling import DEFAULT_MAX_FILES, check_ceiling

            assert DEFAULT_MAX_FILES > 0
            files = _files(tmp_path, ["src/a.py"])
            assert check_ceiling(files, {}) is None


# --- offender naming ---


class TestOffenderReporting:
    """The refusal must name the directory to add to .backupignore."""

    def test_names_the_rust_target_dir(self, tmp_path: Path) -> None:
        """baud's shape: the offender is app/src-tauri/target, not the deps leaf."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan.ceiling import check_ceiling

            rels = [f"app/src-tauri/target/debug/deps/o{i}.rcgu.o" for i in range(10)]
            rels += ["app/src/main.rs", "README.md"]
            breach = check_ceiling(_files(tmp_path, rels), {"max_backup_files": 5})
            assert breach is not None
            top_dir = breach.offenders[0][0]
            assert top_dir == "app/src-tauri/target"

    def test_offender_counts_are_real(self, tmp_path: Path) -> None:
        """The reported count matches the files under that directory."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan.ceiling import check_ceiling

            rels = [f"target/debug/o{i}.o" for i in range(7)]
            breach = check_ceiling(_files(tmp_path, rels), {"max_backup_files": 3})
            assert breach is not None
            assert breach.offenders[0] == ("target/debug", 7, 0)

    def test_root_level_files_group_under_dot(self, tmp_path: Path) -> None:
        """Files at the project root have no directory to blame."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan.ceiling import check_ceiling

            breach = check_ceiling(_files(tmp_path, ["a.txt", "b.txt", "c.txt"]), {"max_backup_files": 2})
            assert breach is not None
            assert breach.offenders[0][0] == "."

    def test_detail_lines_name_the_config_escape_hatch(self, tmp_path: Path) -> None:
        """The operator is told how to raise the ceiling deliberately."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan.ceiling import check_ceiling

            breach = check_ceiling(_files(tmp_path, [f"t/{i}.o" for i in range(6)]), {"max_backup_files": 5})
            assert breach is not None
            text = "\n".join(breach.detail_lines())
            assert "max_backup_files" in text
            assert ".backupignore" in text

    def test_summary_reads_as_a_refusal(self, tmp_path: Path) -> None:
        """summary() states the measurement and the ceiling."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan.ceiling import check_ceiling

            breach = check_ceiling(_files(tmp_path, [f"t/{i}.o" for i in range(6)]), {"max_backup_files": 5})
            assert breach is not None
            assert "6" in breach.summary()
            assert "5" in breach.summary()


# --- refusal is enforced end-to-end ---


class TestRunRefusal:
    """A breach must stop the run before a single byte is copied."""

    def _project(self, tmp_path: Path, n: int = 40, max_files: int = 5) -> Path:
        """Build a project whose heavy dir is NOT covered by .backupignore.

        Deliberately not named target/ or build/: those are now seeded into
        every .backupignore, so a fixture using them measures the ignore
        rule rather than the ceiling. The ceiling exists precisely for the
        artifact dir nobody has thought of yet.
        """
        import json

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
        from aipass.backup.apps.handlers.path.builder import build_snapshot_path
        from aipass.backup.apps.modules.snapshot import run_snapshot

        root = self._project(tmp_path)
        result = run_snapshot(str(root), show_panels=False)

        assert result.success is False
        assert result.files_copied == 0
        assert "refused" in result.errors[0].lower()
        dest = build_snapshot_path(str(root))
        assert not dest.exists() or not any(dest.rglob("*.blob"))

    def test_versioned_refuses_and_writes_no_store(self, tmp_path: Path) -> None:
        """run_versioned refuses over-ceiling and creates no versioned content."""
        from aipass.backup.apps.handlers.path.builder import build_versioned_store
        from aipass.backup.apps.modules.versioned import run_versioned

        root = self._project(tmp_path)
        result = run_versioned(str(root), show_panels=False)

        assert result.success is False
        assert result.files_copied == 0
        store = build_versioned_store(str(root))
        assert not store.exists() or not any(store.rglob("*.blob"))

    def test_versioned_refuses_a_pre_scanned_set(self, tmp_path: Path) -> None:
        """The 'all' path hands versioned a pre-scanned list — still measured.

        Before this guard, run_versioned skipped config entirely on the
        pre_scanned branch, so the orchestrated path was the unguarded one.
        """
        from aipass.backup.apps.handlers.path.builder import build_versioned_store
        from aipass.backup.apps.modules.versioned import run_versioned

        root = self._project(tmp_path)
        pre = [(str(p), str(p.relative_to(root))) for p in root.rglob("*") if p.is_file() and ".backup" not in p.parts]
        result = run_versioned(str(root), show_panels=False, pre_scanned=pre)

        assert result.success is False
        store = build_versioned_store(str(root))
        assert not store.exists() or not any(store.rglob("*.blob"))

    def test_all_refuses_before_either_store_is_written(self, tmp_path: Path) -> None:
        """'all' writes nothing on breach — belt and braces with the sub-guards."""
        from aipass.backup.apps.handlers.path.builder import build_snapshot_path, build_versioned_store
        from aipass.backup.apps.modules.all import handle_command

        root = self._project(tmp_path)
        assert handle_command("all", [str(root), "--quiet"]) is True

        store = build_versioned_store(str(root))
        dest = build_snapshot_path(str(root))
        assert not store.exists() or not any(store.rglob("*.blob"))
        assert not dest.exists() or not any(dest.rglob("*.blob"))

    def test_all_refuses_without_re_walking_the_tree(self, tmp_path: Path) -> None:
        """'all' must refuse on its own shared scan, not delegate to the sub-guards.

        This is what the guard in all.py buys: run_snapshot does its OWN full
        walk (it takes no pre_scanned), so letting the breach fall through
        means walking a runaway tree a second time before refusing it. On
        baud's 33k-file target tree that second walk is the expensive half
        of a refusal that should cost seconds.
        """
        from unittest.mock import patch as _patch

        from aipass.backup.apps.modules import all as all_mod

        root = self._project(tmp_path)
        with _patch.object(all_mod, "run_snapshot") as snap, _patch.object(all_mod, "run_versioned") as ver:
            assert all_mod.handle_command("all", [str(root), "--quiet"]) is True

        snap.assert_not_called()
        ver.assert_not_called()

    def test_under_ceiling_still_backs_up(self, tmp_path: Path) -> None:
        """The guard refuses runaways, not ordinary projects."""
        from aipass.backup.apps.modules.snapshot import run_snapshot

        root = self._project(tmp_path, n=3, max_files=100)
        result = run_snapshot(str(root), show_panels=False)

        assert result.success is True
        assert result.files_copied >= 1


class TestSharedScanSeeding:
    """The 'all' shared scan must run against a seeded .backupignore."""

    def test_first_run_seeds_ignore_before_the_shared_scan(self, tmp_path: Path) -> None:
        """A project's FIRST 'all' run must not back up what the seed excludes.

        create_backup_dir() is what writes .backupignore, and it used to run
        first inside run_snapshot — AFTER 'all' had already taken the shared
        scan. So on run one, load_spec() read a file that did not exist,
        returned an empty spec, and handed versioned every path the seed was
        about to exclude. Live-proven on a fresh Rust project: snapshot
        skipped target/ correctly while versioned copied it anyway. Both
        printed "3/3 files checked", which is what hid it.
        """
        from aipass.backup.apps.handlers.path.builder import build_versioned_store
        from aipass.backup.apps.modules.all import handle_command

        root = tmp_path / "rustproj"
        (root / "app" / "src-tauri" / "target" / "debug" / "deps").mkdir(parents=True)
        (root / "app" / "src-tauri" / "target" / "debug" / "deps" / "big.rcgu.o").write_bytes(b"x" * 64)
        (root / "src").mkdir()
        (root / "src" / "main.rs").write_text("fn main() {}", encoding="utf-8")

        assert not (root / ".backupignore").exists()
        # 'all' calls run_drive_sync unconditionally — keep the suite off the network.
        with patch("aipass.backup.apps.modules.drive_sync.run_drive_sync", return_value={}):
            assert handle_command("all", [str(root), "--quiet"]) is True

        store = build_versioned_store(str(root))
        leaked = list(store.rglob("*rcgu*")) if store.exists() else []
        assert leaked == [], f"seed-excluded artifacts reached the versioned store: {leaked}"


# =============================================


# =============================================
