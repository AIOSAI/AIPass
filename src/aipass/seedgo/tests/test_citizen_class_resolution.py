"""Pins for architecture_check resolving citizen_class to a template dir, mirror kept honest."""

# =================== META ====================
# Name: test_citizen_class_resolution.py
# Description: Template baseline resolves class via the mirrored registry, never a raw path join
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-08-28
# =============================================

import json
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import architecture_check

# Tests may reach into spawn's real registry — that is the whole point of a
# drift pin. Production code may not (seedgo's own encapsulation/handlers
# standards refuse a cross-branch handler import), which is why the mirror
# exists and why this file is the thing that keeps it true.
from aipass.spawn.apps.handlers import class_registry


def _branch(tmp_path: Path, citizen_class: str) -> Path:
    """Build a minimal branch whose passport claims citizen_class. Returns its entry point."""
    branch = tmp_path / "mybranch"
    apps = branch / "apps"
    apps.mkdir(parents=True)
    entry = apps / "mybranch.py"
    entry.write_text('"""Entry."""\n', encoding="utf-8")
    trinity = branch / ".trinity"
    trinity.mkdir()
    (trinity / "passport.json").write_text(json.dumps({"identity": {"citizen_class": citizen_class}}), encoding="utf-8")
    return entry


def _template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Plant the ONE template (templates/citizen/) and point the checker at it."""
    templates = tmp_path / "templates"
    citizen = templates / "citizen"
    (citizen / "apps").mkdir(parents=True)
    (citizen / "apps" / "{{BRANCH}}.py").write_text('"""Entry."""\n', encoding="utf-8")
    monkeypatch.setattr(architecture_check, "SPAWN_TEMPLATES_DIR", templates)
    return citizen


class TestRegisteredClassesResolveToTheOneTemplate:
    """manager and specialist both score against templates/citizen/."""

    def test_manager_resolves_to_citizen_template(self, tmp_path, monkeypatch):
        """The recorded defect, pinned cured.

        Before passport 2.0 the checker joined the class onto the templates path,
        so every manager branch scored 'No template for citizen_class "manager"'
        against a directory that has never existed -- a real branch failing for
        the auditor's mistake. There is no templates/manager/ now either, by
        design, which is exactly why this must be pinned rather than assumed.
        """
        _template(tmp_path, monkeypatch)
        entry = _branch(tmp_path, "manager")

        result = architecture_check.check_template_baseline(str(entry))

        assert result, "manager must produce a scored baseline, not an empty result"
        assert all(c["passed"] for c in result), [c for c in result if not c["passed"]]
        assert result[0]["name"] == "Template baseline (manager)"
        assert "spawn/templates/citizen/" in result[0]["message"]

    def test_specialist_resolves_to_the_same_template(self, tmp_path, monkeypatch):
        """Two classes, one template -- the class does not pick a scaffold."""
        _template(tmp_path, monkeypatch)
        entry = _branch(tmp_path, "specialist")

        result = architecture_check.check_template_baseline(str(entry))

        assert all(c["passed"] for c in result), [c for c in result if not c["passed"]]
        assert result[0]["name"] == "Template baseline (specialist)"
        assert "spawn/templates/citizen/" in result[0]["message"]

    def test_both_classes_score_identically(self, tmp_path, monkeypatch):
        """Same tree, different class -- the per-item verdicts must not differ.

        Pinned as a whole-result comparison rather than two scores: a future fork
        that quietly gave one class extra template items would still tie on 'all
        passed' while scoring a different set.
        """
        _template(tmp_path, monkeypatch)
        entry = _branch(tmp_path, "manager")
        as_manager = architecture_check.check_template_baseline(str(entry))

        passport = entry.parent.parent / ".trinity" / "passport.json"
        passport.write_text(json.dumps({"identity": {"citizen_class": "specialist"}}), encoding="utf-8")
        as_specialist = architecture_check.check_template_baseline(str(entry))

        def strip(checks):
            return [(c["name"], c["passed"], c["message"]) for c in checks[1:]]

        # Non-empty first: two classes that both fail resolution outright would
        # compare [] == [] and report agreement where nothing was scored at all.
        assert strip(as_manager), "no per-item checks were scored"
        assert strip(as_manager) == strip(as_specialist)


class TestRefusedClassesScoreAViolation:
    """A class the registry refuses is a named scored violation -- never a crash, never a pass."""

    @pytest.mark.parametrize("legacy", sorted(architecture_check.LEGACY_CITIZEN_CLASSES))
    def test_every_retired_class_scores_by_name(self, tmp_path, monkeypatch, legacy):
        """Parametrised off the mirror, which the drift pin holds equal to spawn's."""
        _template(tmp_path, monkeypatch)
        entry = _branch(tmp_path, legacy)

        result = architecture_check.check_template_baseline(str(entry))

        assert len(result) == 1
        assert result[0]["passed"] is False, "an un-migrated passport must not score as compliant"
        assert result[0]["message"].startswith("Legacy citizen_class")
        assert f'"{legacy}"' in result[0]["message"]
        assert "mybranch/.trinity/passport.json" in result[0]["message"]

    def test_legacy_names_the_replacement_class(self, tmp_path, monkeypatch):
        """The violation says what to write instead, so the reader is not left guessing."""
        _template(tmp_path, monkeypatch)
        entry = _branch(tmp_path, "aipass_framework")

        message = architecture_check.check_template_baseline(str(entry))[0]["message"]

        assert '"specialist"' in message
        assert "migrate" in message.lower()

    def test_forbidden_class_is_not_labelled_legacy(self, tmp_path, monkeypatch):
        """'admin' was never a class, so 'migrate this passport' would be the wrong advice."""
        _template(tmp_path, monkeypatch)
        entry = _branch(tmp_path, "admin")

        result = architecture_check.check_template_baseline(str(entry))

        assert result[0]["passed"] is False
        assert result[0]["message"].startswith("Forbidden citizen_class")
        assert "DPLAN-0288" in result[0]["message"]

    def test_unknown_class_still_fails_loudly(self, tmp_path, monkeypatch):
        """Invented values are neither retired nor forbidden -- they are just wrong."""
        _template(tmp_path, monkeypatch)
        entry = _branch(tmp_path, "wizard")

        result = architecture_check.check_template_baseline(str(entry))

        assert result[0]["passed"] is False
        assert result[0]["message"].startswith("Unknown citizen_class")
        assert '"wizard"' in result[0]["message"]
        assert "manager" in result[0]["message"] and "specialist" in result[0]["message"]

    def test_refusal_never_reaches_the_filesystem(self, tmp_path, monkeypatch):
        """A refused class must fail on the value, not on a directory that happens to exist.

        Planting templates/aipass_framework/ recreates the pre-archive world: the
        raw join would find it and score a full clean baseline against a template
        that is no longer anyone's, reporting the un-migrated passport as fine.
        """
        templates = _template(tmp_path, monkeypatch).parent
        fossil = templates / "aipass_framework"
        (fossil / "apps").mkdir(parents=True)
        (fossil / "apps" / "{{BRANCH}}.py").write_text('"""Entry."""\n', encoding="utf-8")
        entry = _branch(tmp_path, "aipass_framework")

        result = architecture_check.check_template_baseline(str(entry))

        assert len(result) == 1
        assert result[0]["passed"] is False


