"""Canaries for what the shipped templates are allowed to contain.

A template is a blueprint: every file in it is copied into every new citizen,
forever. Build artifacts that drift in are invisible — they cost nothing to
create and never fail anything — so they need a standing test rather than a
review pass.

`.pytest_cache/` drifted in this way (flagged 2026-08-07, still shipping on
2026-08-13): the copy engine skips `__pycache__` but not `.pytest_cache`, so
every branch was born carrying spawn's own cached test node IDs
(DPLAN-0291 audit).
"""

from pathlib import Path

import pytest

import aipass.spawn
from aipass.spawn.apps.handlers.class_registry import get_available_classes, get_template_dir

ARTIFACT_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}

# __pycache__ reappears in the template tree whenever anything imports its .py files.
# It is gitignored and never copied, so its presence on disk proves nothing — the tree
# canaries below check only the artifacts that persist and get committed.
TRANSIENT_DIRS = {"__pycache__"}
PERSISTENT_ARTIFACTS = ARTIFACT_DIRS - TRANSIENT_DIRS

TEMPLATE_CLASSES = sorted(get_available_classes())


def _template_registry(class_name: str) -> Path:
    return get_template_dir(class_name) / ".spawn" / ".template_registry.json"


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_no_build_artifacts_in_template_tree(class_name):
    """No cache directory may live in a template — it would be copied into every branch."""
    template = get_template_dir(class_name)

    found = [
        str(path.relative_to(template))
        for path in template.rglob("*")
        if path.is_dir() and path.name in PERSISTENT_ARTIFACTS
    ]

    assert found == [], f"{class_name} template ships build artifacts: {found}"


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_no_build_artifacts_tracked_in_registry(class_name):
    """The registry must not track artifacts either — tracking re-adds them on update."""
    import json

    registry_path = _template_registry(class_name)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    tracked = list(registry.get("files", {}).values()) + list(registry.get("directories", {}).values())
    paths = [entry if isinstance(entry, str) else entry.get("path", "") for entry in tracked]

    polluted = [p for p in paths if any(part in ARTIFACT_DIRS for part in Path(p).parts)]

    assert polluted == [], f"{class_name} registry tracks build artifacts: {polluted}"


def test_copy_engine_skips_artifact_dirs():
    """The skip set is the enforcement point — keep it honest about every cache dir."""
    from aipass.spawn.apps.handlers.file_ops import SKIP_NAMES

    assert ARTIFACT_DIRS <= set(SKIP_NAMES)


def test_spawn_package_ships_no_artifact_dirs():
    """Belt and braces: the installed package itself carries no cache dirs under templates/."""
    templates_root = Path(aipass.spawn.__file__).parent / "templates"

    found = [str(p) for p in templates_root.rglob("*") if p.is_dir() and p.name in PERSISTENT_ARTIFACTS]

    assert found == []


# ---------------------------------------------------------------------------
# Mint completeness — a truncated template must refuse, never mint quietly
# ---------------------------------------------------------------------------

# The exact files the repo-root .gitignore swallowed out of the (then) project_agent
# template until 2026-08-17: blanket rules for .ai_mail.local/, DASHBOARD.local.json,
# logs/ and artifacts/ with no negation for that template. A fresh clone got 12 of 18
# files, and the mint copied what it found without a word of complaint. That template
# retired to templates/.archive/ with DPLAN-0319 R3; the casualty LIST did not, because
# the gitignore rules that caused it still apply to the one template that replaced it.
FRESH_CLONE_CASUALTIES = (
    ".ai_mail.local/inbox.json",
    ".ai_mail.local/README.md",
    "artifacts/birth_certificate.json",
    "artifacts/README.md",
    "logs/README.md",
    "DASHBOARD.local.json",
)


def _truncated_template(tmp_path, class_name=None, casualties=FRESH_CLONE_CASUALTIES):
    """Copy a real template, then remove files the way a fresh clone would.

    The manifest (.spawn/.template_registry.json) is deliberately KEPT — it is
    tracked, so a truncated clone still carries the template's own declaration
    of what it should contain. That declaration is the only evidence left that
    the missing files ever existed.
    """
    import shutil

    stripped = tmp_path / "stripped_template"
    template = get_template_dir(class_name) if class_name else get_template_dir()
    shutil.copytree(template, stripped)
    for rel in casualties:
        (stripped / rel).unlink()
    return stripped


