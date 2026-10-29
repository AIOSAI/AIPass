# =================== AIPass ====================
# Name: doctor.py
# Description: System health aggregation — aipass doctor command
# Version: 1.14.0
# Created: 2026-04-16
# Modified: 2026-10-28
# =============================================

"""aipass doctor — system health aggregation."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional
from rich.markup import escape
from aipass.cli.apps.modules import console, error as cli_error, success
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

from aipass.aipass.shared.registry_discovery import find_registry as _discover_registry
from aipass.aipass.shared.project_home import _detect_aipass_home, find_fenceless_projects

from aipass.aipass.apps.handlers.cross_os import RunRecordError, generate_run_record
from aipass.aipass.apps.handlers.cross_os.doctor_rows import check_cross_os, record_path_arg
from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.provider_wire import platform_bridge_command
from aipass.aipass.apps.handlers.settings_backup import DOOR_DOCTOR_FIX, DOOR_INSTALL
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
    PackagesUnknown,
    check_placement,
    check_pyproject,
    check_registry_consistency,
    check_gitignore_coverage,
    check_root_artifacts,
    detect_pollution,
    disable_shadows,
    find_instruction_shadows,
    find_project_root,
    scan_agents,
)
from aipass.aipass.apps.modules._doctor_smoke import check_smoke, print_smoke_json
from aipass.aipass.apps.modules._doctor_fix import (
    print_json_report,
    print_remediation_report,
)
from aipass.aipass.apps.modules._doctor_wire import (
    _prompt_auto_wire as prompt_auto_wire,
    check_provider_sides,
    check_settings_scalars,
    check_wire_verify,
    fix_provider_settings,
    merge_manifest_rows,
    reconcile_stale_deny,
    settings_fix_report,
)
from aipass.aipass.apps.handlers.system_detect.system_detector import (
    detect_claude_code,
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

AGENTS_MD_MIN_CLAUDE = (2, 1, 277)

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

    git = detect_git()
    if git["found"]:
        results.append(CheckResult("git", GLYPH_PASS, git["version"], ""))
    else:
        results.append(CheckResult("git", GLYPH_FAIL, "not found", "Install git: https://git-scm.com/downloads"))

    sh = detect_shell()
    results.append(CheckResult("shell", GLYPH_PASS, sh["name"], ""))

    os_info = detect_os()
    detail = f"{os_info['os_name']} {os_info['release']}".strip()
    results.append(CheckResult("OS", GLYPH_PASS, detail, ""))

    ram = detect_ram()
    ram_detail = f"{ram['total_gb']} GB"
    if ram["ok"]:
        results.append(CheckResult("RAM", GLYPH_PASS, ram_detail, ""))
    elif ram["warning"]:
        results.append(CheckResult("RAM", GLYPH_WARN, ram_detail, "AIPass runs better with 4 GB+ RAM"))
    else:
        results.append(CheckResult("RAM", GLYPH_FAIL, ram_detail, "AIPass requires at least 2 GB RAM"))

    cpu = detect_cpu()
    results.append(CheckResult("CPU", GLYPH_PASS, f"{cpu['count']} cores", ""))

    method = detect_install_method()
    results.append(CheckResult("install", GLYPH_PASS, method, ""))

    results.append(_claude_code_row())

    return results


def _claude_code_row() -> CheckResult:
    """The `claude code` row: projects carry their instructions in AGENTS.md only.

    No claude on PATH is a plain row, since AIPass runs under other CLIs too.
    """
    claude = detect_claude_code()
    if not claude["found"]:
        return CheckResult("claude code", GLYPH_PASS, "not on PATH", "")
    version = claude["version"]
    if version is None:
        return CheckResult("claude code", GLYPH_WARN, f"version unreadable: {claude['raw']!r}", "")
    shown = ".".join(str(part) for part in version)
    if version >= AGENTS_MD_MIN_CLAUDE:
        return CheckResult("claude code", GLYPH_PASS, shown, "")
    return CheckResult(
        "claude code", GLYPH_WARN, shown, "Claude Code reads AGENTS.md from v2.1.277: run 'claude update'"
    )


def _configured_aipass_home() -> str:
    """``env.AIPASS_HOME`` from ~/.claude/settings.json; "" when absent or unreadable (global settings row FAILs)."""
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
        return [CheckResult("global settings", GLYPH_FAIL, "~/.claude/settings.json unreadable", "Repair its JSON")]
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

    A second install to another home overwrites ``~/.claude/settings.json``, so terminal
    tooling and Claude Code point at different trees while every row stays green. Silent
    when they agree; a pair that cannot be resolved is a WARN row (silence reads as agreement).
    """
    if not active or not configured:
        return []
    try:
        # resolve(): the same tree reached through a symlink or trailing slash is not a split.
        same = Path(active).resolve() == Path(configured).resolve()
    except (OSError, RuntimeError) as exc:  # RuntimeError: a symlink loop, Python 3.12 and older
        logger.warning("[doctor] could not resolve AIPASS_HOME pair: %s", exc)
        return [
            CheckResult(
                "AIPASS_HOME pair",
                GLYPH_WARN,
                f"cannot be compared — resolve failed: {exc}",
                f"Check both paths exist and hold no symlink loop: {active}, {configured}",
            )
        ]
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


