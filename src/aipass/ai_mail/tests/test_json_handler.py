# =================== AIPass ====================
# Name: test_json_handler.py
# Description: Tests for JSON handler (auto-creating & self-healing JSON system)
# Version: 1.1.0
# Created: 2026-03-27
# Modified: 2026-09-02
# =============================================

"""Tests for json_handler -- default factory, validation, paths, load/save, ensure_module."""

import ast
import json
import sys
import importlib
import pytest
from pathlib import Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.json_utils.json_handler as jh_mod
from aipass.ai_mail.apps.handlers.json_utils.json_handler import (
    get_json_path,
    validate_json_structure,
    load_template,
    ensure_json_exists,
    load_json,
    save_json,
    ensure_module_jsons,
)

# The functions imported above are bound to ``jh_mod``'s namespace, so every
# patch in this file must target ``jh_mod`` itself.  Under pytest-xdist another
# test on the same worker can evict this key from sys.modules; a re-import would
# then create a second, divergent module instance and any test that reloads or
# mocks via sys.modules would leave the shared object stale.
_MODULE_KEY = jh_mod.__name__


def _module_chain(module) -> dict:
    """Map the module *and every ancestor package* to the objects imported here.

    importlib.reload() needs both ``sys.modules[module.__name__] is module`` and
    ``sys.modules[parent_package]`` (it reads ``parent.__path__``), so pinning
    only the leaf is not enough.
    """
    parts = module.__name__.split(".")
    chain = {".".join(parts[:i]): sys.modules[".".join(parts[:i])] for i in range(1, len(parts))}
    chain[module.__name__] = module
    return chain


_MODULE_CHAIN = _module_chain(jh_mod)


# ---- Fixtures --------------------------------------------------------


@pytest.fixture(autouse=True)
def _pin_module_identity():
    """Keep sys.modules pointing at the module objects this file imported.

    Restores the exact pre-test objects on both sides of every test so
    importlib.reload() and the monkeypatch.setattr calls below always act on
    the same instances, whatever a neighbouring test did to sys.modules.
    """
    sys.modules.update(_MODULE_CHAIN)
    yield
    sys.modules.update(_MODULE_CHAIN)


@pytest.fixture(autouse=True)
def _isolate_json_dir(tmp_path, monkeypatch):
    """Redirect AI_MAIL_JSON_DIR and JSON_TEMPLATES_DIR to tmp_path."""
    monkeypatch.setattr(jh_mod, "AI_MAIL_JSON_DIR", tmp_path / "json_out")
    monkeypatch.setattr(jh_mod, "JSON_TEMPLATES_DIR", tmp_path / "templates")


@pytest.fixture
def template_dir(tmp_path):
    """Create a templates/default/ directory with sample templates."""
    tpl_dir = tmp_path / "templates" / "default"
    tpl_dir.mkdir(parents=True)
    return tpl_dir


@pytest.fixture
def config_template(template_dir, monkeypatch):
    """Write a config template and point JSON_TEMPLATES_DIR at it."""
    tpl = {"module_name": "{{MODULE_NAME}}", "version": "1.0.0", "config": {"max_log_entries": 50}}
    tpl_file = template_dir / "config.json"
    tpl_file.write_text(json.dumps(tpl))
    monkeypatch.setattr(jh_mod, "JSON_TEMPLATES_DIR", template_dir.parent)
    return tpl_file


@pytest.fixture
def data_template(template_dir, monkeypatch):
    """Write a data template."""
    tpl = {"created": "{{TIMESTAMP}}", "last_updated": "{{TIMESTAMP}}"}
    tpl_file = template_dir / "data.json"
    tpl_file.write_text(json.dumps(tpl))
    monkeypatch.setattr(jh_mod, "JSON_TEMPLATES_DIR", template_dir.parent)
    return tpl_file


@pytest.fixture
def log_template(template_dir, monkeypatch):
    """Write a log template (empty list)."""
    tpl_file = template_dir / "log.json"
    tpl_file.write_text("[]")
    monkeypatch.setattr(jh_mod, "JSON_TEMPLATES_DIR", template_dir.parent)
    return tpl_file


# ---- get_json_path tests (get_path) ----------------------------------


def test_get_json_path_returns_path():
    """get_json_path returns a pathlib.Path object."""
    result = get_json_path("email", "config")
    assert isinstance(result, Path), "paths_return_path: should return Path"


def test_get_json_path_correct_filename():
    """Path ends with module_type pattern."""
    result = get_json_path("email", "data")
    assert result.name == "email_data.json"


# ---- validate_json_structure tests (validate) ------------------------


def test_validate_config_valid():
    """Valid config structure passes validation."""
    data = {"module_name": "test", "version": "1.0", "config": {}}
    assert validate_json_structure(data, "config") is True
    # config_keys check: module_name is a required key
    assert "module_name" in data


def test_validate_config_missing_keys():
    """Config missing required keys fails validation."""
    data = {"version": "1.0"}
    assert validate_json_structure(data, "config") is False


def test_validate_data_valid():
    """Valid data structure passes."""
    data = {"created": "2026-01-01", "last_updated": "2026-01-01"}
    assert validate_json_structure(data, "data") is True


