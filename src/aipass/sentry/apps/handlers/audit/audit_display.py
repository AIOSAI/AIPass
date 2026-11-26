# =================== AIPass ====================
# Name: audit_display.py
# Description: Audit Display Module
# Version: 1.7.3
# Created: 2026-03-05
# Modified: 2026-11-26
# =============================================

"""
Audit Display Module
"""

from typing import List, Dict
from collections import defaultdict

from aipass.cli import console, warning

from aipass.sentry.apps.handlers.audit.discovery import DEFAULT_PACK_CORPUS
from aipass.sentry.apps.handlers.json import json_handler


def print_introspection() -> None:
    """Display module info and connected handlers."""
    console.print()
    console.print("[bold cyan]audit_display Module[/bold cyan]")
    console.print("Formats and prints audit results to console (branch summaries, system summaries, bypass audits)")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [dim]None — this is a pure display module with no handler imports[/dim]")
    console.print()

    console.print("[yellow]Public API:[/yellow]")
    console.print("  [dim]- print_branch_summary(audit_result, no_bypass, group)[/dim]")
    console.print("  [dim]- print_system_summary(audit_results, no_bypass, group)[/dim]")
    console.print("  [dim]- group_names(audit_results)[/dim]")
    console.print()

    console.print("[yellow]External Dependencies:[/yellow]")
    console.print("  [dim]- aipass.cli (console)[/dim]")
    console.print()

    console.print("[yellow]Consumed By:[/yellow]")
    console.print("  [dim]- modules/standards_audit.py (imports display functions)[/dim]")
    console.print()


def _format_standard_name(name: str) -> str:
    """Convert 'DEEP_NESTING' or 'deep_nesting' to 'Deep Nesting'."""
    return name.replace("_", " ").title()


def _render_violations(standard_name: str, violations: list, console_obj) -> None:
    """Generic renderer for standard violation lists, five shown, the rest counted."""
    console_obj.print()
    console_obj.print(f"  [bold red]{standard_name.upper()} VIOLATIONS ({len(violations)} files):[/bold red]")

    shown = violations[:5]
    for violation in shown:
        file_path = violation.get("path", violation.get("file", ""))
        score = violation.get("score", 0)
        # A path has no space to break at: wrapped, it leaves its cross alone on a line with no reason.
        console_obj.print(
            f"    [red]✗[/red] [magenta]{file_path}[/magenta] [dim](score: {score}%)[/dim]", soft_wrap=True
        )
        for issue in violation.get("issues", []):
            console_obj.print(f"      [dim]• {issue}[/dim]")
        if not violation.get("issues") and violation.get("message"):
            console_obj.print(f"      [dim]• {violation['message']}[/dim]")

    if len(violations) > 5:
        console_obj.print(f"    [dim]... and {len(violations) - 5} more[/dim]")


def _render_architecture_violations(audit_result: dict, console_obj) -> None:
    """Special renderer for architecture standard — reads from results['checks']."""
    results = audit_result.get("results", {})
    arch_result = results.get("architecture", {})
    checks = arch_result.get("checks", [])
    failed_checks = [c for c in checks if not c.get("passed", False)]

    if not failed_checks:
        return

    console_obj.print()
    console_obj.print(f"  [bold red]ARCHITECTURE VIOLATIONS ({len(failed_checks)} missing):[/bold red]")

    missing_dirs = [c for c in failed_checks if "Dir:" in c.get("name", "") or "Directory:" in c.get("name", "")]
    missing_files = [c for c in failed_checks if "File:" in c.get("name", "")]
    other_failures = [c for c in failed_checks if c not in missing_dirs and c not in missing_files]

    if missing_dirs:
        console_obj.print(f"       [dim]Missing directories ({len(missing_dirs)}):[/dim]")
        for check in missing_dirs[:5]:
            name = check.get("name", "").replace("Dir: ", "").replace("Directory: ", "")
            console_obj.print(f"         [red]✗[/red] {name}")
        if len(missing_dirs) > 5:
            console_obj.print(f"         [dim]... and {len(missing_dirs) - 5} more[/dim]")

    if missing_files:
        console_obj.print(f"       [dim]Missing files ({len(missing_files)}):[/dim]")
        for check in missing_files[:5]:
            name = check.get("name", "").replace("File: ", "")
            console_obj.print(f"         [red]✗[/red] {name}")
        if len(missing_files) > 5:
            console_obj.print(f"         [dim]... and {len(missing_files) - 5} more[/dim]")

    if other_failures:
        for check in other_failures:
            console_obj.print(f"         [dim]• {check.get('message', '')}[/dim]")


