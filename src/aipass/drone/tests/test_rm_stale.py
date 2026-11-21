# =================== AIPass ====================
# Name: test_rm_stale.py
# Description: drone rm --stale: the stale-temp sweep, its age, args, record and summary
# Version: 1.0.1
# Created: 2026-11-15
# Modified: 2026-11-20
# =============================================

"""Tests for apps/handlers/rm_handler.py's stale sweep and apps/modules/rm.py's --stale lane."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(covered_elsewhere) — the deletion record's contents, pinned in tests/test_deletion_log.py
# sentry: no-test-needed(covered_elsewhere) — containment and the fences, pinned in tests/test_rm.py

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.drone.apps.handlers.rm_handler import (
    format_age,
    format_stale_summary,
    parse_age,
    parse_stale_args,
    safe_delete,
    stale_sweep,
)
from aipass.drone.apps.modules.rm import handle_command

from .conftest import logged_lines, rail_answers, rm_ledger

#: A mode-0 folder only stops a caller the kernel holds to permissions: not as root.
_PERMISSIONS_DO_NOT_BIND = os.geteuid() == 0
_PERMISSIONS_REASON = "needs file permissions that bind the caller"


@pytest.fixture(autouse=True)
def _a_citizen_seat(monkeypatch):
    """The verified-admin rail says no: run from the admin seat, the real rail says yes and the plain verb crosses."""
    rail_answers(monkeypatch, False)


# Stale mode crosses the sibling fence on purpose: the fixture stands in @drone and sweeps @api,
# so a lost crossing turns the whole block red, not one test.

_DAY = 86_400

#: The twelve keys a plain delete record has always carried.
_PLAIN_RECORD_KEYS = {
    "timestamp",
    "lane",
    "outcome",
    "caller",
    "cwd",
    "requested",
    "path",
    "reason",
    "kind",
    "size_bytes",
    "entry_count",
    "measured",
}


def _aged(path: Path, age_seconds: float, body: str = "x") -> Path:
    """Write *path* and backdate its mtime by *age_seconds*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    then = time.time() - age_seconds
    os.utime(path, (then, then))
    return path


def _sweep(*tokens: str):
    return stale_sweep(parse_stale_args(list(tokens)))


@pytest.fixture()
def stale_tree(project_with_branches, monkeypatch):
    """@drone stands at home; @api's tree holds one stale temp and one of each skip."""
    monkeypatch.chdir(project_with_branches / "src" / "aipass" / "drone")
    api = project_with_branches / "src" / "aipass" / "api"
    return {
        "api": api,
        "stale": _aged(api / "api_json" / "tmpab12cd.tmp", 11 * _DAY, "abc"),
        "young": _aged(api / "api_json" / ".4242_7.tmp", 9 * _DAY),
        "not_tmp": _aged(api / "api_json" / "api_log.json", 11 * _DAY),
        "not_json_folder": _aged(api / "scratch" / "old.tmp", 11 * _DAY),
    }


class TestStaleAge:
    @pytest.mark.parametrize(("text", "seconds"), [("10d", 864_000), ("36h", 129_600), ("90m", 5_400)])
    def test_the_three_forms(self, text, seconds):
        assert parse_age(text) == seconds

    @pytest.mark.parametrize("text", ["10", "10s", "2w", "d", "-5d", "10D", "1.5d", "10d ", "", "0d", "٣d"])
    def test_anything_else_is_refused_naming_the_three_forms(self, text):
        """Includes zero (a write in flight is younger than any real age) and a
        non-ASCII digit, which ``\\d`` would have matched and ``int()`` read."""
        with pytest.raises(ValueError) as caught:
            parse_age(text)
        message = str(caught.value)
        assert "10d" in message
        assert "36h" in message
        assert "90m" in message

    @pytest.mark.parametrize(
        ("seconds", "shown"), [(11 * _DAY + 3 * 3600 + 120, "11d3h"), (5_400, "1h30m"), (59, "0m")]
    )
    def test_format_age(self, seconds, shown):
        assert format_age(seconds) == shown


