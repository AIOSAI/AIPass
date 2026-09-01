# ===================AIPASS====================
# META DATA HEADER
# Name: bot_factory.py - Bot creation and deletion factory
# Date: 2026-06-15
# Version: 1.0.0
# Category: skills/lib/telegram/apps/handlers
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-06-15): Ported from Dev-Pass — rewired registry, logger, config, base_bot path
#
# CODE STANDARDS:
#   - Pure functions with proper error handling (graceful - never raise)
#   - Uses aipass.prax logger
#   - Stdlib only (urllib for HTTP, subprocess for systemd)
# =============================================

"""
Bot Creation and Deletion Factory

Manages the full lifecycle of Telegram bots in the multi-bot architecture:
- Validate bot tokens via Telegram getMe API
- Validate branch names against AIPASS_REGISTRY.json
- Write per-bot config files via config module secret store
- Register/deregister bots in the central bot registry
- Set BotFather commands via setMyCommands API
- Enable/disable/stop systemd user services
- Auto-start bot processes via Popen fire-and-forget

All HTTP calls use urllib (stdlib). No external dependencies.
"""

# Standard library
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Logging
from aipass.prax import logger
from aipass.skills.apps.handlers.module_paths import module_file

# JSON handler (seedgo standard)
from aipass.skills.apps.handlers.json import json_handler  # noqa: F401

# Internal imports
from aipass.api.apps.modules.secrets import set_secret as _api_set_secret

from .telegram_standards import build_botfather_commands

from .bot_registry import (
    deregister_bot,
    ensure_registry,
    get_bot,
    get_bot_by_branch,
    register_bot,
)

# =============================================
# CONSTANTS
# =============================================

TELEGRAM_API = "https://api.telegram.org/bot{token}"
SYSTEMD_DIR = Path.home() / ".config" / "systemd" / "user"
_BOT_CONFIG_DIR = Path.home() / ".aipass" / "telegram_bots"
CLAUDE_BIN = str(Path.home() / ".local" / "bin" / "claude")

# Command menu built from telegram_standards (single source of truth)

# =============================================
# TELEGRAM API HELPERS
# =============================================


def validate_token(bot_token: str) -> Optional[dict]:
    """
    Validate a bot token via the Telegram getMe API call.

    Args:
        bot_token: Telegram bot token string (e.g., "123456:ABC-DEF...").

    Returns:
        Bot info dict with keys like "id", "username", "first_name" on success.
        None if the token is invalid or the API is unreachable.
    """
    url = f"{TELEGRAM_API.format(token=bot_token)}/getMe"

    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        if result.get("ok") and result.get("result"):
            bot_info = result["result"]
            logger.info("Token validated: @%s (id=%s)", bot_info.get("username"), bot_info.get("id"))
            return bot_info

        logger.warning("Token validation failed: API returned ok=false")
        return None

    except HTTPError as e:
        logger.warning("Token validation HTTP error %d: %s", e.code, e.reason)
        return None
    except URLError as e:
        logger.warning("Token validation network error: %s", e)
        return None
    except Exception as e:
        logger.warning("Token validation unexpected error: %s", e)
        return None


def _find_registry() -> Optional[Path]:
    """Walk up from CWD to find AIPASS_REGISTRY.json."""
    current = Path.cwd().resolve()
    for parent in [current, *current.parents]:
        candidate = parent / "AIPASS_REGISTRY.json"
        if candidate.exists():
            return candidate
    return None


def validate_branch(branch_name: str) -> Optional[dict]:
    """
    Check that a branch exists in AIPASS_REGISTRY.json.

    Args:
        branch_name: Branch name to validate (case-insensitive, matches name or email).

    Returns:
        Branch info dict from the registry on success, None if invalid.
    """
    if not branch_name or not branch_name.strip():
        logger.warning("validate_branch: empty or blank branch name")
        return None

    registry_path = _find_registry()
    if not registry_path:
        logger.warning("Branch registry not found (walked up from CWD)")
        return None

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)

        branches = registry.get("branches", [])
        target = branch_name.lower().replace("@", "")

        for branch_entry in branches:
            clean_email = branch_entry.get("email", "").replace("@", "").lower()
            if clean_email == target or branch_entry.get("name", "").lower() == target:
                logger.info("Branch validated: %s -> %s", branch_name, branch_entry.get("path"))
                return branch_entry

        logger.warning("Branch '%s' not found in registry", branch_name)
        return None

    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read branch registry: %s", e)
        return None


