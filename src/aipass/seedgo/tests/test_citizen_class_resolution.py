# =================== META ====================
# Name: test_citizen_class_resolution.py
# Description: Template baseline resolves class via spawn's modules gateway, never a mirror or a path join
# Version: 1.0.2
# Created: 2026-08-28
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/aipass_standards/architecture_check.py resolving citizen_class via spawn's gateway."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — the baseline's per-item dir and file rows; tests/test_coverage_arch_checklist.py
# seedgo: no-test-needed(stdlib) — json.load() reading the passport file

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import architecture_check

# The gateway is what production imports; the handler behind it is what these
# tests read to enumerate cases (the retired-name list is spawn's to own, and a
# test that hardcoded it would be the mirror coming back in through the door).
from aipass.spawn.apps import modules as spawn_gateway
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

    @pytest.mark.parametrize("legacy", sorted(class_registry.LEGACY_CLASSES))
    def test_every_retired_class_scores_by_name(self, tmp_path, monkeypatch, legacy):
        """Parametrised off spawn's own retired-name map, so a name added there is covered here."""
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

        assert "specialist" in message, "the replacement class must be named"
        assert "migrat" in message.lower(), "the reader must be told this is a migration, not a typo"
        # Spawn's own refusal is carried verbatim, never paraphrased.
        assert class_registry.refuse_legacy_class("aipass_framework") in message

    def test_forbidden_class_is_not_labelled_legacy(self, tmp_path, monkeypatch):
        """'admin' was never a class, so 'migrate this passport' would be the wrong advice."""
        _template(tmp_path, monkeypatch)
        entry = _branch(tmp_path, "admin")

        result = architecture_check.check_template_baseline(str(entry))

        message = result[0]["message"]
        assert result[0]["passed"] is False
        assert not message.startswith("Legacy citizen_class"), "admin must never be told to migrate"
        assert "migrat" not in message.lower()
        # The privilege refusal is what marks this lane apart, in spawn's words.
        assert "DPLAN-0288" in message
        assert "privilege" in message

    def test_unknown_class_still_fails_loudly(self, tmp_path, monkeypatch):
        """Invented values are neither retired nor forbidden -- they are just wrong."""
        _template(tmp_path, monkeypatch)
        entry = _branch(tmp_path, "wizard")

        result = architecture_check.check_template_baseline(str(entry))

        message = result[0]["message"]
        assert result[0]["passed"] is False
        assert not message.startswith("Legacy citizen_class"), "an invented name is not a migration"
        assert "migrat" not in message.lower()
        assert "DPLAN-0288" not in message, "a typo is not the admin privilege refusal"
        assert '"wizard"' in message
        assert "manager" in message and "specialist" in message

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