def check_identity() -> List[CheckResult]:
    """Run Identity group checks. Public for tests/test_doctor.py; product caller: _compute_doctor_groups."""
    results: List[CheckResult] = []

    reg_path = _find_registry()
    if reg_path:
        active_home = _tree_in_use(reg_path.parent)
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

    if "branches" in reg_data:
        results.append(CheckResult("registry valid", GLYPH_PASS, "", ""))
    else:
        results.append(CheckResult("registry valid", GLYPH_FAIL, "missing 'branches' key", "Re-run 'aipass init'"))

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


def check_provider_manifest(
    interactive: bool = False,
    settings_path: Optional[Path] = None,
    os_name: Optional[str] = None,
) -> List[CheckResult]:
    """Check provider settings against manifest. Returns hook/env/permission results.

    Public: init_flow's report reads the manifest gaps through it. The --fix write lives in
    fix_provider_settings. settings_path and os_name are test seams; product callers pass neither.
    """
    if settings_path is None:
        settings_path = Path.home() / ".claude" / "settings.json"
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

    manifest_hooks = claude_section.get("hooks", [])
    provider: dict = {}
    if settings_path.exists():
        try:
            provider = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[doctor] provider settings read error: %s", exc)
    provider = provider if isinstance(provider, dict) else {}
    provider_hooks: dict = provider.get("hooks", {})

    missing_hooks = []
    for hook in manifest_hooks:
        # Same OS transform provider_wire applies at write time, so verify agrees with write.
        command = platform_bridge_command(hook.get("command", ""), os_name)
        event = hook.get("event", "")
        if not command or not event:
            continue
        event_entries = provider_hooks.get(event, [])
        hook_matcher = hook.get("matcher", "")
        found = any(
            isinstance(e, dict)
            and e.get("matcher", "") == hook_matcher
            and any(isinstance(h, dict) and h.get("command") == command for h in e.get("hooks", []))
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
                "Run 'aipass doctor --fix' to wire them (it backs the settings file up first)",
            )
        )

    missing_env: List[str] = []
    manifest_env = claude_section.get("env", {})
    if manifest_env:
        provider_env: dict = provider.get("env", {})
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

    missing_deny: List[str] = []
    missing_ask: List[str] = []
    manifest_perms = claude_section.get("permissions", {})
    manifest_deny = manifest_perms.get("deny", [])
    manifest_ask = manifest_perms.get("ask", [])
    if manifest_deny or manifest_ask:
        provider_perms: dict = provider.get("permissions", {})
        provider_deny = set(provider_perms.get("deny", []))
        provider_ask = set(provider_perms.get("ask", []))

        # Check deny rules (use ~ form only, skip expanded $HOME duplicates)
        missing_deny = [r for r in manifest_deny if r not in provider_deny]
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

    settings_rows, missing_settings = check_settings_scalars(manifest, settings_path)
    results.extend(CheckResult(*row) for row in settings_rows)
    results.extend(CheckResult(*row) for row in check_provider_sides(manifest, manifest_path))

    # Gate on what the wire verb would actually change, not on the glyphs: a settings key
    # the user set to their own value warns forever and must never trigger the prompt.
    if interactive and (missing_hooks or missing_env or missing_deny or missing_ask or missing_settings):
        wired = prompt_auto_wire(
            manifest_path,
            missing_hooks,
            missing_env,
            missing_deny,
            missing_ask,
            missing_settings,
            settings_path=settings_path,
        )
        if wired:  # the re-read after a wire reads the same file, on the same platform
            return check_provider_manifest(interactive=False, settings_path=settings_path, os_name=os_name)

    return results


_MAX_NAMED_EXTRAS = 3


def _registry_citizen_names() -> set[str]:
    """Lowercased names of every citizen the root registry lists. Empty on failure: the registry row FAILs it."""
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

    Anchored: a description that mentions another @branch must not count.
    """
    names: list[str] = []
    for line in stdout.splitlines():
        match = re.match(r"\s*@([A-Za-z0-9_-]+)", line)
        if match:
            names.append(match.group(1).lower())
    return names


def _check_drone_systems() -> List[CheckResult]:
    """The `drone` row — routed systems, reconciled against the registry.

    ``@git`` is routed but owns no passport, so routed and registered counts differ on a
    healthy install; the row names the difference and stays PASS.
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