def set_bot_commands(bot_token: str, commands: list[dict]) -> bool:
    """
    Set BotFather commands via the Telegram setMyCommands API.

    Args:
        bot_token: Telegram bot token.
        commands: List of command dicts, each with "command" and "description" keys.

    Returns:
        True if commands were set successfully, False otherwise.
    """
    url = f"{TELEGRAM_API.format(token=bot_token)}/setMyCommands"

    payload = {"commands": commands}
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"})

    try:
        with urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("ok"):
                logger.info("Bot commands set successfully (%d commands)", len(commands))
                return True
            logger.warning("setMyCommands failed: %s", result.get("description"))
            return False

    except (HTTPError, URLError) as e:
        logger.warning("Failed to set bot commands: %s", e)
        return False
    except Exception as e:
        logger.warning("Unexpected error setting bot commands: %s", e)
        return False


# =============================================
# SYSTEMD SERVICE MANAGEMENT
# =============================================


def _install_service_unit() -> bool:
    """Copy telegram-bot@.service into ~/.config/systemd/user/ and reload."""
    UNIT_SRC = module_file(__file__).parents[2] / "telegram-bot@.service"
    UNIT_DST_DIR = Path.home() / ".config" / "systemd" / "user"
    UNIT_DST = UNIT_DST_DIR / "telegram-bot@.service"

    try:
        UNIT_DST_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(UNIT_SRC, UNIT_DST)
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        logger.info("Installed service unit: %s", UNIT_DST)
        return True
    except OSError as e:
        logger.warning("Failed to install service unit: %s", e)
        return False


def enable_service(bot_id: str) -> bool:
    """
    Enable the systemd user service for a bot (does not start it).

    Installs the unit file if missing, then runs:
    systemctl --user enable telegram-bot@{bot_id}

    Args:
        bot_id: Bot identifier used in the service template.

    Returns:
        True if the service was enabled successfully, False otherwise.
    """
    _install_service_unit()
    SERVICE_NAME = f"telegram-bot@{bot_id}"
    try:
        result = subprocess.run(
            ["systemctl", "--user", "enable", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            logger.info("Enabled systemd service: %s", SERVICE_NAME)
            return True

        logger.warning("Failed to enable service %s: %s", SERVICE_NAME, result.stderr.strip())
        return False

    except subprocess.TimeoutExpired:
        logger.warning("Timeout enabling service: %s", SERVICE_NAME)
        return False
    except OSError as e:
        logger.warning("Error enabling service %s: %s", SERVICE_NAME, e)
        return False


def disable_service(bot_id: str) -> bool:
    """
    Disable the systemd user service for a bot.

    Runs: systemctl --user disable telegram-bot@{bot_id}

    Args:
        bot_id: Bot identifier used in the service template.

    Returns:
        True if the service was disabled successfully, False otherwise.
    """
    SERVICE_NAME = f"telegram-bot@{bot_id}"
    try:
        result = subprocess.run(
            ["systemctl", "--user", "disable", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            logger.info("Disabled systemd service: %s", SERVICE_NAME)
            return True

        logger.warning("Failed to disable service %s: %s", SERVICE_NAME, result.stderr.strip())
        return False

    except subprocess.TimeoutExpired:
        logger.warning("Timeout disabling service: %s", SERVICE_NAME)
        return False
    except OSError as e:
        logger.warning("Error disabling service %s: %s", SERVICE_NAME, e)
        return False


def start_bot_process(bot_id: str) -> bool:
    """
    Launch the bot process via subprocess.Popen (fire-and-forget).

    Starts base_bot.py --bot-id {bot_id} as a detached process.
    This is called after create_bot() to auto-start the new bot.

    Args:
        bot_id: Bot identifier to start.

    Returns:
        True if the process was launched successfully, False otherwise.
    """
    MODULE_PATH = "aipass.skills.lib.telegram.apps.handlers.base_bot"

    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", MODULE_PATH, "--bot-id", bot_id],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("Started bot process: bot_id=%s, pid=%d", bot_id, proc.pid)
        return True

    except OSError as e:
        logger.warning("Failed to start bot process for '%s': %s", bot_id, e)
        return False


def launch_mirror_session(
    bot_id: str,
    work_dir: str,
    session_name: str,
) -> bool:
    """Launch the canonical tmux mirror session with --dangerously-skip-permissions.

    Creates a detached tmux session running Claude Code in autonomous mirror mode.
    The session uses --dangerously-skip-permissions because a detached tmux session
    has no operator to approve permission prompts — without it, the session hangs.

    Args:
        bot_id: Bot identifier (set as AIPASS_BOT_ID env var in the session).
        work_dir: Working directory for the Claude session.
        session_name: tmux session name (e.g. "telegram-api").

    Returns:
        True if the session was launched successfully.
    """
    import os

    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True,
        )
        if result.returncode == 0:
            logger.info("Mirror session '%s' already running — skipping launch", session_name)
            return True
    except FileNotFoundError:
        logger.error("tmux not found — cannot launch mirror session")
        return False

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)

    try:
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session_name, "-c", work_dir],
            check=True,
            capture_output=True,
            env=env,
        )
    except subprocess.CalledProcessError as e:
        logger.error("Failed to create tmux session '%s': %s", session_name, e)
        return False

    subprocess.run(
        [
            "tmux",
            "send-keys",
            "-t",
            session_name,
            f"export AIPASS_BOT_ID={bot_id}",
            "Enter",
        ],
        capture_output=True,
    )

    import time

    time.sleep(0.3)

    claude_cmd = f"AIPASS_SESSION_TYPE=interactive-mirror {CLAUDE_BIN} --dangerously-skip-permissions"
    subprocess.run(
        ["tmux", "send-keys", "-t", session_name, claude_cmd, "Enter"],
        capture_output=True,
    )

    logger.info(
        "Mirror session '%s' launched (bot_id=%s, work_dir=%s, skip-perms=true)",
        session_name,
        bot_id,
        work_dir,
    )
    return True


