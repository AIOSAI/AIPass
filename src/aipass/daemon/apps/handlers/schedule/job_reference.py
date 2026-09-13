# =================== AIPass ====================
# Name: job_reference.py
# Description: The job-authoring reference printed by drone @daemon run --help
# Version: 1.0.0
# Created: 2026-09-11
# Modified: 2026-09-11
# =============================================

"""The job-authoring reference that ``drone @daemon run --help`` prints: schema, schedule
types, command jobs, optional fields, and the recovery lane.

Data, not behaviour. It lives here rather than inline in ``apps/modules/run.py`` because
it is 79 lines of static text, and run.py is held under seedgo's 600-line module cap
(DPLAN-0338 wave 1a pushed it to 647). The module still does the printing; a handler
may not. Each entry is one ``console.print`` argument: Rich markup, and "" for a blank line.
"""

from typing import List

from aipass.daemon.apps.handlers.json import json_handler


def job_reference_lines() -> List[str]:
    """Every line of the authoring reference, in print order. "" is a blank line."""
    lines = _REFERENCE_LINES
    json_handler.log_operation("job_reference_lines", {"count": len(lines)})
    return list(lines)


_REFERENCE_LINES = [
    "\n[bold cyan]SCHEDULING — How to author a job:[/bold cyan]",
    "  [bold]File:[/bold] src/aipass/<branch>/.daemon/schedule.json",
    "",
    "  [bold]Schema:[/bold]",
    "    {",
    '      "version": 1,',
    '      "branch": "@<branch>",',
    '      "jobs": [',
    "        {",
    '          "id": "my-job",',
    '          "enabled": true,',
    '          "schedule": { "type": "interval", "interval_minutes": 30 },',
    '          "wake": { "fresh": true, "model": "haiku" },',
    '          "prompt": "Do something, then STOP."',
    "        }",
    "      ]",
    "    }",
    "",
    "  [bold]Schedule types:[/bold]",
    "    [cyan]interval[/cyan]  interval_minutes: N",
    "              [dim]Fires when elapsed >= N since last_run.[/dim]",
    "              [dim]Never run and no slot -> fires IMMEDIATELY (warned in run.log).[/dim]",
    "    [cyan]daily[/cyan]     time: HH:MM",
    "              [dim]+/-15 min window, once per day.[/dim]",
    "    [cyan]hourly[/cyan]    time: M  [dim](minute of hour)[/dim]",
    "              [dim]+/-15 min window, once per hour.[/dim]",
    "    [cyan]once[/cyan]      due_date: YYYY-MM-DD",
    "              [dim]Fires when date <= today, then marks completed.[/dim]",
    "    [cyan]rotation[/cyan]  time: HH:MM",
    "              [dim]Daily window, but wakes the NEXT citizen on the fleet[/dim]",
    "              [dim]roster instead of the owner. See drone @daemon rotation.[/dim]",
    "",
    "  [bold]wake options:[/bold]  fresh (bool), model (haiku/sonnet — use light models)",
    "",
    '  [bold]Command jobs:[/bold] "command" instead of "prompt" — run as a subprocess, nobody woken',
    '    "command": "drone rm --stale 10d ../..", "timeout_seconds": 600,',
    '    "notify": { "email": "@devpulse" }   [dim](a mail on start and on finish)[/dim]',
    "    [dim]drone must be the first token. No shell: no globs, pipes or ';'. Runs in the[/dim]",
    "    [dim]owner's branch, so drone logs it as the owner. Exactly one of prompt/command.[/dim]",
    "",
    "  [bold]Optional schedule fields:[/bold]",
    '    [cyan]slot[/cyan]      "2026-09-06T03:00:00"   [dim](interval jobs)[/dim]',
    "              [dim]An ISO instant naming ONE occurrence of the rhythm you want.[/dim]",
    "              [dim]A job that has never run is seeded from it, so the first fire[/dim]",
    "              [dim]lands on the next slot instead of the next tick. Without it,[/dim]",
    "              [dim]enabling a weekly job at 01:34 locks it to 01:34 forever.[/dim]",
    "              [dim]A past slot keeps its phase — it is rolled forward, not used raw.[/dim]",
    "    [cyan]catch_up[/cyan]  false                   [dim](daily, rotation and hourly jobs)[/dim]",
    "              [dim]ON UNLESS YOU SET false (DPLAN-0332, 2026-09-08). When a[/dim]",
    "              [dim]window closed with no run, the job fires once afterwards and[/dim]",
    "              [dim]stamps caught_up on the runstate row. Set false when a late[/dim]",
    "              [dim]run is worthless.[/dim]",
    "    [cyan]catch_up_max_age_hours[/cyan]  24         [dim](optional)[/dim]",
    "              [dim]A missed window older than this is logged MISSED and not[/dim]",
    "              [dim]queued. Unlimited by default: ten days away should still be[/dim]",
    "              [dim]exactly one wake.[/dim]",
    "",
    "  [bold]Staggering:[/bold] Prefer `slot` on interval jobs. Seeding last_run values",
    "  in daemon_json/daemon_runstate.json by hand still works for the other types.",
    "",
    "[bold cyan]RECOVERY AFTER A GAP (DPLAN-0332):[/bold cyan]",
    "  Every tick stamps last_tick. If the next tick is more than 30 min later,",
    "  the scheduler was away: it names the cause from the host boot time (machine",
    "  off, scheduler stopped while up, or both), enumerates every window that",
    "  closed inside the gap, and queues ONE catch-up per job carrying them all.",
    "  Ten days off is one wake with ten dates, never ten wakes.",
    "",
    "  The queue drains one at a time fleet-wide: the next fires when the previous",
    "  completes, or 60 min later if it never reports. Three refusals park an entry",
    "  at the tail so it cannot block the queue — it is never dropped.",
    "",
    "  Every wake carries a header saying why it is awake: SCHEDULED with the last",
    "  run, or CATCH-UP with the gap, the cause and the missed windows. The agent",
    "  is told the truth about time and decides what matters — nothing is replayed.",
    "",
    "  [bold]run.log:[/bold] GAP once per gap, then QUEUED / CATCH-UP FIRED /",
    "  CATCH-UP FAILED / SUPERSEDED. The MISSED line still names every windowed job",
    "  whose window closed unrun, once per job per day.",
    "",
]
