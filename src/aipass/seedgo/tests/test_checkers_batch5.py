# =================== META ====================
# Name: test_checkers_batch5.py
# Description: Unit tests for ruff_check and clear_text_secret_logging checker handlers (batch 5)
# Version: 1.4.0
# Created: 2026-04-16
# Modified: 2026-10-10
# =============================================

"""Tests for apps/handlers/aipass_standards/ruff_check.py and clear_text_secret_logging_check.py."""

# ruff_check is the 33rd seedgo standard. Its per-file lane, check_module, has no
# test in this file.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — ruff's own lint and format verdicts; subprocess.run is sealed, its output built here
# seedgo: no-test-needed(stdlib) — shutil.which's PATH search; the tests only choose what PATH holds
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules for clear_text_secret_logging; tests/test_bypass.py

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import clear_text_secret_logging_check as secret_logging
from aipass.seedgo.apps.handlers.aipass_standards.ruff_check import check_branch

_RUN = "aipass.seedgo.apps.handlers.aipass_standards.ruff_check.subprocess.run"


# =============================================
# HELPERS
# =============================================


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_branch(tmp_path: Path) -> Path:
    apps = tmp_path / "apps"
    (apps / "modules").mkdir(parents=True)
    (apps / "handlers").mkdir(parents=True)
    return tmp_path


def _ruff_proc(violations: list, returncode: int = 1) -> MagicMock:
    """Build a fake subprocess.CompletedProcess with JSON output."""
    proc = MagicMock()
    proc.stdout = json.dumps(violations)
    proc.stderr = ""
    proc.returncode = returncode
    return proc


def _fmt_proc(unformatted_files: list[str] | None = None) -> MagicMock:
    """Build a fake subprocess.CompletedProcess for ruff format --check."""
    proc = MagicMock()
    if unformatted_files:
        proc.stdout = "\n".join(unformatted_files) + "\n"
        proc.returncode = 1
    else:
        proc.stdout = ""
        proc.returncode = 0
    proc.stderr = ""
    return proc


def _make_violation(filename: str, code: str = "F401", row: int = 1) -> dict:
    return {
        "filename": filename,
        "code": code,
        "location": {"row": row, "column": 1},
        "end_location": {"row": row, "column": 10},
        "message": f"Mock violation {code}",
    }


