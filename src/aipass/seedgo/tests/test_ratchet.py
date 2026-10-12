# =================== AIPass ====================
# Name: test_ratchet.py
# Description: Template v1 — the ratchet verb, its pick and its series
# Version: 1.0.0
# Created: 2026-10-12
# Modified: 2026-10-12
# =============================================

"""Tests for apps/modules/ratchet.py and the handlers it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in handlers/ratchet/ parses and imports
# seedgo: no-test-needed(documentation) — that the public handler functions carry docstrings
# seedgo: no-test-needed(generated) — a real campaign's artifact; tests/test_audit_tests_lane_adapter.py covers it
# seedgo: no-test-needed(cli) — Rich's rendering of the standings

import json

import pytest

from aipass.seedgo.apps.handlers import registry_scan
from aipass.seedgo.apps.handlers.audit_tests import artifact, refusal, runner
from aipass.seedgo.apps.handlers.ratchet import series
from aipass.seedgo.apps.modules import CommandRefused, ratchet


def _artifact(run_id="r1", started="2026-10-12T16:00:00+00:00", status="measured"):
    """An audit-tests artifact holding one pseudo-tested campaign."""
    return {
        "status": "published",
        "provenance": {"run_id": run_id, "started": started},
        "groups": {
            "pytest.pseudo_tested": {
                "status": status,
                "reason": "" if status == "measured" else "the unmutated suite is not green",
                "functions_total": 4,
                "functions_probed": 4,
                "functions_executed": 3,
                "budget_seconds": 1800,
                "budget_exhausted": False,
                "killed_by_assertion": 1,
                "killed_by_error": 1,
                "elapsed_seconds": 6.0,
                "seconds_per_mutant": 1.5,
                "pseudo_tested": [{"relpath": "apps/a.py", "qualname": "Shape.area", "lineno": 9}],
                "uncovered": {"functions": [{"relpath": "apps/a.py", "qualname": "unused", "lineno": 20}]},
                "mutants": [
                    {"relpath": "apps/a.py", "qualname": "crashes", "outcome": "killed", "kill_cause": "error"},
                    {"relpath": "apps/a.py", "qualname": "asserted", "outcome": "killed", "kill_cause": "assertion"},
                    {"relpath": "apps/a.py", "qualname": "timed_out", "outcome": "killed", "kill_cause": "unknown"},
                    {"relpath": "apps/a.py", "qualname": "Shape.area", "outcome": "survived", "kill_cause": None},
                ],
            }
        },
    }


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    """Two registered branches, the series and the artifacts all under tmp_path."""
    registry = tmp_path / "AIPASS_REGISTRY.json"
    branches = []
    for name in ("BETA", "alpha"):
        path = tmp_path / "src" / "aipass" / name.lower()
        (path / "tests").mkdir(parents=True)
        (path / "apps").mkdir()
        (path / "apps" / f"{name.lower()}.py").write_text("# entry point\n", encoding="utf-8")
        branches.append({"name": name, "path": str(path)})
    registry.write_text(json.dumps({"branches": branches}), encoding="utf-8")
    monkeypatch.setattr(registry_scan, "find_registry", lambda: registry)
    monkeypatch.setattr(registry_scan, "caller_registries", list)

    store = tmp_path / ".seedgo"
    monkeypatch.setattr(series, "ARTIFACT_DIR", store)
    monkeypatch.setattr(artifact, "ARTIFACT_DIR", store)
    return store


@pytest.fixture
def probe(monkeypatch):
    """Replace the suite run with a recorder; tests set what it returns."""
    calls = []
    state = {"document": _artifact(), "code": 0}

    def _run_target(target, options=None):
        calls.append((target.name, dict(options or {})))
        return runner.RunResult(target, state["document"], None, state["code"])

    monkeypatch.setattr(runner, "run_target", _run_target)
    state["calls"] = calls
    return state


def _series(store):
    """The series lines on disk, parsed."""
    path = store / series.SERIES_NAME
    return [json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


class TestIntrospection:
    def test_bare_ratchet_describes_itself_and_runs_nothing(self, fleet, probe, capsys):
        assert ratchet.handle_command("ratchet", []) is True

        out, _ = capsys.readouterr()
        assert "pick, run, record" in out
        assert probe["calls"] == []

    def test_an_unknown_subcommand_is_refused_with_exit_7(self, fleet, probe, capsys):
        with pytest.raises(CommandRefused) as refused:
            ratchet.handle_command("ratchet", ["sweep"])

        _, err = capsys.readouterr()
        assert refused.value.code == refusal.EXIT_UNKNOWN_ARGUMENT
        assert "'sweep'" in err
        assert probe["calls"] == []


class TestPick:
    def test_a_never_probed_branch_wins_alphabetically_and_nothing_is_written(self, fleet, probe, capsys):
        ratchet.handle_command("ratchet", ["pick"])

        out, _ = capsys.readouterr()
        assert "next probe: alpha" in out
        assert "never probed; first alphabetically of 2" in out
        assert probe["calls"] == []
        assert not (fleet / series.SERIES_NAME).exists()

    def test_the_branch_probed_longest_ago_wins_once_every_branch_has_a_point(self, fleet, probe, capsys):
        series.append({"branch": "alpha", "date": "2026-10-12T00:00:00+00:00"}, fleet)
        series.append({"branch": "BETA", "date": "2026-10-05T00:00:00+00:00"}, fleet)

        ratchet.handle_command("ratchet", ["pick"])

        out, _ = capsys.readouterr()
        assert "next probe: BETA" in out
        assert "last probe 2026-10-05" in out

    def test_a_broken_series_line_refuses_and_names_the_line(self, fleet, probe, capsys):
        fleet.mkdir(parents=True, exist_ok=True)
        (fleet / series.SERIES_NAME).write_text('{"branch": "alpha"}\nnot json\n', encoding="utf-8")

        with pytest.raises(CommandRefused) as refused:
            ratchet.handle_command("ratchet", ["pick"])

        _, err = capsys.readouterr()
        assert refused.value.code == refusal.EXIT_UNPROVEN
        assert "line 2" in err


class TestRun:
    def test_run_probes_the_pick_with_the_campaign_opted_in_at_the_default_budget(self, fleet, probe):
        ratchet.handle_command("ratchet", ["run"])

        assert probe["calls"] == [("alpha", {"execution_groups": ["pseudo_tested"], "budget_seconds": 1800})]

    def test_a_budget_flag_reaches_the_probe(self, fleet, probe):
        ratchet.handle_command("ratchet", ["run", "--budget", "3600"])

        assert probe["calls"][0][1]["budget_seconds"] == 3600

    def test_a_budget_with_no_number_is_refused_before_anything_runs(self, fleet, probe):
        with pytest.raises(CommandRefused) as refused:
            ratchet.handle_command("ratchet", ["run", "--budget", "soon"])

        assert refused.value.code == refusal.EXIT_UNKNOWN_ARGUMENT
        assert probe["calls"] == []

    def test_run_appends_one_line_keyed_by_qualname_and_archives_the_artifact(self, fleet, probe, capsys):
        ratchet.handle_command("ratchet", ["run"])

        (line,) = _series(fleet)
        assert line["branch"] == "alpha" and line["trigger"] == "weekly" and line["slice"] == "1/1"
        assert line["pick_reason"].startswith("never probed")
        assert line["pseudo_tested"] == ["apps/a.py::Shape.area"]
        assert line["uncovered"] == ["apps/a.py::unused"]
        assert line["crash_only"] == ["apps/a.py::crashes"]
        assert line["open_survivors"] == 1
        assert line["declared_equivalent"] is None
        archived = fleet / "ratchet" / "alpha_r1.json"
        assert json.loads(archived.read_text(encoding="utf-8")) == probe["document"]
        out, _ = capsys.readouterr()
        assert "alpha: 1 open survivor(s) of 4 probed" in out

    def test_the_next_run_moves_on_to_the_branch_not_yet_probed(self, fleet, probe):
        ratchet.handle_command("ratchet", ["run"])
        probe["document"] = _artifact(run_id="r2", started="2026-10-19T10:00:00+00:00")

        ratchet.handle_command("ratchet", ["run"])

        assert [name for name, _ in probe["calls"]] == ["alpha", "BETA"]
        assert [line["branch"] for line in _series(fleet)] == ["alpha", "BETA"]

    def test_a_refused_probe_still_writes_its_line_and_exits_non_zero(self, fleet, probe, capsys):
        probe["document"] = _artifact(status="not_applicable")
        probe["code"] = refusal.EXIT_UNPROVEN

        with pytest.raises(CommandRefused) as refused:
            ratchet.handle_command("ratchet", ["run"])

        (line,) = _series(fleet)
        assert refused.value.code == refusal.EXIT_UNPROVEN
        assert line["status"] == "not_applicable"
        assert line["reason"] == "the unmutated suite is not green"
        assert line["open_survivors"] is None
        _, err = capsys.readouterr()
        assert "probe not_applicable" in err


class TestRecord:
    def _publish(self, fleet, document):
        fleet.mkdir(parents=True, exist_ok=True)
        (fleet / "audit_tests_alpha.json").write_text(json.dumps(document), encoding="utf-8")

    def test_record_writes_the_artifacts_campaign_once(self, fleet, probe, capsys):
        self._publish(fleet, _artifact())

        ratchet.handle_command("ratchet", ["record", "@alpha"])
        ratchet.handle_command("ratchet", ["record", "@alpha"])

        (line,) = _series(fleet)
        assert line["trigger"] == "record" and line["run_id"] == "r1"
        assert probe["calls"] == []
        out, err = capsys.readouterr()
        assert "already in the series" in err + out

    def test_an_artifact_without_a_campaign_is_refused_and_nothing_is_written(self, fleet, probe, capsys):
        document = _artifact()
        document["groups"]["pytest.pseudo_tested"] = {"status": "not_applicable", "reason": "not requested"}
        self._publish(fleet, document)

        with pytest.raises(CommandRefused) as refused:
            ratchet.handle_command("ratchet", ["record", "@alpha"])

        assert refused.value.code == refusal.EXIT_NO_UNITS
        assert _series(fleet) == []
        _, err = capsys.readouterr()
        assert "not requested" in err
