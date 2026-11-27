# =================== AIPass ====================
# Name: cloud.py
# Description: The cloud dispatch lane: start a Claude Code cloud session, record it on the mail, poll for its PR
# Version: 1.1.2
# Created: 2026-11-26
# Modified: 2026-11-26
# =============================================

"""
The cloud dispatch lane (provider "cloud").

wake.py builds the start command, dispatch_monitor.py runs run() in the same systemd-scope
monitor every local lane uses. The result is a PR, found by a drone @git pr list read with
the mail id as marker; the wake-back is mail written here, since the VM's mailbox dies with it.
Reference: docs/wake_providers.md
"""

import json
import os
import re
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.email.inbox_lock import inbox_lock

CLOUD = "cloud"
ENV_ID_KEY = "cloud_environment_id"
POLL_KEY = "cloud_poll_seconds"
CEILING_KEY = "cloud_ceiling_seconds"
CONFIG_DEFAULTS = {POLL_KEY: 180, CEILING_KEY: 4 * 3600}
START_TIMEOUT = 300
# The monitor's exit codes: the start output held no session id; the poll could not read pr list.
START_FAILED = -8
POLL_FAILED = -9
# The URL anywhere in the output: a pty may colour the label, a CLI release may rename it.
SESSION_URL = re.compile(r"(https://claude\.ai/code/([A-Za-z0-9_-]+)[^\s\x1b]*)")
MAX_FAILED_READS = 5
# script -c takes the brief as one argv string; the kernel caps one at 128 KiB.
MAX_BODY_BYTES = 64_000
BODY_LINES = 12
RESULT_KEYS = ("number", "head", "head_sha", "url", "state", "ci")

FOOTER = (
    "\n\n---\nYou are {target} in a Claude Code cloud VM, at the clone root. First run `drone {target} --help`; if "
    "AIPass is not installed, open the PR anyway with the setup output in the body. Do the task above. "
    "Open exactly one PR with base dev from your harness branch. The PR body starts with the line "
    "`dispatch: {mail_id}` and ends with your report. No mail, no dispatch, no git commands: the "
    "harness's GitHub tools are the route. Touched test files only, no full suite."
)


def run_cli(cmd: List[str], cwd: Optional[str] = None, env: Optional[dict] = None, timeout: int = 60):
    """Run one argv, never a shell string; the one process edge of this lane."""
    return subprocess.run(
        cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout
    )


