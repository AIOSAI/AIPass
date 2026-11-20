# =================== AIPass ====================
# Name: project_defaults.py
# Description: A project's first-seat defaults: .updateignore, test-write policy, First wake checklist
# Version: 1.1.0
# Created: 2026-11-20
# Modified: 2026-11-20
# =============================================

"""A new project seat's defaults, chosen by the arrival its caller names (spawn never guesses it). See docs/birth.md"""

from pathlib import Path

from aipass.prax import logger

from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.json import json_handler
from aipass.spawn.apps.handlers.update_ignore import IGNORE_NAME, UpdateIgnoreUnreadable, read_ignore

ARRIVALS = ("fresh", "adopted")
PROJECT_TEMPLATE_DIR = Path(__file__).parents[2] / "templates" / "project"
LOCAL_PROMPT_REL = Path(".aipass") / "aipass_local_prompt.md"
# Where @hooks' test-write gate looks, walking up from the session: the project root's .aipass/.
TEST_POLICY_REL = Path(".aipass") / "test_write_policy.json"


def arrival_refusal(arrival) -> str | None:
    """The refusal for an arrival with no defaults, or None for one of ARRIVALS or none at all."""
    if arrival is None or arrival in ARRIVALS:
        return None
    return f"--arrival must be one of {', '.join(ARRIVALS)}, not {arrival!r}"


def stamp_onboarding(target: Path, arrival: str) -> str:
    """Put the First wake checklist under the local prompt's title; OSError when it cannot be written."""
    prompt = Path(target) / LOCAL_PROMPT_REL
    if not prompt.is_file():
        logger.warning("[spawn] %s has no %s, First wake not stamped", target, LOCAL_PROMPT_REL)
        return f"not stamped: the template rendered no {LOCAL_PROMPT_REL}"
    block = (PROJECT_TEMPLATE_DIR / f"onboarding_{arrival}.md").read_text(encoding="utf-8")
    title, newline, rest = prompt.read_text(encoding="utf-8").partition("\n")
    atomic_write_text(prompt, f"{title}{newline}\n{block}{rest}")
    json_handler.log_operation("first_wake_stamped", data={"prompt": str(prompt), "arrival": arrival})
    return f"stamped ({arrival})"


def stamp_updateignore(project_root: Path, arrival: str) -> str:
    """Stamp the default .updateignore unless the owner wrote a row; a header-only file keeps its text above it."""
    path = Path(project_root) / IGNORE_NAME
    try:
        rows = read_ignore(project_root)
    except UpdateIgnoreUnreadable as exc:
        return f"kept: {exc}"
    if rows:
        logger.info("[spawn] %s already has %d row(s), the owner's: default not stamped", path, len(rows))
        return f"kept: the owner's {len(rows)} row(s)"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    default = (PROJECT_TEMPLATE_DIR / f"updateignore_{arrival}").read_text(encoding="utf-8")
    atomic_write_text(path, f"{existing.rstrip()}\n\n{default}" if existing.strip() else default)
    json_handler.log_operation("updateignore_stamped", data={"path": str(path), "arrival": arrival})
    return f"stamped ({arrival})"


def stamp_test_policy(project_root: Path) -> str:
    """Stamp the project's test-write policy (off, named) unless a policy file is already there."""
    path = Path(project_root) / TEST_POLICY_REL
    if path.exists():
        logger.info("[spawn] %s already exists, the owner's: policy not stamped", path)
        return "kept: the owner's file"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, (PROJECT_TEMPLATE_DIR / TEST_POLICY_REL.name).read_text(encoding="utf-8"))
    json_handler.log_operation("test_policy_stamped", data={"path": str(path)})
    return "stamped (off)"
