# =================== AIPass ====================
# Name: test_handlers_fence.py
# Description: The handlers fence (foreign importer refused, kin and door pass) and the write fence (where services write)
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-11-23
# =============================================

"""Tests for apps/handlers/__init__.py, the import fence, in a fresh interpreter per case; and apps/handlers/write_fence.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that apps/handlers/__init__.py parses and imports

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import json

from aipass.memory.apps.handlers import write_fence
from aipass.memory.tests import support_fence

KIN_PROBE = Path(support_fence.__file__)
FOREIGN_SHAPES = ["pkg", "deep", "dyn", "chain", "mock", "sibling"]
SERVED_RULE = "services write where they serve"


def _probe(seat: Path, shape: str, cwd: Path) -> str:
    """Run the probe at `seat` in a fresh interpreter; answer its one output line."""
    done = subprocess.run(
        [sys.executable, str(seat), shape],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=str(cwd),
    )
    assert done.returncode == 0, done.stderr[-600:]
    return done.stdout.strip().splitlines()[-1]


@pytest.fixture
def foreign_seat(tmp_path: Path) -> Path:
    """A copy of the probe under a path whose branch segment reads 'foreign'."""
    seat = tmp_path / "aipass" / "foreign" / "probe.py"
    seat.parent.mkdir(parents=True)
    shutil.copy(KIN_PROBE, seat)
    return seat


@pytest.fixture
def elsewhere_seat(tmp_path: Path) -> Path:
    """A copy of the probe under a path with no branch segment at all."""
    seat = tmp_path / "elsewhere" / "probe.py"
    seat.parent.mkdir(parents=True)
    shutil.copy(KIN_PROBE, seat)
    return seat


class TestAForeignImporterIsRefused:
    """Whatever route it takes, code outside this branch does not get these handlers."""

    @pytest.mark.parametrize("shape", FOREIGN_SHAPES)
    def test_a_foreign_branch_is_refused_and_named(self, foreign_seat, tmp_path, shape):
        """Every import shape from a foreign seat is refused (mock surfaces as AttributeError)."""
        answer = _probe(foreign_seat, shape, tmp_path)
        assert answer.startswith(("DENIED", "REFUSED")), answer
        if answer.startswith("DENIED"):
            named = "sibling" if shape == "sibling" else "foreign"
            assert f"Caller branch: {named}" in answer, answer

    def test_a_seat_with_no_branch_segment_is_refused_as_unknown(self, elsewhere_seat, tmp_path):
        """A user's script or a project outside any aipass tree is foreign too."""
        answer = _probe(elsewhere_seat, "pkg", tmp_path)
        assert answer == "DENIED Caller branch: unknown", answer

    @pytest.mark.parametrize("shape", FOREIGN_SHAPES)
    def test_the_cwd_inside_this_branch_buys_a_foreign_seat_nothing(self, foreign_seat, shape):
        """The process cwd is not a frame: bootstrap pseudo filenames must not read as kin."""
        answer = _probe(foreign_seat, shape, KIN_PROBE.parents[1])
        assert answer.startswith(("DENIED", "REFUSED")), answer
        if answer.startswith("DENIED"):
            named = "sibling" if shape == "sibling" else "foreign"
            assert f"Caller branch: {named}" in answer, answer


class TestKinAndTheDoorPass:
    """This branch's own files import freely and the package door is open to all."""

    @pytest.mark.parametrize("shape", ["pkg", "deep", "dyn", "chain", "mock"])
    def test_the_branch_itself_is_allowed(self, tmp_path, shape):
        """The probe from its own seat passes, mock.patch's unittest/pkgutil route included."""
        assert _probe(KIN_PROBE, shape, tmp_path) == "ALLOWED"

    def test_the_package_door_is_open_to_a_foreign_branch(self, foreign_seat, tmp_path):
        """A foreign seat reading a name through the package door passes: kin asks for the handlers."""
        assert _probe(foreign_seat, "door", tmp_path) == "ALLOWED"

    def test_the_apps_package_does_not_import_its_handlers(self):
        """An `import handlers` in apps/__init__.py would make every caller look like kin."""
        apps_init = KIN_PROBE.parents[1] / "apps" / "__init__.py"
        source = apps_init.read_text(encoding="utf-8")
        assert "import handlers" not in source, source


class TestServicesWriteWhereTheyServe:
    """The write fence admits the AIPass root and every declared external branch directory, nothing else."""

    def test_a_write_into_a_declared_external_branch_passes(self, declared_externals):
        """@wren at its root's top and @grow nested at seed/src/grow/grow: both directories and files under them."""
        for branch in (declared_externals.wren, declared_externals.grow):
            assert write_fence.fence_write(branch, lane="probe") is None
            assert write_fence.fence_write(branch / ".trinity" / "local.json", lane="probe") is None
            assert write_fence.fence_write(branch / ".chroma", lane="probe") is None

    def test_the_root_still_passes(self, declared_externals):
        """Positive control: admitting externals does not narrow the home root."""
        assert write_fence.fence_write(declared_externals.home / "src" / "x" / "local.json", lane="probe") is None

    def test_an_undeclared_path_is_refused_with_the_rule_named(self, declared_externals, tmp_path):
        """An arbitrary path stays refused; the refusal names the root and the rule, not the retired one."""
        target = tmp_path / "elsewhere" / ".trinity" / "local.json"

        refusal = write_fence.fence_write(target, lane="probe") or ""

        assert str(declared_externals.home.resolve()) in refusal
        assert SERVED_RULE in refusal
        assert "never write one" not in refusal

    def test_a_declared_root_outside_its_branches_is_refused(self, declared_externals):
        """The declaration admits the root's BRANCHES: its registry, a sibling directory and the root itself stay out."""
        seed = declared_externals.seed
        for target in (seed, seed / "SEED_REGISTRY.json", seed / "src" / "other" / "local.json", seed / "src" / "grow"):
            assert SERVED_RULE in (write_fence.fence_write(target, lane="probe") or ""), target

    def test_a_listed_branch_without_a_passport_is_refused(self, declared_externals):
        """External membership is presence: a registry row whose directory holds no passport admits nothing."""
        registry = declared_externals.seed / "SEED_REGISTRY.json"
        rows = json.loads(registry.read_text(encoding="utf-8"))
        rows["branches"].append({"name": "BARE", "path": "src/bare", "email": "@bare", "status": "active"})
        registry.write_text(json.dumps(rows), encoding="utf-8")
        (declared_externals.seed / "src" / "bare").mkdir(parents=True)

        refusal = write_fence.fence_write(declared_externals.seed / "src" / "bare" / "local.json", lane="probe")
        assert SERVED_RULE in (refusal or "")

    def test_a_symlink_inside_an_external_does_not_carry_a_write_out_of_it(self, declared_externals, tmp_path):
        """The fence judges where the bytes land, for an external as for the root."""
        foreign = tmp_path / "foreign"
        foreign.mkdir()
        door = declared_externals.wren / "door"
        door.symlink_to(foreign, target_is_directory=True)

        assert SERVED_RULE in (write_fence.fence_write(door / "local.json", lane="probe") or "")