class TestStaleArgs:
    def test_flags_ride_in_any_slot(self):
        request = parse_stale_args(["a", "--dry-run", "--stale", "36h", "b"])
        assert (request.age, request.age_seconds, request.dry_run, request.dirs) == ("36h", 129_600, True, ("a", "b"))

    def test_the_equals_spelling_is_read(self):
        request = parse_stale_args(["--stale=90m", "a"])
        assert (request.age, request.dry_run, request.dirs) == ("90m", False, ("a",))

    @pytest.mark.parametrize(
        "tokens",
        [
            ["--stale"],
            ["--stale", "10d"],
            ["--stale", "10d", "--dryrun", "a"],
            ["--stale", "10d", "--stale", "5d", "a"],
            ["--staleness", "a"],
            ["--stale", "--dry-run", "a"],
        ],
        ids=["no-age", "no-dir", "typo-dry-run", "twice", "unknown-spelling", "flag-in-age-slot"],
    )
    def test_malformed_requests_are_refused(self, tokens):
        with pytest.raises(ValueError):
            parse_stale_args(tokens)


class TestStaleSweep:
    def test_the_stale_tmp_in_a_json_folder_is_deleted(self, stale_tree):
        report = _sweep("--stale", "10d", str(stale_tree["api"]))
        assert not stale_tree["stale"].exists()
        assert (report.deleted, report.refusals) == (1, [])

    def test_a_dot_named_stale_tmp_is_deleted_without_dot(self, stale_tree):
        """The atomic-write leftovers are dot names; the dot guard is the plain lane's, not this sweep's."""
        leftover = _aged(stale_tree["api"] / "api_json" / ".999558_87.tmp", 11 * _DAY)
        _sweep("--stale", "10d", str(stale_tree["api"]))
        assert not leftover.exists()

    @pytest.mark.parametrize("survivor", ["young", "not_tmp", "not_json_folder"])
    def test_the_three_skip_rules(self, stale_tree, survivor):
        """Younger than AGE, not named .tmp, not inside a _json folder: untouched."""
        _sweep("--stale", "10d", str(stale_tree["api"]))
        assert stale_tree[survivor].exists()

    def test_the_parent_folder_is_the_one_that_counts(self, stale_tree):
        """A _json GRANDPARENT is not enough — the rule reads the parent's name."""
        deeper = _aged(stale_tree["api"] / "api_json" / "sub" / "old.tmp", 11 * _DAY)
        _sweep("--stale", "10d", str(stale_tree["api"]))
        assert deeper.exists()

    def test_a_symlink_named_tmp_is_skipped(self, stale_tree):
        """The LINK is aged too, so only the regular-file rule can spare it."""
        target = _aged(stale_tree["api"] / "elsewhere" / "real.tmp", 11 * _DAY)
        link = stale_tree["api"] / "api_json" / "link.tmp"
        link.symlink_to(target)
        then = time.time() - 11 * _DAY
        os.utime(link, (then, then), follow_symlinks=False)

        report = _sweep("--stale", "10d", str(stale_tree["api"]))

        assert link.is_symlink()
        assert target.exists()
        assert report.matched == 1

    def test_a_directory_named_tmp_is_skipped(self, stale_tree):
        folder = stale_tree["api"] / "api_json" / "held.tmp"
        folder.mkdir()
        then = time.time() - 11 * _DAY
        os.utime(folder, (then, then))
        _sweep("--stale", "10d", str(stale_tree["api"]))
        assert folder.is_dir()

    def test_the_walk_never_enters_a_carve_out(self, stale_tree):
        hidden = _aged(stale_tree["api"] / ".trinity" / "trinity_json" / "old.tmp", 11 * _DAY)
        _sweep("--stale", "10d", str(stale_tree["api"]))
        assert hidden.exists()

    @pytest.mark.parametrize("sandbox", [".archive", "dropbox"])
    def test_the_walk_never_enters_a_sandbox_and_the_stale_temp_beside_it_goes(self, stale_tree, sandbox):
        """Nothing looks into a dropbox or an .archive (owner ruling).

        Mutant killed: _find_stale's sandbox prune dropped (both ids)."""
        kept = _aged(stale_tree["api"] / sandbox / "api_json" / "old.tmp", 11 * _DAY)
        _sweep("--stale", "10d", str(stale_tree["api"]))
        assert kept.exists()
        assert not stale_tree["stale"].exists()

    def test_a_carve_out_dir_is_refused_and_recorded(self, stale_tree, tmp_path):
        trinity = stale_tree["api"] / ".trinity"
        hidden = _aged(trinity / "trinity_json" / "old.tmp", 11 * _DAY)

        report = _sweep("--stale", "10d", str(trinity))

        assert hidden.exists()
        assert len(report.refusals) == 1
        assert "Protected directory" in report.refusals[0]
        (record,) = rm_ledger(tmp_path)
        assert (record["outcome"], record["mode"], record["age"]) == ("refused", "stale", "10d")

    def test_a_dir_outside_the_project_is_refused(self, stale_tree, tmp_path_factory):
        """Outside the project but inside the system temp dir: the plain lane's
        temp roots are not swept here."""
        outside = tmp_path_factory.mktemp("outside")
        litter = _aged(outside / "x_json" / "old.tmp", 11 * _DAY)

        report = _sweep("--stale", "10d", str(outside))

        assert litter.exists()
        assert "outside allowed roots" in report.refusals[0]

    def test_a_missing_dir_is_a_refusal(self, stale_tree, tmp_path):
        report = _sweep("--stale", "10d", str(stale_tree["api"] / "nope"))
        assert "does not exist" in report.refusals[0]
        assert rm_ledger(tmp_path)[0]["outcome"] == "not_found"

    def test_a_refused_dir_logs_info_like_every_deliberate_refusal(self, stale_tree):
        with patch("aipass.drone.apps.handlers.rm_handler.logger") as log:
            _sweep("--stale", "10d", str(stale_tree["api"] / ".trinity"))

        assert not log.warning.called
        assert any("refused" in line for line in logged_lines(log.info))

    @pytest.mark.parametrize("dry_run", [False, True])
    @pytest.mark.parametrize("nested_first", [False, True])
    def test_overlapping_dirs_walk_each_folder_once(self, stale_tree, nested_first, dry_run):
        """A real run hides a double walk — the first pass already unlinked what
        the second would list — so the folder count and the dry run carry it."""
        dirs = [str(stale_tree["api"]), str(stale_tree["api"] / "api_json")]
        if nested_first:
            dirs.reverse()
        report = _sweep("--stale", "10d", *(["--dry-run"] if dry_run else []), *dirs)
        assert (report.folders_scanned, report.matched, report.refusals) == (3, 1, [])