def environment_id(branch_path: Path) -> Tuple[str, str]:
    """The citizen's hosted environment id from its passport, or ("", why it cannot be used)."""
    passport_file = branch_path / ".trinity" / "passport.json"
    try:
        passport = json.loads(passport_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return "", f"its passport {passport_file} could not be read ({e})"
    env_id = (passport.get("citizenship") or {}).get(ENV_ID_KEY) if isinstance(passport, dict) else None
    if not isinstance(env_id, str) or not env_id.strip():
        return "", f"its passport has no citizenship.{ENV_ID_KEY}; the cloud lane never falls back to a local wake"
    return env_id.strip(), ""


def drone_json(args: List[str], cwd: Path) -> Tuple[object, str]:
    """A drone read's --json answer, or (None, why it could not be read)."""
    try:
        result = run_cli(["drone", *args], cwd=str(cwd))
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"drone {' '.join(args)} could not run ({e})"
    if result.returncode != 0:
        return (
            None,
            f"drone {' '.join(args)} exited {result.returncode}: {(result.stderr or result.stdout).strip()[:200]}",
        )
    try:
        return json.loads(result.stdout), ""
    except json.JSONDecodeError as e:
        return None, f"drone {' '.join(args)} answered no JSON ({e})"


def ahead_refusal(branch_path: Path) -> str:
    """Why local dev cannot be cloned as it stands, or "": the session clones origin/dev from GitHub."""
    status, why = drone_json(["@git", "status", "--all", "--json"], branch_path)
    if not isinstance(status, dict):
        return f"cannot tell whether local dev is ahead of origin/dev: {why or 'the answer is not an object'}"
    if status.get("upstream") != "origin/dev":
        return f"the checkout tracks {status.get('upstream')!r}, not origin/dev; the cloud session clones dev"
    ahead = status.get("ahead")
    if not isinstance(ahead, int):
        return f"cannot tell whether local dev is ahead of origin/dev: ahead is {ahead!r}"
    if ahead > 0:
        return f"local dev is {ahead} commit(s) ahead of origin/dev; the cloud session would not see them, push first"
    return ""


def start_refusal(branch_path: Path) -> str:
    """Why a cloud dispatch to this branch is refused before any mail is sent, or ""."""
    json_handler.log_operation("cloud_start_refusal", {"branch": str(branch_path)})
    _, refusal = environment_id(branch_path)
    return refusal or ahead_refusal(branch_path)


def dispatch_refusal(target: str, admin: bool, local_flags: List[str], body: str = "") -> Tuple[bool, str]:
    """(True, "") when `dispatch --cloud` may send to target, else (False, why), decided before any mail.

    local_flags are the local-wake flags the caller was given: they have no meaning in a cloud session.
    """
    from aipass.ai_mail.apps.handlers.dispatch.wake import resolve_branch
    from aipass.ai_mail.apps.handlers.registry.read import RegistryUnreadable

    if local_flags:
        return False, f"{', '.join(local_flags)} apply to local wakes, not --cloud"
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        return False, "cloud briefs are limited to 64 KB; put the log in the repo and name the path"
    try:
        resolved = resolve_branch(target, admin=admin)
    except RegistryUnreadable as e:
        return False, f"the registry is unreadable ({e})"
    if resolved is None:
        return False, f"unknown agent {target}"
    refusal = start_refusal(resolved[0])
    return (False, f"{resolved[1]} cannot work in the cloud: {refusal}") if refusal else (True, "")


def brief(body: str, target: str, mail_id: str) -> str:
    """The session's prompt: the mail body as written, then ai_mail's fixed footer."""
    return body + FOOTER.format(target=target, mail_id=mail_id)


def start_cmd(script_bin: str, claude_bin: str, env_id: str, prompt: str, log: str) -> List[str]:
    """`script -qfec <one command> <log>`: claude --cloud refuses without a terminal, script gives it one.

    script needs ONE command string, so it is shlex.join of the argv: a $WORD in the body stays literal.
    """
    settings = json.dumps({"remote": {"defaultEnvironmentId": env_id}})
    return [script_bin, "-qfec", shlex.join([claude_bin, "--cloud", prompt, "--settings", settings]), log]


def parse_view(text: str) -> Optional[Tuple[str, str]]:
    """(session_id, url) from the first https://claude.ai/code/<id>?... in the start output, or None."""
    match = SESSION_URL.search(text or "")
    return (match.group(2), match.group(1)) if match else None


def _edit_mail(inbox_file: Path, pick: Callable[[List[dict]], Optional[dict]], fields: dict) -> Optional[dict]:
    """Merge fields into the picked mail's cloud block, under the inbox lock; the edited mail, or None if none picked.

    An unreadable inbox raises (OSError, ValueError): the caller decides what a lost record costs.
    """
    with inbox_lock(inbox_file):
        data = json.loads(inbox_file.read_text(encoding="utf-8"))
        mail = pick(data.get("messages", []))
        if mail is None:
            return None
        mail["cloud"] = {**(mail.get("cloud") or {}), **fields}
        inbox_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return mail


def mark_requested(inbox_file: Path, subject: str) -> Optional[str]:
    """Tag the newest unmarked dispatch mail with this subject as a cloud request; its id, or None if none matches.

    Raises OSError or ValueError when the inbox cannot be read or written.
    """
    mail = _edit_mail(
        inbox_file,
        lambda messages: next(
            (
                m
                for m in messages
                if isinstance(m, dict) and m.get("auto_execute") and m.get("subject") == subject and "cloud" not in m
            ),
            None,
        ),
        {"requested": True},
    )
    return mail.get("id") if mail else None


def update_mail(inbox_file: Path, mail_id: str, **fields) -> str:
    """Record fields on this mail's cloud block through the inbox lock; "" when written, else why not."""
    try:
        mail = _edit_mail(
            inbox_file,
            lambda messages: next((m for m in messages if isinstance(m, dict) and m.get("id") == mail_id), None),
            fields,
        )
    except (OSError, ValueError) as e:
        logger.warning("[cloud] mail %s in %s not updated with %s: %s", mail_id, inbox_file, fields, e)
        return f"inbox {inbox_file} unwritable: {e}"
    return "" if mail else f"mail {mail_id} is no longer in {inbox_file}"


def find_open(inbox_file: Path) -> Optional[dict]:
    """The newest mail carrying a cloud session that is not closed, or None.

    Raises OSError or ValueError when the inbox cannot be read: unreadable is not "none open".
    """
    with inbox_lock(inbox_file):
        data = json.loads(inbox_file.read_text(encoding="utf-8"))
    for mail in data.get("messages", []):
        if isinstance(mail, dict) and (mail.get("cloud") or {}).get("session_id") and mail.get("status") != "closed":
            return mail
    return None


def steer_cmd(claude_bin: str, text: str, session_id: str) -> List[str]:
    """The steer argv: queue text into the running session; it never returns the reply."""
    return [claude_bin, "-p", text, "--cloud", session_id, "--output-format", "json"]


def steer(text: str, session_id: str) -> Tuple[bool, str]:
    """Send text to the cloud session: (True, "") when queued, else (False, why not)."""
    from aipass.ai_mail.apps.handlers.dispatch.wake import _find_bin

    json_handler.log_operation("cloud_steer", {"session_id": session_id})
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    queued = "; the text may still have been queued"
    try:
        # A paused VM restores before it answers: the start's timeout, not run_cli's 60 s.
        result = run_cli(steer_cmd(_find_bin("claude"), text, session_id), env=env, timeout=START_TIMEOUT)
    except OSError as e:
        return False, f"claude -p --cloud {session_id} could not run ({e})"
    except subprocess.SubprocessError as e:
        return False, f"claude -p --cloud {session_id} did not answer ({e}){queued}"
    said = (result.stderr or result.stdout).strip()[:200]
    try:
        answer = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return False, f"claude -p --cloud {session_id} exited {result.returncode} with no JSON ({e}): {said}{queued}"
    if result.returncode != 0 or not (isinstance(answer, dict) and answer.get("ok")):
        return False, f"claude -p --cloud {session_id} exited {result.returncode} without ok: {said}{queued}"
    return True, ""


def pr_rows(mail_id: str, cwd: Path) -> Tuple[Optional[List[dict]], str]:
    """(the PRs in any state and on any base whose body carries this mail id, head claude/, ""), or (None, why)."""
    rows, why = drone_json(
        ["@git", "pr", "list", "--head", "claude/", "--marker", mail_id, "--state", "all", "--json"], cwd
    )
    if not isinstance(rows, list):
        why = why or f"drone @git pr list answered {rows!r}, not a list"
        logger.warning("[cloud] pr list for %s unreadable, next poll retries: %s", mail_id, why)
        return None, why
    return [r for r in rows if isinstance(r, dict) and str(r.get("head", "")).startswith("claude/")], ""


def pr_body_head(number: object, cwd: Path) -> str:
    """The first lines `drone @git pr view <#>` prints, or why there are none."""
    try:
        result = run_cli(["drone", "@git", "pr", "view", str(number)], cwd=str(cwd))
    except (OSError, subprocess.SubprocessError) as e:
        return f"(pr view {number} could not run: {e})"
    if result.returncode != 0:
        return f"(pr view {number} exited {result.returncode})"
    return "\n".join(result.stdout.splitlines()[:BODY_LINES])


def wake_back_mail(target: str, mail_id: str, row: dict, url: str, body_head: str) -> Tuple[str, str]:
    """(subject, body) of the result mail: one PR the session opened or pushed."""
    number = row.get("number")
    subject = f"Cloud dispatch result: {target} PR #{number} (ci {row.get('ci')})"
    body = (
        f"{target}'s cloud session answered mail {mail_id} with PR #{number}: {row.get('title')}\n"
        f"PR: #{number} {row.get('url') or ''} (read it: drone @git pr view {number})\n"
        f"Head: {row.get('head')} -> {row.get('base')} · state {row.get('state')} · CI {row.get('ci')}\n"
        f"Session: {url}\n"
        f'Steer it: drone @ai_mail email {target} "text" --cloud\n\n'
        f"Body (first lines):\n{body_head}"
    )
    return subject, body


def timeout_mail(target: str, mail_id: str, url: str, ceiling: int, failed: int, reads: int) -> Tuple[str, str]:
    """(subject, body) of the ceiling mail: no PR came; the dispatch mail stays open."""
    subject = f"Cloud dispatch timeout: {target}, no PR after {ceiling // 60} min"
    body = (
        f"{target}'s cloud session for mail {mail_id} opened no PR with `dispatch: {mail_id}` in "
        f"{ceiling // 60} minutes; the poll has stopped and the mail stays open.\n"
        f"{failed} of the {reads} pr list reads failed.\n"
        f"Session: {url}\n"
        f'Steer it: drone @ai_mail email {target} "text" --cloud (nobody polls for its PR now)'
    )
    return subject, body


def failed_mail(target: str, mail_id: str, url: str, why: str) -> Tuple[str, str]:
    """(subject, body) of the mail when pr list could not be read MAX_FAILED_READS times in a row."""
    subject = f"Cloud dispatch failed: {target}, pr list unreadable"
    body = (
        f"{MAX_FAILED_READS} drone @git pr list reads in a row failed, so the poll for mail {mail_id} has stopped; "
        f"{target}'s session may still open a PR and the mail stays open.\nLast error: {why}\n"
        f"Session: {url}\n"
        f'Steer it: drone @ai_mail email {target} "text" --cloud (nobody polls for its PR now)'
    )
    return subject, body


def _is_new(row: dict, reported: Dict[object, dict]) -> bool:
    """A PR number not yet reported, or a new head sha on one that was (a push after a steer)."""
    old = reported.get(row.get("number"))
    return old is None or old.get("head_sha") != row.get("head_sha")


def _poll(
    cfg: dict, cwd: Path, target: str, url: str, inbox_file: Path, mail: Callable[[str, str], bool]
) -> Tuple[List[dict], str, dict]:
    """Poll until the ceiling, mailing every new PR; (the PRs reported, why the poll ended, the read counts)."""
    mail_id, deadline = cfg["mail"], time.time() + cfg["ceiling"]
    reported: Dict[object, dict] = {}
    reads = {"reads": 0, "failed": 0, "in_a_row": 0, "why": ""}
    while time.time() < deadline:
        time.sleep(cfg["poll"])
        rows, why = pr_rows(mail_id, cwd)
        reads["reads"] += 1
        if rows is None:
            reads.update(failed=reads["failed"] + 1, in_a_row=reads["in_a_row"] + 1, why=why)
            if reads["in_a_row"] >= MAX_FAILED_READS:
                return list(reported.values()), "pr list failed", reads
            continue
        reads["in_a_row"] = 0
        for row in (r for r in rows if _is_new(r, reported)):
            reported[row.get("number")] = row
            row["mailed"] = mail(*wake_back_mail(target, mail_id, row, url, pr_body_head(row.get("number"), cwd)))
            if not row["mailed"]:
                logger.warning("[cloud] result mail for %s PR #%s NOT delivered", mail_id, row.get("number"))
            results = [{k: r.get(k) for k in RESULT_KEYS} for r in reported.values()]
            update_mail(inbox_file, mail_id, done=True, results=results)
        # New rows are mailed first: a PR opened and merged between two reads still gets its mail.
        if reported and all(r.get("state") != "OPEN" for r in rows):
            return list(reported.values()), "closed", reads
    return list(reported.values()), "ceiling", reads


def run(
    cmd: List[str],
    cwd: Path,
    env: dict,
    cfg: dict,
    target: str,
    inbox_file: Path,
    mail: Callable[[str, str], bool],
    started: Callable[[], None],
) -> dict:
    """Start the session, record it on the mail, poll for its PR; the monitor's outcome fields.

    cfg is {"mail", "poll", "ceiling"}; mail(subject, body) sends to the dispatcher and says whether it went;
    started() runs once the session is on the mail: nothing runs locally after that, so the lock can go.
    """
    json_handler.log_operation("cloud_run", {"target": target, "mail": cfg.get("mail")})
    log = Path(cmd[-1])
    try:
        run_cli(cmd, cwd=str(cwd), env=env, timeout=START_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("[cloud] %s start did not finish cleanly, reading its log: %s", target, e)
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.warning("[cloud] %s start log %s unreadable: %s", target, log, e)
        text = f"(start log {log} unreadable: {e})"
    view = parse_view(text)
    if view is None:
        tail = "\n".join(text.strip().splitlines()[-10:])
        sent = mail(
            f"Cloud dispatch refused: {target}",
            f"The cloud start for mail {cfg['mail']}: no session id found in the start output; a session may "
            f"still exist, check claude.ai/code. Nothing ran locally.\n\nStart output (last lines):\n{tail}",
        )
        logger.warning("[cloud] %s start output holds no session id — refused", target)
        return {
            "exit_code": START_FAILED,
            "status": "REFUSED (no session id in the cloud start output)",
            "wake_result": "mailed_refusal" if sent else "failed_refusal_mail",
            "run_line": "run: cloud · no session",
        }
    session_id, url = view
    update_mail(
        inbox_file, cfg["mail"], session_id=session_id, url=url, started=datetime.now().astimezone().isoformat()
    )
    logger.info("[cloud] %s session %s started for mail %s: %s", target, session_id, cfg["mail"], url)
    started()
    reported, ended, reads = _poll(cfg, cwd, target, url, inbox_file, mail)
    update_mail(inbox_file, cfg["mail"], ended=ended)
    run_line = f"run: cloud · session {url}"
    if reported:
        numbers = ", ".join(f"#{r.get('number')}" for r in reported)
        return {
            "exit_code": 0,
            "status": f"completed (cloud PR {numbers})",
            "wake_result": "mailed" if all(r["mailed"] for r in reported) else "failed_result_mail",
            "run_line": run_line,
        }
    if ended == "pr list failed":
        sent = mail(*failed_mail(target, cfg["mail"], url, reads["why"]))
        return {
            "exit_code": POLL_FAILED,
            "status": f"FAILED (pr list failed {MAX_FAILED_READS} times in a row: {reads['why']})",
            "wake_result": "mailed_failure" if sent else "failed_failure_mail",
            "run_line": run_line,
        }
    sent = mail(*timeout_mail(target, cfg["mail"], url, cfg["ceiling"], reads["failed"], reads["reads"]))
    return {
        "exit_code": 0,
        "status": f"TIMEOUT (cloud, no PR in {cfg['ceiling']}s)",
        "wake_result": "mailed_timeout" if sent else "failed_timeout_mail",
        "run_line": run_line,
    }
