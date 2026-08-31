# =================== AIPass ====================
# Name: doctor.py
# Description: System health aggregation — aipass doctor command
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-16
# =============================================

"""aipass doctor — system health aggregation."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple

from aipass.cli.apps.modules import console, error as cli_error, success
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

from aipass.aipass.shared.registry_discovery import find_registry as _discover_registry
from aipass.aipass.shared.project_home import _detect_aipass_home, find_fenceless_projects

from aipass.aipass.apps.handlers.cross_os import (
    CrossOsGapError,
    PreflightResult,
    RunRecordError,
    check_hookstatus,
    check_routing,
    check_versions,
    gaps_for_platform,
    generate_run_record,
)
from aipass.aipass.apps.handlers.cross_os import run_e2e as run_e2e_preflight
from aipass.aipass.apps.handlers.cross_os.preflight import E2E_UNRUNNABLE_PREFIX
from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.provider_wire import _platform_bridge_command
from aipass.aipass.apps.handlers.sandbox_check.sandbox_checker import (
    check_broker_alive,
    check_bwrap_functional,
    check_bwrap_present,
    check_node_present,
    check_rg_present,
    check_sandbox_flag,
    check_srt_resolvable,
    is_linux,
)
from aipass.aipass.apps.handlers.admin_lane import check_admin_lane
from aipass.aipass.apps.handlers.structure_scan.structure_scanner import (
    check_placement,
    check_pyproject,
    check_registry_consistency,
    check_root_artifacts,
    detect_pollution,
    find_project_root,
    scan_agents,
)
from aipass.aipass.apps.modules._doctor_fix import (
    print_json_report,
    print_remediation_report,
)
from aipass.aipass.apps.modules._doctor_wire import (
    _auto_wire_provider,
    _prompt_auto_wire as prompt_auto_wire,
    check_wire_verify,
    reconcile_stale_deny,
)
from aipass.aipass.apps.handlers.system_detect.system_detector import (
    detect_cpu,
    detect_git,
    detect_install_method,
    detect_os,
    detect_python,
    detect_ram,
    detect_shell,
)
from aipass.aipass.apps.handlers.module_root import module_file
from aipass.aipass.apps.handlers.ui.progress import (
    GLYPH_FAIL,
    GLYPH_PASS,
    GLYPH_WARN,
    format_check,
    make_doctor_progress,
)

COMMAND = "doctor"

# module_file, not resolve(): import-time cwd read on Windows (module_root).
_BRANCH_ROOT = module_file(__file__).parents[2]


class CheckResult(NamedTuple):
    """Single doctor check result."""

    label: str
    glyph: str
    detail: str
    remediation: str


def _find_registry() -> Path | None:
    """Find *_REGISTRY.json via shared discovery (walk-up from CWD + branch root)."""
    result = _discover_registry(package_root=str(_BRANCH_ROOT))
    return result if result is not None and result.exists() else None


def _check_system() -> List[CheckResult]:
    """Run System group checks."""
    results: List[CheckResult] = []

    # Python
    py = detect_python()
    if py["ok"]:
        glyph, detail, rem = GLYPH_PASS, py["version"], ""
    elif py["warning"]:
        glyph, detail = GLYPH_WARN, py["version"]
        rem = "Python 3.8 reaches end-of-life — upgrade to 3.9+"
    else:
        glyph, detail = GLYPH_FAIL, py["version"]
        rem = "Upgrade Python: https://python.org/downloads"
    results.append(CheckResult("python", glyph, detail, rem))

    # git
    git = detect_git()
    if git["found"]:
        results.append(CheckResult("git", GLYPH_PASS, git["version"], ""))
    else:
        results.append(CheckResult("git", GLYPH_FAIL, "not found", "Install git: https://git-scm.com/downloads"))

    # shell
    sh = detect_shell()
    results.append(CheckResult("shell", GLYPH_PASS, sh["name"], ""))

    # OS
    os_info = detect_os()
    detail = f"{os_info['os_name']} {os_info['release']}".strip()
    results.append(CheckResult("OS", GLYPH_PASS, detail, ""))

    # RAM
    ram = detect_ram()
    ram_detail = f"{ram['total_gb']} GB"
    if ram["ok"]:
        results.append(CheckResult("RAM", GLYPH_PASS, ram_detail, ""))
    elif ram["warning"]:
        results.append(CheckResult("RAM", GLYPH_WARN, ram_detail, "AIPass runs better with 4 GB+ RAM"))
    else:
        results.append(CheckResult("RAM", GLYPH_FAIL, ram_detail, "AIPass requires at least 2 GB RAM"))

    # CPU
    cpu = detect_cpu()
    results.append(CheckResult("CPU", GLYPH_PASS, f"{cpu['count']} cores", ""))

    # install method
    method = detect_install_method()
    results.append(CheckResult("install", GLYPH_PASS, method, ""))

    return results


def _configured_aipass_home() -> str:
    """``env.AIPASS_HOME`` from ~/.claude/settings.json, or "" when absent."""
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return ""
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.info("[doctor] global settings.json unreadable: %s", exc)
        return ""
    return str(data.get("env", {}).get("AIPASS_HOME", "") or "")


def _check_global_aipass_home() -> List[CheckResult]:
    """Check ~/.claude/settings.json env.AIPASS_HOME for stale or temp paths."""
    from aipass.aipass.apps.handlers.init.bootstrap import is_throwaway_path

    results: List[CheckResult] = []
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return results
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.info("[doctor] global settings.json unreadable: %s", exc)
        return results
    home_val = data.get("env", {}).get("AIPASS_HOME", "")
    if not home_val:
        return results
    home_path = Path(home_val)
    if not home_path.exists():
        results.append(
            CheckResult(
                "global AIPASS_HOME",
                GLYPH_FAIL,
                f"path does not exist: {home_val}",
                "Fix: edit ~/.claude/settings.json env.AIPASS_HOME to the real repo root",
            )
        )
    elif is_throwaway_path(home_val):
        results.append(
            CheckResult(
                "global AIPASS_HOME",
                GLYPH_FAIL,
                f"points to throwaway path: {home_val}",
                "Fix: edit ~/.claude/settings.json env.AIPASS_HOME to the real repo root",
            )
        )
    else:
        results.append(CheckResult("global AIPASS_HOME", GLYPH_PASS, home_val, ""))
    return results


def _check_home_agreement(active: str, configured: str) -> List[CheckResult]:
    """Compare the tree doctor is standing in against the one Claude Code uses.

    Doctor has always printed both on adjacent lines and never compared them.
    That gap hides a SPLIT-BRAIN install: a second install to a different home
    takes an unconditional overwrite of ``~/.claude/settings.json``, so terminal
    tooling (bashrc, symlinks) keeps pointing at tree 1 while Claude Code's env
    and every hook command point at tree 2 — two registries, two citizen_id
    sets, and every individual doctor row still green.

    Silent when they agree: both values are already on screen, so a third row
    saying so would be noise. Loud when they do not, because unlike an optional
    capability this is never a valid state.

    Args:
        active: The tree this doctor run resolved (registry parent / env).
        configured: ``env.AIPASS_HOME`` from ``~/.claude/settings.json``.

    Returns:
        One CheckResult when the trees disagree, otherwise an empty list.
    """
    if not active or not configured:
        return []
    try:
        # resolve() collapses trailing slashes and symlinks — the same tree
        # reached two ways is one tree, not a split.
        same = Path(active).resolve() == Path(configured).resolve()
    except OSError as exc:
        logger.warning("[doctor] could not resolve AIPASS_HOME pair: %s", exc)
        return []
    if same:
        return []

    logger.warning("[doctor] split-brain install: active=%s configured=%s", active, configured)
    return [
        CheckResult(
            "AIPASS_HOME split",
            GLYPH_FAIL,
            f"terminal uses {active}, Claude Code uses {configured}",
            "Two installs are live — point ~/.claude/settings.json env.AIPASS_HOME at the tree you work in",
        )
    ]


def _check_owner_seating() -> List[CheckResult]:
    """Check owner/identity health via the frozen sync-registry --check contract."""
    try:
        proc = subprocess.run(
            ["drone", "@spawn", "sync-registry", "--check", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        logger.info("[doctor] drone not on PATH — skipping owner seating check")
        return [CheckResult("owner", GLYPH_WARN, "drone not found", "Install drone to check owner seating")]
    except subprocess.TimeoutExpired:
        logger.warning("[doctor] sync-registry --check timed out")
        return [CheckResult("owner", GLYPH_WARN, "check timed out", "")]

    stdout = proc.stdout.strip()
    if not stdout:
        if proc.returncode == 0:
            return [CheckResult("owner", GLYPH_PASS, "clean (no details)", "")]
        return [CheckResult("owner", GLYPH_WARN, "no output from check", "")]

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        logger.warning("[doctor] sync-registry --check returned non-JSON: %s", stdout[:200])
        return [CheckResult("owner", GLYPH_WARN, "unparseable check output", "")]

    issues = data.get("issues", [])
    owner_name = data.get("owner")
    owner_uid = data.get("owner_uid", "")
    uid_short = owner_uid[:8] if owner_uid else ""

    if data.get("clean", False) and not issues:
        detail = f"@{owner_name} OK (seated, uid {uid_short})" if owner_name else "OK"
        return [CheckResult("owner", GLYPH_PASS, detail, "")]

    results: List[CheckResult] = []
    for issue in issues:
        flag = issue.get("flag", "unknown")
        detail = issue.get("detail", flag)
        results.append(CheckResult(f"owner/{flag}", GLYPH_FAIL, detail, "Run 'aipass doctor --fix'"))

    if not results:
        label = f"@{owner_name} ISSUES" if owner_name else "UNSEATED"
        results.append(CheckResult("owner", GLYPH_FAIL, label, "Run 'aipass doctor --fix'"))

    return results


def _fix_owner_seating() -> List[CheckResult]:
    """Delegate owner/identity repair to spawn's sync-registry --fix."""
    try:
        proc = subprocess.run(
            ["drone", "@spawn", "sync-registry", "--fix"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        logger.info("[doctor] drone not on PATH — skipping owner fix")
        return [CheckResult("owner fix", GLYPH_WARN, "drone not found", "")]
    except subprocess.TimeoutExpired:
        logger.warning("[doctor] sync-registry --fix timed out")
        return [CheckResult("owner fix", GLYPH_WARN, "fix timed out", "")]

    if proc.returncode == 0:
        return [CheckResult("owner fix", GLYPH_PASS, "registry reconciled", "")]
    detail = proc.stderr.strip()[:120] if proc.stderr else "non-zero exit"
    return [CheckResult("owner fix", GLYPH_FAIL, detail, "")]


def _check_identity() -> List[CheckResult]:
    """Run Identity group checks."""
    results: List[CheckResult] = []

    # Project root + registry — single lookup
    reg_path = _find_registry()
    if reg_path:
        active_home = str(reg_path.parent)
        results.append(CheckResult("AIPASS_HOME", GLYPH_PASS, active_home, ""))
    else:
        active_home = os.environ.get("AIPASS_HOME", "")
        if active_home:
            results.append(CheckResult("AIPASS_HOME", GLYPH_PASS, active_home, ""))
        else:
            results.append(
                CheckResult(
                    "AIPASS_HOME",
                    GLYPH_WARN,
                    "not set",
                    "Set in ~/.bashrc: export AIPASS_HOME=/path/to/aipass",
                )
            )

    results.extend(_check_global_aipass_home())
    # Both values are now on screen — say so when they disagree (silent when they agree)
    results.extend(_check_home_agreement(active_home, _configured_aipass_home()))

    if reg_path is None:
        results.append(CheckResult("registry", GLYPH_FAIL, "not found", "Run 'aipass init' to create registry"))
        return results

    branch_count = 0
    try:
        with open(reg_path, "r", encoding="utf-8") as f:
            reg_data = json.load(f)
        branch_count = len(reg_data.get("branches", []))
        results.append(CheckResult("registry", GLYPH_PASS, f"{branch_count} branches", ""))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[doctor] registry parse error: %s", exc)
        results.append(CheckResult("registry", GLYPH_FAIL, "corrupt JSON", "Manually inspect AIPASS_REGISTRY.json"))
        return results

    # Registry valid — has branches key
    if "branches" in reg_data:
        results.append(CheckResult("registry valid", GLYPH_PASS, "", ""))
    else:
        results.append(CheckResult("registry valid", GLYPH_FAIL, "missing 'branches' key", "Re-run 'aipass init'"))

    # hooks.json presence (project-level hook config)
    hooks_json = reg_path.parent / ".aipass" / "hooks.json"
    if hooks_json.exists():
        results.append(CheckResult("hooks.json", GLYPH_PASS, "present", ""))
    else:
        results.append(
            CheckResult(
                "hooks.json",
                GLYPH_WARN,
                "not found",
                "Run 'aipass init update' to create .aipass/hooks.json",
            )
        )

    # Passport readable
    passport = _BRANCH_ROOT / ".trinity" / "passport.json"
    if passport.exists():
        try:
            with open(passport, "r", encoding="utf-8") as f:
                pdata = json.load(f)
            role = pdata.get("identity", {}).get("role", "unknown")
            results.append(CheckResult("passport", GLYPH_PASS, f"role: {role}", ""))
        except Exception as exc:
            logger.warning("[doctor] passport read error: %s", exc)
            results.append(CheckResult("passport", GLYPH_WARN, "unreadable", "Check .trinity/passport.json"))
    else:
        results.append(CheckResult("passport", GLYPH_WARN, "not found", ""))

    results.extend(_check_owner_seating())

    return results


def _find_manifest() -> Path | None:
    """Find provider_manifest.json by walking up from CWD, AIPASS_HOME env, or settings.json."""
    aipass_home = os.environ.get("AIPASS_HOME", "")
    if not aipass_home:
        settings_path = Path.home() / ".claude" / "settings.json"
        if settings_path.exists():
            try:
                settings_env = json.loads(settings_path.read_text(encoding="utf-8")).get("env", {})
                aipass_home = settings_env.get("AIPASS_HOME", "")
            except Exception as exc:
                logger.info("[doctor] settings.json read for AIPASS_HOME fallback failed: %s", exc)

    for start in (Path.cwd(), Path(aipass_home) if aipass_home else None):
        if start is None:
            continue
        p = start.resolve()
        for parent in (p, *p.parents):
            candidate = parent / ".claude" / "provider_manifest.json"
            if candidate.exists():
                return candidate
            if parent == parent.parent:
                break
    return None


def _check_provider_manifest(interactive: bool = False, fix: bool = False) -> List[CheckResult]:
    """Check provider settings against manifest. Returns hook/env/permission results."""
    results: List[CheckResult] = []

    manifest_path = _find_manifest()
    if manifest_path is None:
        results.append(
            CheckResult(
                "hooks", GLYPH_WARN, "manifest not found", "Expected .claude/provider_manifest.json in project root"
            )
        )
        return results

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[doctor] manifest read error: %s", exc)
        results.append(CheckResult("hooks", GLYPH_WARN, "manifest unreadable", "Check .claude/provider_manifest.json"))
        return results

    claude_section = manifest.get("cli", {}).get("claude", {})
    if not claude_section:
        results.append(CheckResult("hooks", GLYPH_WARN, "manifest has no claude section", ""))
        return results

    # --- Hook commands wired in provider settings ---
    manifest_hooks = claude_section.get("hooks", [])
    provider_settings_path = Path.home() / ".claude" / "settings.json"
    provider_hooks: dict = {}
    if provider_settings_path.exists():
        try:
            provider_hooks = json.loads(provider_settings_path.read_text(encoding="utf-8")).get("hooks", {})
        except Exception as exc:
            logger.warning("[doctor] provider settings read error (hooks): %s", exc)

    missing_hooks = []
    for hook in manifest_hooks:
        # Same OS transform provider_wire applies at write time, so verify agrees with write (DPLAN-0234).
        command = _platform_bridge_command(hook.get("command", ""))
        event = hook.get("event", "")
        if not command or not event:
            continue
        event_entries = provider_hooks.get(event, [])
        hook_matcher = hook.get("matcher", "")
        found = any(
            isinstance(e, dict) and command in json.dumps(e) and e.get("matcher", "") == hook_matcher
            for e in event_entries
        )
        if not found:
            label = command.rsplit(" ", 1)[-1] if " " in command else command
            if label.startswith(f"{event}:"):
                label = label[len(event) + 1 :]
            missing_hooks.append(f"{event}:{label}")

    missing_hooks = list(dict.fromkeys(missing_hooks))

    if not missing_hooks:
        results.append(CheckResult("hooks", GLYPH_PASS, f"{len(manifest_hooks)} provider hooks wired", ""))
    else:
        results.append(
            CheckResult(
                "hooks",
                GLYPH_WARN,
                f"{len(missing_hooks)} hook(s) missing from provider settings: {', '.join(missing_hooks)}",
                "Run aipass init run or manually add bridge entries to ~/.claude/settings.json",
            )
        )

    # --- Env vars in provider settings ---
    missing_env: List[str] = []
    manifest_env = claude_section.get("env", {})
    if manifest_env:
        provider_settings_path = Path.home() / ".claude" / "settings.json"
        provider_env: dict = {}
        if provider_settings_path.exists():
            try:
                provider_env = json.loads(provider_settings_path.read_text(encoding="utf-8")).get("env", {})
            except Exception as exc:
                logger.warning("[doctor] provider settings read error (env): %s", exc)

        missing_env = [k for k in manifest_env if k not in provider_env]
        if not missing_env:
            results.append(CheckResult("env vars", GLYPH_PASS, f"{len(manifest_env)} provider env vars set", ""))
        else:
            results.append(
                CheckResult(
                    "env vars",
                    GLYPH_WARN,
                    f"{len(missing_env)} env var(s) missing: {', '.join(missing_env)}",
                    "Add to ~/.claude/settings.json env block — see provider_manifest.json",
                )
            )

    # --- Permissions ---
    missing_deny: List[str] = []
    missing_ask: List[str] = []
    manifest_perms = claude_section.get("permissions", {})
    manifest_deny = manifest_perms.get("deny", [])
    manifest_ask = manifest_perms.get("ask", [])
    if manifest_deny or manifest_ask:
        provider_settings_path = Path.home() / ".claude" / "settings.json"
        provider_perms: dict = {}
        if provider_settings_path.exists():
            try:
                provider_perms = json.loads(provider_settings_path.read_text(encoding="utf-8")).get("permissions", {})
            except Exception as exc:
                logger.warning("[doctor] provider settings read error (permissions): %s", exc)

        provider_deny = set(provider_perms.get("deny", []))
        provider_ask = set(provider_perms.get("ask", []))

        # Check deny rules (use ~ form only, skip expanded $HOME duplicates)
        missing_deny = [r for r in manifest_deny if r not in provider_deny]
        # Check ask rules
        missing_ask = [r for r in manifest_ask if r not in provider_ask]
        total_expected = len(manifest_deny) + len(manifest_ask)
        total_missing = len(missing_deny) + len(missing_ask)

        if total_missing == 0:
            results.append(CheckResult("permissions", GLYPH_PASS, f"{total_expected} permission rules set", ""))
        else:
            results.append(
                CheckResult(
                    "permissions",
                    GLYPH_WARN,
                    f"{total_missing} permission rule(s) missing",
                    "Add to ~/.claude/settings.json permissions — see provider_manifest.json",
                )
            )

    # --- Interactive auto-wire prompt / --fix auto-accept ---
    if (interactive or fix) and any(r.glyph != GLYPH_PASS for r in results):
        wired = False
        if fix:
            actions = _auto_wire_provider(manifest_path, interactive=False)
            for action in actions:
                success(action)
            wired = bool(actions)
        else:
            wired = prompt_auto_wire(manifest_path, missing_hooks, missing_env, missing_deny, missing_ask)

        if wired:
            return _check_provider_manifest(interactive=False, fix=False)

    return results


_MAX_NAMED_EXTRAS = 3


def _registry_citizen_names() -> set[str]:
    """Lowercased names of every citizen the root registry lists. Empty on failure."""
    reg_path = _find_registry()
    if reg_path is None:
        return set()
    try:
        data = json.loads(reg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("[doctor] could not read registry for citizen names: %s", exc)
        return set()
    branches = data.get("branches")
    if not isinstance(branches, list):
        return set()
    return {str(b.get("name", "")).lower() for b in branches if isinstance(b, dict) and b.get("name")}


def _drone_system_names(stdout: str) -> list[str]:
    """Names drone routes, read from the START of each line.

    Deliberately anchored: the old row counted every line CONTAINING "@", so a
    description mentioning another branch inflated the count. A routed name is
    the first token on its line, never one quoted inside prose.
    """
    names: list[str] = []
    for line in stdout.splitlines():
        match = re.match(r"\s*@([A-Za-z0-9_-]+)", line)
        if match:
            names.append(match.group(1).lower())
    return names


def _check_drone_systems() -> List[CheckResult]:
    """The `drone` row — routed systems, reconciled against the registry.

    ``drone systems`` lists everything ADDRESSABLE; the registry lists
    CITIZENS. They are different sets: ``@git`` is routed by drone but owns no
    branch directory and no passport, so a healthy install shows 19 routed
    against 18 registered. Printing the bare routed count next to the
    registry's count elsewhere on the same screen made two correct numbers look
    like a discrepancy — two independent readers tripped on it the same day.

    So the row now reconciles and NAMES the difference. It stays a PASS either
    way: a routed service without a passport is normal, not a fault.
    """
    results: List[CheckResult] = []
    try:
        proc = subprocess.run(["drone", "systems"], capture_output=True, text=True, timeout=10)
    except FileNotFoundError as exc:
        logger.warning("[doctor] drone not found: %s", exc)
        return [
            CheckResult(
                "drone",
                GLYPH_FAIL,
                "not found",
                "Ensure aipass is installed: clone the repo and run setup.sh",
            )
        ]
    except subprocess.TimeoutExpired as exc:
        logger.warning("[doctor] drone systems timed out: %s", exc)
        return [CheckResult("drone", GLYPH_WARN, "timed out", "")]

    if proc.returncode != 0:
        return [
            CheckResult(
                "drone",
                GLYPH_FAIL,
                "exit non-zero",
                "Ensure aipass is installed: clone the repo and run setup.sh",
            )
        ]

    routed = _drone_system_names(proc.stdout)
    if not routed:
        return [CheckResult("drone", GLYPH_PASS, "ok", "")]

    registered = _registry_citizen_names()
    # Only drone-side extras matter here. A citizen the registry lists but drone
    # does not route is a different question, and the registry row already owns it.
    extras = sorted({name for name in routed if name not in registered}) if registered else []

    if not extras:
        detail = f"{len(routed)} citizens"
    else:
        shown = ", ".join(f"@{n}" for n in extras[:_MAX_NAMED_EXTRAS])
        if len(extras) > _MAX_NAMED_EXTRAS:
            shown += f" +{len(extras) - _MAX_NAMED_EXTRAS} more"
        detail = f"{len(routed) - len(extras)} citizens + {len(extras)} routed service ({shown})"

    logger.info("[doctor] drone routed=%d registered=%d extras=%s", len(routed), len(registered), extras)
    results.append(CheckResult("drone", GLYPH_PASS, detail, ""))
    return results


def _check_services(verbose: bool = False) -> List[CheckResult]:
    """Run Services group checks."""
    results: List[CheckResult] = []

    results.extend(_check_drone_systems())

    # pytest --collect-only
    try:
        # Find repo root (where src/ lives)
        repo_root = None
        for parent in _BRANCH_ROOT.parents:
            if (parent / "src").exists() and (parent / "pyproject.toml").exists():
                repo_root = parent
                break
        cwd = str(repo_root) if repo_root else str(_BRANCH_ROOT)

        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "src/aipass/", "--collect-only", "-q"],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=cwd,
        )
        output = proc.stdout + proc.stderr
        if proc.returncode == 0:
            # Count collected lines
            collected = [ln for ln in output.splitlines() if "<" in ln or "::" in ln]
            detail = f"{len(collected)} tests collected" if collected else "ok"
            results.append(CheckResult("pytest collect", GLYPH_PASS, detail, ""))
        else:
            results.append(CheckResult("pytest collect", GLYPH_WARN, "collection issues", "Run pytest to diagnose"))
    except FileNotFoundError as exc:
        logger.warning("[doctor] pytest not found: %s", exc)
        results.append(CheckResult("pytest collect", GLYPH_WARN, "pytest not found", "pip install pytest"))
    except subprocess.TimeoutExpired as exc:
        logger.warning("[doctor] pytest collect timed out: %s", exc)
        results.append(
            CheckResult(
                "pytest collect",
                GLYPH_WARN,
                "timed out (90s)",
                "Run manually: pytest src/aipass/ --collect-only -q — may just be a slow/shared-CPU environment",
            )
        )

    # hooks + env + permissions — manifest-driven provider check
    manifest_checks = _check_provider_manifest()
    results.extend(manifest_checks)

    # wire_verify guard — catch empty/orphaned/duplicate provider hook entries
    results.extend(CheckResult(*r) for r in check_wire_verify())

    # stale rm deny rules — detect only (fix runs in run_doctor when --fix)
    for tup in reconcile_stale_deny(fix=False):
        results.append(CheckResult(*tup))

    # admin lane — informational only; a dark lane is a valid install, so this
    # never errors and never names a ceremony command, only the doc
    for tup in check_admin_lane():
        results.append(CheckResult(*tup))

    return results


def _check_community() -> List[CheckResult]:
    """Run Community group checks."""
    results: List[CheckResult] = []

    # ai_mail readable
    mail_dir = _BRANCH_ROOT / ".ai_mail.local"
    if mail_dir.exists() and mail_dir.is_dir():
        results.append(CheckResult("ai_mail", GLYPH_PASS, "readable", ""))
    else:
        results.append(CheckResult("ai_mail", GLYPH_FAIL, "not found", "Run 'aipass init' to set up mailbox"))

    # dropbox writable — only check if project has agents (dropbox is optional for fresh projects)
    reg_path = _find_registry()
    dropbox = None
    if reg_path:
        dropbox = reg_path.parent / "dropbox"
    if dropbox and dropbox.exists():
        writable = os.access(dropbox, os.W_OK)
        if writable:
            results.append(CheckResult("dropbox", GLYPH_PASS, "writable", ""))
        else:
            results.append(CheckResult("dropbox", GLYPH_WARN, "not writable", "Check dropbox directory permissions"))

    return results


# --- Structure check group ---


def _check_structure() -> List[CheckResult]:
    """Run Structure group checks — agent placement, pollution, registry consistency."""
    results: List[CheckResult] = []

    project_root = find_project_root(Path.cwd())
    if project_root is None:
        results.append(
            CheckResult("project root", GLYPH_WARN, "not detected", "Run from inside an AIPass project directory")
        )
        return results

    agents = scan_agents(project_root)
    results.append(CheckResult("agents found", GLYPH_PASS, f"{len(agents)} agents", ""))

    # Placement
    placement_issues = check_placement(agents, project_root)
    if placement_issues:
        for issue in placement_issues:
            glyph = GLYPH_WARN if issue.severity == "warn" else GLYPH_FAIL
            results.append(
                CheckResult(f"placement: {issue.agent_name}", glyph, issue.actual_path, issue.expected_pattern)
            )
    else:
        results.append(CheckResult("placement", GLYPH_PASS, "all agents correctly placed", ""))

    # Pollution
    pollution = detect_pollution(agents)
    if pollution:
        for hit in pollution:
            locs = ", ".join(hit.locations)
            results.append(
                CheckResult(
                    f"pollution: {hit.agent_name}",
                    GLYPH_FAIL,
                    f"{len(hit.locations)} copies",
                    f"Duplicate branch name at: {locs}",
                )
            )
    else:
        results.append(CheckResult("pollution", GLYPH_PASS, "no duplicates", ""))

    # Registry consistency
    reg_path = _discover_registry(start_path=project_root)
    if reg_path and reg_path.exists():
        reg_issues = check_registry_consistency(reg_path, agents, project_root=project_root)
        if reg_issues:
            for issue in reg_issues:
                glyph = GLYPH_FAIL if issue.problem == "missing" else GLYPH_WARN
                results.append(
                    CheckResult(f"registry: {issue.branch_name}", glyph, issue.problem, issue.registered_path)
                )
        else:
            results.append(CheckResult("registry paths", GLYPH_PASS, "all paths valid", ""))
    else:
        results.append(CheckResult("registry", GLYPH_WARN, "not found", "Expected *_REGISTRY.json in project root"))

    # Detect AIPASS_HOME once — used both to skip the standard root .venv
    # (setup.sh creates a real, non-symlink .venv there by design) and for
    # the CLAUDE.md fence check below.
    aipass_home = _detect_aipass_home()

    # Root artifacts
    root_hits = check_root_artifacts(project_root, aipass_home=aipass_home)
    if root_hits:
        for hit in root_hits:
            glyph = GLYPH_PASS if hit.severity == "pass" else GLYPH_WARN
            results.append(CheckResult(f"root: {hit.name}", glyph, hit.description, ""))
    else:
        results.append(CheckResult("root artifacts", GLYPH_PASS, "none misplaced", ""))

    # Pyproject
    pyproject = check_pyproject(project_root)
    if pyproject["found"]:
        results.append(CheckResult("pyproject.toml", GLYPH_PASS, "present", ""))
    else:
        results.append(CheckResult("pyproject.toml", GLYPH_WARN, "missing", "Create pyproject.toml for pip packaging"))

    # CLAUDE.md ancestor fence — nested projects/<name> must exclude the host's
    # CLAUDE.md + .claude/CLAUDE.md, or Claude Code inherits them via ancestor walk.
    if aipass_home:
        fenceless = find_fenceless_projects(aipass_home)
        if fenceless:
            for proj in fenceless:
                results.append(
                    CheckResult(
                        f"CLAUDE.md fence: {proj.name}",
                        GLYPH_WARN,
                        "missing claudeMdExcludes",
                        f"Run 'aipass init update {proj}'",
                    )
                )
        else:
            results.append(CheckResult("CLAUDE.md fence", GLYPH_PASS, "all nested projects fenced", ""))

    return results


# --- Sandbox check group ---


def _check_sandbox() -> List[CheckResult]:
    """Run Sandbox group checks — kernel sandbox prerequisites."""
    results: List[CheckResult] = []

    if not is_linux():
        results.append(CheckResult("sandbox", GLYPH_PASS, "kernel sandbox: Linux-only, not checked", ""))
        return results

    flag = check_sandbox_flag()
    flag_on = flag["enabled"]
    flag_label = "ON" if flag_on else "OFF"
    results.append(CheckResult("sandbox flag", GLYPH_PASS, f"AIPASS_SANDBOX_ENABLED={flag_label}", ""))

    def _sev(ok: bool) -> str:
        if ok:
            return GLYPH_PASS
        return GLYPH_FAIL if flag_on else GLYPH_WARN

    def _suffix(ok: bool) -> str:
        if ok or flag_on:
            return ""
        return " (inert — flag is off)"

    bwrap = check_bwrap_present()
    results.append(
        CheckResult(
            "bwrap",
            _sev(bwrap["found"]),
            bwrap["path"] or "not found" + _suffix(bwrap["found"]),
            "" if bwrap["found"] else "sudo apt install bubblewrap",
        )
    )

    if bwrap["found"]:
        func = check_bwrap_functional()
        detail = func["detail"]
        if not func["ok"] and func["sysctl_value"] is not None:
            detail = f"{detail} (apparmor_restrict_unprivileged_userns={func['sysctl_value']})"
        results.append(
            CheckResult(
                "bwrap functional",
                _sev(func["ok"]),
                detail + _suffix(func["ok"]),
                "",
            )
        )

    node = check_node_present()
    results.append(
        CheckResult(
            "node",
            _sev(node["found"]),
            node["path"] or "not found" + _suffix(node["found"]),
            "" if node["found"] else "Install Node.js: https://nodejs.org/",
        )
    )

    srt = check_srt_resolvable()
    results.append(
        CheckResult(
            "srt (@anthropic-ai/sandbox-runtime)",
            _sev(srt["found"]),
            srt["path"] or "not found" + _suffix(srt["found"]),
            "" if srt["found"] else srt["install_hint"],
        )
    )

    rg = check_rg_present()
    results.append(
        CheckResult(
            "rg (ripgrep)",
            _sev(rg["found"]),
            rg["path"] or "not found" + _suffix(rg["found"]),
            "" if rg["found"] else "sudo apt install ripgrep  (or static binary to ~/.local/bin/rg)",
        )
    )

    project_root = find_project_root(Path.cwd())
    broker = check_broker_alive(project_root)
    results.append(
        CheckResult(
            "broker daemon",
            _sev(broker["alive"]),
            broker["detail"] + _suffix(broker["alive"]),
            "",
        )
    )

    return results


# --- Cross-OS pre-flight group ---


def _cross_os_gap_rows() -> List[CheckResult]:
    """OS-gap cross-reference rows (slice 1): tracked gaps for this platform.

    Machine pre-flight — surfaces OS-specific gaps from tests/CROSS_OS_TESTING.md
    for this box. Never claims the checklist's human green. WARN per gap, a single
    PASS when none apply, a single WARN when the registry can't be read (never
    silent).
    """
    platform_name = sys.platform
    try:
        gaps = gaps_for_platform(platform_name)
    except CrossOsGapError as exc:
        logger.warning("[doctor] cross-OS gap registry unavailable: %s", exc)
        return [
            CheckResult(
                "cross-os registry (pre-flight)",
                GLYPH_WARN,
                f"pre-flight: gap registry unavailable — {exc}",
                "Ensure tests/CROSS_OS_TESTING.md has a 'Known cross-OS gap registry' table",
            )
        ]

    if not gaps:
        return [
            CheckResult(
                "cross-os (pre-flight)",
                GLYPH_PASS,
                f"pre-flight: no tracked cross-OS gaps for {platform_name}",
                "",
            )
        ]

    return [
        CheckResult(
            f"cross-os gap #{gap.number} (pre-flight)",
            GLYPH_WARN,
            f"pre-flight: {gap.symptom}",
            f"tracked gap [{gap.status}] — owner {gap.owner}; human Layer-3 pass still required",
        )
        for gap in gaps
    ]


def _preflight_row(label: str, result: PreflightResult, remediation: str) -> CheckResult:
    """Map a non-mutating PreflightResult to a labelled pre-flight CheckResult.

    ok -> PASS, else FAIL. The detail is always prefixed 'pre-flight:' so a row
    can never be mistaken for the checklist's human acceptance green.
    """
    glyph = GLYPH_PASS if result.ok else GLYPH_FAIL
    return CheckResult(f"{label} (pre-flight)", glyph, f"pre-flight: {result.detail}", "" if result.ok else remediation)


def _e2e_row(result: PreflightResult) -> CheckResult:
    """Map the heavy e2e PreflightResult to a CheckResult (PASS/FAIL/WARN).

    ok -> PASS. Un-runnable infra cases (dir missing, no pytest, timeout) -> WARN.
    Real test failures -> FAIL.
    """
    if result.ok:
        glyph, remediation = GLYPH_PASS, ""
    elif result.detail.startswith(E2E_UNRUNNABLE_PREFIX):
        glyph = GLYPH_WARN
        remediation = "Ensure a project .venv with pytest (or system pytest) and tests/e2e are present"
    else:
        glyph, remediation = GLYPH_FAIL, "Run 'pytest tests/e2e -q' from the repo root to inspect the failures"
    return CheckResult("e2e suite (pre-flight)", glyph, f"pre-flight: {result.detail}", remediation)


def _check_cross_os(run_e2e: bool = False) -> List[CheckResult]:
    """Cross-OS pre-flight group (Layer-3-lite): gap cross-reference + machine routes.

    Combines the slice-1 OS-gap rows with the non-mutating routing / --version /
    hookstatus probes (Phase 4 / 1.3 / 6.3). None of these wake a citizen. When
    ``run_e2e`` is set, also runs the heavy Phase-2 e2e suite. Every row is
    labelled pre-flight and still needs the human Layer-3 pass.
    """
    results = _cross_os_gap_rows()

    results.append(
        _preflight_row(
            "routing", check_routing(), "Ensure aipass is installed (setup.sh) so 'drone systems' and routes resolve"
        )
    )
    results.append(
        _preflight_row(
            "versions", check_versions(), "Ensure 'drone' and 'aipass' are on PATH (clone the repo, run setup.sh)"
        )
    )
    results.append(
        _preflight_row("hookstatus", check_hookstatus(), "Check @hooks routing: 'drone @hooks status' should exit 0")
    )

    if run_e2e:
        results.append(_e2e_row(run_e2e_preflight()))

    return results


def run_cross_os(run_e2e: bool = False) -> int:
    """Render only the cross-OS pre-flight group (`aipass doctor --cross-os`).

    Returns the error (FAIL) count; warnings do not fail, matching run_doctor.
    When ``run_e2e`` is set (``--cross-os --e2e``), the heavy e2e suite runs too.
    """
    console.print()
    console.print("[bold cyan]aipass doctor --cross-os[/bold cyan]")
    console.print("[dim]machine pre-flight (Layer-3-lite) — augments, never replaces, the human acceptance pass[/dim]")
    if run_e2e:
        console.print("[dim]--e2e: running the heavy Phase-2 e2e wiring suite (builds a wheel + fresh venv)…[/dim]")
    console.print()

    checks = _check_cross_os(run_e2e=run_e2e)
    pass_count = 0
    warn_count = 0
    error_count = 0

    console.print("  [bold]Cross-OS[/bold]")
    for check in checks:
        line = format_check(check.label, check.glyph, check.detail, check.remediation)
        console.print(line)
        if check.glyph == GLYPH_PASS:
            pass_count += 1
        elif check.glyph == GLYPH_WARN:
            warn_count += 1
        else:
            error_count += 1
    console.print()

    console.print("[dim]─────────────────────────────────[/dim]")
    console.print(
        f"  [green]✓ pass: {pass_count}[/green]  "
        f"[yellow]! warnings: {warn_count}[/yellow]  "
        f"[red]✗ errors: {error_count}[/red]"
    )
    console.print()

    logger.info("[doctor] cross-os run — pass=%d warn=%d error=%d", pass_count, warn_count, error_count)
    return error_count


def _record_path_arg(args: list[str]) -> str | None:
    """Extract the optional PATH value following ``--record`` (None if absent).

    ``--record`` may stand alone (default path) or be followed by a path; a
    following token that starts with ``-`` is another flag, not the path.
    """
    if "--record" not in args:
        return None
    idx = args.index("--record")
    if idx + 1 < len(args):
        candidate = args[idx + 1]
        if not candidate.startswith("-"):
            return candidate
    return None


def run_cross_os_record(path: str | None = None, run_e2e: bool = False) -> int:
    """Generate a machine pre-flight Run Record (`aipass doctor --cross-os --record`).

    Thin console wrapper: generation (env capture + machine-provable rows, human
    rows left blank/marked) lives in the cross_os handler. Returns 0 on success,
    1 if the file could not be written (never crashes).
    """
    console.print()
    console.print("[bold cyan]aipass doctor --cross-os --record[/bold cyan]")
    console.print(
        "[dim]machine pre-flight DRAFT — auto-fills what the machine can prove; "
        "a human still runs the real Layer-3 pass[/dim]"
    )
    if run_e2e:
        console.print("[dim]--e2e: running the heavy Phase-2 e2e suite (builds a wheel + fresh venv)…[/dim]")
    console.print()

    try:
        written = generate_run_record(path, run_heavy_e2e=run_e2e)
    except RunRecordError as exc:
        cli_error(str(exc))
        logger.error("[doctor] cross-os run record failed: %s", exc)
        return 1

    success(f"Run Record written: {written}")
    console.print("[dim]Complete the '— human' rows and run the real Layer-3 acceptance pass before it counts.[/dim]")
    console.print()
    logger.info("[doctor] cross-os run record written to %s", written)
    return 0


# --- Main doctor run ---


def _compute_doctor_groups(
    verbose: bool = False, interactive: bool = False, fix: bool = False
) -> Dict[str, List[CheckResult]]:
    """Run all six check groups (optionally auto-fixing). Returns them by group name."""
    group_specs = [
        ("System", _check_system),
        ("Identity", _check_identity),
        ("Services", lambda: _check_services(verbose=verbose)),
        ("Community", _check_community),
        ("Structure", _check_structure),
        ("Sandbox", _check_sandbox),
    ]
    groups: Dict[str, List[CheckResult]] = {}
    with make_doctor_progress() as progress:
        for name, runner in group_specs:
            task_id = progress.add_task(f"checking {name}...", total=None)
            groups[name] = runner()
            progress.remove_task(task_id)

    if interactive or fix:
        manifest_results = _check_provider_manifest(interactive=interactive, fix=fix)
        if manifest_results:
            groups["Services"] = [
                r for r in groups.get("Services", []) if r.label not in ("hooks", "env vars", "permissions")
            ] + manifest_results

    if fix:
        stale_results = [CheckResult(*tup) for tup in reconcile_stale_deny(fix=True)]
        if stale_results:
            services = groups.get("Services", [])
            groups["Services"] = [r for r in services if r.label != "rm deny migration"] + stale_results

        wire_recheck = [CheckResult(*r) for r in check_wire_verify()]
        services = groups.get("Services", [])
        groups["Services"] = [r for r in services if r.label != "wire verify"] + wire_recheck

        owner_fix = _fix_owner_seating()
        identity = groups.get("Identity", [])
        groups["Identity"] = [r for r in identity if not r.label.startswith("owner")] + owner_fix

    return groups


def _print_doctor_groups(groups: Dict[str, List[CheckResult]]) -> tuple[int, int, int]:
    """Print each group's checks. Returns (pass_count, warn_count, error_count)."""
    pass_count = 0
    warn_count = 0
    error_count = 0

    for group_name, checks in groups.items():
        console.print(f"  [bold]{group_name}[/bold]")
        for check in checks:
            line = format_check(check.label, check.glyph, check.detail, check.remediation)
            console.print(line)
            if check.glyph == GLYPH_PASS:
                pass_count += 1
            elif check.glyph == GLYPH_WARN:
                warn_count += 1
            else:
                error_count += 1
        console.print()

    console.print("[dim]─────────────────────────────────[/dim]")
    summary_parts = [
        f"[green]✓ pass: {pass_count}[/green]",
        f"[yellow]! warnings: {warn_count}[/yellow]",
        f"[red]✗ errors: {error_count}[/red]",
    ]
    console.print("  " + "  ".join(summary_parts))
    console.print()
    return pass_count, warn_count, error_count


def run_doctor(verbose: bool = False, interactive: bool = False, fix: bool = False) -> int:
    """Run all six groups and print results. Returns error count."""
    console.print()
    console.print("[bold cyan]aipass doctor[/bold cyan]")
    console.print()

    groups = _compute_doctor_groups(verbose=verbose, interactive=interactive, fix=fix)
    pass_count, warn_count, error_count = _print_doctor_groups(groups)

    logger.info("[doctor] run complete — pass=%d warn=%d error=%d", pass_count, warn_count, error_count)
    return error_count


def run_doctor_preflight(fix: bool = True) -> tuple[int, List[str]]:
    """Run doctor automatically in the install tail, before the concierge says hello.

    Patrick's ruling (round-2 addendum 2): doctor must run as part of install,
    not be offered later as a chat option — and hook wiring is P1, so a
    still-broken hooks/wire-verify result is surfaced separately for the
    caller to put at the TOP of the ACTION NEEDED block.

    Returns (error_count, hook_action_items) — hook_action_items is empty
    when provider hooks are fully wired after the fix pass.
    """
    console.print()
    console.print("[bold cyan]Running aipass doctor...[/bold cyan]")
    console.print()

    groups = _compute_doctor_groups(fix=fix)
    _pass_count, _warn_count, error_count = _print_doctor_groups(groups)

    logger.info("[doctor] preflight complete — errors=%d", error_count)

    hook_labels = {"hooks", "wire verify"}
    hook_action_items = [
        f"{r.label}: {r.detail}" for r in groups.get("Services", []) if r.label in hook_labels and r.glyph != GLYPH_PASS
    ]
    return error_count, hook_action_items


# --- Output formatting ---


def print_introspection() -> None:
    """Display module info and connected handlers."""
    console.print()
    console.print("[bold cyan]doctor Module[/bold cyan]")
    console.print("System health aggregation — flutter-doctor-style output")
    console.print()
    console.print("[yellow]Groups:[/yellow] System, Identity, Services, Community, Structure, Sandbox")
    console.print("[yellow]Next:[/yellow]  [green]aipass doctor[/green] / [green]aipass doctor --fix[/green]")
    console.print()


def print_help() -> None:
    """Print help information."""
    console.print()
    console.print("[bold cyan]aipass doctor[/bold cyan] — System health aggregation")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass doctor[/green]           [dim]# Run all checks[/dim]")
    console.print("  [green]aipass doctor --verbose[/green] [dim]# Show sub-check detail[/dim]")
    console.print("  [green]aipass doctor --fix[/green]     [dim]# Auto-wire, owner seat repair + remediation[/dim]")
    console.print("  [green]aipass doctor --fix --json[/green][dim]# Remediation as JSON (for spawn)[/dim]")
    console.print("  [green]aipass doctor --cross-os[/green][dim]# OS-gap + routing/version/hooks pre-flight[/dim]")
    console.print("  [green]aipass doctor --cross-os --e2e[/green][dim]# …also run the heavy e2e suite[/dim]")
    console.print(
        "  [green]aipass doctor --cross-os --record [PATH][/green]"
        "[dim]# write a machine pre-flight Run Record draft (human completes it)[/dim]"
    )
    console.print()
    console.print("[yellow]OUTPUT:[/yellow]  pass / warn / error (color-coded)")
    console.print("[yellow]EXIT:[/yellow]    0 = pass/warn  |  1 = errors found")
    console.print()


# --- Command handler ---


def handle_command(command: str, args: list[str]) -> bool:
    """Handle 'doctor' command routing.

    Args:
        command: Command name.
        args: Additional arguments.

    Returns:
        True if handled (command == 'doctor'), False otherwise.
    """
    if command != "doctor":
        return False

    if wants_help(args):
        print_help()
        return True

    if args and args[0] == "--info":
        print_introspection()
        return True

    if "--cross-os" in args:
        e2e = "--e2e" in args
        if "--record" in args:
            record_path = _record_path_arg(args)
            rc = run_cross_os_record(record_path, run_e2e=e2e)
            json_handler.log_operation("doctor_cross_os_record", {"path": record_path, "e2e": e2e, "rc": rc})
            if rc != 0:
                raise SystemExit(1)
            return True
        error_count = run_cross_os(run_e2e=e2e)
        json_handler.log_operation("doctor_cross_os", {"error_count": error_count, "e2e": e2e})
        if error_count > 0:
            raise SystemExit(1)
        return True

    verbose = "--verbose" in args or "-v" in args
    fix_mode = "--fix" in args
    json_mode = "--json" in args

    if json_mode and fix_mode:
        project_root = find_project_root(Path.cwd())
        if project_root:
            print_json_report(project_root)
        return True

    error_count = run_doctor(verbose=verbose, interactive=True, fix=fix_mode)
    if fix_mode:
        project_root = find_project_root(Path.cwd())
        if project_root:
            print_remediation_report(project_root)
    json_handler.log_operation("doctor_run", {"error_count": error_count, "fix": fix_mode})
    if error_count > 0:
        raise SystemExit(1)
    return True
