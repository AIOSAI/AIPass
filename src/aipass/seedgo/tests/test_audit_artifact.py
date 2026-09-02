"""Tests for the audit artifact writer (handlers/audit/artifact.py).

The core regression is the reason the artifact exists: audit_display.py caps at
10 files, 3 diagnostics per file and 5 violations per standard, and clips
messages at 60 chars. A consumer that read that display as complete published a
violation count that never existed. These tests build a result set BIGGER than
every one of those caps and assert the artifact still carries all of it.
"""

# =================== META ====================
# Name: test_audit_artifact.py
# Description: Completeness + join-key tests for audit/artifact.py
# Version: 1.0.0
# Created: 2026-08-11
# Modified: 2026-08-11
# =============================================

# seedgo:bypass standard=architecture reason="test files live in tests/, not apps/"
# seedgo:bypass standard=encapsulation reason="tests import handlers directly for unit testing"

import json
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.audit import artifact as audit_artifact


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Deliberately longer than the display's 60-char clip.
LONG_MESSAGE = (
    "Line 412 uses a bare print() instead of the cli console, which means the "
    "output bypasses Rich styling and stderr routing entirely"
)


@pytest.fixture(autouse=True)
def _quiet_json_handler(monkeypatch):
    """Keep the operation log out of seedgo_json/ during tests."""
    monkeypatch.setattr(audit_artifact.json_handler, "log_operation", lambda *a, **k: True)


def _make_results(branch_root: Path, file_count: int = 14):
    """One branch result carrying file_count files x 2 standards of findings.

    14 files beats the display's 10-file cap; 2 standards x 14 files = 28
    violations beats its 5-per-standard cap.
    """
    cli_violations = []
    naming_violations = []
    for i in range(file_count):
        rel = f"apps/modules/module_{i:02d}.py"
        abs_path = str(branch_root / rel)
        cli_violations.append(
            {
                "file": f"module_{i:02d}.py",
                "path": abs_path,
                "score": 50,
                "issues": [f"{LONG_MESSAGE} (file {i})"],
                "message": f"{LONG_MESSAGE} (file {i})",
            }
        )
        naming_violations.append(
            {
                "file": f"module_{i:02d}.py",
                "path": abs_path,
                "score": 60,
                "issues": [f"snake_case violation number {i}"],
                "message": f"snake_case violation number {i}",
            }
        )

    return [
        {
            "branch": {"name": "PRAX", "path": str(branch_root), "entry_file": str(branch_root / "apps/prax.py")},
            "scores": {"cli": 50, "naming": 60, "architecture": 80},
            "advisory_standards": [],
            "average": 63,
            "files_checked": file_count,
            "elapsed": 1.5,
            "cli_violations": cli_violations,
            "naming_violations": naming_violations,
            "results": {
                "architecture": {
                    "score": 80,
                    "checks": [
                        {"name": "Dir: apps/handlers", "passed": True, "message": "found"},
                        {"name": "File: README.md", "passed": False, "message": f"missing — {LONG_MESSAGE}"},
                    ],
                }
            },
            "type_errors": 8,
            "type_error_files": [
                {
                    "file": str(branch_root / "apps/modules/typed.py"),
                    "errors": 8,
                    "warnings": 1,
                    # 8 diagnostics — the display shows 3 per file.
                    "diagnostics": [
                        {"line": 10 + n, "severity": "error", "message": f"{LONG_MESSAGE} (diag {n})", "rule": "rt"}
                        for n in range(8)
                    ],
                }
            ],
            "info_lines": [{"standard": "bypass", "message": "2 inert rules"}],
            "deprecated_patterns": [],
            "test_map": None,
        }
    ]