def _put_ruff_on_path(tmp_path: Path, monkeypatch) -> None:
    """PATH holds only a stand-in ruff; subprocess.run is sealed, so it never runs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Windows finds ruff.exe through PATHEXT and ignores the bit; POSIX needs the bit.
    for name in ("ruff", "ruff.exe"):
        stub = bin_dir / name
        stub.write_text("", encoding="utf-8")
        if sys.platform != "win32":
            os.chmod(stub, 0o755)
    monkeypatch.setenv("PATH", str(bin_dir))


def _branch_result(tmp_path: Path, monkeypatch, violations: list, ruff_bypass: list | None = None) -> dict:
    """check_branch on a fresh branch whose ruff reports these lint hits and no format hits."""
    branch = _make_branch(tmp_path)
    if ruff_bypass is not None:
        bypass_file = branch / ".seedgo" / "ruff_bypass.json"
        bypass_file.parent.mkdir(parents=True, exist_ok=True)
        bypass_file.write_text(json.dumps(ruff_bypass), encoding="utf-8")
    _put_ruff_on_path(tmp_path, monkeypatch)
    lint = _ruff_proc(violations, returncode=1 if violations else 0)
    with patch(_RUN, side_effect=[lint, _fmt_proc()]):
        return check_branch(str(branch))


def _hits(tmp_path: Path, count: int) -> list:
    return [_make_violation(str(tmp_path / "apps" / "modules" / "x.py"), "F401", i) for i in range(count)]


# =============================================
# 1. Score bands, through check_branch
# =============================================


class TestScoreFromCount:
    def test_zero_violations(self, tmp_path: Path, monkeypatch) -> None:
        """Zero violations maps to score 100. Mutant: the clean score returns 99 in apps/handlers/aipass_standards/ruff_check.py — killed."""
        assert _branch_result(tmp_path, monkeypatch, [])["score"] == 100

    def test_one_violation(self, tmp_path: Path, monkeypatch) -> None:
        """One violation falls in the 1–5 band, score 95. Mutant: the band starts at 2 in apps/handlers/aipass_standards/ruff_check.py — killed."""
        assert _branch_result(tmp_path, monkeypatch, _hits(tmp_path, 1))["score"] == 95

    def test_five_violations(self, tmp_path: Path, monkeypatch) -> None:
        """Five violations is the upper bound of the 1–5 band, score 95. Mutant: count < 5 in apps/handlers/aipass_standards/ruff_check.py — killed."""
        assert _branch_result(tmp_path, monkeypatch, _hits(tmp_path, 5))["score"] == 95

    def test_six_violations(self, tmp_path: Path, monkeypatch) -> None:
        """Six violations enters the 6–20 band, score 85. Mutant: the 95 band reaches 6 in apps/handlers/aipass_standards/ruff_check.py — killed."""
        assert _branch_result(tmp_path, monkeypatch, _hits(tmp_path, 6))["score"] == 85

    def test_fifty_one_violations(self, tmp_path: Path, monkeypatch) -> None:
        """51 violations enters the 51–100 band, score 50. Mutant: the 70 band reaches 51 in apps/handlers/aipass_standards/ruff_check.py — killed."""
        assert _branch_result(tmp_path, monkeypatch, _hits(tmp_path, 51))["score"] == 50

    def test_over_hundred(self, tmp_path: Path, monkeypatch) -> None:
        """101+ violations hits the floor band, score 25. Mutant: the 50 band reaches 101 in apps/handlers/aipass_standards/ruff_check.py — killed."""
        assert _branch_result(tmp_path, monkeypatch, _hits(tmp_path, 101))["score"] == 25


# =============================================
# 2. Ruff bypass (.seedgo/ruff_bypass.json)
# =============================================


class TestIsRuffBypassed:
    def test_no_bypass_rules(self, tmp_path: Path, monkeypatch) -> None:
        """Empty bypass list never matches any violation. Mutant: an empty list matches all in apps/handlers/aipass_standards/ruff_check.py — killed."""
        v = _make_violation(str(tmp_path / "apps" / "module.py"), "F401", 10)
        assert _branch_result(tmp_path, monkeypatch, [v], ruff_bypass=[])["score"] == 95

    def test_file_and_code_match(self, tmp_path: Path, monkeypatch) -> None:
        """Rule matching file and code bypasses the violation. Mutant: file must match whole in apps/handlers/aipass_standards/ruff_check.py — killed."""
        v = _make_violation(str(tmp_path / "apps" / "module.py"), "F401", 10)
        bypass = [{"file": "module.py", "code": "F401"}]
        assert _branch_result(tmp_path, monkeypatch, [v], ruff_bypass=bypass)["score"] == 100

    def test_code_mismatch(self, tmp_path: Path, monkeypatch) -> None:
        """Rule with different code does not bypass the violation. Mutant: the code is ignored in apps/handlers/aipass_standards/ruff_check.py — killed."""
        v = _make_violation(str(tmp_path / "apps" / "module.py"), "F401", 10)
        bypass = [{"file": "module.py", "code": "E501"}]
        assert _branch_result(tmp_path, monkeypatch, [v], ruff_bypass=bypass)["score"] == 95

    def test_line_match(self, tmp_path: Path, monkeypatch) -> None:
        """Rule with matching line number bypasses the violation. Mutant: a line rule never matches in apps/handlers/aipass_standards/ruff_check.py — killed."""
        v = _make_violation(str(tmp_path / "apps" / "module.py"), "F401", 42)
        bypass = [{"file": "module.py", "code": "F401", "line": 42}]
        assert _branch_result(tmp_path, monkeypatch, [v], ruff_bypass=bypass)["score"] == 100

    def test_line_mismatch(self, tmp_path: Path, monkeypatch) -> None:
        """Rule targeting a different line does not bypass the violation. Mutant: the line is ignored in apps/handlers/aipass_standards/ruff_check.py — killed."""
        v = _make_violation(str(tmp_path / "apps" / "module.py"), "F401", 10)
        bypass = [{"file": "module.py", "code": "F401", "line": 99}]
        assert _branch_result(tmp_path, monkeypatch, [v], ruff_bypass=bypass)["score"] == 95

    def test_file_only_matches_any_code(self, tmp_path: Path, monkeypatch) -> None:
        """File-only rule bypasses all codes in that file. Mutant: a missing code matches none in apps/handlers/aipass_standards/ruff_check.py — killed."""
        v = _make_violation(str(tmp_path / "apps" / "module.py"), "E501", 1)
        bypass = [{"file": "module.py"}]
        assert _branch_result(tmp_path, monkeypatch, [v], ruff_bypass=bypass)["score"] == 100


# =============================================
# 3. check_branch
# =============================================


@patch("aipass.seedgo.apps.handlers.aipass_standards.ruff_check.json_handler")
class TestCheckBranch:
    def test_clean_branch_scores_100(self, mock_json, tmp_path: Path, monkeypatch) -> None:
        """Branch with zero ruff violations scores 100."""
        branch = _make_branch(tmp_path)
        clean_proc = _ruff_proc([], returncode=0)
        fmt_clean = _fmt_proc()
        _put_ruff_on_path(tmp_path, monkeypatch)
        with patch(_RUN, side_effect=[clean_proc, fmt_clean]):
            result = check_branch(str(branch))
        assert result["score"] == 100
        assert result["passed"] is True
        assert result["standard"] == "RUFF_CHECK"
        assert "advisory" not in result

    def test_violations_caught_and_scored(self, mock_json, tmp_path: Path, monkeypatch) -> None:
        """Branch with violations reports count and drops score."""
        branch = _make_branch(tmp_path)
        violations = [_make_violation(str(branch / "apps" / "modules" / "x.py"), "F401", i) for i in range(10)]
        proc = _ruff_proc(violations, returncode=1)
        fmt_clean = _fmt_proc()
        _put_ruff_on_path(tmp_path, monkeypatch)
        with patch(_RUN, side_effect=[proc, fmt_clean]):
            result = check_branch(str(branch))
        assert result["score"] == 85  # 10 violations → 6–20 band
        assert result["passed"] is False  # the row gates since 2026-09-25
        assert "10 violation" in result["checks"][0]["message"]

    def test_an_unformatted_file_alone_fails_the_row(self, mock_json, tmp_path: Path, monkeypatch) -> None:
        """The row covers format too: one unformatted file, zero lint hits, still gates."""
        branch = _make_branch(tmp_path)
        fmt_dirty = _fmt_proc([f"Would reformat: {branch / 'apps' / 'x.py'}"])
        _put_ruff_on_path(tmp_path, monkeypatch)
        with patch(_RUN, side_effect=[_ruff_proc([], returncode=0), fmt_dirty]):
            result = check_branch(str(branch))
        assert result["score"] == 98
        assert result["passed"] is False
        assert "1 file(s) need formatting — x.py" in result["checks"][1]["message"]

    def test_standard_bypass_respected(self, mock_json, tmp_path: Path) -> None:
        """Standard-level bypass via bypass_rules returns score 100."""
        branch = _make_branch(tmp_path)
        bypass = [{"standard": "ruff_check"}]
        result = check_branch(str(branch), bypass_rules=bypass)
        assert result["score"] == 100
        assert result["passed"] is True

    def test_ruff_not_installed_skips(self, mock_json, tmp_path: Path, monkeypatch) -> None:
        """Missing ruff binary returns score 100 with skipped status."""
        branch = _make_branch(tmp_path)
        (tmp_path / "empty").mkdir()
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        result = check_branch(str(branch))
        assert result["score"] == 100
        assert result["passed"] is True
        assert result.get("status") == "skipped"
        assert "not installed" in result["checks"][0]["message"]

    def test_ruff_bypass_json_filters_violations(self, mock_json, tmp_path: Path, monkeypatch) -> None:
        """Violations listed in .seedgo/ruff_bypass.json are filtered out."""
        branch = _make_branch(tmp_path)
        v_path = str(branch / "apps" / "modules" / "thing.py")
        violations = [
            _make_violation(v_path, "F401", 1),
            _make_violation(v_path, "E501", 10),
        ]
        proc = _ruff_proc(violations, returncode=1)
        fmt_clean = _fmt_proc()
        # Bypass the F401
        bypass_file = branch / ".seedgo" / "ruff_bypass.json"
        bypass_file.parent.mkdir(parents=True, exist_ok=True)
        bypass_file.write_text(json.dumps([{"file": "thing.py", "code": "F401"}]), encoding="utf-8")
        _put_ruff_on_path(tmp_path, monkeypatch)
        with patch(_RUN, side_effect=[proc, fmt_clean]):
            result = check_branch(str(branch))
        # Only 1 active violation (E501), score should be 95
        assert result["score"] == 95
        assert "1 violation" in result["checks"][0]["message"]

    def test_timeout_returns_score_zero(self, mock_json, tmp_path: Path, monkeypatch) -> None:
        """Subprocess timeout returns score 0 and passed False."""
        import subprocess as sp

        branch = _make_branch(tmp_path)
        _put_ruff_on_path(tmp_path, monkeypatch)
        with patch(_RUN, side_effect=sp.TimeoutExpired(cmd="ruff", timeout=60)):
            result = check_branch(str(branch))
        assert result["score"] == 0
        assert result["passed"] is False
        assert "timed out" in result["checks"][0]["message"]


# =============================================
# 4. clear_text_secret_logging (dispatch 82800a7a, CodeQL on PR #774)
# =============================================

#: @api apps/handlers/host/tokens.py as on disk 2026-10-10, cut to the three
#: warning calls CodeQL py/clear-text-logging-sensitive-data traced into prax's
#: SystemLogger.warning (logger.py:135). Both sources read secrets_store.SECRETS_BASE
#: (store_path :182, lock_path :267); on disk the calls are :324, :438 and :370.
TOKENS_SPECIMEN = """from aipass.prax import logger
from aipass.api.apps.handlers.auth import secrets as secrets_store