def test_validate_log_valid():
    """Log type expects a list."""
    assert validate_json_structure([], "log") is True
    assert validate_json_structure({}, "log") is False


def test_validate_invalid_type():
    """Unknown json_type returns False (invalid_mode_raises alternative)."""
    result = validate_json_structure({}, "nonexistent_type")
    assert result is False


def test_validate_config_not_dict():
    """Non-dict config fails."""
    assert validate_json_structure("string", "config") is False


# ---- load_template tests (default_factory) ---------------------------


def test_load_template_creates_default(config_template):
    """load_template loads and applies _create_default template with placeholders."""
    result = load_template("config", "my_module")
    assert result is not None
    assert result["module_name"] == "my_module"


def test_load_template_missing_file():
    """Missing template file returns None (FileNotFoundError resilience)."""
    result = load_template("nonexistent", "test")
    assert result is None


# ---- ensure_json_exists tests (ensure_exists) ------------------------


def test_ensure_json_exists_creates_file(config_template, tmp_path, monkeypatch):
    """ensure_json_exists auto-creates JSON from template when missing."""
    monkeypatch.setattr(jh_mod, "AI_MAIL_JSON_DIR", tmp_path / "json_out")
    result = ensure_json_exists("test_mod", "config")
    assert result is True
    json_path = get_json_path("test_mod", "config")
    assert json_path.exists()


def test_ensure_json_exists_no_overwrite(config_template, tmp_path, monkeypatch):
    """ensure_json_exists does not overwrite valid existing files (no_overwrite / already_exists)."""
    monkeypatch.setattr(jh_mod, "AI_MAIL_JSON_DIR", tmp_path / "json_out")
    # Create first
    ensure_json_exists("test_mod", "config")
    json_path = get_json_path("test_mod", "config")
    first_content = json_path.read_text()

    # Ensure again — should not overwrite
    ensure_json_exists("test_mod", "config")
    assert json_path.read_text() == first_content


def test_ensure_json_exists_no_template():
    """Returns False when no template available for type."""
    result = ensure_json_exists("test_mod", "nonexistent")
    assert result is False


# ---- load_json tests (load) -----------------------------------------


def test_load_json_auto_creates(config_template, tmp_path, monkeypatch):
    """load_json auto-creates missing files via ensure_json_exists."""
    monkeypatch.setattr(jh_mod, "AI_MAIL_JSON_DIR", tmp_path / "json_out")
    result = load_json("auto_mod", "config")
    assert isinstance(result, dict)
    assert result["module_name"] == "auto_mod"


def test_load_json_missing_file_no_template():
    """load_json returns None when file doesn't exist and no template."""
    result = load_json("missing_mod", "nonexistent")
    assert result is None


# ---- save_json tests (save) -----------------------------------------


def test_save_json_valid_config(tmp_path, monkeypatch):
    """save_json writes valid config data."""
    monkeypatch.setattr(jh_mod, "AI_MAIL_JSON_DIR", tmp_path / "json_out")
    (tmp_path / "json_out").mkdir(parents=True)
    data = {"module_name": "test", "version": "1.0", "config": {"key": "val"}}
    result = save_json("test", "config", data)
    assert result is True

    # Verify file contents
    saved = json.loads(get_json_path("test", "config").read_text())
    assert saved["module_name"] == "test"


def test_save_json_invalid_structure():
    """save_json rejects data that fails validation."""
    result = save_json("test", "config", {"incomplete": True})
    assert result is False


def test_save_json_data_updates_timestamp(tmp_path, monkeypatch):
    """save_json for data type updates last_updated field."""
    monkeypatch.setattr(jh_mod, "AI_MAIL_JSON_DIR", tmp_path / "json_out")
    (tmp_path / "json_out").mkdir(parents=True)
    data = {"created": "2026-01-01", "last_updated": "2026-01-01"}
    save_json("ts_mod", "data", data)
    saved = json.loads(get_json_path("ts_mod", "data").read_text())
    assert saved["last_updated"] != "2026-01-01"  # Updated to today


# ---- ensure_module_jsons tests (ensure_module) -----------------------


def test_ensure_module_jsons_returns_true(config_template, data_template, log_template, tmp_path, monkeypatch):
    """ensure_module_jsons creates all 3 JSON types for a module."""
    monkeypatch.setattr(jh_mod, "AI_MAIL_JSON_DIR", tmp_path / "json_out")
    result = ensure_module_jsons("full_mod")
    assert result is True


# ---- Infrastructure mocking tests -----------------------------------


def test_sys_modules_mock_json_handler(monkeypatch):
    """Verify json_handler can be mocked via sys.modules for import isolation."""
    mock_mod = MagicMock()
    # monkeypatch.setitem restores the entry automatically; the manual
    # try/finally this replaced deleted the key outright whenever the module
    # was already missing, leaving every later test without it.
    monkeypatch.setitem(sys.modules, _MODULE_KEY, mock_mod)
    # After mocking sys.modules, reimport_after_mock with importlib.reload
    # would pick up the mock (we just verify the mechanism works)
    assert sys.modules[_MODULE_KEY] is mock_mod


