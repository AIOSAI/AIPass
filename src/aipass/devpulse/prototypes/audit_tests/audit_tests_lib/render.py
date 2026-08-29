# =================== AIPass ====================
# Name: render.py - the terminal summary
# Description: plain-text report; per-group only, never one number
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""Render the artifact as plain text.

No external dependency, and no single number -- Law S2 applies to what a human
reads as much as to what a machine parses, because the number a human quotes is
the one that ends up in a report.
"""

from __future__ import annotations

RULE = "-" * 78
MAX_SHOWN = 12


def render(document: dict) -> str:
    """The terminal report: per group, never a single number across them (Law S2)."""
    lines: list[str] = [RULE, f"audit-tests (MVP prototype) - {document['target'].get('name', '?')}", RULE]
    target = document["target"]
    lines += [
        f"  target      {target.get('path', '?')}",
        f"  copy        {target.get('copy', '?')}",
        f"  test files  {target.get('test_files', '?')}",
        f"  cache       {document['cache']}",
        f"  status      {document['status'].upper()}",
        "",
    ]

    if document["status"] == "refused":
        refusal = document["refusal"] or {}
        lines += [
            "REFUSED - nothing was published.",
            f"  reason  {refusal.get('reason', '?')}",
        ]
        for detail in refusal.get("detail", []):
            lines.append(f"          {detail}")
        lines += ["", _harness_block(document), RULE]
        return "\n".join(lines)

    lines += _groups_block(document)
    lines += ["", _harness_block(document), RULE]
    return "\n".join(lines)


def _groups_block(document: dict) -> list[str]:
    """One line per group in the closed list, including the ones not built."""
    lines = ["GROUPS (per-group only; there is deliberately no overall figure)", ""]
    for name, group in document["groups"].items():
        status = group["status"]
        if status != "measured":
            lines.append(f"  {name:<20} {status:<16} {group.get('reason', '')}")
            continue
        if "score" in group:
            verdict = "PASS" if group.get("passed") else "FAIL"
            lines.append(f"  {name:<20} SCORED {group['score']:>3}      {verdict}")
        else:
            lines.append(f"  {name:<20} nominated        {group.get('nomination_count', 0)} suspect(s), unconvicted")
    lines.append("")

    hygiene = document["groups"]["hygiene"]
    if hygiene["status"] == "measured":
        lines += _hygiene_detail(hygiene)
    for name in ("static_ruff_pt", "static_self_skip", "static_mock_drift"):
        group = document["groups"][name]
        if group["status"] == "measured" and group.get("nomination_count"):
            lines += _nomination_detail(name, group)
    return lines


def _hygiene_detail(group: dict) -> list[str]:
    """The convicted nodeids and the paths they wrote, capped for the terminal."""
    violations = group.get("violations", [])
    if not violations:
        lines = ["  hygiene: no write left the sandbox.", ""]
    else:
        lines = [f"  hygiene: {len(violations)} distinct out-of-sandbox write(s)", ""]
        for item in violations[:MAX_SHOWN]:
            escape = "  [escapes the copy via symlink]" if item.get("escapes_copy_via_symlink") else ""
            lines.append(f"    {item['nodeid']}")
            lines.append(f"      {item['event']:<16} {item['where']:<13} {item['path']}{escape}")
        if len(violations) > MAX_SHOWN:
            lines.append(f"    ... {len(violations) - MAX_SHOWN} more, all in the artifact")
        lines.append("")
    tmp = group.get("tmpdir_writes", 0)
    if tmp:
        lines.append(f"  informational: {tmp} write(s) inside TMPDIR, allowed by the declared sandbox")
        lines.append("")
    return lines


def _nomination_detail(name: str, group: dict) -> list[str]:
    """A few suspects from a nominating group, labelled as unconvicted."""
    lines = [f"  {name}: {group['nomination_count']} nominated (unconvicted)"]
    for item in group.get("nominations", [])[:MAX_SHOWN]:
        label = item.get("species") or item.get("code", "")
        detail = item.get("detail") or item.get("message", "")
        lines.append(f"    {item.get('file', '?')}:{item.get('line', 0)}  {label}  {detail}")
    if group["nomination_count"] > MAX_SHOWN:
        lines.append(f"    ... {group['nomination_count'] - MAX_SHOWN} more, all in the artifact")
    lines.append("")
    return lines


def _harness_block(document: dict) -> str:
    """What the harness proved about itself: canary, copy liveness, baseline."""
    harness = document["harness"]
    suite = harness.get("suite", {})
    tree = harness.get("real_target_tree", {})
    lines = [
        "HARNESS SELF-REPORT (the checker's own verdict on itself)",
        f"  hook installed        {harness.get('hook_installed')}",
        f"  canary caught         {harness.get('canary_caught')}",
        f"  copy verified live    {harness.get('copy_verified_live')}  ({harness.get('copy_resolved_to', '')})",
        f"  suite counts          {suite.get('counts')}  exit={suite.get('returncode')}",
        f"  baseline passed       {suite.get('baseline_passed')}  matches={suite.get('matches_baseline')}",
        f"  real tree unchanged   {tree.get('unchanged')}",
        f"  allowances            {', '.join(a['name'] for a in harness.get('allowances', []))}",
    ]
    return "\n".join(lines)