def _home_venv_python(home: Path) -> Path:
    """The home's venv interpreter: .venv/Scripts/python.exe on Windows, else .venv/bin/python."""
    if os.name == "nt":
        return home / ".venv" / "Scripts" / "python.exe"
    return home / ".venv" / "bin" / "python"


def _check_pytest_collect(verbose: bool) -> List[CheckResult]:
    """Collect the install home's suite with the home's own venv, cwd at the home.

    Never sys.executable: on the pipx route that is pipx's venv, with no pytest and no src/ beside it.
    """
    home_val = _configured_aipass_home() or os.environ.get("AIPASS_HOME", "")
    if not home_val:
        fix = "Set env.AIPASS_HOME in ~/.claude/settings.json (aipass install does)"
        return [CheckResult("pytest collect", GLYPH_WARN, "AIPASS_HOME not set", fix)]
    home = Path(home_val)
    python = _home_venv_python(home)
    if not python.is_file():
        fix = f"Run ./setup.sh in {home} to create it"
        return [CheckResult("pytest collect", GLYPH_WARN, f"no venv at home ({home})", fix)]
    try:
        proc = subprocess.run(
            [str(python), "-m", "pytest", "src/aipass/", "--collect-only", "-q"],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=str(home),
        )
    except FileNotFoundError as exc:
        logger.warning("[doctor] home venv python would not run: %s", exc)
        return [CheckResult("pytest collect", GLYPH_WARN, f"venv python will not run ({python})", "")]
    except subprocess.TimeoutExpired as exc:
        logger.warning("[doctor] pytest collect timed out: %s", exc)
        fix = "Run manually: pytest src/aipass/ --collect-only -q — may just be a slow/shared-CPU environment"
        return [CheckResult("pytest collect", GLYPH_WARN, "timed out (90s)", fix)]
    lines = [ln.replace("[", r"\[") for ln in (proc.stdout + proc.stderr).splitlines()]  # markup-escaped
    if proc.returncode == 0:
        collected = [ln for ln in lines if "<" in ln or "::" in ln]
        detail = f"{len(collected)} tests collected" if collected else "ok"
        return [CheckResult("pytest collect", GLYPH_PASS, detail, "")]
    if "No module named pytest" in proc.stderr:
        fix = f"{python} -m pip install pytest"
        return [CheckResult("pytest collect", GLYPH_WARN, "pytest not installed in the home venv", fix)]
    # --verbose: pytest's ERROR lines (else its last line) under the row
    errs = [ln for ln in lines if ln.startswith("ERROR")] or lines[-1:]
    detail = "collection issues" + "".join(f"\n      {ln}" for ln in errs[:_MAX_NAMED_EXTRAS] if verbose)
    return [CheckResult("pytest collect", GLYPH_WARN, detail, "Run pytest to diagnose")]


def _check_services(verbose: bool = False) -> List[CheckResult]:
    """Run Services group checks."""
    results: List[CheckResult] = []

    results.extend(_check_drone_systems())
    results.extend(_check_pytest_collect(verbose))

    manifest_checks = check_provider_manifest()
    results.extend(manifest_checks)

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

    mail_dir = _BRANCH_ROOT / ".ai_mail.local"
    if mail_dir.exists() and mail_dir.is_dir():
        results.append(CheckResult("ai_mail", GLYPH_PASS, "readable", ""))
    else:
        results.append(CheckResult("ai_mail", GLYPH_FAIL, "not found", "Run 'aipass init' to set up mailbox"))

    # dropbox is optional for fresh projects: checked only once the project has agents
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

    # Placement — a root whose package names are unknown is one WARN row, never a placement issue
    unknown_packages: List[PackagesUnknown] = []
    placement_issues = check_placement(agents, project_root, unknown_packages)
    for unread in unknown_packages:
        results.append(
            CheckResult(
                "package names",
                GLYPH_WARN,
                f"unknown at {unread.root} — {unread.reason}",
                "Placement is not measured against packages there; install tomli or fix pyproject.toml",
            )
        )
    if placement_issues:
        for issue in placement_issues:
            glyph = GLYPH_WARN if issue.severity == "warn" else GLYPH_FAIL
            results.append(
                CheckResult(f"placement: {issue.agent_name}", glyph, issue.actual_path, issue.expected_pattern)
            )
    else:
        results.append(CheckResult("placement", GLYPH_PASS, "all agents correctly placed", ""))

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

    # setup.sh creates a real (non-symlink) .venv at AIPASS_HOME by design; root artifacts skip it.
    aipass_home = _detect_aipass_home()

    root_hits = check_root_artifacts(project_root, aipass_home=aipass_home)
    if root_hits:
        for hit in root_hits:
            glyph = GLYPH_PASS if hit.severity == "pass" else GLYPH_WARN
            results.append(CheckResult(f"root: {hit.name}", glyph, hit.description, ""))
    else:
        results.append(CheckResult("root artifacts", GLYPH_PASS, "none misplaced", ""))

    pyproject = check_pyproject(project_root)
    if pyproject["found"]:
        results.append(CheckResult("pyproject.toml", GLYPH_PASS, "present", ""))
    else:
        results.append(CheckResult("pyproject.toml", GLYPH_WARN, "missing", "Create pyproject.toml for pip packaging"))

    # Nested projects/<name> must exclude the host's AGENTS.md and CLAUDE.md pairs,
    # or Claude Code inherits them through the ancestor walk.
    if aipass_home:
        fenceless = find_fenceless_projects(aipass_home)
        if fenceless:
            for proj in fenceless:
                results.append(
                    CheckResult(
                        f"instruction fence: {proj.name}",
                        GLYPH_WARN,
                        "claudeMdExcludes misses the host AGENTS.md",
                        f"Run 'aipass init update {proj}'",
                    )
                )
        else:
            results.append(CheckResult("instruction fence", GLYPH_PASS, "all nested projects fenced", ""))

    results.extend(_check_instruction_shadow(project_root))
    results.extend(CheckResult(*row) for row in check_gitignore_coverage(project_root))
    return results