def test_reimport_after_mock():
    """importlib.reload restores module after mock replacement."""
    # _pin_module_identity guarantees sys.modules holds this exact object, which
    # is what reload() requires; reload re-executes in place so the module
    # identity every other test module holds stays valid.
    assert sys.modules[_MODULE_KEY] is jh_mod
    reloaded = importlib.reload(jh_mod)
    assert reloaded is jh_mod
    assert hasattr(jh_mod, "get_json_path")


# --- Durability: the write stages and swaps, it never truncates -------
#
# save_json wrote with open(path, "w") + json.dump until 2026-09-02. The
# truncation happens when the file is OPENED, so any failure during the dump
# destroyed the live document while save_json returned False — the caller heard
# "did not save" when the truth was "your previous document is gone too". This
# is the citizen mail store. Found by seedgo's durability contract (FPLAN-0481),
# which observed a concurrent reader seeing an EMPTY mailbox six times in one
# four-writer run, and reproduced here on the real handler before the cure.
#
# Deliberately only two pins. seedgo's contract already runs the six helper
# behaviours and the concurrency race against every branch including this one;
# copying them here would be a twin, not coverage.


def _truncating_open_sites(source: str) -> list:
    """Write-mode ``open()`` CALLS in *source*, found by shape, not by spelling.

    AST, not a regex, and the reason is that the first version of this guard
    went red on the CURED file: its regex matched the docstring EXPLAINING the
    defect, because prose quoting ``open(path, "w")`` is indistinguishable from
    code to a character match. Same lesson as this branch's inspect.stack() ban
    (2026-08-31) — a ban on a spelling convicts prose.

    ``os.fdopen`` is excluded by matching the callable, not by a lookbehind: it
    receives a descriptor mkstemp already created privately, so it has no live
    document to truncate.

    Returns:
        ``line:mode`` strings, one per offending call.
    """
    offenders = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "open":
            continue
        mode = None
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            mode = node.args[1].value
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = kw.value.value
        if isinstance(mode, str) and mode[:1] in ("w", "a"):
            offenders.append(f"line {node.lineno}: open(..., {mode!r})")
    return offenders


def test_the_source_guard_convicts_a_truncating_write():
    """Negative control: a guard that convicts nothing reports any file clean."""
    assert _truncating_open_sites('open(p, "w")') == ["line 1: open(..., 'w')"]
    assert _truncating_open_sites('open(p, mode="a")') == ["line 1: open(..., 'a')"]


def test_the_source_guard_acquits_reads_fdopen_and_prose():
    """Positive control, and the exact three things it must NOT convict.

    The prose case is the one that already caught me: this file and the handler
    both discuss ``open(path, "w")`` in docstrings, and a character match
    convicts both.
    """
    assert _truncating_open_sites('open(p, "r")') == []
    assert _truncating_open_sites('os.fdopen(fd, "w")') == []
    assert _truncating_open_sites('"""Until today it used open(path, \'w\')."""') == []


def test_no_truncating_open_survives_in_the_handler_source():
    """No write-mode open() on a path remains in the handler.

    A guard, not a style rule: one re-introduced write-mode open restores the
    whole defect and reads as harmless in review. os.fdopen is exempt — it
    wraps a descriptor mkstemp already created privately, so there is no live
    document for it to truncate.

    It earned its keep immediately: written against save_json, it convicted a
    SECOND truncating write in ensure_json_exists that the brief never named.
    That is why it bans the shape rather than a line.
    """
    offenders = _truncating_open_sites(Path(jh_mod.__file__).read_text(encoding="utf-8"))

    assert offenders == [], f"truncating open() found in handler source: {offenders}"


def test_save_json_routes_through_the_bounded_replace_helper(tmp_path, monkeypatch):
    """A successful save reaches _replace_with_retry — staged, then swapped.

    Counted on the HELPER rather than on os.replace on purpose: a counter on the
    syscall stays green if someone inlines os.replace and drops the bounded
    retry, which is exactly the refactor the source guard above cannot see and
    this pin exists to forbid.
    """
    calls = []
    real_helper = jh_mod._replace_with_retry

    def counting_helper(source, destination):
        calls.append((source, destination))
        real_helper(source, destination)

    monkeypatch.setattr(jh_mod, "_replace_with_retry", counting_helper)
    monkeypatch.setattr(jh_mod, "get_json_path", lambda *a, **k: tmp_path / "store.json")

    assert save_json("mail", "data", {"created": "2026-09-02", "last_updated": "2026-09-02"}) is True
    assert len(calls) == 1, f"helper called {len(calls)} times, expected exactly 1"

    staged, destination = calls[0]
    # The temp is staged in the TARGET's directory — a cross-filesystem rename
    # is not atomic, so a temp in /tmp would silently reintroduce the window.
    assert Path(staged).parent == Path(destination).parent
    assert not Path(staged).exists(), "staged temp survived the swap"
    assert json.loads((tmp_path / "store.json").read_text(encoding="utf-8"))["created"] == "2026-09-02"
