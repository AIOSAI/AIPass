# =================== AIPass ====================
# Name: test_post_compact_regrounding.py
# Version: 1.0.0
# Description: Tests for post_compact_regrounding lifecycle handler (DPLAN-0276)
# Branch: hooks
# Created: 2026-08-01
# Modified: 2026-08-01
# =============================================

"""Tests for handlers/lifecycle/post_compact_regrounding.py.

Replays the DPLAN-0276 incident: PreCompact can fire several times back-to-back
with no intervening UserPromptSubmit, so cadence's normal turn-0 grounding path
never runs. This PostToolUse backstop must inject grounding content directly via
additionalContext the next time any tool runs, exactly once per compact, and
stay silent otherwise.
"""

import json
from unittest.mock import patch


class TestPostCompactRegrounding:
    def test_silent_when_nothing_pending(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding

        with patch("aipass.hooks.apps.modules.cadence.consume_regroup_pending", return_value=False):
            result = post_compact_regrounding.handle({"cwd": str(tmp_path)})

        assert result == {"stdout": "", "exit_code": 0}

    def test_injects_all_sections_when_pending(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding

        with (
            patch("aipass.hooks.apps.modules.cadence.consume_regroup_pending", return_value=True),
            patch("aipass.hooks.apps.modules.grounding_content.load_kernel", return_value="KERNEL"),
            patch("aipass.hooks.apps.modules.grounding_content.load_navmap", return_value="NAVMAP"),
            patch("aipass.hooks.apps.modules.grounding_content.load_branch", return_value="BRANCH"),
            patch("aipass.hooks.apps.modules.grounding_content.load_identity", return_value="IDENTITY"),
        ):
            result = post_compact_regrounding.handle({"cwd": str(tmp_path)})

        assert result["exit_code"] == 0
        assert result["sound"] == "post compact reground"
        payload = json.loads(result["stdout"])
        assert payload["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        context = payload["hookSpecificOutput"]["additionalContext"]
        assert "KERNEL" in context
        assert "NAVMAP" in context
        assert "BRANCH" in context
        assert "IDENTITY" in context
        assert "DPLAN-0276" in context

    def test_silent_when_pending_but_all_content_empty(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding

        with (
            patch("aipass.hooks.apps.modules.cadence.consume_regroup_pending", return_value=True),
            patch("aipass.hooks.apps.modules.grounding_content.load_kernel", return_value=""),
            patch("aipass.hooks.apps.modules.grounding_content.load_navmap", return_value=""),
            patch("aipass.hooks.apps.modules.grounding_content.load_branch", return_value=""),
            patch("aipass.hooks.apps.modules.grounding_content.load_identity", return_value=""),
        ):
            result = post_compact_regrounding.handle({"cwd": str(tmp_path)})

        assert result == {"stdout": "", "exit_code": 0}

    def test_one_loader_failing_does_not_block_the_others(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding

        with (
            patch("aipass.hooks.apps.modules.cadence.consume_regroup_pending", return_value=True),
            patch("aipass.hooks.apps.modules.grounding_content.load_kernel", side_effect=OSError("boom")),
            patch("aipass.hooks.apps.modules.grounding_content.load_navmap", return_value="NAVMAP"),
            patch("aipass.hooks.apps.modules.grounding_content.load_branch", return_value=""),
            patch("aipass.hooks.apps.modules.grounding_content.load_identity", return_value="IDENTITY"),
        ):
            result = post_compact_regrounding.handle({"cwd": str(tmp_path)})

        payload = json.loads(result["stdout"])
        context = payload["hookSpecificOutput"]["additionalContext"]
        assert "NAVMAP" in context
        assert "IDENTITY" in context

    def test_cadence_check_failure_is_silent(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding

        with patch("aipass.hooks.apps.modules.cadence.consume_regroup_pending", side_effect=RuntimeError("boom")):
            result = post_compact_regrounding.handle({"cwd": str(tmp_path)})

        assert result == {"stdout": "", "exit_code": 0}

    def test_end_to_end_replays_incident_multiple_resets_one_fire(self, tmp_path):
        """No mocking of cadence: several PreCompact resets fire back-to-back
        (the actual incident pattern), then the next tool call must reground
        exactly once and stay silent after that."""
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding
        from aipass.hooks.apps.modules import cadence

        cadence._turn = None
        cadence._config = None

        with (
            patch("aipass.hooks.apps.modules.cadence._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "incident-session"}),
            patch("aipass.hooks.apps.modules.grounding_content.load_kernel", return_value="KERNEL"),
            patch("aipass.hooks.apps.modules.grounding_content.load_navmap", return_value="NAVMAP"),
            patch("aipass.hooks.apps.modules.grounding_content.load_branch", return_value="BRANCH"),
            patch("aipass.hooks.apps.modules.grounding_content.load_identity", return_value="IDENTITY"),
        ):
            cadence.reset_counter()
            cadence.reset_counter()
            cadence.reset_counter()

            first = post_compact_regrounding.handle({"cwd": str(tmp_path)})
            second = post_compact_regrounding.handle({"cwd": str(tmp_path)})

        assert "KERNEL" in first["stdout"]
        assert second == {"stdout": "", "exit_code": 0}


class TestActiveStartupInstruction:
    """The passive half (kernel/navmap/branch/identity) re-injects itself; the ACTIVE
    half — re-read .trinity, refresh the dashboard — only ever ran off a greeting,
    and a mid-task post-compact continuation never gets one."""

    def _ground(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding

        with (
            patch("aipass.hooks.apps.modules.cadence.consume_regroup_pending", return_value=True),
            patch("aipass.hooks.apps.modules.grounding_content.load_kernel", return_value="KERNEL"),
            patch("aipass.hooks.apps.modules.grounding_content.load_navmap", return_value=""),
            patch("aipass.hooks.apps.modules.grounding_content.load_branch", return_value=""),
            patch("aipass.hooks.apps.modules.grounding_content.load_identity", return_value=""),
        ):
            result = post_compact_regrounding.handle({"cwd": str(tmp_path)})
        return json.loads(result["stdout"])["hookSpecificOutput"]["additionalContext"]

    def test_instruction_is_present(self, tmp_path):
        assert "ACTIVE RE-GROUNDING" in self._ground(tmp_path)

    def test_names_the_trinity_files_to_read(self, tmp_path):
        context = self._ground(tmp_path)
        for name in ("passport.json", "local.json", "observations.json"):
            assert name in context

    def test_names_the_dashboard_refresh(self, tmp_path):
        context = self._ground(tmp_path)
        assert "drone @prax dashboard refresh" in context
        assert "DASHBOARD.local.json" in context

    def test_instruction_precedes_the_injected_content(self, tmp_path):
        """It says 'do this BEFORE resuming' — it has to arrive before the wall of
        re-injected prompt text, not buried under it."""
        context = self._ground(tmp_path)
        assert context.index("ACTIVE RE-GROUNDING") < context.index("KERNEL")

    def test_keeps_the_newest_first_memory_reminder(self, tmp_path):
        """The active instruction is additive — it must not displace what was there."""
        assert "NEWEST-FIRST" in self._ground(tmp_path)

    def test_tells_the_agent_to_surface_contradictions(self, tmp_path):
        """Kernel rule: memory vs reality mismatch gets SAID, not silently reconciled."""
        assert "SAY SO" in self._ground(tmp_path)

    def test_still_silent_when_not_pending(self, tmp_path):
        """The instruction rides the existing one-shot token — it must not turn the
        backstop into something that fires on every tool call."""
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding

        with patch("aipass.hooks.apps.modules.cadence.consume_regroup_pending", return_value=False):
            result = post_compact_regrounding.handle({"cwd": str(tmp_path)})

        assert result["stdout"] == ""


# =============================================================================
# release_notice — DPLAN-0335 leg 2
#
# These pin apps/modules/release_notice.py and its two doors. They live in this
# file because the post-compact regroup is one of those two doors and the
# test-write gate refuses new test files by policy (DPLAN-0323); a dedicated
# tests/test_release_notice.py is the right long-term home and is proposed to
# @devpulse in the dispatch reply.
# =============================================================================

_RN = "aipass.hooks.apps.modules.release_notice"

MANAGER_PASSPORT = '{"identity": {"citizen_class": "manager"}}'
SPECIALIST_PASSPORT = '{"identity": {"citizen_class": "specialist"}}'


def _make_project(root, passport_json=MANAGER_PASSPORT, stamped=None, source_repo=False):
    """Build a project tree and return the branch cwd the hook would run in.

    root/
      PROJ_REGISTRY.json              <- the project marker every fence uses
      .aipass/scaffold_manifest.json  <- only when *stamped* is given
      src/branch/.trinity/passport.json
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "PROJ_REGISTRY.json").write_text("{}", encoding="utf-8")
    branch = root / "src" / "branch"
    (branch / ".trinity").mkdir(parents=True)
    (branch / ".trinity" / "passport.json").write_text(passport_json, encoding="utf-8")
    if stamped is not None:
        aipass_dir = root / ".aipass"
        aipass_dir.mkdir(exist_ok=True)
        (aipass_dir / "scaffold_manifest.json").write_text(
            json.dumps({"aipass_version": stamped, "stamped_at": "2026-09-01T10:00:00", "files": {}}),
            encoding="utf-8",
        )
    if source_repo:
        (root / "src" / "aipass").mkdir(parents=True, exist_ok=True)
        (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    return branch


def _notice(cwd, installed="2.8.4"):
    from aipass.hooks.apps.modules import release_notice

    with patch.object(release_notice, "_installed_version", return_value=installed):
        return release_notice.build_notice({"cwd": str(cwd)})


class TestReleaseNoticeModule:
    def test_stale_scaffold_names_both_versions_and_the_preview(self, tmp_path):
        cwd = _make_project(tmp_path / "proj", stamped="2.8.1")
        out = _notice(cwd)
        assert "2.8.4" in out
        assert "2.8.1" in out
        assert "2026-09-01" in out
        assert f"aipass init update {tmp_path / 'proj'} --dry-run" in out

    def test_it_never_tells_the_agent_to_apply_on_its_own(self, tmp_path):
        """Patrick's rule, 2026-09-09: apply only on his or devpulse's go."""
        out = _notice(_make_project(tmp_path / "proj", stamped="2.8.1"))
        assert "Apply ONLY with Patrick's or devpulse's go" in out
        assert "--dry-run" in out

    def test_the_stamp_shows_the_date_not_the_full_timestamp(self, tmp_path):
        """@aipass stamps a full UTC ISO instant with microseconds. Printing it
        raw spends ~20 characters, every wake, on a block whose only job is
        'you are behind'."""
        out = _notice(_make_project(tmp_path / "proj", stamped="2.8.1"))
        assert "(2026-09-01)" in out
        assert "T10:00:00" not in out

    def test_a_non_iso_stamp_is_passed_through_rather_than_guessed_at(self, tmp_path):
        from aipass.hooks.apps.modules.release_notice import _stamp_date

        assert _stamp_date("sometime last week") == "sometime last week"
        assert _stamp_date("2026-09-01T07:55:36.794203+00:00") == "2026-09-01"

    def test_current_scaffold_is_silent(self, tmp_path):
        assert _notice(_make_project(tmp_path / "proj", stamped="2.8.4")) == ""

    def test_a_newer_scaffold_than_the_runtime_is_silent(self, tmp_path):
        """A downgraded install must not nag the project to 'update' backwards."""
        assert _notice(_make_project(tmp_path / "proj", stamped="2.9.0")) == ""

    def test_absent_manifest_counts_as_behind(self, tmp_path):
        out = _notice(_make_project(tmp_path / "proj"))
        assert "never stamped" in out
        assert "2.8.4" in out

    def test_unparseable_stamped_version_counts_as_behind(self, tmp_path):
        out = _notice(_make_project(tmp_path / "proj", stamped="unknown"))
        assert "2.8.4" in out

    def test_a_non_manager_hears_nothing(self, tmp_path):
        """VACUITY GUARD: the same tree with a manager passport DOES speak, so
        'silent' here means the class gate refused it — not that the fixture is
        malformed and the renderer bailed for some unrelated reason."""
        quiet = _make_project(tmp_path / "quiet", passport_json=SPECIALIST_PASSPORT)
        loud = _make_project(tmp_path / "loud", passport_json=MANAGER_PASSPORT)
        assert _notice(quiet) == ""
        assert _notice(loud) != ""

    def test_a_passport_1_0_top_level_class_still_counts(self, tmp_path):
        """Passport 2.0 moved citizen_class inside identity (DPLAN-0319); a 1.0
        manager must not be silently demoted to 'not a manager'."""
        cwd = _make_project(tmp_path / "proj", passport_json='{"citizen_class": "manager"}')
        assert _notice(cwd) != ""

    def test_no_passport_above_the_cwd_is_silent(self, tmp_path):
        bare = tmp_path / "bare"
        (bare / "src").mkdir(parents=True)
        (bare / "PROJ_REGISTRY.json").write_text("{}", encoding="utf-8")
        assert _notice(bare / "src") == ""

    def test_a_cwd_outside_any_project_is_silent(self, tmp_path):
        loose = tmp_path / "loose" / "branch"
        (loose / ".trinity").mkdir(parents=True)
        (loose / ".trinity" / "passport.json").write_text(MANAGER_PASSPORT, encoding="utf-8")
        assert _notice(loose) == ""

    def test_the_aipass_source_repo_is_skipped(self, tmp_path):
        """devpulse's own passport says manager, and `aipass init update` refuses
        its own repo — so without this skip the loudest seat on the machine gets
        a notice it can never clear. VACUITY GUARD: the identical tree without
        src/aipass + pyproject.toml does speak."""
        src = _make_project(tmp_path / "src_repo", source_repo=True)
        plain = _make_project(tmp_path / "plain_repo")
        assert _notice(src) == ""
        assert _notice(plain) != ""

    def test_an_unparseable_installed_version_stays_quiet(self, tmp_path):
        """An AIPass defect must not become every manager's every-wake nag."""
        assert _notice(_make_project(tmp_path / "proj"), installed="dev") == ""

    def test_it_writes_nothing(self, tmp_path):
        """The notice reads two files and creates none — no manifest, no stamp,
        no state file. Proven by a full tree snapshot, paths and mtimes."""
        cwd = _make_project(tmp_path / "proj", stamped="2.8.1")

        def snapshot():
            return sorted((str(p), p.stat().st_mtime_ns) for p in tmp_path.rglob("*"))

        before = snapshot()
        assert _notice(cwd) != ""
        assert snapshot() == before


class TestReleaseNoticeVersionCompare:
    def test_short_and_long_forms_of_the_same_version_are_equal(self):
        """Without zero-padding, (2, 8) < (2, 8, 0) and a scaffold stamped '2.8'
        would be reported behind '2.8.0' forever."""
        from aipass.hooks.apps.modules.release_notice import _is_behind, _version_tuple

        assert _is_behind(_version_tuple("2.8"), _version_tuple("2.8.0")) is False
        assert _is_behind(_version_tuple("2.8.0"), _version_tuple("2.8")) is False

    def test_patch_and_minor_bumps_read_as_behind(self):
        from aipass.hooks.apps.modules.release_notice import _is_behind, _version_tuple

        assert _is_behind(_version_tuple("2.8.1"), _version_tuple("2.8.4")) is True
        assert _is_behind(_version_tuple("2.8"), _version_tuple("2.9.0")) is True
        assert _is_behind(_version_tuple("2.10.0"), _version_tuple("2.9.0")) is False

    def test_a_prerelease_suffix_parses_to_its_numeric_core(self):
        from aipass.hooks.apps.modules.release_notice import _version_tuple

        assert _version_tuple("2.9.0rc1") == (2, 9, 0)

    def test_a_non_numeric_version_is_unparseable(self):
        from aipass.hooks.apps.modules.release_notice import _version_tuple

        assert _version_tuple("dev") is None
        assert _version_tuple("") is None


class TestReleaseNoticeSessionStartDoor:
    def _handle(self, cwd, source, installed="2.8.4"):
        from aipass.hooks.apps.handlers.lifecycle import release_notice as door
        from aipass.hooks.apps.modules import release_notice

        with patch.object(release_notice, "_installed_version", return_value=installed):
            return door.handle({"cwd": str(cwd), "source": source})

    def test_startup_fires(self, tmp_path):
        result = self._handle(_make_project(tmp_path / "proj"), "startup")
        assert "AIPASS RELEASE NOTICE" in result["stdout"]
        assert result["exit_code"] == 0

    def test_clear_fires(self, tmp_path):
        assert "AIPASS RELEASE NOTICE" in self._handle(_make_project(tmp_path / "proj"), "clear")["stdout"]

    def test_resume_is_skipped(self, tmp_path):
        """Restored context already carries the block if it fired."""
        assert self._handle(_make_project(tmp_path / "proj"), "resume") == {"stdout": "", "exit_code": 0}

    def test_compact_is_skipped(self, tmp_path):
        """The post-compact regroup owns that boundary — firing both would print
        the same block twice for one compaction."""
        assert self._handle(_make_project(tmp_path / "proj"), "compact") == {"stdout": "", "exit_code": 0}

    def test_a_raising_module_never_escapes_into_session_start(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle import release_notice as door

        with patch.object(door, "load_content", side_effect=RuntimeError("boom")):
            assert door.handle({"cwd": str(tmp_path), "source": "startup"}) == {"stdout": "", "exit_code": 0}


class TestReleaseNoticeCompactDoor:
    def _reground(self, cwd, notice):
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding

        with (
            patch("aipass.hooks.apps.modules.cadence.consume_regroup_pending", return_value=True),
            patch("aipass.hooks.apps.modules.grounding_content.load_kernel", return_value="KERNEL"),
            patch("aipass.hooks.apps.modules.grounding_content.load_navmap", return_value=""),
            patch("aipass.hooks.apps.modules.grounding_content.load_branch", return_value=""),
            patch("aipass.hooks.apps.modules.grounding_content.load_identity", return_value=""),
            patch(f"{_RN}.build_notice", **notice),
        ):
            return post_compact_regrounding.handle({"cwd": str(cwd)})

    def test_the_notice_rides_the_regroup_ahead_of_the_grounding(self, tmp_path):
        """Issue #752 moved it: the notice opens the regroup with the branch section,
        so it lands in part 1 on every seat instead of trailing a payload whose tail
        is exactly what a display cap cuts."""
        result = self._reground(tmp_path, {"return_value": "NOTICE-BLOCK"})
        context = json.loads(result["stdout"])["hookSpecificOutput"]["additionalContext"]
        assert "NOTICE-BLOCK" in context
        assert context.index("NOTICE-BLOCK") < context.index("KERNEL")

    def test_a_raising_notice_does_not_cost_the_regroup(self, tmp_path):
        result = self._reground(tmp_path, {"side_effect": RuntimeError("boom")})
        context = json.loads(result["stdout"])["hookSpecificOutput"]["additionalContext"]
        assert "KERNEL" in context

    def test_the_notice_is_not_even_built_when_there_is_no_grounding(self, tmp_path):
        """Guard order, not just output: a bare notice under a re-ground header
        would read as a regroup that reground nothing, and the two file reads
        would be spent on a block nobody sees."""
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding
        from aipass.hooks.apps.modules import release_notice

        with (
            patch("aipass.hooks.apps.modules.cadence.consume_regroup_pending", return_value=True),
            patch("aipass.hooks.apps.modules.grounding_content.load_kernel", return_value=""),
            patch("aipass.hooks.apps.modules.grounding_content.load_navmap", return_value=""),
            patch("aipass.hooks.apps.modules.grounding_content.load_branch", return_value=""),
            patch("aipass.hooks.apps.modules.grounding_content.load_identity", return_value=""),
            patch.object(release_notice, "build_notice", return_value="NOTICE") as spy,
        ):
            result = post_compact_regrounding.handle({"cwd": str(tmp_path)})

        assert result == {"stdout": "", "exit_code": 0}
        spy.assert_not_called()


# =============================================================================
# Issue #752 — one fire must stay under Claude Code's hook display limit
#
# Claude Code 2.1.267 persists a hook additionalContext longer than 10,000
# UTF-16 units to a file and shows the agent a 2,000-char preview. The backstop
# used to send ~21,500 in one fire. These pin the budgeted, ordered, multi-part
# re-ground against sections at the sizes measured on 2026-09-10 (the largest
# of each across the hooks, devpulse, memory, vera and baud seats).
# =============================================================================

_PCR = "aipass.hooks.handlers.lifecycle.post_compact_regrounding"
_GC = "aipass.hooks.apps.modules.grounding_content"

TODAYS_SIZES = {"branch": 8840, "identity": 3428, "kernel": 3034, "navmap": 7886}
NOTICE_SIZE = 405


def _section(tag, size):
    """Multi-line text of exactly *size* chars whose every line is uniquely tagged,
    so 'nothing lost' can be checked line by line across the parts."""
    width = 80
    lines = [f"{tag}-L{i:04d} ".ljust(width - 1, "x") for i in range(max(1, size // width))]
    lines[-1] += "x" * (size - len("\n".join(lines)))
    return "\n".join(lines)


class TestRegroupBudget752:
    def _sequence(self, tmp_path, sizes=None, notice_size=NOTICE_SIZE, events=12, resets=1):
        """Real cadence (autouse-isolated state), real packer, sized sections.
        Returns the additionalContext of every non-silent fire, in order."""
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding
        from aipass.hooks.apps.modules import cadence

        sizes = sizes or TODAYS_SIZES
        cadence._turn = None
        with (
            patch(f"{_GC}.load_branch", return_value=_section("BRANCH", sizes["branch"])),
            patch(f"{_GC}.load_identity", return_value=_section("IDENTITY", sizes["identity"])),
            patch(f"{_GC}.load_kernel", return_value=_section("KERNEL", sizes["kernel"])),
            patch(f"{_GC}.load_navmap", return_value=_section("NAVMAP", sizes["navmap"])),
            patch(f"{_RN}.build_notice", return_value=_section("NOTICE", notice_size) if notice_size else ""),
        ):
            for _ in range(resets):
                cadence.reset_counter()
            fired = []
            for _ in range(events):
                result = post_compact_regrounding.handle({"cwd": str(tmp_path)})
                if result["stdout"]:
                    fired.append(json.loads(result["stdout"])["hookSpecificOutput"]["additionalContext"])
        return fired

    def test_the_budget_sits_below_the_measured_limit(self):
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding

        assert post_compact_regrounding.REGROUP_FIRE_BUDGET < 10_000
        assert "sgr = 1e4" in post_compact_regrounding.__doc__

    def test_a_manager_seat_at_todays_sizes_never_exceeds_the_budget(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.post_compact_regrounding import REGROUP_FIRE_BUDGET, _cc_len

        fired = self._sequence(tmp_path)
        assert len(fired) > 1, "today's sizes cannot fit one fire - the split is the point"
        assert sum(_cc_len(f) for f in fired) > 20_000, "the fixture must be at today's scale"
        for part, context in enumerate(fired, 1):
            assert _cc_len(context) <= REGROUP_FIRE_BUDGET, f"part {part} is {_cc_len(context)} units"

    def test_nothing_is_lost_across_the_parts(self, tmp_path):
        """VACUITY GUARD for the budget pin: a packer that met the cap by dropping
        or truncating content would pass it. Every tagged line arrives exactly once."""
        stream = "\n".join(self._sequence(tmp_path))
        for tag, size in [*TODAYS_SIZES.items(), ("notice", NOTICE_SIZE)]:
            for line in _section(tag.upper(), size).split("\n"):
                assert stream.count(line) == 1, f"{line[:20]}... arrived {stream.count(line)} times"

    def test_branch_then_identity_then_kernel_then_navmap(self, tmp_path):
        """A cap, if one ever bites, must cut the least important tail."""
        stream = "\n".join(self._sequence(tmp_path))
        order = [stream.index(f"{tag}-L0000") for tag in ("BRANCH", "IDENTITY", "KERNEL", "NAVMAP")]
        assert order == sorted(order)

    def test_the_manager_notice_lands_in_part_one(self, tmp_path):
        fired = self._sequence(tmp_path)
        assert "NOTICE-L0000" in fired[0]
        assert fired[0].index("NOTICE-L0000") < fired[0].index("BRANCH-L0000")

    def test_the_active_instruction_rides_part_one_only(self, tmp_path):
        fired = self._sequence(tmp_path)
        assert "ACTIVE RE-GROUNDING" in fired[0]
        assert all("ACTIVE RE-GROUNDING" not in later for later in fired[1:])

    def test_every_header_states_the_count_actually_emitted(self, tmp_path):
        fired = self._sequence(tmp_path)
        total = len(fired)
        for part, context in enumerate(fired, 1):
            assert context.startswith(f"[POST-COMPACT RE-GROUND {part}/{total} ")

    def test_one_regroup_per_compaction_however_many_tool_calls_follow(self, tmp_path):
        """DPLAN-0276's 17-fires-per-session defect stays cured: three resets on one
        boundary, forty tool calls, and the sequence is exactly the planned parts."""
        fired = self._sequence(tmp_path, events=40, resets=3)
        assert 1 < len(fired) <= 4
        assert len(set(fired)) == len(fired)

    def test_each_fire_writes_one_sized_log_line(self, tmp_path):
        from aipass.hooks.apps.modules import cadence

        with patch.object(cadence, "logger") as log:
            fired = self._sequence(tmp_path)
        lines = [c.args[0] % tuple(c.args[1:]) for c in log.info.call_args_list]
        fire_lines = [line for line in lines if line.startswith("[HOOKS] regroup fired ")]
        assert len(fire_lines) == len(fired)
        for part, line in enumerate(fire_lines, 1):
            assert f"part={part}/{len(fired)}" in line
            assert "bytes=" in line and "chars=" in line
        log.warning.assert_not_called()

    def test_a_section_larger_than_a_whole_part_is_split_between_lines(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.post_compact_regrounding import REGROUP_FIRE_BUDGET, _cc_len

        sizes = {"branch": 25_000, "identity": 10, "kernel": 10, "navmap": 10}
        fired = self._sequence(tmp_path, sizes=sizes, notice_size=0)
        assert all(_cc_len(f) <= REGROUP_FIRE_BUDGET for f in fired)
        stream = "\n".join(fired)
        for line in _section("BRANCH", 25_000).split("\n"):
            assert stream.count(line) == 1

    def test_a_single_line_longer_than_a_part_is_cut_not_dropped(self):
        from aipass.hooks.apps.handlers.lifecycle.post_compact_regrounding import (
            REGROUP_FIRE_BUDGET,
            _cc_len,
            _pack,
        )

        line = "".join(chr(ord("a") + i % 26) for i in range(20_000))
        parts = _pack([("branch", line)], "INSTRUCTION")
        assert all(_cc_len(text) <= REGROUP_FIRE_BUDGET for text, _ in parts)
        rejoined = "".join(
            text.split("\n\n", 1)[1]
            .replace("[… continued from the previous re-ground part]\n", "")
            .replace("\n[… continued in the next re-ground part]", "")
            for text, _ in parts
        )
        assert line in rejoined.replace("INSTRUCTION\n\n", "")

    def test_the_budget_counts_utf16_units_not_code_points(self):
        """Claude Code compares a JS string length. An emoji is one Python char and
        two JS units, so a packer counting len() would overshoot on emoji-heavy text."""
        from aipass.hooks.apps.handlers.lifecycle.post_compact_regrounding import (
            REGROUP_FIRE_BUDGET,
            _cc_len,
            _pack,
        )

        text = "\n".join("\U0001f600" * 60 for _ in range(100))  # 6,000 code points, 12,000 units
        assert len(text) < REGROUP_FIRE_BUDGET < _cc_len(text)
        parts = _pack([("branch", text)], "I")
        assert len(parts) > 1
        assert all(_cc_len(p) <= REGROUP_FIRE_BUDGET for p, _ in parts)