def _render_type_errors(audit_result: dict, console_obj) -> None:
    """Special renderer for type errors (pyright diagnostics) — different structure."""
    type_errors = audit_result.get("type_errors", 0)
    type_error_files = audit_result.get("type_error_files", [])
    files_checked = audit_result.get("files_checked", 0)

    if type_errors > 0:
        console_obj.print()
        console_obj.print(f"  [bold red]TYPE ERRORS ({type_errors} errors):[/bold red]")
        # Every cap announces itself: a silent cap reads as a short list, 'clean' for 'not shown'.
        failing = [f for f in type_error_files if f.get("errors", 0) > 0]
        for file_result in failing[:10]:
            console_obj.print(f"    [red]✗[/red] {file_result['file']} [dim]({file_result['errors']} errors)[/dim]")
            diagnostics = file_result.get("diagnostics", [])
            for diag in diagnostics[:3]:
                msg = diag.get("message", "")
                clipped = f"{msg[:60]}…" if len(msg) > 60 else msg
                console_obj.print(f"      [dim]L{diag.get('line', '?')}: {clipped}[/dim]")
            if len(diagnostics) > 3:
                console_obj.print(f"      [dim]... and {len(diagnostics) - 3} more in this file[/dim]")
        if len(failing) > 10:
            console_obj.print(f"    [dim]... and {len(failing) - 10} more files[/dim]")
    elif files_checked > 0:
        console_obj.print("  [green]✓[/green] No type errors")


def _render_test_map(audit_result: dict, console_obj) -> None:
    """Show custom function test coverage summary (informational, not scored)."""
    test_map = audit_result.get("test_map")
    if not test_map:
        return
    total = test_map.get("total_functions", 0)
    if total == 0:
        return
    tested = test_map.get("tested_functions", 0)
    branch_name = test_map.get("branch", "")
    console_obj.print(
        f"  [dim]Custom Test Opportunities: {total} public functions, {tested} tested."
        f" Run: drone @sentry test_map @{branch_name}[/dim]"
    )


def _render_info_lines(audit_result: dict, console_obj) -> None:
    """Show non-scored signpost lines from checkers, at 100% too: context, not failure."""
    for entry in audit_result.get("info_lines", []):
        message = entry.get("message", "")
        if message:
            console_obj.print(f"  [dim]ⓘ {message}[/dim]")


#: Cell states a checker may publish in a fleet row; an unknown state prints, never vanishes.
_FLEET_STATE_STYLE = {"over": "red", "error": "red", "absent": "dim", "under": ""}


def _fleet_rows(audit_results: List[Dict]) -> List[Dict]:
    """Every ``fleet_row`` the pack's checkers published, in the order audited.

    A generic channel: any checker returning ``{branch, title, cells, notes}`` gets a table.
    """
    rows = []
    for result in audit_results:
        for _standard, data in sorted(result.get("results", {}).items()):
            if not isinstance(data, dict):
                continue
            row = data.get("fleet_row")
            if isinstance(row, dict) and row.get("cells"):
                rows.append(row)
    return rows


def _fleet_columns(rows: List[Dict]) -> List[tuple]:
    """(label, cap) per column, first-seen order, cap from the first row that knows one."""
    caps: Dict[str, int | None] = {}
    for row in rows:
        for cell in row["cells"]:
            label = str(cell.get("label", ""))
            if caps.get(label) is None:
                caps[label] = cell.get("cap")
    return list(caps.items())


def _fleet_cell_text(cell: dict) -> str:
    """One cell's unpadded text — the number, or why there is not one."""
    state = str(cell.get("state", ""))
    if state == "absent":
        return "—"
    if state == "error":
        return "ERR"
    chars = cell.get("chars")
    return f"{chars:,}" if isinstance(chars, int) else "?"