class TestStaleCrossesTheSiblingFence:
    def test_stale_mode_deletes_inside_a_sibling_branch(self, stale_tree):
        assert handle_command("--stale", ["10d", str(stale_tree["api"])]) is True
        assert not stale_tree["stale"].exists()

    def test_the_plain_verb_still_refuses_the_same_file(self, stale_tree, tmp_path):
        assert handle_command(str(stale_tree["stale"])) is False
        assert stale_tree["stale"].exists()
        assert "sibling branch api" in rm_ledger(tmp_path)[0]["reason"]


class TestStaleDryRun:
    def test_dry_run_lists_every_candidate_and_deletes_nothing(self, stale_tree, capsys, tmp_path):
        assert handle_command("--stale", ["10d", "--dry-run", str(stale_tree["api"])]) is True

        out = capsys.readouterr().out
        assert stale_tree["stale"].exists()
        candidate_lines = [line for line in out.splitlines() if "would delete" in line]
        assert len(candidate_lines) == 1
        assert str(stale_tree["stale"].resolve()) in candidate_lines[0]
        assert "11d0h" in candidate_lines[0]
        assert "3 B" in candidate_lines[0]
        assert "files deleted 0" in out.splitlines()[-1]
        assert rm_ledger(tmp_path) == [], "a dry run deletes nothing, so it records nothing"

    def test_a_dry_run_refusal_prints_and_fails_but_is_not_recorded(self, stale_tree, tmp_path):
        """No delete was attempted, so the ledger has nothing to say about it."""
        assert handle_command("--stale", ["10d", "--dry-run", str(stale_tree["api"] / "nope")]) is False
        assert rm_ledger(tmp_path) == []