class TestGatewayIsTheOnlySource:
    """The mirror is retired. Nothing here may answer the class question locally."""

    def test_import_path_is_the_declared_gateway(self):
        """Production imports the two names from spawn's modules gateway.

        Pinned on the source text, not just on behaviour: reaching around to
        spawn.apps.handlers would still work at runtime while failing seedgo's
        own encapsulation and handlers standards, and a checker that breaks the
        rule it enforces on 17 branches is worse than a wrong answer.
        """
        source = Path(architecture_check.__file__).read_text(encoding="utf-8")
        assert "from aipass.spawn.apps.modules import get_template_dir, refuse_legacy_class" in source
        assert "spawn.apps.handlers" not in source

    def test_imported_names_are_spawns_own_callables(self):
        """Identity, not equivalence.

        A local reimplementation that merely agreed today would satisfy any
        behavioural pin and drift the moment spawn changed. This fails the
        instant the checker stops calling spawn's actual function.
        """
        assert architecture_check.get_template_dir is spawn_gateway.get_template_dir
        assert architecture_check.refuse_legacy_class is spawn_gateway.refuse_legacy_class
        assert architecture_check.get_template_dir is class_registry.get_template_dir
        assert architecture_check.refuse_legacy_class is class_registry.refuse_legacy_class

    def test_no_local_class_table_survives(self):
        """The mirrored constants are gone, by name.

        They were module-level and importable, so anything that still reads them
        would break loudly — but a NEW table under a new name is the failure this
        guards, which is why the source is checked for the shape as well.
        """
        for retired in ("CITIZEN_CLASS_TEMPLATES", "LEGACY_CITIZEN_CLASSES", "FORBIDDEN_CITIZEN_CLASSES"):
            assert not hasattr(architecture_check, retired), f"{retired} came back"

        # Read as CODE, not as text: the docstrings name "admin" and
        # "aipass_framework" as examples on purpose, and a substring search
        # would either fail on the prose or be weakened until it saw nothing.
        # Only a string LITERAL carrying one of these values is a second source.
        tree = ast.parse(Path(architecture_check.__file__).read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        spawns_facts = set(class_registry.LEGACY_CLASSES) | set(class_registry.FORBIDDEN_CLASSES)
        baked = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
        } & spawns_facts
        assert not baked, f"{sorted(baked)} baked into seedgo code -- spawn's facts to hold, not mine"

    def test_the_import_has_no_silent_fallback(self):
        """A missing gateway must kill the import, not degrade to a guess.

        The whole point of retiring the mirror is that spawn is the one source;
        a try/except ImportError around it would quietly restore two sources,
        with the fallback answering only on the days spawn is broken.
        """
        source = Path(architecture_check.__file__).read_text(encoding="utf-8")
        assert "except ImportError" not in source
        assert "ModuleNotFoundError" not in source

    def test_a_missing_gateway_fails_loudly_at_import(self):
        """Behaviour, not just source: block the gateway and the checker must die.

        The source pin above says no `except ImportError` is written; this proves
        the consequence in a fresh interpreter, which also covers a fallback
        arriving by some other spelling. Run as a subprocess because the import
        must fail from cold — this module is already in sys.modules here.
        """
        script = textwrap.dedent(
            """
            import sys

            class Blocker:
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == "aipass.spawn.apps.modules":
                        raise ImportError("gateway removed")
                    return None

            sys.meta_path.insert(0, Blocker())
            try:
                from aipass.seedgo.apps.handlers.aipass_standards import architecture_check
            except ImportError:
                print("LOUD")
            else:
                print("SILENT")
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, encoding="utf-8", timeout=120
        )
        assert proc.stdout.strip() == "LOUD", f"stdout={proc.stdout!r} stderr={proc.stderr[-400:]!r}"

    def test_resolution_matches_spawn_on_every_value_spawn_knows(self, tmp_path, monkeypatch):
        """Mutant: refused class made citizen in apps/handlers/aipass_standards/architecture_check.py — killed."""
        # End to end: the checker's answer IS spawn's answer, for every known value.
        known = (
            sorted(class_registry.CITIZEN_CLASSES)
            + sorted(class_registry.LEGACY_CLASSES)
            + sorted(class_registry.FORBIDDEN_CLASSES)
            + ["wizard", ""]
        )
        # Floor, not a mirror: the counts belong to spawn, so this asserts the
        # registries are populated rather than pinning what they hold. With them
        # empty the walk below would only exercise the two literals above.
        assert class_registry.CITIZEN_CLASSES, "spawn registers no citizen class - the walk proves nothing"
        templates = _template(tmp_path, monkeypatch).parent
        entry = _branch(tmp_path, "")
        passport = entry.parent.parent / ".trinity" / "passport.json"
        for value in known:
            expected = spawn_gateway.get_template_dir(value).name if class_registry.validate_class(value) else None
            if expected:
                (templates / expected / "apps").mkdir(parents=True, exist_ok=True)
            passport.write_text(json.dumps({"identity": {"citizen_class": value}}), encoding="utf-8")
            head = architecture_check.check_template_baseline(str(entry))[0]
            # Reached through the command: a resolved class names spawn's directory in
            # the scored summary, a refused one is a single failed row.
            if expected is None:
                assert head["passed"] is False, f"{value!r}: spawn refuses it, the checker passed it"
                assert head["name"] == "Template baseline", f"{value!r}: refused yet scored as a class"
            else:
                assert head["name"] == f"Template baseline ({value})", f"{value!r}: spawn resolves it, checker refused"
                assert f"spawn/templates/{expected}/" in head["message"], f"{value!r}: checker said {head!r}"

    def test_the_three_lanes_stay_apart(self, tmp_path, monkeypatch):
        """Retired, forbidden and unregistered each get their own answer.

        Compared as a set of three distinct messages rather than three separate
        assertions: the failure being guarded is two lanes collapsing into one
        sentence, which no single-lane assertion can see. Read through the
        scored row, whose message carries the refusal verbatim.
        Mutant: spawn's refusal text dropped from the unresolved lane in
        apps/handlers/aipass_standards/architecture_check.py — killed.
        """
        _template(tmp_path, monkeypatch)
        messages = {
            lane: architecture_check.check_template_baseline(str(_branch(tmp_path / lane, value)))[0]["message"]
            for lane, value in (("legacy", "aipass_framework"), ("forbidden", "admin"), ("unknown", "wizard"))
        }
        assert len(set(messages.values())) == 3
        assert "migrat" in messages["legacy"].lower()
        assert "migrat" not in messages["forbidden"].lower()
        assert "migrat" not in messages["unknown"].lower()
        assert "DPLAN-0288" in messages["forbidden"]
        assert "DPLAN-0288" not in messages["unknown"]


class TestResolutionSeamMatchesSpawn:
    """The one path fact seedgo still derives itself: the templates root."""

    def test_template_root_matches_spawn(self):
        """seedgo's SPAWN_TEMPLATES_DIR is the parent of what spawn's resolver returns.

        The checker keeps its own root constant so tests can point it at a fixture
        tree; that seam is only honest while it agrees with spawn. If spawn moves
        templates/, this fails here instead of silently scoring the fleet against
        a directory that no longer exists.
        """
        available = class_registry.get_available_classes()
        assert available, "spawn registers no citizen class - there is no root to agree about"
        for citizen_class in available:
            spawn_dir = spawn_gateway.get_template_dir(citizen_class).resolve()
            assert spawn_dir.parent == architecture_check.SPAWN_TEMPLATES_DIR.resolve()

    def test_checker_does_not_join_the_class_name(self):
        """The raw join is gone from the source, not just unreachable at runtime."""
        source = Path(architecture_check.__file__).read_text(encoding="utf-8")
        assert "SPAWN_TEMPLATES_DIR / citizen_class" not in source

    def test_live_template_dir_is_on_disk(self):
        """The template the fleet is actually scored against exists.

        Live-state, deliberately: the gateway can resolve perfectly and still
        name a directory nobody shipped.
        """
        available = class_registry.get_available_classes()
        assert available, "spawn registers no citizen class - no template dir is being checked"
        for citizen_class in available:
            dir_name = spawn_gateway.get_template_dir(citizen_class).name
            live = architecture_check.SPAWN_TEMPLATES_DIR / dir_name
            assert live.is_dir(), f"resolved template dir is missing on disk: {live}"