def _render_fleet_table(audit_results: List[Dict], console_obj) -> None:
    """Print the fleet table a checker published, one row per branch.

    Padding sits inside the Rich markup, or style tags count as width; a bordered Table wraps at 80.
    """
    rows = _fleet_rows(audit_results)
    if not rows:
        return

    columns = _fleet_columns(rows)
    widths = [max(len(label), len(f"{cap:,}") if isinstance(cap, int) else 1, 6) + 1 for label, cap in columns]
    for row in rows:
        by_label = {str(cell.get("label", "")): cell for cell in row["cells"]}
        for index, (label, _cap) in enumerate(columns):
            cell = by_label.get(label)
            if cell is not None:
                widths[index] = max(widths[index], len(_fleet_cell_text(cell)) + 1)
    name_width = max([len("BRANCH"), *(len(str(row.get("branch", ""))) for row in rows)]) + 2

    console_obj.print()
    console_obj.print(f"[bold]{rows[0].get('title', 'FLEET TABLE')}[/bold]")
    console_obj.print(
        "[dim]cap on the line under each column · red = over cap · — = absent (not a violation) "
        "· ERR = a cap or a file could not be read[/dim]"
    )
    head = "".join(f"{label:>{widths[i]}}" for i, (label, _cap) in enumerate(columns))
    caps = "".join(
        f"{(f'{cap:,}' if isinstance(cap, int) else '?'):>{widths[i]}}" for i, (_label, cap) in enumerate(columns)
    )
    console_obj.print(f"[bold]{'BRANCH':<{name_width}}{head}[/bold]")
    console_obj.print(f"[dim]{'cap':<{name_width}}{caps}[/dim]")
    console_obj.print(f"[dim]{'─' * (name_width + sum(widths))}[/dim]")

    for row in rows:
        by_label = {str(cell.get("label", "")): cell for cell in row["cells"]}
        line = f"[cyan]{str(row.get('branch', '')):<{name_width}}[/cyan]"
        for index, (label, _cap) in enumerate(columns):
            cell = by_label.get(label)
            if cell is None:
                line += f"{'':>{widths[index]}}"
                continue
            text = f"{_fleet_cell_text(cell):>{widths[index]}}"
            style = _FLEET_STATE_STYLE.get(str(cell.get("state", "")), "yellow")
            line += f"[{style}]{text}[/{style}]" if style else text
        console_obj.print(line)

    for row in rows:
        for note in row.get("notes", []):
            console_obj.print(f"  [yellow]⚠[/yellow] [dim]{row.get('branch', '')}: {note}[/dim]")


def _render_deprecated_patterns(audit_result: dict, console_obj) -> None:
    """Special renderer for deprecated patterns — different structure."""
    deprecated_patterns = audit_result.get("deprecated_patterns", [])

    if not deprecated_patterns:
        return

    console_obj.print()
    console_obj.print(f"  [bold yellow]DEPRECATED PATTERNS ({len(deprecated_patterns)}):[/bold yellow]")
    for pattern in deprecated_patterns:
        console_obj.print(f"    [yellow]⚠[/yellow] {pattern['path']}")
        console_obj.print(f"      [dim]→ {pattern['message']}[/dim]")


#: How many re-run checkers to name before the line stops being readable.
_MAX_NAMED_RERUNS = 4


def cache_tag(audit_result: dict) -> str:
    """The `(cached)` suffix for a branch line, and what a partial hit re-ran.

    A partial hit must not read as a cold scan; a cold, ``--full`` or stamp-bust run prints nothing.
    """
    if audit_result.get("_cache_hit"):
        return " [dim](cached)[/dim]"
    partial = audit_result.get("_cache_partial")
    if not partial:
        return ""
    parts = []
    if partial["checkers_cached"] < partial["checkers_total"]:
        parts.append(f"{partial['checkers_cached']} of {partial['checkers_total']} checkers")
    if partial["files_cached"] < partial["files_total"]:
        parts.append(f"{partial['files_cached']} of {partial['files_total']} files")
    if not parts:
        return ""
    reran = partial.get("reran") or []
    named = ", ".join(reran[:_MAX_NAMED_RERUNS])
    if len(reran) > _MAX_NAMED_RERUNS:
        named += f" (+{len(reran) - _MAX_NAMED_RERUNS} more)"
    detail = f"; re-ran {named}" if reran else ""
    return f" [dim](cached: {', '.join(parts)}{detail})[/dim]"