def _shadow_root() -> Optional[Path]:
    """The project doctor stands in: the one root --fix renames shadows under."""
    return find_project_root(Path.cwd())


def _check_instruction_shadow(project_root: Path) -> List[CheckResult]:
    """A live CLAUDE file beside AGENTS.md: Claude Code reads it and never sees AGENTS.md."""
    rows: List[CheckResult] = []
    for shadow in find_instruction_shadows(project_root):
        agents = shadow.agents_path.relative_to(project_root).as_posix()
        texts = "equal, the rename is the whole fix" if shadow.equal else "differ, copying it over is the owner's call"
        label = f"instruction shadow: {shadow.path.relative_to(project_root).as_posix()}"
        cure = f"mv '{shadow.path}' '{shadow.path}(disabled)', or {_FIX_COMMAND} (renames only)"
        rows.append(CheckResult(label, GLYPH_FAIL, f"Claude Code reads it, not {agents}; texts {texts}", cure))
    return rows or [CheckResult("instruction shadow", GLYPH_PASS, "no live CLAUDE file beside AGENTS.md", "")]


def _fix_instruction_shadow() -> List[CheckResult]:
    """--fix: rename each shadow to '(disabled)' beside it; the rechecked rows, then one row per action."""
    root = _shadow_root()
    if root is None or not (actions := disable_shadows(root)):
        return []
    fixed = [CheckResult("shadow fix", GLYPH_PASS if ok else GLYPH_WARN, action, "") for ok, action in actions]
    return _check_instruction_shadow(root) + fixed


def _check_sandbox() -> List[CheckResult]:
    """Run Sandbox group checks — kernel sandbox prerequisites, only when the flag is on.

    Off, the hook gates do the containing, so a missing prerequisite is no finding: one PASS row.
    """
    flag = check_sandbox_flag()
    if not flag["enabled"]:
        setting = f"={flag['raw_value']}" if flag["raw_value"] else " unset"
        return [
            CheckResult("sandbox", GLYPH_PASS, f"off (AIPASS_SANDBOX_ENABLED{setting}); prerequisites not checked", "")
        ]

    results: List[CheckResult] = []
    if not is_linux():
        results.append(CheckResult("sandbox", GLYPH_PASS, "kernel sandbox: Linux-only, not checked", ""))
        return results

    results.append(CheckResult("sandbox flag", GLYPH_PASS, "AIPASS_SANDBOX_ENABLED=ON", ""))

    def _sev(ok: bool) -> str:
        return GLYPH_PASS if ok else GLYPH_FAIL

    def _found(label: str, probe: dict, cure: str) -> CheckResult:
        return CheckResult(label, _sev(probe["found"]), probe["path"] or "not found", "" if probe["found"] else cure)

    bwrap = check_bwrap_present()
    results.append(_found("bwrap", bwrap, "sudo apt install bubblewrap"))

    if bwrap["found"]:
        func = check_bwrap_functional()
        detail = func["detail"]
        if not func["ok"] and func["sysctl_value"] is not None:
            detail = f"{detail} (apparmor_restrict_unprivileged_userns={func['sysctl_value']})"
        results.append(CheckResult("bwrap functional", _sev(func["ok"]), detail, ""))

    node = check_node_present()
    results.append(_found("node", node, "Install Node.js: https://nodejs.org/"))

    srt = check_srt_resolvable()
    results.append(_found("srt (@anthropic-ai/sandbox-runtime)", srt, srt["install_hint"]))

    rg = check_rg_present()
    results.append(_found("rg (ripgrep)", rg, "sudo apt install ripgrep  (or static binary to ~/.local/bin/rg)"))

    project_root = find_project_root(Path.cwd())
    broker = check_broker_alive(project_root)
    results.append(CheckResult("broker daemon", _sev(broker["alive"]), broker["detail"], ""))

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

    checks = check_cross_os(run_e2e=run_e2e)
    pass_count = 0
    warn_count = 0
    error_count = 0

    console.print("  [bold]Cross-OS[/bold]")
    for check in checks:  # rows carry registry and probe text, never markup: escaped so brackets print as written
        line = format_check(escape(check.label), check.glyph, escape(check.detail), escape(check.remediation))
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


