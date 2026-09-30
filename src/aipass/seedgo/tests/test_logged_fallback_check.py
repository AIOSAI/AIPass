# =================== META ====================
# Name: test_logged_fallback_check.py
# Description: logged_fallback_check — an except returning a default the success path can also return
# Version: 1.0.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""Tests for apps/handlers/aipass_standards/logged_fallback_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — an except with no logger call and no raise; tests/test_checkers_batch7.py

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import logged_fallback_check as checker


def _verdict(tmp_path, body, name="client.py"):
    """(score, the one check's message) for a file planted under apps/."""
    apps = tmp_path / "apps"
    apps.mkdir(exist_ok=True)
    path = apps / name
    path.write_text(body, encoding="utf-8")
    result = checker.check_module(str(path))
    return result["score"], result["checks"][0]["message"]


def _lines(message):
    """The file:line heads of every finding in a message."""
    return [line.split(" ")[0] for line in message.splitlines()]


#: The pack's newest checker, the model this one was built from.
MODEL = Path(__file__).parent.parent / "apps" / "handlers" / "aipass_standards" / "os_walk_onerror_check.py"

#: @backup's apps/handlers/drive/client.py, get_or_create_backup_folder as on disk 2026-09-25,
#: docstring and the create half cut. The handler's `return None` is line 23 here, 184 on disk;
#: the success path's `return None` (no service) is line 10.
SPECIMEN = """class DriveClient:
    def get_or_create_backup_folder(self) -> str | None:
        # Short-circuit: verify cached ID
        if self.backup_folder_id:
            if self._verify_folder_id(self.backup_folder_id):
                return self.backup_folder_id
            self.backup_folder_id = None

        if not self.drive_service:
            return None

        # Search for existing
        query = f"name='{BACKUP_FOLDER_NAME}' and mimeType='{FOLDER_MIME}' and trashed=false"
        try:
            request = self.drive_service.files().list(q=query, spaces="drive", fields="files(id,name)")
            result = self._api_call(request)
            if result and result.get("files"):
                self.backup_folder_id = result["files"][0]["id"]
                return self.backup_folder_id
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning(f"Failed to search for backup folder: {exc}")
            return None
        return self._create(query)
"""

SPECIMEN_LINE = 23

#: @backup's _api_call as on disk (client.py:116-128): its success path returns a call, so its
#: None is a sentinel by this rule. The conflation lives in the caller above, which IS convicted.
API_CALL = """class DriveClient:
    def _api_call(self, request, max_retries=3):
        try:
            return api_call_with_retry(request, max_retries=max_retries)
        except Exception as first_exc:
            logger.info(f"API call failed, rebuilding thread service: {first_exc}")
            try:
                self._thread_local.service = self._build_thread_service()
                return api_call_with_retry(request, max_retries=1)
            except Exception as exc:
                self.last_error = str(exc)
                logger.info(f"API call retry also failed: {exc}")
                return None
"""


def _function(handler_return, success_return, setup=""):
    """A function whose handler ends in one return and whose success path ends in another."""
    return (
        "def fetch(key):\n"
        f"{setup}"
        "    try:\n"
        "        value = load(key)\n"
        "    except OSError as exc:\n"
        "        logger.warning(exc)\n"
        f"        return {handler_return}\n"
        "    if value is None:\n"
        f"        return {success_return}\n"
        "    return value\n"
    )


class TestTheModelFilePasses:
    def test_the_model_checker_scores_100(self):
        assert checker.check_module(str(MODEL))["score"] == 100


class TestThePlantedSpecimen:
    def test_backups_folder_search_is_convicted_on_its_handler_return(self, tmp_path):
        score, message = _verdict(tmp_path, SPECIMEN)
        assert score == 0
        assert _lines(message) == [f"client.py:{SPECIMEN_LINE}"]

    def test_a_finding_names_the_default_the_reason_and_the_cure(self, tmp_path):
        message = _verdict(tmp_path, _function("None", "None"))[1]
        assert message == (
            "client.py:6 except returns None - the success path can return the same value, so the caller "
            "cannot tell failure from an answer; re-raise, or return a value the success path cannot return "
            "and name it in the docstring"
        )

    def test_the_specimen_cured_by_a_raise_passes(self, tmp_path):
        handler_tail = "            return None\n        return self._create"
        cured = SPECIMEN.replace(handler_tail, "            raise\n        return self._create")
        assert _verdict(tmp_path, cured) == (100, "No handler returns a default the success path can also return")

    def test_backups_api_call_none_is_a_sentinel_and_passes(self, tmp_path):
        assert _verdict(tmp_path, API_CALL)[0] == 100


class TestTheSameValue:
    @pytest.mark.parametrize("default", ["None", "False", "True", "0", "''", "'unknown'", "[]", "{}", "()", "set()"])
    def test_an_equal_literal_on_the_success_path_convicts(self, tmp_path, default):
        assert _verdict(tmp_path, _function(default, default))[0] == 0

    def test_a_name_first_bound_to_the_literal_convicts(self, tmp_path):
        body = (
            "def find(pattern):\n"
            "    results = []\n"
            "    try:\n"
            "        results = search(pattern)\n"
            "    except OSError as exc:\n"
            "        logger.warning(exc)\n"
            "        return []\n"
            "    return results\n"
        )
        assert _lines(_verdict(tmp_path, body)[1]) == ["client.py:7"]

    def test_an_empty_constructor_and_its_literal_are_the_same_value(self, tmp_path):
        assert _verdict(tmp_path, _function("dict()", "{}"))[0] == 0

    @pytest.mark.parametrize("text", ["f'failed: {exc}'", "str(exc)"])
    def test_a_string_from_the_exception_convicts_beside_a_string_success(self, tmp_path, text):
        assert _verdict(tmp_path, _function(text, "'empty'"))[0] == 0

    def test_logging_does_not_acquit(self, tmp_path):
        body = _function("None", "None").replace("logger.warning(exc)", "logger.error(exc)\n        logger.info(exc)")
        assert _verdict(tmp_path, body)[0] == 0