def store_path():
    return secrets_store.SECRETS_BASE / "host_api" / "tokens.json"


def lock_path():
    return secrets_store.SECRETS_BASE / "host_api" / "tokens.lock"


def save_tokens(content):
    target = store_path()
    temporary = target.parent / ".tokens.tmp"
    try:
        temporary.write_bytes(content)
    except OSError as cleanup_error:
        logger.warning("could not remove the temp store at %s: %s", temporary, cleanup_error)


def _drop_lock(path):
    try:
        path.unlink()
    except OSError as e:
        logger.warning("could not remove the token store lock at %s: %s", path, e)


def take_lock():
    path = lock_path()
    if path.exists():
        logger.warning("breaking a stale token store lock at %s", path)
        _drop_lock(path)
"""

#: The temp-store call (:324 on disk), the _drop_lock call (:438) and the stale-lock call (:370).
TOKENS_ROWS = [19, 26, 32]

#: @api apps/handlers/auth/secrets.py as on disk 2026-10-10, cut to the module-level
#: SECRETS_BASE binding (:29) and the three warnings it reaches (:62, :187, :216 on disk).
AUTH_SECRETS_SPECIMEN = """from pathlib import Path
from aipass.prax import logger

SECRETS_BASE = Path.home() / ".secrets" / "aipass"


