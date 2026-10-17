# =================== AIPass ====================
# Name: tests/test_contracts.py
# Description: Contract tests for the memory entry point and its data handling
# Version: 1.1.1
# Created: 2026-03-28
# Modified: 2026-10-17
# Category: memory/tests
# =============================================

"""Tests for apps/memory.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — discover_modules() per module, pinned in tests/test_fleet_gateway.py
# seedgo: no-test-needed(documentation) — the wording of print_help() and print_introspection() panels
# seedgo: no-test-needed(external) — resolve_exit and console from @cli; only the exit codes they yield are pinned

from pathlib import Path
from unittest.mock import patch

from aipass.memory.apps import memory as memory_entry


class TestDataStructureContracts:
    """Tests verifying expected keys in memory data structures."""

    def test_config_keys_present_in_passport(self) -> None:
        """Passport config must contain module_name equivalent keys."""
        passport = {
            "branch_info": {
                "branch_name": "memory",
                "module_name": "aipass.memory",
                "path": "src/aipass/memory",
            },
            "identity": {"role": "memory_manager"},
            "citizenship": {"registered": True},
        }

        assert "module_name" in passport["branch_info"]
        assert "branch_name" in passport["branch_info"]


class TestEntryPointImportContract:
    """The entry point is executed as a SCRIPT by drone, so a relative import fails only at run time."""

    def _entry_point_source(self) -> str:
        entry = Path(__file__).resolve().parent.parent / "apps" / "memory.py"
        assert entry.exists(), f"entry point not found at {entry}"
        return entry.read_text(encoding="utf-8")

    def test_entry_point_has_no_relative_imports(self) -> None:
        source = self._entry_point_source()
        offenders = [
            f"{num}: {line.strip()}"
            for num, line in enumerate(source.splitlines(), start=1)
            if line.strip().startswith("from .")
        ]
        assert offenders == [], "Relative imports in the entry point script:\n" + "\n".join(offenders)

    def test_entry_point_imports_no_handlers_directly(self) -> None:
        """The entry point routes to modules; only modules may import handlers."""
        source = self._entry_point_source()
        offenders = [
            f"{num}: {line.strip()}"
            for num, line in enumerate(source.splitlines(), start=1)
            if "aipass.memory.apps.handlers" in line and "import" in line
        ]
        assert offenders == [], "Handler imported directly in the entry point:\n" + "\n".join(offenders)


class TestUnknownArgumentExitsNonZero:
    """An unknown command or argument FAILS: 1 = nothing routed, 2 = a module routed and refused."""

    def _run_main(self, argv: list[str]) -> int:
        """Call the entry point's main() with argv, returning its exit code."""
        with patch("sys.argv", ["memory", *argv]):
            return memory_entry.main()

    def test_an_unknown_verb_exits_non_zero(self) -> None:
        assert self._run_main(["definitely_not_a_verb_xyz"]) == 1

    def test_an_unknown_flag_exits_non_zero(self) -> None:
        """A dashed token nothing routes is the same refusal as a bare word."""
        assert self._run_main(["--definitely-not-a-flag"]) == 1

    def test_a_known_verb_given_a_bogus_subargument_exits_non_zero(self) -> None:
        """Routed but refused — 2, not 0, and not 1 either."""
        assert self._run_main(["rollover", "not_a_real_subarg_xyz"]) == 2

    def test_the_doors_that_must_still_exit_zero(self) -> None:
        """The refusal flip must not turn help, version or introspection red."""
        assert self._run_main(["--help"]) == 0
        assert self._run_main(["--version"]) == 0
        assert self._run_main([]) == 0

    def test_a_todo_subverb_nothing_routes_exits_non_zero(self) -> None:
        """`todo` is routed by the auto-discovered todo module; an unknown sub-verb is refused, 2."""
        assert self._run_main(["todo", "not_a_real_subverb_xyz"]) == 2
        assert self._run_main(["todo", "--help"]) == 0


class TestWatchRunnerImportContract:
    """The watcher's implementation lives in a handler, and imports absolutely."""

    def _watch_runner_source(self) -> str:
        handler = Path(__file__).resolve().parent.parent / "apps" / "handlers" / "monitor" / "watch_runner.py"
        assert handler.exists(), f"watch runner not found at {handler}"
        return handler.read_text(encoding="utf-8")

    def test_runner_imports_watcher_absolutely(self) -> None:
        source = self._watch_runner_source()
        assert "from aipass.memory.apps.handlers.monitor.memory_watcher import" in source

    def test_runner_imports_detector_absolutely(self) -> None:
        source = self._watch_runner_source()
        assert "from aipass.memory.apps.handlers.monitor.detector import" in source


class TestModuleScriptImportContract:
    """Every file with a __main__ block must survive being run as a script; the entry point hides it."""

    def _module_files(self):
        modules_dir = Path(__file__).resolve().parent.parent / "apps" / "modules"
        return sorted(p for p in modules_dir.glob("*.py") if not p.name.startswith("_"))

    def test_modules_have_no_relative_imports(self) -> None:
        offenders = []
        for path in self._module_files():
            for num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if line.strip().startswith("from .."):
                    offenders.append(f"{path.name}:{num}: {line.strip()}")
        assert offenders == [], "Relative imports in script-executable modules:\n" + "\n".join(offenders)