def stop_service(bot_id: str) -> bool:
    """
    Stop the systemd user service for a bot.

    Runs: systemctl --user stop telegram-bot@{bot_id}

    Args:
        bot_id: Bot identifier used in the service template.

    Returns:
        True if the service was stopped successfully, False otherwise.
    """
    SERVICE_NAME = f"telegram-bot@{bot_id}"
    try:
        result = subprocess.run(
            ["systemctl", "--user", "stop", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            logger.info("Stopped systemd service: %s", SERVICE_NAME)
            return True

        logger.warning("Failed to stop service %s: %s", SERVICE_NAME, result.stderr.strip())
        return False

    except subprocess.TimeoutExpired:
        logger.warning("Timeout stopping service: %s", SERVICE_NAME)
        return False
    except OSError as e:
        logger.warning("Error stopping service %s: %s", SERVICE_NAME, e)
        return False


def start_service(bot_id: str) -> bool:
    """
    Start the systemd user service for a bot.

    Runs: systemctl --user start telegram-bot@{bot_id}

    Args:
        bot_id: Bot identifier used in the service template.

    Returns:
        True if the service was started successfully, False otherwise.
    """
    SERVICE_NAME = f"telegram-bot@{bot_id}"
    try:
        result = subprocess.run(
            ["systemctl", "--user", "start", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            logger.info("Started systemd service: %s", SERVICE_NAME)
            return True

        logger.warning("Failed to start service %s: %s", SERVICE_NAME, result.stderr.strip())
        return False

    except subprocess.TimeoutExpired:
        logger.warning("Timeout starting service: %s", SERVICE_NAME)
        return False
    except OSError as e:
        logger.warning("Error starting service %s: %s", SERVICE_NAME, e)
        return False


# =============================================
# BOT LIFECYCLE
# =============================================


def create_bot(
    bot_id: str,
    bot_token: str,
    branch_name: Optional[str] = None,
    work_dir: Optional[str] = None,
    bot_name: Optional[str] = None,
    allowed_user_ids: Optional[list[int]] = None,
    shared_session: Optional[str] = None,
    attach_only: bool = False,
    chat_id: Optional[int] = None,
) -> Optional[dict]:
    """
    Create a new bot: validate, write config, register, setup systemd.

    Steps:
    1. Validate token via getMe
    2. If branch_name provided: validate branch name is non-empty
    3. Check bot_id not already registered
    4. Persist per-bot config via the in-process @api secrets API
    5. Register in bot registry
    6. Set BotFather commands via setMyCommands API
    7. Enable systemd service
    7.5. Mirror mode: launch canonical tmux session with skip-perms
    8. Auto-start the bot (systemd for mirror, Popen for standard)

    Args:
        bot_id: Unique identifier for this bot (e.g., "dev_central", "base").
        bot_token: Telegram bot token from BotFather.
        branch_name: AIPass branch name to associate, or None for base bot.
        work_dir: Working directory for Claude sessions. Defaults to home dir if None.
        bot_name: Human-readable bot name. Auto-generated if None.
        allowed_user_ids: List of Telegram user IDs allowed to use this bot.
        shared_session: tmux session name for mirror mode (attach to existing session).
        attach_only: When True, bot only attaches — never spawns its own session.
        chat_id: Pre-configured Telegram chat ID for mirror mapping.

    Returns:
        Bot info dict on success, None on any failure.
    """
    # Step 1: Validate token
    bot_info = validate_token(bot_token)
    if not bot_info:
        logger.warning("create_bot failed: invalid token for bot_id '%s'", bot_id)
        return None

    BOT_USERNAME = bot_info.get("username", "unknown")

    # Step 2: Validate branch if provided
    RESOLVED_WORK_DIR = str(Path.home()) if work_dir is None else str(work_dir)
    if branch_name:
        branch_info = validate_branch(branch_name)
        if not branch_info:
            logger.warning("create_bot failed: branch '%s' not valid", branch_name)
            return None
        # Use registry path as source of truth when branch_name is provided
        REGISTRY_PATH = branch_info.get("path", "")
        if REGISTRY_PATH:
            if work_dir and str(work_dir) != REGISTRY_PATH:
                logger.warning(
                    "create_bot: explicit work_dir '%s' differs from registry path '%s' — using registry",
                    work_dir,
                    REGISTRY_PATH,
                )
            RESOLVED_WORK_DIR = REGISTRY_PATH

    # Step 3: Check not already registered
    existing = get_bot(bot_id)
    if existing:
        logger.warning("create_bot failed: bot_id '%s' already registered", bot_id)
        return None

    # Also check no other bot owns this branch
    if branch_name:
        branch_bot = get_bot_by_branch(branch_name)
        if branch_bot:
            logger.warning(
                "create_bot failed: branch '%s' already has bot '%s'",
                branch_name,
                branch_bot.get("bot_id"),
            )
            return None

    # Step 4: Build config and persist to @api secrets store + local shadow.
    ensure_registry()
    _BOT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    RESOLVED_BOT_NAME = bot_name or f"AIPass {bot_id.replace('_', ' ').title()} Bot"
    CONFIG_PATH = _BOT_CONFIG_DIR / f"{bot_id}.json"

    config_data = {
        "bot_id": bot_id,
        "bot_token": bot_token,
        "bot_name": RESOLVED_BOT_NAME,
        "branch_name": branch_name,
        "work_dir": RESOLVED_WORK_DIR,
        "allowed_user_ids": allowed_user_ids or [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "shared_session": shared_session,
        "attach_only": attach_only,
        "chat_id": chat_id,
    }

    # Step 4a: Write to @api secrets store (load_bot_config reads from here)
    try:
        _api_set_secret("telegram", bot_id, config_data, as_json=True)
        logger.info("Persisted bot config to @api secrets: telegram/%s", bot_id)
    except OSError as e:
        logger.error("create_bot failed: could not persist config to @api for '%s': %s", bot_id, e)
        return None

    # Step 4b: Write local shadow file (staging artifact, not runtime source)
    try:
        CONFIG_PATH.write_text(
            json.dumps(config_data, indent=2),
            encoding="utf-8",
        )
        logger.info("Wrote bot config shadow: %s", CONFIG_PATH)
    except OSError as e:
        logger.warning("Failed to write shadow config (non-fatal): %s", e)

    # Step 5: Register in bot registry
    registered = register_bot(
        bot_id=bot_id,
        username=BOT_USERNAME,
        branch_name=branch_name,
        work_dir=RESOLVED_WORK_DIR,
        config_path=str(CONFIG_PATH),
        bot_token_ref=f"@api:telegram/{bot_id}",
    )
    if not registered:
        CONFIG_PATH.unlink(missing_ok=True)
        logger.warning("create_bot failed: registry registration failed for '%s'", bot_id)
        return None

    # Step 6: Set BotFather commands
    set_bot_commands(bot_token, build_botfather_commands())

    # Step 7: Enable systemd service
    enable_service(bot_id)

    # Step 7.5: Mirror mode — launch canonical tmux session
    mirror_launched = False
    if shared_session and attach_only:
        mirror_launched = launch_mirror_session(session_name=shared_session, bot_id=bot_id, work_dir=RESOLVED_WORK_DIR)
        if not mirror_launched:
            logger.warning(
                "Mirror session launch failed for '%s' — bot may need manual session start",
                bot_id,
            )

    # Step 8: Auto-start the bot poller
    if shared_session and attach_only:
        started = start_service(bot_id)
    else:
        started = start_bot_process(bot_id)

    logger.info(
        "Bot created: %s (@%s, branch=%s, work_dir=%s, started=%s, mirror=%s)",
        bot_id,
        BOT_USERNAME,
        branch_name,
        RESOLVED_WORK_DIR,
        started,
        mirror_launched,
    )

    return {
        "bot_id": bot_id,
        "username": BOT_USERNAME,
        "bot_name": RESOLVED_BOT_NAME,
        "branch_name": branch_name,
        "work_dir": RESOLVED_WORK_DIR,
        "config_path": str(CONFIG_PATH),
        "service_name": f"telegram-bot@{bot_id}",
        "auto_started": started,
        "shared_session": shared_session,
        "attach_only": attach_only,
        "mirror_launched": mirror_launched,
    }


def delete_bot(bot_id: str, kill_tmux: bool = True) -> bool:
    """
    Delete a bot: stop service, kill tmux, remove config, deregister.

    Steps:
    1. Stop and disable systemd service
    2. Kill tmux session if exists and kill_tmux is True
    3. Remove config file
    4. Clean up pending files (both v1 and v2 naming)
    5. Deregister from registry

    Args:
        bot_id: Bot identifier to delete.
        kill_tmux: Whether to kill the associated tmux session (default True).

    Returns:
        True if the bot was fully cleaned up, False on any failure.
    """
    bot = get_bot(bot_id)
    if not bot:
        logger.warning("delete_bot failed: bot '%s' not found in registry", bot_id)
        return False

    # Step 1: Stop and disable systemd service
    stop_service(bot_id)
    disable_service(bot_id)

    # Step 2: Kill tmux session if requested
    if kill_tmux:
        TMUX_SESSION_NAME = f"telegram-{bot_id}"
        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", TMUX_SESSION_NAME],
                capture_output=True,
                text=True,
                timeout=5,
            )
            logger.info("Killed tmux session: %s", TMUX_SESSION_NAME)
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.info(
                "tmux kill-session for '%s' skipped (may not exist): %s",
                TMUX_SESSION_NAME,
                e,
            )

    # Step 3: Remove config file
    CONFIG_PATH = bot.get("config_path", "")
    if CONFIG_PATH:
        try:
            Path(CONFIG_PATH).unlink(missing_ok=True)
            logger.info("Removed config file: %s", CONFIG_PATH)
        except OSError as e:
            logger.warning("Failed to remove config file: %s", e)

    # Step 4: Clean up pending files (both v1 and v2 naming)
    PENDING_DIR = Path.home() / ".aipass" / "telegram_pending"
    BRANCH_NAME = bot.get("branch_name", bot_id)

    # v2 naming: bot-{bot_id}.json
    PENDING_V2 = PENDING_DIR / f"bot-{bot_id}.json"
    PENDING_V2.unlink(missing_ok=True)

    # v1 naming: telegram-{branch_name}.json
    if BRANCH_NAME:
        PENDING_V1 = PENDING_DIR / f"telegram-{BRANCH_NAME}.json"
        PENDING_V1.unlink(missing_ok=True)

    # Step 5: Deregister from registry
    if not deregister_bot(bot_id):
        logger.warning("delete_bot: deregistration failed for '%s'", bot_id)
        return False

    logger.info("Bot deleted: %s", bot_id)
    return True
