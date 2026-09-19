[<- Back to the README](../README.md)

# Monitoring and reports

Home for the monitoring handlers — activity collection, red flags, memory health, and report generation — starting with memory entry health.

---

## Memory Entry Health (via @memory)

`branch-health <BRANCH>` resolves the branch name case-insensitively against the registry
**before** it generates anything, so `drone`, `DRONE` and `dRoNe` all reach the same report and
an unknown name is refused once — non-zero, with the token named — instead of rendering two
"not found" blocks and exiting 0 (@devpulse fleet sweep 2026-09-07, row 21). A missing branch
name is a refusal on the same terms. It closes with an entry-health block sourced from @memory's public API,
`get_branch_health(branch_name)` — entry-count (is a `.trinity` file over its rollover trigger)
and entry-size (is any entry over its character cap).

The call lives in `apps/modules/activity_report.py`, never in `apps/handlers/monitoring/memory_health.py`
— seedgo blocks handler-to-other-branch imports, so the module layer is the only legal caller.

Caps are **not** re-encoded on this side. They live in @memory's `memory.config.json`, where defaults
are deep-merged with per-branch overrides; a copy here would be a snapshot that drifts.

| Fact | Severity | Rendered |
|------|----------|----------|
| `should_rollover: True` | INFO — rollover being due is not a fault; it auto-fires at the next PreCompact | `[PENDING]` |
| `total_violations > 0` | WARNING — a write got past the character-cap gate | `[!] WARNING` |
| memory file absent | skipped, not an error | `[SKIP]` |
| unknown branch / @memory not importable | named reason, never an empty section | `[!]` |

Markers are uppercase deliberately: `console.print()` parses Rich markup, so a lowercase tag like
`[ok]` reads as a style name and is silently swallowed — the marker vanishes on screen while a test
asserting on the returned string still passes. `TestMarkersSurviveRichMarkup` renders through Rich
to pin this.

Those render-through-Rich tests name `force_terminal` **and** `color_system` explicitly, and strip
ANSI before asserting. Both are load-bearing, and each was paid for:

- Rich decides whether to emit escape codes from `is_terminal`, and `FORCE_COLOR` in the environment
  makes even a `StringIO` count as one. `ReprHighlighter` then wraps every bracket and number in
  **bold**, so a plain-substring assert fails while the marker is plainly visible. `no_color=True`
  does not help — it strips colour, not attributes. This suite was green in the morning and red the
  same evening on byte-identical code, and the reds blocked a fleet commit train.
- `force_terminal=True` alone is still not deterministic: under `TERM=dumb` Rich resolves no colour
  system and emits plain text regardless. An early draft of the fix passed under `FORCE_COLOR` and
  failed under `TERM=dumb` — the same defect, one layer along.

The suite is verified green under `FORCE_COLOR=3`, `TERM=dumb`, `NO_COLOR=1`, and
`TERM=xterm-256color` (re-measured 2026-09-05: 36 passed under each of the four).
Both classes live in `tests/test_activity_report.py`. `TestSharedConsoleContract` separately pins the hazard behaviourally against
the real `aipass.cli` console: it asserts a lowercase tag is still swallowed there, so a cli change
surfaces here rather than blanking this report.

---
