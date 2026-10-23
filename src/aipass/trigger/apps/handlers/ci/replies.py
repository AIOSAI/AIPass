# =================== AIPass ====================
# Name: replies.py
# Description: CI red lane reply contracts - owner and seedgo reply parsers, the two briefs, the CHANGELOG insert
# Version: 1.0.0
# Created: 2026-10-22
# Modified: 2026-10-22
# =============================================

"""
CI Replies Handler - the shapes the owner and @seedgo answer in, and the briefs that ask for them
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from aipass.trigger.apps.handlers.json import json_handler

OWNER_LABELS = ("FILES", "CHANGELOG", "NOTE")
_LABEL = re.compile(r"^\s*(FILES|CHANGELOG|NOTE):\s*(.*)$")
_VERDICT = re.compile(r"^\s*VERDICT:\s*(OK|HELD)\s*$")
_UNRELEASED = re.compile(r"^##\s*\[?Unreleased\]?\s*$", re.IGNORECASE)


def parse_owner_reply(text: str) -> Dict[str, Any]:
    """Split an owner reply into files, changelog and note; `files` is None when no FILES: block exists."""
    blocks: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for line in text.splitlines():
        label = _LABEL.match(line)
        if label:
            name = label.group(1)
            blocks[name] = [label.group(2)] if label.group(2).strip() else []
            current = name
        elif current:
            blocks[current].append(line)
    files = None
    if "FILES" in blocks:
        files = [p.strip().lstrip("-* ").strip() for p in blocks["FILES"] if p.strip()]
    changelog = next((line.strip() for line in blocks.get("CHANGELOG", []) if line.strip()), "")
    if changelog and not changelog.startswith("- "):
        changelog = f"- {changelog.lstrip('-* ').strip()}"
    reply = {"files": files, "changelog": changelog, "note": "\n".join(blocks.get("NOTE", [])).strip()}
    json_handler.log_operation("ci_owner_reply_parsed", {"files": len(files or []), "has_files": files is not None})
    return reply


def parse_verdict(text: str) -> Optional[Dict[str, str]]:
    """Read seedgo's reply: None unless the first non-blank line is `VERDICT: OK` or `VERDICT: HELD`."""
    lines = text.strip().splitlines()
    match = _VERDICT.match(lines[0]) if lines else None
    if not match:
        return None
    rest = "\n".join(lines[1:]).strip()
    json_handler.log_operation("ci_verdict_parsed", {"verdict": match.group(1)})
    return {"verdict": match.group(1), "body": rest}


def outside_owner_tree(files: List[str], owner: str) -> List[str]:
    """Paths the cure door will refuse: not under src/aipass/<owner>/ and not CHANGELOG.md."""
    prefix = f"src/aipass/{owner}/"
    return [p for p in files if not (p.startswith(prefix) or p == "CHANGELOG.md") or ".." in p.split("/")]


def commit_message(owner: str, run_id: str, changelog: str, note: str) -> str:
    """The door's message: `fix(<owner>): <what>, run <id>`, the what taken from the bullet or the note."""
    source = changelog.lstrip("- ").strip() or note.strip() or "CI red cured"
    bold = re.match(r"\*\*(.+?)\*\*", source)
    what = (bold.group(1) if bold else source.splitlines()[0]).strip().rstrip(".")
    if len(what) > 72:
        what = what[:69].rstrip() + "..."
    return f"fix({owner}): {what}, run {run_id}"


def insert_changelog_bullet(changelog_text: str, bullet: str) -> Optional[str]:
    """CHANGELOG text with *bullet* first under Unreleased's `### Fixed`; None when there is no Unreleased."""
    lines = changelog_text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if _UNRELEASED.match(line.strip())), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    fixed = next((i for i in range(start + 1, end) if lines[i].strip() == "### Fixed"), None)
    if fixed is None:
        lines[start + 1 : start + 1] = ["\n", "### Fixed\n", "\n", f"{bullet}\n"]
    else:
        at = fixed + 1
        while at < end and not lines[at].strip():
            at += 1
        lines[at:at] = [f"{bullet}\n"]
    return "".join(lines)


def append_changelog(path: Path, bullet: str) -> Optional[str]:
    """Write *bullet* under Unreleased in the CHANGELOG at *path*; answers the text to restore, None if present."""
    original = path.read_text(encoding="utf-8")
    if bullet in original:
        return None
    updated = insert_changelog_bullet(original, bullet)
    if updated is None:
        raise ValueError(f"{path.name} has no Unreleased section")
    path.write_text(updated, encoding="utf-8")
    json_handler.log_operation("ci_changelog_appended", {"file": path.name})
    return original


def restore_changelog(path: Path, original: str) -> None:
    """Put the CHANGELOG back as it was before a cure the door did not push."""
    path.write_text(original, encoding="utf-8")
    json_handler.log_operation("ci_changelog_restored", {"file": path.name})


def owner_brief(payload: Dict[str, Any]) -> str:
    """The dispatch body for the branch that owns the red."""
    owner, run_id = payload["owner"], payload["run_id"]
    failing = "\n".join(f"  {line}" for line in payload.get("lines", [])) or "  (no failing lines captured)"
    return f"""CI is red on dev and the failure is yours. Cure it in your own tree.

Run: {run_id}
Workflow: {payload.get("workflow", "")}
Step: {payload.get("step", "")}
URL: {payload.get("url", "") or "(not resolved)"}

Failing lines:
{failing}

You have no git. Do not commit, push or open a PR: @trigger takes your files through
@seedgo's review and pushes the cure through drone's ci-cure door.

1. Medic-mute yourself before editing: drone @trigger medic mute @{owner}
2. Cure the cause in src/aipass/{owner}/ only; run your tests and drone @seedgo audit aipass @{owner}.
3. Reply to THIS mail (drone @ai_mail reply <this mail's id> "...") in exactly this shape,
   each label on its own line:

FILES:
src/aipass/{owner}/path/one.py
src/aipass/{owner}/tests/test_one.py
CHANGELOG:
- **One line for Unreleased: what was wrong and what is right now** (@{owner}; files and versions)
NOTE:
What was wrong and why this cure addresses the cause rather than the symptom.

A reply with no FILES: block holds the run: nothing is pushed and @devpulse gets the reason.
"""


def seedgo_brief(cure: Dict[str, Any]) -> str:
    """The dispatch body for @seedgo's one review of a cure."""
    failing = "\n".join(f"  {line}" for line in cure.get("lines", [])) or "  (no failing lines captured)"
    files = "\n".join(f"  {path}" for path in cure.get("files", []))
    return f"""Review a CI cure before @trigger pushes it.

Run: {cure["run_id"]}  Owner: @{cure["owner"]}
Workflow: {cure.get("workflow", "")}  Step: {cure.get("step", "")}
URL: {cure.get("url", "") or "(not resolved)"}

Failing lines:
{failing}

Files:
{files}

Owner's note:
{cure.get("note", "") or "(none)"}

Diff:
{cure.get("diff", "") or "(empty: new files do not show in drone @git diff)"}

Answer two things:
1. Does the cure address the cause or silence the symptom? Run the owner's tests and
   drone @seedgo audit aipass @{cure["owner"]} as part of the answer.
2. What does the checker learn from this red?

Reply to THIS mail (drone @ai_mail reply <this mail's id> "...") with the first line exactly
VERDICT: OK
or
VERDICT: HELD
then the reason (on HELD), then the checker lesson. Do not edit the owner's files.
"""