def _write_and_load(tmp_path: Path, results, **kwargs) -> dict:
    """Write the artifact to tmp_path and read it back as parsed JSON."""
    out = audit_artifact.write_audit_artifact(results, output_path=tmp_path / "out" / "audit.json", **kwargs)
    return json.loads(out.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Completeness — the core regression
# ---------------------------------------------------------------------------


def test_all_violations_survive_display_caps(tmp_path):
    """14 files x 2 standards = 28 violations, plus 2 more — all 30 must land."""
    branch_root = tmp_path / "prax"
    results = _make_results(branch_root)
    # Two extra on a third standard, for a round 30.
    results[0]["scores"]["imports"] = 40
    results[0]["imports_violations"] = [
        {
            "file": "extra_a.py",
            "path": str(branch_root / "apps/handlers/extra_a.py"),
            "score": 40,
            "issues": ["bare import"],
            "message": "bare import",
        },
        {
            "file": "extra_b.py",
            "path": str(branch_root / "apps/handlers/extra_b.py"),
            "score": 40,
            "issues": ["bare import"],
            "message": "bare import",
        },
    ]

    doc = _write_and_load(tmp_path, results)

    assert len(doc["violations"]) == 30
    assert doc["metadata"]["totals"]["violations"] == 30
    # Every one of the 14 files is present, not just the display's first 10.
    cli_files = {v["file"] for v in doc["violations"] if v["standard"] == "cli"}
    assert len(cli_files) == 14
    assert "apps/modules/module_13.py" in cli_files


def test_all_diagnostics_survive_per_file_cap(tmp_path):
    """The display shows 3 diagnostics per file; the artifact keeps all 8."""
    branch_root = tmp_path / "prax"
    doc = _write_and_load(tmp_path, _make_results(branch_root))

    assert len(doc["type_errors"]) == 1
    diagnostics = doc["type_errors"][0]["diagnostics"]
    assert len(diagnostics) == 8
    assert {d["line"] for d in diagnostics} == set(range(10, 18))
    assert doc["metadata"]["totals"]["type_errors"] == 8


def test_messages_are_not_clipped_at_60_chars(tmp_path):
    """No 60-char clip, no ellipsis — full text in message, issues and diagnostics."""
    branch_root = tmp_path / "prax"
    doc = _write_and_load(tmp_path, _make_results(branch_root))

    violation = next(v for v in doc["violations"] if v["standard"] == "cli")
    assert len(LONG_MESSAGE) > 60
    assert violation["message"] == f"{LONG_MESSAGE} (file 0)"
    assert violation["issues"] == [f"{LONG_MESSAGE} (file 0)"]
    assert "…" not in violation["message"]

    diag = doc["type_errors"][0]["diagnostics"][0]
    assert diag["message"] == f"{LONG_MESSAGE} (diag 0)"

    failed = next(c for c in doc["failed_checks"] if c["standard"] == "architecture")
    assert failed["message"] == f"missing — {LONG_MESSAGE}"


def test_branch_level_failed_checks_are_kept(tmp_path):
    """Architecture-style findings live only in results[std]['checks'] — keep them."""
    branch_root = tmp_path / "prax"
    doc = _write_and_load(tmp_path, _make_results(branch_root))

    names = [c["name"] for c in doc["failed_checks"]]
    assert names == ["File: README.md"]  # the passing check is not a finding
    assert doc["metadata"]["totals"]["failed_checks"] == 1


# ---------------------------------------------------------------------------
# Join keys — (file, standard) against .seedgo/bypass.json
# ---------------------------------------------------------------------------


def test_violations_carry_branch_relative_file_and_standard(tmp_path):
    """Join keys are explicit fields, matching bypass.json's 'file' + 'standard'."""
    branch_root = tmp_path / "prax"
    doc = _write_and_load(tmp_path, _make_results(branch_root))

    violation = next(v for v in doc["violations"] if v["standard"] == "cli" and v["file_name"] == "module_03.py")
    # bypass.json rules are written as branch-relative POSIX paths.
    assert violation["file"] == "apps/modules/module_03.py"
    assert violation["standard"] == "cli"
    assert violation["branch"] == "PRAX"
    assert violation["abs_path"] == str(branch_root / "apps/modules/module_03.py")


def test_join_against_bypass_rules_needs_no_string_parsing(tmp_path):
    """A real (file, standard) join: one bypass rule matches exactly one row."""
    branch_root = tmp_path / "prax"
    doc = _write_and_load(tmp_path, _make_results(branch_root))

    bypass_rules = [{"file": "apps/modules/module_07.py", "standard": "naming", "reason": "intentional"}]
    keys = {(r["file"], r["standard"]) for r in bypass_rules}
    matched = [v for v in doc["violations"] if (v["file"], v["standard"]) in keys]

    assert len(matched) == 1
    assert matched[0]["file_name"] == "module_07.py"


def test_relative_paths_from_checkers_pass_through(tmp_path):
    """Some checkers report relative paths already — those stay as-is."""
    branch_root = tmp_path / "prax"
    results = _make_results(branch_root, file_count=1)
    results[0]["cli_violations"] = [
        {"file": "apps/modules/rel.py", "score": 0, "issues": ["x"], "message": "x"},
    ]
    doc = _write_and_load(tmp_path, results)

    row = next(v for v in doc["violations"] if v["standard"] == "cli")
    assert row["file"] == "apps/modules/rel.py"


def test_type_errors_carry_join_keys(tmp_path):
    """Diagnostics rows join the same way, under the 'diagnostics' standard."""
    branch_root = tmp_path / "prax"
    doc = _write_and_load(tmp_path, _make_results(branch_root))

    row = doc["type_errors"][0]
    assert row["file"] == "apps/modules/typed.py"
    assert row["standard"] == "diagnostics"
    assert row["branch"] == "PRAX"


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_metadata_block_is_well_formed(tmp_path):
    """Schema version, ISO-8601 timestamp, version, branches, scope."""
    from datetime import datetime

    branch_root = tmp_path / "prax"
    doc = _write_and_load(tmp_path, _make_results(branch_root), pack="aipass", specific_branch="PRAX")
    meta = doc["metadata"]

    assert meta["schema_version"] == audit_artifact.SCHEMA_VERSION
    # Parses as ISO-8601 and carries a timezone.
    parsed = datetime.fromisoformat(meta["generated_at"])
    assert parsed.tzinfo is not None
    assert meta["pack"] == "aipass"
    assert meta["scope"] == "single-branch"
    assert meta["target_branch"] == "PRAX"
    assert meta["branches"] == ["PRAX"]
    assert meta["branch_count"] == 1
    assert set(meta["totals"]) == {"violations", "failed_checks", "type_error_files", "type_errors"}


def test_scope_is_full_fleet_without_a_target_branch(tmp_path):
    branch_root = tmp_path / "prax"
    doc = _write_and_load(tmp_path, _make_results(branch_root), pack="aipass")

    assert doc["metadata"]["scope"] == "full-fleet"
    assert doc["metadata"]["target_branch"] is None


def test_branch_entries_carry_scores_and_counts(tmp_path):
    branch_root = tmp_path / "prax"
    doc = _write_and_load(tmp_path, _make_results(branch_root))
    entry = doc["branches"][0]

    assert entry["name"] == "PRAX"
    assert entry["average"] == 63
    assert entry["scores"]["cli"] == 50
    assert entry["files_checked"] == 14
    assert entry["violation_count"] == 28
    assert entry["type_errors"] == 8
    assert entry["cache_hit"] is False


def test_multiple_branches_all_appear(tmp_path):
    """A fleet run keeps every branch's rows, each self-identifying."""
    first = _make_results(tmp_path / "prax", file_count=3)
    second = _make_results(tmp_path / "flow", file_count=4)
    second[0]["branch"]["name"] = "FLOW"

    doc = _write_and_load(tmp_path, first + second)

    assert doc["metadata"]["branches"] == ["PRAX", "FLOW"]
    assert len([v for v in doc["violations"] if v["branch"] == "PRAX"]) == 6
    assert len([v for v in doc["violations"] if v["branch"] == "FLOW"]) == 8


# ---------------------------------------------------------------------------
# Failure surfacing + paths
# ---------------------------------------------------------------------------


def test_write_failure_raises_rather_than_passing_silently(tmp_path):
    """A file where the parent directory should be — must raise, not no-op."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    results = _make_results(tmp_path / "prax", file_count=1)

    with pytest.raises(OSError):
        audit_artifact.write_audit_artifact(results, output_path=blocker / "sub" / "audit.json")


def test_default_path_is_derived_not_hardcoded(tmp_path):
    """Default lands in seedgo's own .seedgo/, derived from the handler's location."""
    default = audit_artifact.default_artifact_path()

    assert default.name == "last_audit.json"
    assert default.parent.name == ".seedgo"
    # Derived from this checkout, wherever it lives.
    assert default.parent.parent == Path(audit_artifact.__file__).resolve().parents[3]
    assert default.parent.parent.name == "seedgo"


def test_scoped_run_does_not_clobber_the_fleet_artifact(tmp_path):
    """A single-branch run writes its own file; last_audit.json stays fleet-only.

    @prax ran 'audit aipass @prax' and it overwrote last_audit.json with a
    one-branch document. metadata.scope was honest, but a consumer reading the
    file cold measured one branch and concluded the other 16 were clean.
    """
    scoped = audit_artifact.default_artifact_path("prax")
    fleet = audit_artifact.default_artifact_path()

    assert scoped != fleet
    assert scoped.name == "last_audit_prax.json"
    assert scoped.parent == fleet.parent


def test_no_bypass_run_does_not_clobber_the_normal_artifact(tmp_path):
    """A --no-bypass run writes its own file — same tree, deliberately lower numbers.

    Identical hazard to the scoped-run one above: a consumer reading
    last_audit.json cold has no way to know the run that produced it had every
    bypass rule switched off, and would publish the raw score as the real one.
    """
    fleet = audit_artifact.default_artifact_path()
    fleet_raw = audit_artifact.default_artifact_path(no_bypass=True)
    scoped_raw = audit_artifact.default_artifact_path("prax", no_bypass=True)

    assert fleet_raw != fleet
    assert fleet_raw.name == "last_audit_no_bypass.json"
    assert scoped_raw.name == "last_audit_prax_no_bypass.json"
    assert scoped_raw != audit_artifact.default_artifact_path("prax")


def test_a_second_pack_does_not_clobber_the_aipass_fleet_record(tmp_path):
    """A non-default pack writes its own file; last_audit.json stays the aipass record.

    THE LIVE DEFECT, found by running the shadow cycle: `audit pytest_quality`
    is a fleet run with no flags, so it took the same path as `audit aipass`
    and overwrote last_audit.json with a 12-standard shadow score that gates
    nothing. The file sat that way for ~25 minutes. A consumer reading it cold
    expects the 47-standard compliance record and would have measured a pack
    whose numbers nobody may act on.

    Identical in kind to the scoped-run and no-bypass hazards pinned above, and
    the cure is theirs: the pack is part of the name. `aipass` stays unsuffixed
    because it IS the compliance record every existing consumer already reads.
    """
    fleet = audit_artifact.default_artifact_path()
    shadow = audit_artifact.default_artifact_path(pack="pytest_quality")

    assert shadow != fleet
    assert shadow.name == "last_audit_pack_pytest_quality.json"
    assert shadow.parent == fleet.parent


def test_the_default_pack_keeps_the_historical_artifact_name(tmp_path):
    """`aipass` and an unstated pack both answer last_audit.json.

    The counter-arm, and it is load-bearing: CI and every saved consumer read
    that exact name. A cure that renamed the aipass artifact would fix the
    collision by breaking the thing the collision endangered.
    """
    assert audit_artifact.default_artifact_path(pack="aipass") == audit_artifact.default_artifact_path()
    assert audit_artifact.default_artifact_path(pack=None).name == "last_audit.json"
    assert audit_artifact.default_artifact_path(pack="aipass", specific_branch="prax").name == "last_audit_prax.json"


def test_pack_and_branch_and_bypass_all_discriminate_together(tmp_path):
    """Three axes, three suffixes, no pair collides.

    Pinned because the defect was precisely one axis missing from a function
    that already handled the other two: partial discrimination reads as full
    discrimination at the call site.
    """
    paths = {
        audit_artifact.default_artifact_path(),
        audit_artifact.default_artifact_path(specific_branch="prax"),
        audit_artifact.default_artifact_path(no_bypass=True),
        audit_artifact.default_artifact_path(pack="pytest_quality"),
        audit_artifact.default_artifact_path(pack="pytest_quality", specific_branch="prax"),
        audit_artifact.default_artifact_path(pack="pytest_quality", no_bypass=True),
        audit_artifact.default_artifact_path(pack="pytest_quality", specific_branch="prax", no_bypass=True),
    }

    assert len(paths) == 7


def test_no_bypass_write_lands_on_its_own_path(tmp_path, monkeypatch):
    """write_audit_artifact routes a --no-bypass run away from the normal file."""
    monkeypatch.setattr(audit_artifact, "_SEEDGO_ROOT", tmp_path)

    out = audit_artifact.write_audit_artifact(_make_results(tmp_path / "prax", file_count=1), no_bypass=True)

    assert out.name == "last_audit_no_bypass.json"
    assert not (tmp_path / ".seedgo" / "last_audit.json").exists()


def test_metadata_records_whether_bypasses_were_disabled(tmp_path):
    """metadata.no_bypass tells a consumer which number it is holding."""
    branch_root = tmp_path / "prax"

    raw = _write_and_load(tmp_path, _make_results(branch_root), no_bypass=True)
    normal = _write_and_load(tmp_path, _make_results(branch_root))

    assert raw["metadata"]["no_bypass"] is True
    assert normal["metadata"]["no_bypass"] is False


def test_scoped_write_lands_on_the_scoped_path(tmp_path, monkeypatch):
    """write_audit_artifact routes a scoped run to the scoped default."""
    monkeypatch.setattr(audit_artifact, "_SEEDGO_ROOT", tmp_path)

    out = audit_artifact.write_audit_artifact(_make_results(tmp_path / "prax", file_count=1), specific_branch="prax")

    assert out.name == "last_audit_prax.json"
    assert not (tmp_path / ".seedgo" / "last_audit.json").exists()


def test_fleet_write_still_lands_on_last_audit_json(tmp_path, monkeypatch):
    """A full-fleet run keeps the canonical name consumers already read."""
    monkeypatch.setattr(audit_artifact, "_SEEDGO_ROOT", tmp_path)

    out = audit_artifact.write_audit_artifact(_make_results(tmp_path / "prax", file_count=1))

    assert out.name == "last_audit.json"
    assert out == tmp_path / ".seedgo" / "last_audit.json"


def test_write_creates_missing_directories(tmp_path):
    """Destination directory is created on demand."""
    target = tmp_path / "deep" / "nested" / "audit.json"
    out = audit_artifact.write_audit_artifact(_make_results(tmp_path / "prax", file_count=1), output_path=target)

    assert out == target
    assert target.exists()


def test_empty_result_set_writes_a_valid_document(tmp_path):
    """No branches audited is still a well-formed artifact, not a crash."""
    doc = _write_and_load(tmp_path, [])

    assert doc["violations"] == []
    assert doc["branches"] == []
    assert doc["metadata"]["branch_count"] == 0
    assert doc["metadata"]["totals"]["violations"] == 0