class TestMintCompleteness:
    """A mint that cannot deliver the template's own contract must fail out loud.

    Found the hard way: with those six files gitignored, `create` against the
    truncated template exited 0, printed "Agent created", registered the citizen
    — and produced an empty artifacts/ (no birth certificate) and an empty
    .ai_mail.local/ (no
    inbox.json, so the citizen could not receive mail at all). Silent success on
    a broken citizen is the opposite of "code is truth — fail honestly".
    """

    def test_truncated_template_refuses_and_names_what_is_missing(self, tmp_path):
        """The refusal must name every file that never landed."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        template = _truncated_template(tmp_path)
        registry = tmp_path / "AIPASS_REGISTRY.json"

        result = _spawn_agent(
            str(tmp_path / "minted"),
            template_dir=str(template),
            registry_path=str(registry),
        )

        assert result["success"] is False, "an incomplete mint reported success"
        for rel in FRESH_CLONE_CASUALTIES:
            assert rel in result["error"], f"refusal never names {rel}: {result['error']}"

    def test_truncated_mint_is_never_registered(self, tmp_path):
        """No half-citizen in the registry — refuse before the registry write."""
        import json

        from aipass.spawn.apps.modules.core import _spawn_agent

        template = _truncated_template(tmp_path)
        registry = tmp_path / "AIPASS_REGISTRY.json"

        result = _spawn_agent(
            str(tmp_path / "minted"),
            template_dir=str(template),
            registry_path=str(registry),
        )

        assert result["registry_updated"] is False
        if registry.exists():
            names = [b["name"] for b in json.loads(registry.read_text(encoding="utf-8")).get("branches", [])]
            assert "MINTED" not in names, f"broken citizen registered anyway: {names}"

    def test_cli_create_exits_nonzero_and_prints_no_success(self, tmp_path):
        """The command itself must not exit 0 or say "Agent created"."""
        from unittest.mock import patch

        from aipass.spawn.apps.spawn import handle_create

        template = _truncated_template(tmp_path)

        with (
            patch("aipass.spawn.apps.spawn.console") as mock_console,
            patch("aipass.spawn.apps.spawn.error") as mock_error,
        ):
            code = handle_create(
                [
                    str(tmp_path / "minted"),
                    "--template",
                    str(template),
                    "--registry",
                    str(tmp_path / "AIPASS_REGISTRY.json"),
                ]
            )

        assert code == 1
        printed = " ".join(str(call) for call in mock_console.print.call_args_list)
        assert "Agent created" not in printed, printed
        mock_error.assert_called_once()

    @pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
    def test_complete_template_still_mints(self, tmp_path, class_name):
        """The guard must not fire on the real, whole templates — either class."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / f"whole_{class_name}"
        result = _spawn_agent(
            str(target),
            citizen_class=class_name,
            registry_path=str(tmp_path / "AIPASS_REGISTRY.json"),
        )

        assert result["success"] is True, result.get("error")
        assert (target / "artifacts" / "birth_certificate.json").is_file()
        assert (target / ".ai_mail.local" / "inbox.json").is_file()

    def test_custom_template_without_manifest_still_mints(self, tmp_path):
        """A bare `--template <dir>` carries no manifest — that is not a defect.

        Nothing declares a contract, so the only honest check is that everything
        the directory does contain arrived. It does, so this must succeed.
        """
        from aipass.spawn.apps.modules.core import _spawn_agent

        template = tmp_path / "bare_template"
        (template / "apps").mkdir(parents=True)
        (template / "apps" / "{{BRANCH}}.py").write_text("# {{BRANCHNAME}}\n", encoding="utf-8")
        (template / "notes.md").write_text("hello\n", encoding="utf-8")

        target = tmp_path / "bare_minted"
        result = _spawn_agent(
            str(target),
            template_dir=str(template),
            registry_path=str(tmp_path / "AIPASS_REGISTRY.json"),
        )

        assert result["success"] is True, result.get("error")
        assert (target / "apps" / "bare_minted.py").is_file()
        assert (target / "notes.md").is_file()


class TestExpectedMintPaths:
    """The claim-to-disk mapping is the part that can silently mis-compare.

    A claim like ``apps/{{BRANCH}}.py`` must be checked as ``apps/my_agent.py``.
    Get that wrong and the guard either never fires or fires on every mint.
    """

    def test_branch_placeholder_is_rendered_not_literal(self, tmp_path):
        from aipass.spawn.apps.handlers.mint_verify import expected_mint_paths
        from aipass.spawn.apps.handlers.placeholders import build_replacements_dict

        replacements = build_replacements_dict(tmp_path / "my_agent", "my_agent")
        expected = expected_mint_paths(get_template_dir(), replacements, "my_agent")

        assert "apps/my_agent.py" in expected
        assert not [rel for rel in expected if "{{" in rel], "unrendered placeholder left in a claim"

    def test_verify_mint_returns_only_what_is_missing(self, tmp_path):
        """Present files stay silent; the one absent file is named."""
        import json

        from aipass.spawn.apps.handlers.mint_verify import verify_mint

        template = tmp_path / "tmpl"
        (template / ".spawn").mkdir(parents=True)
        (template / "kept.md").write_text("kept\n", encoding="utf-8")
        (template / ".spawn" / ".template_registry.json").write_text(
            json.dumps(
                {
                    "files": {
                        "f001": {"path": "kept.md"},
                        "f002": {"path": "artifacts/birth_certificate.json"},
                    },
                    "directories": {},
                }
            ),
            encoding="utf-8",
        )

        target = tmp_path / "minted"
        target.mkdir()
        (target / "kept.md").write_text("kept\n", encoding="utf-8")

        assert verify_mint(template, target, {}, "minted") == ["artifacts/birth_certificate.json"]