#: The one group a result with no ``groups`` key prints under (tests, saved artifacts).
LEGACY_GROUP = "standards"


def _icon(pct: int) -> str:
    """The tier icon a score cell carries."""
    return "✅" if pct >= 90 else "⚠️" if pct >= 75 else "❌"


def _cell(name: str, pct: int) -> str:
    """One score cell of the grid."""
    return f"  {name.title():15} {pct:3}% {_icon(pct)}"


def _groups_of(audit_result: Dict) -> Dict[str, List[str]]:
    """The result's groups, or every row under the legacy group when it carries none."""
    return audit_result.get("groups") or {LEGACY_GROUP: sorted(audit_result.get("scores", {}))}


def group_names(audit_results: List[Dict]) -> List[str]:
    """Every group any of these results prints under, alphabetical: what ``--group`` accepts."""
    return sorted({name for result in audit_results for name in _groups_of(result)})


def _mean(values: List[int]) -> int:
    """The integer mean the grid prints."""
    return int(sum(values) / len(values))


def _row_averages(audit_results: List[Dict]) -> Dict[str, int]:
    """Each row's average over the results that scored it."""
    collected = defaultdict(list)
    for result in audit_results:
        for row, pct in result["scores"].items():
            collected[row].append(pct)
    return {row: _mean(values) for row, values in collected.items()}


def _rule_averages(audit_results: List[Dict]) -> Dict[str, Dict[str, int]]:
    """Each row's rules, each averaged over the results that scored it."""
    collected: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
    for result in audit_results:
        for row, rules in (result.get("rule_scores") or {}).items():
            for rule, pct in rules.items():
                collected[row][rule].append(pct)
    return {row: {rule: _mean(v) for rule, v in sorted(rules.items())} for row, rules in collected.items()}


def _union_groups(audit_results: List[Dict]) -> Dict[str, List[str]]:
    """The groups over every result; a legacy result's rows land under the legacy group only if no group holds them."""
    merged: Dict[str, set] = defaultdict(set)
    for result in audit_results:
        for name, rows in (result.get("groups") or {}).items():
            merged[name].update(rows)
    placed = set().union(*merged.values()) if merged else set()
    for result in audit_results:
        if not result.get("groups"):
            merged[LEGACY_GROUP].update(row for row in result.get("scores", {}) if row not in placed)
    return {name: sorted(rows) for name, rows in sorted(merged.items()) if rows}


def _group_rows(audit_results: List[Dict], group: str | None) -> set | None:
    """The rows ``group`` holds, for filtering the violation blocks; None when no group was asked for."""
    return None if group is None else set(_union_groups(audit_results).get(group, []))


def _render_grid(audit_results: List[Dict], group: str | None = None) -> None:
    """The score grid by group: a clean group is one line, an open one lists its rows down two columns.

    ``group`` prints that group alone, open, with every row and rule at 100 too.
    """
    scores = _row_averages(audit_results)
    rules = _rule_averages(audit_results)
    groups = _union_groups(audit_results)
    if any(not result.get("groups") for result in audit_results):
        console.print(f"  [dim]this result carries no groups: its rows print under '{LEGACY_GROUP}'[/dim]")
    for name, rows in groups.items():
        if group is not None and name != group:
            continue
        noun = "row" if len(rows) == 1 else "rows"
        clean = all(scores[row] >= 100 and all(p >= 100 for p in rules.get(row, {}).values()) for row in rows)
        # The legacy group prints every row: a result without groups never folds them away.
        if clean and group is None and name != LEGACY_GROUP:
            console.print(
                f"  [bold]{name:<13}[/bold] [cyan]{len(rows):>2}[/cyan] {noun}  [cyan]100%[/cyan] {_icon(100)}"
            )
            continue
        avg = _mean([scores[row] for row in rows])
        console.print(f"  [bold]{name}[/bold] [dim]{len(rows)} {noun}, average[/dim] [cyan]{avg}%[/cyan] {_icon(avg)}")
        half = (len(rows) + 1) // 2
        # Read down: the left column is the first half, the right the second.
        for left, right in zip(rows[:half], rows[half:] + [None]):
            line = _cell(left, scores[left]) + (f"  {_cell(right, scores[right])}" if right else "")
            console.print(line, highlight=False)
            for row in (left, right) if right else (left,):
                for rule, pct in rules.get(row, {}).items():
                    if group is not None or pct < 100:
                        console.print(f"      [dim]{row} ›[/dim] {rule} [cyan]{pct}%[/cyan]")