class TestMirrorMatchesSpawn:
    """The mirror is only honest while it equals spawn's live registry."""

    def test_class_to_template_mapping_matches(self):
        """Every registered class maps to the directory spawn actually mints from.

        Compared as whole dicts, not key-by-key: a class ADDED in spawn and
        missing here would leave a live branch scored as 'Unknown citizen_class'
        while every mirrored key still agreed.
        """
        spawn_map = {name: spec["template_dir"] for name, spec in class_registry.CITIZEN_CLASSES.items()}
        assert architecture_check.CITIZEN_CLASS_TEMPLATES == spawn_map

    def test_legacy_map_matches(self):
        """A retired name added in spawn must not read as 'Unknown' here.

        The values matter too, not just the keys: the violation quotes the
        replacement class, so a wrong value tells a branch to write the wrong thing.
        """
        assert architecture_check.LEGACY_CITIZEN_CLASSES == class_registry.LEGACY_CLASSES

    def test_forbidden_set_matches(self):
        """A privilege refusal must not degrade into 'Unknown citizen_class'."""
        assert architecture_check.FORBIDDEN_CITIZEN_CLASSES == class_registry.FORBIDDEN_CLASSES

    def test_mirror_and_spawn_agree_on_every_value_they_know(self):
        """End-to-end agreement: spawn's resolver and the mirror answer the same.

        The three dict pins above can all hold while the CODE reading them
        diverges from spawn's behaviour, so this asks the two implementations
        the same questions and compares the answers.
        """
        known = (
            sorted(class_registry.CITIZEN_CLASSES)
            + sorted(class_registry.LEGACY_CLASSES)
            + sorted(class_registry.FORBIDDEN_CLASSES)
            + ["wizard", ""]
        )
        for value in known:
            mirrored, refusal = architecture_check._resolve_template_dir(value)
            # Asked through validate_class rather than by catching the raise:
            # a swallowed ValueError would also swallow a spawn bug that raises
            # for a class it says is valid, and this crosschecks the two.
            spawn_answer = class_registry.get_template_dir(value).name if class_registry.validate_class(value) else None
            assert mirrored == spawn_answer, f"{value!r}: mirror said {mirrored!r}, spawn said {spawn_answer!r}"
            assert bool(refusal) is (spawn_answer is None), f"{value!r}: refusal text and verdict disagree"


class TestResolutionSeamMatchesSpawn:
    """The one path fact seedgo still derives itself: the templates root."""

    def test_template_root_matches_spawn(self):
        """seedgo's SPAWN_TEMPLATES_DIR is the parent of what spawn's resolver returns.

        The checker keeps its own root constant so tests can point it at a fixture
        tree; that seam is only honest while it agrees with spawn. If spawn moves
        templates/, this fails here instead of silently scoring the fleet against
        a directory that no longer exists.
        """
        for citizen_class in class_registry.get_available_classes():
            spawn_dir = class_registry.get_template_dir(citizen_class).resolve()
            assert spawn_dir.parent == architecture_check.SPAWN_TEMPLATES_DIR.resolve()

    def test_checker_does_not_join_the_class_name(self):
        """The raw join is gone from the source, not just unreachable at runtime."""
        source = Path(architecture_check.__file__).read_text(encoding="utf-8")
        assert "SPAWN_TEMPLATES_DIR / citizen_class" not in source

    def test_live_template_dir_is_on_disk(self):
        """The template the fleet is actually scored against exists.

        Live-state, deliberately: the mirror can be perfectly in sync with spawn
        and still name a directory nobody shipped.
        """
        for dir_name in set(architecture_check.CITIZEN_CLASS_TEMPLATES.values()):
            live = architecture_check.SPAWN_TEMPLATES_DIR / dir_name
            assert live.is_dir(), f"mirrored template dir is missing on disk: {live}"