def run_cross_os_record(path: str | None = None, run_e2e: bool = False) -> int:
    """Generate a machine pre-flight Run Record (`aipass doctor --cross-os --record`).

    Returns 0 on success, 1 if the file could not be written (never crashes).
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


def _check_tier0(root: Path, aipass_home: str | None, preview: str) -> List[CheckResult]:
    """Compare a project's tier0 kernel against AIPASS_HOME, with provenance."""
    from aipass.aipass.apps.handlers.init import scaffold_manifest as sm

    canonical = Path(aipass_home) / ".aipass" / "tier0_kernel.md" if aipass_home else None
    if not (canonical and canonical.is_file()):
        return []

    project_hash = sm.hash_file(root / ".aipass" / "tier0_kernel.md")
    if project_hash is None:
        return [CheckResult("tier0_kernel.md", GLYPH_WARN, "not found", preview)]
    if project_hash == sm.hash_file(canonical):
        return [CheckResult("tier0_kernel.md", GLYPH_PASS, "matches AIPASS_HOME", "")]

    recorded_hash = sm.manifest_hashes(root).get(".aipass/tier0_kernel.md")
    if recorded_hash == project_hash:
        # AIPass wrote this and the template has since moved on — an update
        # will refresh it, so the preview command is the whole answer.
        return [CheckResult("tier0_kernel.md", GLYPH_WARN, "template moved on", preview)]

    # The update KEEPS a project-edited or unprovable file: name both ways to settle it, not a
    # bare "differs" the manager cannot clear.
    provenance = "kept (local edits)" if recorded_hash else "kept (unknown provenance)"
    return [
        CheckResult(
            "tier0_kernel.md",
            GLYPH_WARN,
            provenance,
            f"Update keeps your copy. Delete it to take the template, "
            f"or add it to {sm.IGNORE_NAME} to keep it for good",
        )
    ]


def _tree_in_use(root: Path) -> str:
    """The AIPass tree a session at the registry root *root* runs on.

    *root* itself when it is an AIPass tree. An external project keeps its own registry but runs
    on the tree its .claude settings name (local first); *root* when they name none."""
    if (root / "src" / "aipass").is_dir():
        return str(root)
    for name in ("settings.local.json", "settings.json"):
        path = root / ".claude" / name
        if not path.is_file():
            continue
        try:
            named = json.loads(path.read_text(encoding="utf-8")).get("env", {}).get("AIPASS_HOME", "")
        except (json.JSONDecodeError, OSError, AttributeError) as exc:
            logger.warning("[doctor] project settings unreadable for AIPASS_HOME: %s: %s", path, exc)
            continue
        if named:
            return str(named)
    return str(root)


_SKILL_ROW_LABELS = ("shared skills", "skills link", "legacy prep", "provider switch", "skills fix")
_FIX_COMMAND = "aipass doctor --fix"