def print_branch_summary(
    audit_result: Dict,
    no_bypass: bool = False,
    group: str | None = None,
):
    """Print summary for a single branch - always shows full details (audit = comprehensive)

    no_bypass tags the branch and Overall lines, so a raw score never travels unlabelled;
    group prints that group alone, and only its violations.
    """
    json_handler.log_operation("audit_display_rendered", {"branch": audit_result["branch"]["name"]})
    branch = audit_result["branch"]
    avg = audit_result["average"]
    files_checked = audit_result.get("files_checked", 0)

    # Says what was measured, never just how much; the corpus sentence comes from the pack.
    corpus_noun = audit_result.get("corpus_noun") or DEFAULT_PACK_CORPUS["noun"]
    corpus_detail = audit_result.get("corpus_detail") or DEFAULT_PACK_CORPUS["detail"]
    corpus_size = audit_result.get("corpus_size", files_checked)
    cached_tag = cache_tag(audit_result)
    no_bypass_tag = " [bold yellow][BYPASSES DISABLED][/bold yellow]" if no_bypass else ""
    console.print()
    console.print(
        f"[bold cyan]{branch['name']}[/bold cyan] "
        f"[dim]({corpus_size} {corpus_noun} measured — {corpus_detail})[/dim]"
        f"{cached_tag}{no_bypass_tag}"
    )

    _render_grid([audit_result], group)

    # The files each row did not judge, so a 100 over a partial corpus says so.
    declined = audit_result.get("declined") or {}
    if declined:
        counts = ", ".join(f"{name.title()} {len(files)} declined" for name, files in sorted(declined.items()))
        console.print(f"  [dim]Not judged: {counts}[/dim]")

    ignored = audit_result.get("ignored") or {}
    if ignored:
        counts = ", ".join(f"{pattern} {len(files)}" for pattern, files in sorted(ignored.items()))
        console.print(f"  [dim]Ignored by the audit list: {counts}[/dim]")
    for rel in audit_result.get("ignored_tracked") or []:
        warning(f"Ignore list drops tracked source: {rel}")
    for dead in audit_result.get("bypass_dead") or []:
        warning(f"Dead bypass rule [{dead['index']}] {dead['file']} / {dead['standard']}: {dead['why']}")
    for marker in audit_result.get("bypass_markers") or []:
        warning(f"Inline bypass comment, read by nothing: {marker}")

    overall_icon = "✅" if avg >= 90 else "⚠️" if avg >= 75 else "❌"
    waived = audit_result.get("waived")
    waived_tag = f" [dim]· {waived} waived by bypass rows[/dim]" if waived is not None else ""
    console.print(f"  [bold]Overall:{' ' * 8} {avg:3}% {overall_icon}[/bold]{waived_tag}")
    if no_bypass:
        console.print("  [bold yellow]BYPASSES DISABLED[/bold yellow] [dim](--no-bypass) — raw score[/dim]")

    shown = _group_rows([audit_result], group)
    rendered_standards = set()
    for standard_name, score in sorted(audit_result.get("scores", {}).items()):
        if score >= 100 or (shown is not None and standard_name not in shown):
            continue
        violations_key = f"{standard_name}_violations"
        violations = audit_result.get(violations_key, [])
        if standard_name == "architecture":
            _render_architecture_violations(audit_result, console)
            rendered_standards.add(standard_name)
        elif violations:
            _render_violations(standard_name, violations, console)
            rendered_standards.add(standard_name)
        else:
            result_data = audit_result.get("results", {}).get(standard_name, {})
            failed_checks = [c for c in result_data.get("checks", []) if not c.get("passed", True)]
            if failed_checks:
                formatted = _format_standard_name(standard_name)
                console.print(f"    └─ {formatted} issues:")
                for check in failed_checks:
                    console.print(f"       [dim]• {check.get('message', '')}[/dim]")
                rendered_standards.add(standard_name)

    for key in audit_result:
        if not key.endswith("_violations"):
            continue
        standard_name = key.removesuffix("_violations")
        if standard_name in rendered_standards or (shown is not None and standard_name not in shown):
            continue
        violations = audit_result[key]
        if violations:
            _render_violations(standard_name, violations, console)

    if shown is None or "diagnostics" in shown:
        _render_type_errors(audit_result, console)

    _render_test_map(audit_result, console)

    _render_info_lines(audit_result, console)

    _render_deprecated_patterns(audit_result, console)

    # Same arm as the fleet run, so one branch never reads two ways.
    _render_fleet_table([audit_result], console)