class TestStaleRecord:
    def test_a_stale_delete_is_recorded_with_mode_and_age(self, stale_tree, tmp_path):
        _sweep("--stale", "10d", str(stale_tree["api"]))

        (record,) = rm_ledger(tmp_path)
        assert record["path"] == str(stale_tree["stale"].resolve())
        assert (record["lane"], record["outcome"], record["mode"], record["age"]) == ("rm", "deleted", "stale", "10d")
        assert record["requested"] == str(stale_tree["api"])
        assert record["size_bytes"] == 3

    def test_a_plain_move_keeps_its_twelve_keys_plus_where_it_went(self, project_dir, monkeypatch, tmp_path):
        """Without --stale there is no mode key; a move adds moved_to and nothing else."""
        monkeypatch.chdir(project_dir)
        target = project_dir / "build.log"
        target.write_text("x", encoding="utf-8")
        safe_delete([str(target)])
        (record,) = rm_ledger(tmp_path)
        assert set(record) == _PLAIN_RECORD_KEYS | {"moved_to"}


class TestStaleSummary:
    def test_the_summary_line_counts(self, stale_tree, capsys):
        """api, api_json and scratch are walked; .trinity is not."""
        _aged(stale_tree["api"] / "api_json" / "tmpzz99.tmp", 30 * _DAY, "defg")

        assert handle_command("--stale", ["10d", str(stale_tree["api"])]) is True

        assert capsys.readouterr().out.splitlines()[-1] == (
            "rm --stale 10d (swept): folders scanned 3, files matched 2 (7 bytes), "
            "files deleted 2, bytes freed 7, refusals 0"
        )

    def test_the_summary_is_rendered_from_the_report(self, stale_tree):
        request = parse_stale_args(["--stale", "10d", "--dry-run", str(stale_tree["api"])])
        assert format_stale_summary(request, stale_sweep(request)) == (
            "rm --stale 10d (dry run): folders scanned 3, files matched 1 (3 bytes), "
            "files deleted 0, bytes freed 0, refusals 0"
        )

    def test_nothing_matched_is_a_success(self, stale_tree, capsys):
        assert handle_command("--stale", ["10d", str(stale_tree["api"] / "scratch")]) is True
        assert "files matched 0" in capsys.readouterr().out

    def test_a_refusal_fails_the_run(self, stale_tree):
        assert handle_command("--stale", ["10d", str(stale_tree["api"] / "nope")]) is False

    @pytest.mark.skipif(_PERMISSIONS_DO_NOT_BIND, reason=_PERMISSIONS_REASON)
    def test_an_unreadable_folder_is_a_refusal_not_a_silence(self, stale_tree):
        locked = stale_tree["api"] / "locked_json"
        locked.mkdir()
        locked.chmod(0)
        try:
            report = _sweep("--stale", "10d", str(stale_tree["api"]))
        finally:
            locked.chmod(0o700)
        assert any("Cannot scan" in message for message in report.refusals)


class TestStaleNeverFallsIntoThePlainLane:
    def test_a_stale_flag_after_the_dir_still_selects_stale_mode(self, stale_tree, monkeypatch):
        """Standing in @api, the plain lane would remove api_json whole."""
        monkeypatch.chdir(stale_tree["api"])
        assert handle_command("api_json", ["--stale", "10d"]) is True
        assert not stale_tree["stale"].exists()
        assert stale_tree["young"].exists()

    @pytest.mark.parametrize(
        "tokens",
        [["--stale=", "api_json"], ["--staleness", "api_json"], ["--stale", "10d", "--dryrun", "api_json"]],
        ids=["empty-age", "unknown-spelling", "typo-dry-run"],
    )
    def test_a_malformed_stale_request_deletes_nothing(self, stale_tree, monkeypatch, tokens):
        monkeypatch.chdir(stale_tree["api"])
        assert handle_command(tokens[0], tokens[1:]) is False
        assert stale_tree["stale"].exists()
        assert stale_tree["young"].exists()
