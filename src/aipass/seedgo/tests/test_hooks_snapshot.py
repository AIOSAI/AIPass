"""Hook Configuration Snapshot Tests.

Compares current settings.json hook configurations against known-good baselines.
Detects: hooks added/removed, command strings changed, matchers changed, events changed.

Baselines in tests/fixtures/*_hooks_snapshot.json.

# =================== META ====================
# Name: test_hooks_snapshot.py
# Description: Snapshot tests for hook configurations across provider, project, and branch levels
# Version: 1.0.0
# Created: 2026-05-07
# Modified: 2026-05-07
# =============================================
"""

import json
import re
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _find_repo_root() -> Path:
    """Walk up from this file to find the git repo root."""
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        if (parent / ".git").exists():
            return parent
    return Path(__file__).resolve().parents[4]  # fallback


_REPO_ROOT = _find_repo_root()


def _load_fixture(name: str) -> dict:
    """Load a JSON fixture file by name from the fixtures directory."""
    path = FIXTURES / name
    assert path.exists(), f"Fixture missing: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _load_settings_hooks(settings_path: Path) -> dict:
    """Load the hooks dict from a settings.json file, returning empty dict if missing."""
    if not settings_path.exists():
        return {}
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    return data.get("hooks", {})


def _normalize_command(cmd: str) -> str:
    """Normalize a hook command to be path-independent.

    Strips environment-specific absolute paths from hook command strings
    so snapshots are comparable across machines (Linux vs Windows CI).
    Keeps the interpreter and script name, removes path prefixes.
    """
    cmd = cmd.replace("\\", "/")
    cmd = re.sub(r"\$AIPASS_HOME/", "", cmd)
    cmd = re.sub(r"(?:(?<=^)|(?<= ))([A-Za-z]:)?/.+?/AIPass/", "", cmd)
    cmd = re.sub(r"(?:(?<=^)|(?<= ))([A-Za-z]:)?/.+?/\.claude/", ".claude/", cmd)
    return cmd


def _extract_hook_commands(hooks_config: dict) -> dict[str, list[str]]:
    """Extract {event: [command_strings]} from a hooks config, sorted.

    Command strings are normalized to strip environment-specific path
    prefixes so comparisons work across different machines.
    """
    result = {}
    for event, entries in hooks_config.items():
        commands = []
        for entry in entries:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                if cmd:
                    commands.append(_normalize_command(cmd))
        result[event] = sorted(commands)
    return result


def _extract_hook_matchers(hooks_config: dict) -> dict[str, list[str]]:
    """Extract {event: [matchers]} from a hooks config."""
    result = {}
    for event, entries in hooks_config.items():
        matchers = []
        for entry in entries:
            m = entry.get("matcher", "*")
            matchers.append(m)
        result[event] = sorted(matchers)
    return result


# -- Provider hooks snapshot ---------------------------------------------------


@pytest.mark.skipif(
    sys.platform == "win32" or not (Path.home() / ".claude" / "settings.json").exists(),
    reason="No provider settings.json (CI environment) or Windows CI",
)
class TestProviderHooksSnapshot:
    """Compare ~/.claude/settings.json hooks against known-good baseline."""

    @pytest.fixture()
    def baseline(self):
        """Load provider hooks baseline fixture."""
        return _load_fixture("provider_hooks_snapshot.json")

    @pytest.fixture()
    def current(self):
        """Load current provider hooks from ~/.claude/settings.json."""
        return _load_settings_hooks(Path.home() / ".claude" / "settings.json")

    def test_same_events(self, baseline, current):
        """Verify the same hook events exist in baseline and current."""
        assert set(baseline.keys()) == set(current.keys()), (
            f"Event mismatch. Expected: {sorted(baseline.keys())}, Got: {sorted(current.keys())}"
        )

    def test_same_hook_count_per_event(self, baseline, current):
        """Verify the same number of hooks per event in baseline and current."""
        assert len(baseline) == 8, f"provider baseline should snapshot 8 events, got {sorted(baseline)}"
        for event in baseline:
            expected = len(baseline[event])
            actual = len(current.get(event, []))
            assert expected == actual, f"{event}: expected {expected} hooks, got {actual}"

    def test_same_commands(self, baseline, current):
        """Verify all hook command strings match between baseline and current."""
        expected = _extract_hook_commands(baseline)
        actual = _extract_hook_commands(current)
        assert expected == actual, f"Command mismatch:\nExpected: {expected}\nActual: {actual}"

    def test_same_matchers(self, baseline, current):
        """Verify all hook matchers match between baseline and current."""
        expected = _extract_hook_matchers(baseline)
        actual = _extract_hook_matchers(current)
        assert expected == actual, f"Matcher mismatch:\nExpected: {expected}\nActual: {actual}"

    def test_no_unexpected_hooks_added(self, baseline, current):
        """Detect any hooks added since the snapshot was taken."""
        baseline_cmds: set[str] = set()
        current_cmds: set[str] = set()
        for cmds in _extract_hook_commands(baseline).values():
            baseline_cmds.update(cmds)
        for cmds in _extract_hook_commands(current).values():
            current_cmds.update(cmds)
        added = current_cmds - baseline_cmds
        assert not added, f"Hooks added since snapshot: {added}"

    def test_no_hooks_removed(self, baseline, current):
        """Detect any hooks removed since the snapshot was taken."""
        baseline_cmds: set[str] = set()
        current_cmds: set[str] = set()
        for cmds in _extract_hook_commands(baseline).values():
            baseline_cmds.update(cmds)
        for cmds in _extract_hook_commands(current).values():
            current_cmds.update(cmds)
        removed = baseline_cmds - current_cmds
        assert not removed, f"Hooks removed since snapshot: {removed}"