def get_secret(provider, slug):
    provider_dir = SECRETS_BASE / provider
    if not provider_dir.exists():
        logger.warning(f"Provider directory not found: {provider_dir}")
        return None
    json_path = provider_dir / f"{slug}.json"
    raw_path = provider_dir / slug
    return _read_json(json_path) or _read_raw(raw_path)


def _read_json(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning(f"Error reading secret file {path}: {e}")


def _read_raw(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning(f"Error reading secret file {path}: {e}")
"""

#: @drone apps/drone.py as on disk 2026-10-10, cut: _resolve_mail_token hands back its
#: parameter `token`, and the result is logged as `command` (:621 on disk).
RESOLVED_TOKEN_SPECIMEN = """from aipass.prax import logger


def _resolve_mail_token(token):
    return token


def route(cmd_args, exc):
    command = _resolve_mail_token(cmd_args[0])
    logger.warning("Command routing failed for %s: %s", command, exc)
"""

#: @hooks apps/handlers/security/git_gate.py:373 as on disk 2026-10-10, cut to the call.
GIT_GATE_SPECIMEN = """from aipass.prax import logger


def refuse(credentials):
    if credentials:
        logger.warning("[HOOKS] git_gate: credential read refused: %s", credentials[0])
"""


def _secret_rows(source: str) -> list:
    """The convicted line numbers of one source text."""
    return [line for line, _what in secret_logging.scan(source)]


class TestASecretDerivedPathOnALogLineIsConvicted:
    def test_the_three_codeql_flows_in_api_tokens_are_convicted(self) -> None:
        assert _secret_rows(TOKENS_SPECIMEN) == TOKENS_ROWS

    def test_the_row_names_the_source_the_value_came_from(self) -> None:
        whats = [what for _line, what in secret_logging.scan(TOKENS_SPECIMEN)]
        assert whats == [
            "temporary (built from secrets_store.SECRETS_BASE)",
            "path (built from secrets_store.SECRETS_BASE)",
            "path (built from secrets_store.SECRETS_BASE)",
        ]

    def test_the_cured_store_root_name_acquits_every_flow(self) -> None:
        assert _secret_rows(TOKENS_SPECIMEN.replace("SECRETS_BASE", "STORE_ROOT")) == []

    def test_a_module_level_secrets_base_reaches_all_three_api_auth_warnings(self) -> None:
        assert _secret_rows(AUTH_SECRETS_SPECIMEN) == [10, 21, 28]


class TestArmTwoStartsOnlyFromAModuleBindingOrAnAttribute:
    def test_a_returned_token_parameter_logged_under_a_neutral_name_is_acquitted(self) -> None:
        assert _secret_rows(RESOLVED_TOKEN_SPECIMEN) == []

    def test_a_loop_token_built_into_a_neutral_name_is_acquitted(self) -> None:
        source = (
            "from pathlib import Path\nfrom aipass.prax import logger\n\n\n"
            "def tracked(tokens):\n    for token in tokens:\n        path = Path(token)\n"
            "        logger.info('outside: %s', path)\n"
        )
        assert _secret_rows(source) == []

    def test_the_parameter_itself_on_the_log_line_is_still_arm_one(self) -> None:
        source = RESOLVED_TOKEN_SPECIMEN + "\n\ndef refuse(token):\n    logger.warning('refused %s', token)\n"
        assert _secret_rows(source) == [14]


class TestASecretNamedValueOnALogLineIsConvicted:
    def test_an_element_of_a_credentials_list_is_convicted(self) -> None:
        assert _secret_rows(GIT_GATE_SPECIMEN) == [6]

    @pytest.mark.parametrize(
        "call",
        [
            'logger.info(f"sending {api_key}")',
            'logger.error("bad %s" % self.password)',
            'logger.debug("using {}".format(get_bearer()))',
            'logger.critical("value: " + str(client_secret))',
            "logger.exception(token.strip())",
        ],
    )
    def test_every_spelling_of_the_message_is_read(self, call: str) -> None:
        assert _secret_rows(f"from aipass.prax import logger\n{call}\n") == [2]

    def test_an_aliased_prax_logger_is_read(self) -> None:
        assert _secret_rows("from aipass.prax import logger as log\nlog.warning('%s', token)\n") == [2]


class TestAnIdentifierOrARedactionIsAcquitted:
    @pytest.mark.parametrize(
        "argument",
        ["token_id", "n_tokens", "secret_path", "len(token)", "token[-4:]", "mask(password)", "redact_secret(api_key)"],
    )
    def test_the_dispatch_exemptions_are_acquitted(self, argument: str) -> None:
        assert _secret_rows(f"from aipass.prax import logger\nlogger.warning('%s', {argument})\n") == []

    def test_a_first_ten_characters_slice_still_shows_the_secret(self) -> None:
        assert _secret_rows("from aipass.prax import logger\nlogger.warning('%s', token[:10])\n") == [2]

    def test_a_print_or_a_constant_word_is_not_a_log_of_a_value(self) -> None:
        source = "from aipass.prax import logger\nprint(token)\nlogger.warning('token refused')\n"
        assert _secret_rows(source) == []


class TestTheSecretLoggingVerdict:
    def test_a_convicted_file_scores_0_and_names_every_line(self, tmp_path: Path) -> None:
        path = tmp_path / "apps" / "tokens.py"
        _write_file(path, TOKENS_SPECIMEN)
        result = secret_logging.check_module(str(path))
        lines = result["checks"][0]["message"].splitlines()
        assert (result["score"], result["passed"]) == (0, False)
        assert [line.split(" ")[0] for line in lines] == ["tokens.py:19", "tokens.py:26", "tokens.py:32"]

    def test_a_bypass_for_one_line_clears_that_line_only(self, tmp_path: Path) -> None:
        path = tmp_path / "apps" / "tokens.py"
        _write_file(path, TOKENS_SPECIMEN)
        rules = [{"file": str(path), "standard": "clear_text_secret_logging", "lines": [19, 26]}]
        message = secret_logging.check_module(str(path), bypass_rules=rules)["checks"][0]["message"]
        assert message.splitlines()[0].startswith("tokens.py:32 ") and len(message.splitlines()) == 1

    def test_a_clean_file_scores_100(self, tmp_path: Path) -> None:
        path = tmp_path / "apps" / "clean.py"
        _write_file(path, "from aipass.prax import logger\nlogger.info('%s', token_id)\n")
        assert secret_logging.check_module(str(path))["score"] == 100

    def test_the_standard_is_declared_production_only(self) -> None:
        assert (secret_logging.APPLIES_TO, secret_logging.AUDIT_SCOPE) == ("production", "all_files")


# =============================================
# 5. clear_text_secret_logging arm 2 widened (dispatch 39bfe173, CodeQL round nine)
# =============================================

#: @skills lib/telegram/apps/handlers/config.py BEFORE its cure (2026-10-10), cut:
#: load_bot_config's secret = _get_secret(bot_id) (:365) handed to non_secret_keys
#: (:147), whose sorted generator over the document comes back as strays, logged at :376.
TELEGRAM_CONFIG_SPECIMEN = """from aipass.prax import logger
from aipass.api.apps.modules.secrets import get_secret as _api_get_secret

SECRET_FIELDS = ("bot_token", "api_id", "api_hash")


def _get_secret(bot_id):
    return _api_get_secret("telegram", bot_id, as_json=True)


def non_secret_keys(document):
    if not isinstance(document, dict):
        return []
    return sorted(key for key in document if key not in SECRET_FIELDS)


def load_bot_config(bot_id):
    secret = _get_secret(bot_id)
    strays = non_secret_keys(secret)
    if strays:
        logger.warning(
            "Legacy secret document telegram/%s carries %d non-secret key(s) %s",
            bot_id,
            len(strays),
            strays,
        )
    return dict(secret)
"""

#: The cure @skills shipped: the count stays on the line, the key names leave it.
TELEGRAM_CONFIG_CURED = TELEGRAM_CONFIG_SPECIMEN.replace(" non-secret key(s) %s", " non-secret key(s)").replace(
    "            len(strays),\n            strays,\n", "            len(strays),\n"
)

#: A secret document laundered through a neutrally named same-file helper.
LAUNDERED_SPECIMEN = """from aipass.prax import logger
from aipass.api.apps.modules.secrets import get_secret


def describe(document):
    names = [key for key in document]
    return ", ".join(sorted(names))


def report(provider):
    doc = get_secret(provider, "bot")
    summary = describe(doc)
    logger.info("document keys: %s", summary)
    logger.info("provider keys: %s", describe(provider))
"""


def _one_call_rows(call: str) -> list:
    """The rows of a file that assigns one call's result to a neutral name and logs it."""
    return _secret_rows(f"from aipass.prax import logger\n\nvalue = {call}\nlogger.info('%s', value)\n")


class TestASecretNamedCallsResultSeedsArmTwo:
    def test_the_telegram_config_strays_line_is_convicted(self, tmp_path: Path) -> None:
        path = tmp_path / "apps" / "config.py"
        _write_file(path, TELEGRAM_CONFIG_SPECIMEN)
        message = secret_logging.check_module(str(path))["checks"][0]["message"]
        assert message.startswith("config.py:21 logs strays (built from ") and len(message.splitlines()) == 1

    def test_the_cured_count_only_line_is_acquitted(self) -> None:
        assert _secret_rows(TELEGRAM_CONFIG_CURED) == []

    @pytest.mark.parametrize(
        "call",
        ["get_secret(a, b)", "secrets_store.get_secret(a, b)", "load_trusted_keys()", "read_confidential()"],
    )
    def test_a_secret_named_call_assigned_to_a_neutral_name_is_convicted(self, call: str) -> None:
        assert _one_call_rows(call) == [4]

    @pytest.mark.parametrize(
        "call",
        [
            "secrets.token_hex(16)",
            "issue_token(seat)",
            "secret_path(slug)",
            "hash_secret(raw)",
            "get_user_secret(seat)",
            "load_untrusted()",
            "set_secret(a, b, c)",
            "delete_secret(a, b)",
        ],
    )
    def test_a_token_word_identifier_excluded_or_setter_call_seeds_nothing(self, call: str) -> None:
        assert _one_call_rows(call) == []


class TestASameFileHelperCarriesItsArgumentsTaint:
    def test_a_secret_laundered_through_a_same_file_helper_is_convicted(self) -> None:
        assert secret_logging.scan(LAUNDERED_SPECIMEN) == [(13, "summary (built from get_secret(provider, 'bot'))")]

    def test_a_clean_argument_through_the_same_helper_is_acquitted(self) -> None:
        assert 14 not in _secret_rows(LAUNDERED_SPECIMEN)

    def test_a_helper_that_drops_its_argument_returns_clean(self) -> None:
        source = LAUNDERED_SPECIMEN.replace('return ", ".join(sorted(names))', "return str(len(names))")
        assert _secret_rows(source) == []

    def test_a_non_prefix_never_acquits_the_value_through_it(self) -> None:
        source = LAUNDERED_SPECIMEN.replace("describe", "non_secret_keys")
        assert 13 in _secret_rows(source)

    def test_a_local_built_in_one_function_is_not_another_functions_name(self) -> None:
        source = (
            "from aipass.prax import logger\n\n\ndef fetch(slug):\n    value = get_secret(slug)\n    return None\n\n\n"
            "def show(value):\n    logger.info('%s', value)\n"
        )
        assert _secret_rows(source) == []


#: @prax apps/modules/monitor.py as on disk 2026-10-10, cut: argparse's positional
#: `tokens` (branch names) through _standalone_run_args' list() reaches a log line as `args`.
PARSER_TOKENS_SPECIMEN = """from aipass.prax import logger


def _standalone_run_args(tokens):
    tokens = list(tokens)
    return ["run", *tokens]


def _run_monitor(args):
    logger.info(f"Starting unified monitoring (args: {args})")


def main(args):
    _run_monitor(_standalone_run_args(args.tokens))
"""


class TestATokenNamedBindingOrAttributeSeedsNothing:
    def test_argparse_tokens_carried_into_a_neutral_name_are_acquitted(self) -> None:
        assert _secret_rows(PARSER_TOKENS_SPECIMEN) == []

    def test_a_secrets_named_attribute_through_the_same_path_is_convicted(self) -> None:
        assert _secret_rows(PARSER_TOKENS_SPECIMEN.replace("args.tokens", "args.secrets")) == [10]