class TestWhatPasses:
    def test_a_none_sentinel_beside_dict_returns_passes(self, tmp_path):
        assert _verdict(tmp_path, _function("None", "{'found': False}"))[0] == 100

    def test_a_minus_one_sentinel_beside_a_count_passes(self, tmp_path):
        assert _verdict(tmp_path, _function("-1", "len(value)"))[0] == 100

    def test_false_is_not_the_same_value_as_zero(self, tmp_path):
        assert _verdict(tmp_path, _function("False", "0"))[0] == 100

    def test_a_string_from_the_exception_beside_no_string_success_passes(self, tmp_path):
        assert _verdict(tmp_path, _function("f'failed: {exc}'", "None"))[0] == 100

    @pytest.mark.parametrize("raising", ["raise", "raise RuntimeError(key) from exc"])
    def test_a_handler_that_raises_passes(self, tmp_path, raising):
        body = _function("None", "None").replace("logger.warning(exc)", f"if key:\n            {raising}")
        assert _verdict(tmp_path, body)[0] == 100

    def test_a_generator_is_not_judged(self, tmp_path):
        body = _function("None", "None").replace("    return value\n", "    yield value\n")
        assert _verdict(tmp_path, body)[0] == 100

    def test_assign_and_fall_through_is_not_read(self, tmp_path):
        body = (
            "def load_state():\n"
            "    data = {}\n"
            "    try:\n"
            "        data = read()\n"
            "    except OSError as exc:\n"
            "        logger.warning(exc)\n"
            "        data = {}\n"
            "    return data\n"
        )
        assert _verdict(tmp_path, body)[0] == 100

    def test_a_return_in_finally_is_not_the_success_path(self, tmp_path):
        body = (
            "def fetch(key):\n"
            "    try:\n"
            "        return load(key)\n"
            "    except OSError as exc:\n"
            "        logger.warning(exc)\n"
            "        return None\n"
            "    finally:\n"
            "        return None\n"
        )
        assert _verdict(tmp_path, body)[0] == 100

    def test_a_name_first_bound_to_a_parameter_is_not_a_literal(self, tmp_path):
        body = (
            "def fetch(key, fallback):\n"
            "    try:\n"
            "        return load(key)\n"
            "    except OSError as exc:\n"
            "        logger.warning(exc)\n"
            "        return None\n"
            "    fallback = None\n"
            "    return fallback\n"
        )
        assert _verdict(tmp_path, body)[0] == 100

    def test_a_nested_function_does_not_borrow_its_parents_returns(self, tmp_path):
        body = (
            "def outer(key):\n"
            "    def inner():\n"
            "        try:\n"
            "            return load(key)\n"
            "        except OSError as exc:\n"
            "            logger.warning(exc)\n"
            "            return None\n"
            "    if not key:\n"
            "        return None\n"
            "    return inner\n"
        )
        assert _verdict(tmp_path, body)[0] == 100

    def test_a_nested_function_is_judged_on_its_own_returns(self, tmp_path):
        body = "def outer(key):\n" + "".join(f"    {line}\n" for line in _function("None", "None").splitlines())
        assert _lines(_verdict(tmp_path, body)[1]) == ["client.py:7"]


class TestTheEdges:
    def test_every_hit_in_a_file_is_on_one_check(self, tmp_path):
        body = _function("None", "None") + "\n\n" + _function("[]", "[]").replace("def fetch", "def fetch_all")
        assert _lines(_verdict(tmp_path, body)[1]) == ["client.py:6", "client.py:17"]

    def test_a_missing_file_scores_0(self, tmp_path):
        result = checker.check_module(str(tmp_path / "apps" / "gone.py"))
        assert (result["score"], result["passed"]) == (0, False)

    def test_an_unparseable_file_is_not_judged(self, tmp_path):
        score, message = _verdict(tmp_path, "def f(:\n    return None\n")
        assert (score, message) == (100, "Not judged: the file does not parse (ruff convicts that)")

    def test_a_bypass_for_the_standard_passes_the_file(self, tmp_path):
        path = tmp_path / "apps" / "client.py"
        path.parent.mkdir()
        path.write_text(_function("None", "None"), encoding="utf-8")
        rules = [{"file": str(path), "standard": "logged_fallback"}]
        assert checker.check_module(str(path), bypass_rules=rules)["score"] == 100

    def test_a_bypass_for_one_line_clears_that_line_only(self, tmp_path):
        path = tmp_path / "apps" / "client.py"
        path.parent.mkdir()
        body = _function("None", "None") + "\n\n" + _function("[]", "[]").replace("def fetch", "def fetch_all")
        path.write_text(body, encoding="utf-8")
        rules = [{"file": str(path), "standard": "logged_fallback", "lines": [6]}]
        message = checker.check_module(str(path), bypass_rules=rules)["checks"][0]["message"]
        assert _lines(message) == ["client.py:17"]

    def test_the_standard_is_declared_production_only(self):
        assert (checker.APPLIES_TO, checker.AUDIT_SCOPE) == ("production", "all_files")