def _check_shared_skills(root: Path) -> List[CheckResult]:
    """Do both CLIs see every shared skill? Codex reads .agents/skills, Claude Code the .claude/skills link."""
    from aipass.aipass.apps.handlers.init import bootstrap as bs

    state = bs.shared_skills_state(root)
    fix = f"Run: {_FIX_COMMAND}"
    symlinks = (
        "on Windows it needs 'git config core.symlinks true' and the right to make links; without "
        f"them {_FIX_COMMAND} writes a copy that will not follow {bs.SKILLS_REL}"
    )
    rows: List[CheckResult] = []
    if not state["skills"]:
        rows.append(
            CheckResult("shared skills", GLYPH_WARN, f"none in {bs.SKILLS_REL}", f"Run 'aipass init update {root}'")
        )
    elif state["incomplete"]:
        detail = f"no name or description: {', '.join(state['incomplete'])}"
        rows.append(CheckResult("shared skills", GLYPH_WARN, detail, "Give each SKILL.md frontmatter both fields"))
    else:
        detail = f"{len(state['skills'])} in {bs.SKILLS_REL}, each named and described"
        rows.append(CheckResult("shared skills", GLYPH_PASS, detail, ""))

    link = state["link"]
    if link == bs.LINK_STATE_LINKED:
        rows.append(CheckResult("skills link", GLYPH_PASS, f"{bs.SKILLS_LINK_REL} -> {bs.SKILLS_REL}", ""))
    elif link == bs.LINK_STATE_MISSING:
        detail = f"{bs.SKILLS_LINK_REL} missing: Claude Code sees none"
        rows.append(CheckResult("skills link", GLYPH_WARN, detail, f"{fix} ({symlinks})"))
    elif link == bs.LINK_STATE_COPY:
        detail = f"{bs.SKILLS_LINK_REL} is a copy, not a link: it will not follow {bs.SKILLS_REL}"
        rows.append(CheckResult("skills link", GLYPH_WARN, detail, f"Make it the link: {symlinks}"))
    else:
        detail = f"{bs.SKILLS_LINK_REL} points at {state['link_to']}, not {bs.SKILLS_REL}"
        rows.append(CheckResult("skills link", GLYPH_WARN, detail, f"Point it at ../{bs.SKILLS_REL}"))

    if state["legacy_prep"] == "managed":
        detail = f"{bs.LEGACY_PREP_REL} beside {bs.PREP_SKILL_REL}: /prep is offered twice"
        rows.append(CheckResult("legacy prep", GLYPH_WARN, detail, fix))
    elif state["legacy_prep"] == "edited":
        detail = f"{bs.LEGACY_PREP_REL} is edited, so it is yours and kept: /prep is offered twice"
        rows.append(CheckResult("legacy prep", GLYPH_WARN, detail, f"Fold your edits into {bs.PREP_SKILL_REL}"))

    if state["switch_missing"]:
        detail = f"missing {', '.join(state['switch_missing'])}: the chat cannot switch CLI here"
        cure = f"Run 'aipass init update {root}'"
        rows.append(CheckResult("provider switch", GLYPH_WARN, detail, cure))
    else:
        detail = "Claude, Codex and OpenCode switches present (" + ", ".join(rel for rel, _ in bs.SWITCH_PAIR) + ")"
        rows.append(CheckResult("provider switch", GLYPH_PASS, detail, ""))
    return rows


def _fix_shared_skills() -> List[CheckResult]:
    """--fix: make a missing skills link, retire an unedited legacy prep command."""
    from aipass.aipass.apps.handlers.init.bootstrap import repair_shared_skills

    reg_path = _find_registry()
    if reg_path is None:
        return []
    actions = repair_shared_skills(reg_path.parent)
    json_handler.log_operation("doctor_fix_shared_skills", {"root": str(reg_path.parent), "actions": actions})
    return [CheckResult("skills fix", GLYPH_PASS, action, "") for action in actions]