# -- Project hooks snapshot ----------------------------------------------------


class TestProjectHooksSnapshot:
    """Confirm project-root .claude/settings.json has NO hooks (correct state)."""

    @pytest.fixture()
    def baseline(self):
        """Load project hooks baseline fixture (expected empty)."""
        return _load_fixture("project_hooks_snapshot.json")

    @pytest.fixture()
    def current(self):
        """Load current project-root hooks from .claude/settings.json."""
        return _load_settings_hooks(_REPO_ROOT / ".claude" / "settings.json")

    def test_project_has_no_hooks(self, baseline, current):
        """Verify project root settings.json has no hooks configured."""
        assert current == baseline == {}, f"Project root should have no hooks, found: {list(current.keys())}"


# -- Double-fire assertion -----------------------------------------------------


class TestDoubleFire:
    """Verify no hook command string appears at both provider AND project level with different paths."""

    def test_no_command_overlap_different_strings(self):
        """Detect double-fire risk from same script at provider and project with different paths."""
        provider = _load_settings_hooks(Path.home() / ".claude" / "settings.json")
        project = _load_settings_hooks(_REPO_ROOT / ".claude" / "settings.json")

        provider_cmds: set[str] = set()
        project_cmds: set[str] = set()
        for cmds in _extract_hook_commands(provider).values():
            provider_cmds.update(cmds)
        for cmds in _extract_hook_commands(project).values():
            project_cmds.update(cmds)

        # Extract just the script filename from each command for overlap detection
        def script_name(cmd: str) -> str:
            """Extract the .py filename from a hook command string."""
            for part in cmd.split():
                if part.endswith(".py"):
                    return Path(part).name
            return cmd

        provider_scripts = {script_name(c) for c in provider_cmds}
        project_scripts = {script_name(c) for c in project_cmds}
        overlap = provider_scripts & project_scripts

        # If same script appears in both, the command strings MUST be identical (dedup)
        # or it will double-fire. Collected rather than looped over so the assertion
        # runs even when the overlap is empty — an empty overlap is the healthy case,
        # but a loop over it would report green without checking anything.
        double_fire = [
            (script, pc, jc)
            for script in sorted(overlap)
            for pc in sorted(c for c in provider_cmds if script_name(c) == script)
            for jc in sorted(c for c in project_cmds if script_name(c) == script)
            if pc != jc
        ]
        assert not double_fire, (
            f"Double-fire risk: {double_fire} — same script with different command strings at "
            f"provider vs project. "
            f"Claude Code deduplicates by exact string — different strings = fires twice."
        )

    def test_branch_hooks_dont_duplicate_provider(self):
        """Branch-level hooks should NOT include hooks that only work from provider level."""
        branch_baseline = _load_fixture("branch_hooks_snapshot.json")
        provider_only_events = {"PreToolUse", "PostToolUse"}

        leaked = provider_only_events & set(branch_baseline)
        assert not leaked, f"Branch baseline has {sorted(leaked)} hooks — these only fire from provider settings"


# -- Branch hooks snapshot -----------------------------------------------------


class TestBranchHooksSnapshot:
    """Verify branch-level settings match the known-good pattern."""

    @pytest.fixture()
    def baseline(self):
        """Load branch hooks baseline fixture."""
        return _load_fixture("branch_hooks_snapshot.json")

    def test_branch_settings_match_baseline(self, baseline):
        """Spot-check a few branches have the correct hooks."""
        expected_cmds = _extract_hook_commands(baseline)
        assert expected_cmds == {}, (
            f"Branch baseline is the no-hooks pattern — a branch settings.json declaring hooks "
            f"would double-fire against the provider level. Baseline declares: {expected_cmds}"
        )
        branches_to_check = ["seedgo", "devpulse", "aipass"]
        for branch in branches_to_check:
            settings_path = _REPO_ROOT / "src" / "aipass" / branch / ".claude" / "settings.json"
            if not settings_path.exists():
                continue
            current = _load_settings_hooks(settings_path)
            actual_cmds = _extract_hook_commands(current)
            assert expected_cmds == actual_cmds, (
                f"Branch {branch} hooks don't match baseline.\nExpected: {expected_cmds}\nActual: {actual_cmds}"
            )