def print_system_summary(audit_results: List[Dict], no_bypass: bool = False, group: str | None = None):
    """Print system-wide summary with standard averages; no_bypass labels the copied block itself.

    group prints that group's averages alone.
    """
    # On a fleet run this is the only place a branch_level checker's per-branch reading appears.
    _render_fleet_table(audit_results, console)

    total_branches = len(audit_results)
    avg_compliance = int(sum(r["average"] for r in audit_results) / total_branches) if total_branches else 0

    excellent = sum(1 for r in audit_results if r["average"] >= 90)
    good = sum(1 for r in audit_results if 75 <= r["average"] < 90)
    needs_work = sum(1 for r in audit_results if r["average"] < 75)
    cache_served = sum(1 for r in audit_results if r.get("_cache_hit"))

    total_type_errors = sum(r.get("type_errors", 0) for r in audit_results)
    branches_with_type_errors = sum(1 for r in audit_results if r.get("type_errors", 0) > 0)

    console.print()
    console.print("─" * 70)
    if no_bypass:
        console.print("[bold]SYSTEM SUMMARY[/bold] — [bold yellow]BYPASSES DISABLED[/bold yellow][bold]:[/bold]")
    else:
        console.print("[bold]SYSTEM SUMMARY:[/bold]")
    console.print(f"  Total branches:        [cyan]{total_branches}[/cyan]")
    console.print(f"  Average compliance:    [cyan]{avg_compliance}%[/cyan]")
    console.print(f"  Branches ≥90%:         [cyan]{excellent}[/cyan]")
    console.print(f"  Branches 75-89%:       [cyan]{good}[/cyan]")
    console.print(f"  Branches <75%:         [cyan]{needs_work}[/cyan]")
    if total_type_errors > 0:
        console.print(
            f"  Type errors:           [cyan]{total_type_errors}[/cyan] ({branches_with_type_errors} branches)"
        )
    else:
        console.print("  Type errors:           [cyan]0[/cyan]")
    waived = [r["waived"] for r in audit_results if r.get("waived") is not None]
    if waived:
        console.print(
            f"  Waived sites:          {sum(waived)} [dim](bypass rows; a 100 with rows waived is not a clean 100)[/dim]"
        )
    if cache_served:
        console.print(
            f"  Cache-served:          [cyan]{cache_served}/{total_branches}[/cyan] branches (unchanged, skipped re-scan)"
        )
    if no_bypass:
        console.print("  Bypass rules:          [bold yellow]DISABLED[/bold yellow] [dim](raw, not comparable)[/dim]")
    console.print()

    standard_averages = _row_averages(audit_results)

    console.print("[bold]STANDARD AVERAGES:[/bold]")
    console.print("  [dim]each row's average over the branches it scored, by group[/dim]")
    _render_grid(audit_results, group)

    console.print()

    top_issues = sorted(standard_averages.items(), key=lambda x: x[1])[:3]

    if top_issues:
        console.print("[bold]TOP IMPROVEMENT AREAS:[/bold] [dim]the three lowest standard averages[/dim]")
        for i, (standard, avg_score) in enumerate(top_issues, 1):
            branches_failing = sum(1 for r in audit_results if r["scores"].get(standard, 100) < 75)
            console.print(
                f"  {i}. {standard.title():15} (avg: [cyan]{avg_score}%[/cyan], {branches_failing} branches <75%)"
            )

    console.print("─" * 70)
    console.print()