def _check_scaffold() -> List[CheckResult]:
    """Run Scaffold group checks — is this project's AIPass scaffold current?

    Read-only even under ``--fix``: a scaffold update can replace files a manager wrote, so
    it is the owner's decision; doctor reports the drift and names the preview command.
    The shared-skills rows are the exception --fix repairs: a link and an unedited retire overwrite nothing.
    """
    from aipass.aipass.apps.handlers.init import scaffold_manifest as sm
    from aipass.aipass.apps.handlers.init.bootstrap import _MANIFEST_TRACKED, _handler_names

    reg_path = _find_registry()
    if reg_path is None:
        return [CheckResult("scaffold", GLYPH_WARN, "no project registry", "Run 'aipass init' to create one")]

    root = reg_path.parent
    skills_rows = _check_shared_skills(root)
    if (root / "src" / "aipass").is_dir() and (root / "pyproject.toml").exists():
        # The source repo's scaffold IS the templates — nothing to compare to.
        return [CheckResult("scaffold", GLYPH_PASS, "AIPass source repo — hand-maintained", "")] + skills_rows

    preview = f"Run 'aipass init update {root} --dry-run' to see the plan"
    results: List[CheckResult] = []
    try:
        ignored = sm.read_ignore(root)
    except sm.UpdateIgnoreUnreadable as exc:  # no claims known, so no drift is guessed: one row, the update refuses
        return [CheckResult(".updateignore", GLYPH_WARN, "is there but cannot be read — update refuses", str(exc))]

    installed = sm.installed_version()
    manifest = sm.read_manifest(root)
    stamped = sm.stamped_version(root)

    if not manifest:
        results.append(CheckResult("scaffold manifest", GLYPH_WARN, "not stamped", preview))
    else:
        recorded = len(sm.manifest_hashes(root))
        stamped_at = str(manifest.get("stamped_at", ""))[:10]
        results.append(CheckResult("scaffold manifest", GLYPH_PASS, f"{recorded} files, {stamped_at}", ""))

    if stamped == installed:
        results.append(CheckResult("scaffold version", GLYPH_PASS, installed, ""))
    else:
        results.append(CheckResult("scaffold version", GLYPH_WARN, f"{stamped or 'unstamped'} → {installed}", preview))

    aipass_home = _detect_aipass_home()

    # tier0 is the prompt injected every turn — the one file whose drift a
    # manager feels immediately, so it gets its own line rather than a count.
    if not sm.is_ignored(".aipass/tier0_kernel.md", ignored):
        results.extend(_check_tier0(root, aipass_home, preview))

    # hooks.json by handler keys, not existence: presence-only passed a hooks file months stale.
    hooks_path = root / ".aipass" / "hooks.json"
    template_path = Path(aipass_home) / ".aipass" / "project_hooks.json" if aipass_home else None
    if not hooks_path.exists():
        results.append(CheckResult("hooks handlers", GLYPH_WARN, "hooks.json not found", preview))
    elif template_path and template_path.is_file():
        try:
            project_hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
            template_hooks = json.loads(template_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[doctor] hooks compare failed: %s", exc)
            results.append(CheckResult("hooks handlers", GLYPH_WARN, "unreadable", preview))
        else:
            missing = sorted(_handler_names(template_hooks) - _handler_names(project_hooks))
            if missing:
                shown = ", ".join(missing[:3]) + ("…" if len(missing) > 3 else "")
                results.append(CheckResult("hooks handlers", GLYPH_WARN, f"{len(missing)} missing: {shown}", preview))
            else:
                results.append(CheckResult("hooks handlers", GLYPH_PASS, "match template", ""))

            retired = sm.retired_handlers_in(project_hooks)
            if retired:
                results.append(CheckResult("retired handlers", GLYPH_WARN, ", ".join(retired), preview))

    if ignored:
        # Owner-protected files are not drift and never carry a remediation —
        # the whole point of .updateignore is that this project decided already.
        protected = sum(1 for rel in _MANIFEST_TRACKED if sm.is_ignored(rel, ignored))
        results.append(CheckResult(".updateignore", GLYPH_PASS, f"{protected} file(s) owner-protected", ""))

    return results + skills_rows


def _wire_gap(row: CheckResult) -> bool:
    """A non-pass row the interactive wire could close: hooks, env, permissions or a settings key."""
    wired = row.label in ("hooks", "env vars", "permissions") or row.detail.startswith("manifest wants")
    return wired and row.glyph != GLYPH_PASS


def _compute_doctor_groups(
    verbose: bool = False,
    interactive: bool = False,
    fix: bool = False,
    door: str = DOOR_DOCTOR_FIX,
    yes: bool = False,
) -> Dict[str, List[CheckResult]]:
    """Run all six check groups (optionally auto-fixing). Returns them by group name.

    With *fix*, the settings step shows its plan and asks once before writing:
    *yes* skips the question, door ``install`` never asks, and *door*
    names the writer in the settings backup and receipt.
    """
    group_specs = [
        ("System", _check_system),
        ("Identity", check_identity),
        ("Services", lambda: _check_services(verbose=verbose)),
        ("Community", _check_community),
        ("Structure", _check_structure),
        ("Scaffold", _check_scaffold),
        ("Sandbox", _check_sandbox),
    ]
    groups: Dict[str, List[CheckResult]] = {}
    with make_doctor_progress() as progress:
        for name, runner in group_specs:
            task_id = progress.add_task(f"checking {name}...", total=None)
            groups[name] = runner()
            progress.remove_task(task_id)

    if fix:
        settings_rows = [CheckResult(*row) for row in fix_provider_settings(_find_manifest(), door=door, yes=yes)]
        manifest_results = check_provider_manifest()
        if manifest_results:
            groups["Services"] = merge_manifest_rows(groups.get("Services", []), manifest_results)
        stale_results = [CheckResult(*tup) for tup in reconcile_stale_deny(fix=False)]
        services = groups.get("Services", [])
        groups["Services"] = [r for r in services if r.label != "rm deny migration"] + stale_results + settings_rows
    elif interactive and any(_wire_gap(row) for row in groups.get("Services", [])):
        manifest_results = check_provider_manifest(interactive=True)
        if manifest_results:
            groups["Services"] = merge_manifest_rows(groups.get("Services", []), manifest_results)

    if fix:
        wire_recheck = [CheckResult(*r) for r in check_wire_verify()]
        services = groups.get("Services", [])
        groups["Services"] = [r for r in services if r.label != "wire verify"] + wire_recheck

        owner_fix = _fix_owner_seating()
        if any(r.glyph == GLYPH_PASS for r in owner_fix):
            owner_fix = _check_owner_seating()  # exit 0 is not proof the seat is clean
        identity = groups.get("Identity", [])
        groups["Identity"] = [r for r in identity if not r.label.startswith("owner")] + owner_fix

        skills_fix = _fix_shared_skills()
        if skills_fix:
            reg_path = _find_registry()
            rechecked = _check_shared_skills(reg_path.parent) if reg_path else []
            scaffold = [r for r in groups.get("Scaffold", []) if r.label not in _SKILL_ROW_LABELS]
            groups["Scaffold"] = scaffold + rechecked + skills_fix

        shadow_fix = _fix_instruction_shadow()
        if shadow_fix:
            structure = [r for r in groups.get("Structure", []) if not r.label.startswith("instruction shadow")]
            groups["Structure"] = structure + shadow_fix

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


def run_doctor(
    verbose: bool = False,
    interactive: bool = False,
    fix: bool = False,
    yes: bool = False,
    smoke: bool = False,
    model: str = "",
) -> int:
    """Run all six groups and print results. Returns error count. *yes*: --fix writes without asking.

    *smoke*: Services gains one live-turn row per provider (*model*: hooks' provider=model pairs).
    """
    console.print()
    console.print("[bold cyan]aipass doctor[/bold cyan]")
    console.print()

    groups = _compute_doctor_groups(verbose=verbose, interactive=interactive, fix=fix, yes=yes)
    if smoke:
        groups["Services"] = groups.get("Services", []) + [CheckResult(*row) for row in check_smoke(model)]
    pass_count, warn_count, error_count = _print_doctor_groups(groups)

    logger.info("[doctor] run complete — pass=%d warn=%d error=%d", pass_count, warn_count, error_count)
    return error_count


def run_doctor_preflight(fix: bool = True) -> tuple[int, List[str]]:
    """Run doctor automatically in the install tail, before the concierge says hello.

    Hook wiring is P1: a still-broken hooks/wire-verify result comes back separately for the
    top of the ACTION NEEDED block. Returns (error_count, hook_action_items).
    """
    console.print()
    console.print("[bold cyan]Running aipass doctor...[/bold cyan]")
    console.print()

    groups = _compute_doctor_groups(fix=fix, door=DOOR_INSTALL)
    _pass_count, _warn_count, error_count = _print_doctor_groups(groups)

    logger.info("[doctor] preflight complete — errors=%d", error_count)

    hook_labels = {"hooks", "wire verify"}
    hook_action_items = [
        f"{r.label}: {r.detail}" for r in groups.get("Services", []) if r.label in hook_labels and r.glyph != GLYPH_PASS
    ]
    return error_count, hook_action_items


def print_introspection() -> None:
    """Display module info and connected handlers."""
    console.print()
    console.print("[bold cyan]doctor Module[/bold cyan]")
    console.print("System health aggregation — flutter-doctor-style output")
    console.print()
    console.print("[yellow]Groups:[/yellow] System, Identity, Services, Community, Structure, Scaffold, Sandbox")
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
    console.print("  [green]aipass doctor --fix[/green]     [dim]# Settings plan + diff, ask once; owner repair[/dim]")
    console.print("  [green]aipass doctor --fix --yes[/green][dim]# The same, writing without the question[/dim]")
    console.print("  [green]aipass doctor --fix --json[/green][dim]# Remediation + settings plan as JSON[/dim]")
    console.print("  [green]aipass doctor --smoke[/green]   [dim]# + one live model turn per installed provider[/dim]")
    console.print("  [green]aipass doctor --smoke --json[/green] [dim]# hooks' smoke results as JSON[/dim]")
    console.print(
        "  [green]aipass doctor --smoke --model opencode=<model>[/green] [dim]# pick a provider's model[/dim]"
    )
    console.print("    [dim]--smoke spends one model turn per installed provider and needs each one's login;[/dim]")
    console.print("    [dim]not installed, no login, or a spent quota is a skip. Never part of --fix.[/dim]")
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


def handle_command(command: str, args: list[str]) -> bool:
    """Handle 'doctor' command routing."""
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
            record_path = record_path_arg(args)
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
    yes_mode = "--yes" in args
    smoke_mode = "--smoke" in args
    model = args[args.index("--model") + 1] if "--model" in args[:-1] else ""

    if smoke_mode and fix_mode:
        cli_error("--smoke spends model turns and never runs with --fix: run them apart")
        raise SystemExit(1)
    if smoke_mode and json_mode:
        rc = print_smoke_json(model)
        json_handler.log_operation("doctor_smoke_json", {"rc": rc, "model": model})
        if rc:
            raise SystemExit(1)
        return True

    if json_mode and fix_mode:
        settings_report = settings_fix_report(_find_manifest(), yes=yes_mode)
        project_root = find_project_root(Path.cwd())
        if project_root:
            print_json_report(project_root, provider_settings=settings_report)
        else:
            console.print(json.dumps({"provider_settings": settings_report}, indent=2), markup=False, highlight=False)
        return True

    error_count = run_doctor(
        verbose=verbose, interactive=True, fix=fix_mode, yes=yes_mode, smoke=smoke_mode, model=model
    )
    if fix_mode:
        project_root = find_project_root(Path.cwd())
        if project_root:
            print_remediation_report(project_root)
    json_handler.log_operation("doctor_run", {"error_count": error_count, "fix": fix_mode})
    if error_count > 0:
        raise SystemExit(1)
    return True
