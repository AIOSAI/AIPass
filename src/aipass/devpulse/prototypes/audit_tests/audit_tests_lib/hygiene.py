# =================== AIPass ====================
# Name: hygiene.py - the execution tier's one scored group
# Description: runs the suite inside the copy under the audit hook, reads the log
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""Run the target's suite inside the scratch copy and read the gate's log.

The suite is invoked *the way that branch's own agent invokes it* -- one branch,
one path argument, so pytest's rootdir lands on the branch's own ``pytest.ini``.
This is not a detail.  ``wave2_verification.md`` §4a measured a multi-branch
invocation relocating rootdir, loading the repo-root forgery guard, and reporting
**0** writes where the real single-branch workflow forges **31**.  A gate that
measures a configuration nobody uses is worse than no gate.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .logsetup import logger
from .envcopy import EnvSpec

_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped|xfailed|xpassed|deselected)")


@dataclass
class HygieneRun:
    """Everything one gated suite run produced."""

    returncode: int = -1
    timed_out: bool = False
    stdout_tail: str = ""
    header: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    violations: list[dict] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    command: list[str] = field(default_factory=list)


def build_command(spec: EnvSpec, plugin_name: str, extra: list[str] | None = None) -> list[str]:
    """The pytest invocation, with the flags the harness checklist requires."""
    return [
        str(spec.python),
        "-B",  # checklist #2: no bytecode written under the copy
        "-m",
        "pytest",
        spec.test_arg,
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
        "-p",
        plugin_name,
        *(extra or []),
    ]


def build_env(spec: EnvSpec, tmpdir_allowed: bool, disable_hook: bool) -> dict[str, str]:
    """Child environment: inherit, then override only what the probe needs.

    Harness-integrity check #4 -- a pinned ``PATH`` once hid ``~/.local/bin``
    where ``drone`` lives and three probes were discarded over it.
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = spec.pythonpath + (os.pathsep + existing if existing else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["AUDIT_TESTS_LOG"] = str(spec.log_path)
    env["AUDIT_TESTS_ENV_ROOT"] = str(spec.env_root)
    env["AUDIT_TESTS_TARGET_ROOT"] = str(spec.target_copy)
    env["AUDIT_TESTS_TARGET_MODULE"] = spec.target_module
    env["AUDIT_TESTS_TMPDIR_ALLOWED"] = "1" if tmpdir_allowed else "0"
    if disable_hook:
        env["AUDIT_TESTS_DISABLE_HOOK"] = "1"
    else:
        env.pop("AUDIT_TESTS_DISABLE_HOOK", None)
    return env


def parse_counts(stdout: str) -> dict[str, int]:
    """Pull pytest's own tallies out of the ``-q`` summary line."""
    counts: dict[str, int] = {}
    for line in reversed([ln for ln in stdout.splitlines() if ln.strip()]):
        matches = _COUNT_RE.findall(line)
        if matches:
            for number, word in matches:
                counts[word.rstrip("s") if word == "errors" else word] = int(number)
            break
    return counts


def _parse_line(line: str) -> dict | None:
    """One JSONL line, or ``None`` if it did not survive the write."""
    try:
        return json.loads(line)
    except json.JSONDecodeError as exc:
        logger.debug("unparseable gate log line", exc_info=exc)
        return None


def read_log(path: Path) -> tuple[dict, dict, list[dict]]:
    """Split the plugin's JSONL into ``(header, summary, violations)``.

    A truncated final line is counted rather than dropped: the gate's log is
    evidence, and evidence that quietly loses records is the failure mode this
    whole lane exists to catch.
    """
    header: dict = {}
    summary: dict = {}
    violations: list[dict] = []
    unparseable = 0
    if not path.is_file():
        return header, summary, violations
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        record = _parse_line(line)
        if record is None:
            unparseable += 1
            continue
        kind = record.get("rec")
        if kind == "header":
            header = record
        elif kind == "summary":
            summary = record
        elif kind == "violation":
            violations.append(record)
    if unparseable:
        summary = {**summary, "unparseable_log_lines": unparseable}
    return header, summary, violations


def run(
    spec: EnvSpec,
    plugin_name: str,
    timeout: int,
    tmpdir_allowed: bool = True,
    disable_hook: bool = False,
    extra_args: list[str] | None = None,
) -> HygieneRun:
    """Execute the gated suite and return what came back."""
    command = build_command(spec, plugin_name, extra_args)
    env = build_env(spec, tmpdir_allowed, disable_hook)
    result_out, code, timed_out = "", -1, False
    try:
        completed = subprocess.run(
            command,
            cwd=str(spec.run_cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        result_out, code = completed.stdout + completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        logger.debug("suite exceeded %ss", timeout, exc_info=exc)
        timed_out = True
        partial = exc.stdout or ""
        result_out = partial.decode("utf-8", "replace") if isinstance(partial, bytes) else partial
    header, summary, violations = read_log(spec.log_path)
    return HygieneRun(
        returncode=code,
        timed_out=timed_out,
        stdout_tail="\n".join(result_out.splitlines()[-40:]),
        header=header,
        summary=summary,
        violations=violations,
        counts=parse_counts(result_out),
        command=command,
    )
