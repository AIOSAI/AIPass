[<- Back to the README](../README.md)

# monitor — Mission Control

The real-time terminal console: threads, multi-CLI session reading, the commons feed.

---

## Monitor — Mission Control

```bash
drone @prax monitor                      # Show monitor architecture
drone @prax monitor run                  # Launch Mission Control (all branches)
drone @prax monitor run sentry,cli       # Monitor specific branches
drone @prax monitor run commons          # Live social feed of The Commons
drone @prax monitor run commons --logs   # Tail commons' technical logs instead
drone @prax monitor --help               # Monitor usage
```

**On request only — there is no monitor service.** Mission Control is an operator
console, and logging does not depend on it: `system_logs/` and the branch-local
logs are written by the logging handlers whether or not a monitor is running.
Start it when you want to watch, quit it when you are done.

No systemd unit ships for it. An always-on monitor would need a rotation story
for its own output first, and that output must stay *outside* `system_logs/`:
the monitor tails `system_logs/*.log` and @trigger watches it too, so writing
there is a feedback loop.

Real-time unified console showing:
- File changes, log events, drone commands, agent activity
- **Branch scoping** — `monitor run sentry,cli` shows only those branches (see below)
- **Caller attribution** — `CALLER → TARGET` for drone commands
- **Model tags** — `[branch/model]` (e.g., `[devpulse/opus]`, `[devpulse/gpt-5.4]`)
- **Lowercase labels, one colour per branch** — every fleet branch has its own colour in `BRANCH_COLORS`; a name not in the table prints white
- **Tags read in either case** — the log watcher matches agent tags case-insensitively: `[hooks]` and `[HOOKS]`, `[flow]` and `[FLOW]`, `[caller:x]` and `[CALLER:x]` give the same event
- **Multi-CLI** — Claude Code (JSONL), Codex (JSONL) session monitoring
- **Rate tracking** — 4th background thread scans `system_logs/` for runaway log growth every 10s
- **Polling fallback** — automatic fallback when inotify watches are exhausted
- **Soft start** — only shows new activity after launch (seeks to EOF on startup)

Interactive commands inside the monitor: `help`, `status`, `quit`/`exit`/`q`.

**Who counts as a branch.** Names and paths come from declarations, never from
path shape. The citizens are memory's door rows (core `AIPASS_REGISTRY.json`,
in-repo residents, and the roots `AIPASS_ROOTS.json` declares), read through a
60-second cache; then, for any file still unresolved, the nearest
`.trinity/passport.json` walking up to the repo root. First registration wins, so
a project cannot claim a name AIPass already uses. The same rows decide what is
watched: each citizen's `apps/` recursively, its root and `.trinity/` flat, so a
declared-root citizen outside the repo is watched like a core one. A Codex
session is labelled by asking the detector about its CWD, wherever it lives; the
`aipass/<name>` and `src/<name>` path shapes answer only when the detector has
no label.

The project sweep resolves whoever the registries *declare*, not whoever has a
directory. Path
shape is never used: matching path segments against known names labels every
file under the `AIPass` directory as aipass, and misattribution is worse than
UNKNOWN — events land on the wrong screen and are filtered off the right one.

**Branch scoping.** A comma-separated list (`monitor run sentry,cli`) restricts the
display to those branches; bare `run` and `run all` show everything. A
scope covers each named branch's log lines, file changes and CLI sessions —
including session labels that carry a project prefix or model tag
(`aipass/sentry/opus`) — plus commands the branch issued or was targeted by
(`devpulse → prax` appears in both scopes). Filtering happens at the queue, so
out-of-scope traffic never occupies a display slot and cannot push wanted events
out under load. The banner and `status` name the active scope, `status` also
reports how many events the scope is holding back, and a name that is in no
branch registry is called out at launch rather than showing a silently empty
screen. The monitor's own health warnings (file watcher unavailable, and similar)
bypass the scope — a filter must never hide the reason the screen is empty.
The scope is set at launch; there is no runtime `filter` command outside commons
feed mode.

**One rate tracker per machine.** `monitor run` is not single-instance: several
Mission Controls can run side by side, each with its own display and watchers. The
rate tracker is the exception, because two of them would raise every runaway alert
twice. At startup each monitor tries a non-blocking `flock` on
`prax_json/monitor.lock` (`apps/handlers/monitoring/instance_lock.py`). The winner
runs the tracker and writes its PID into the file; the others log that another
monitor runs it and only display events. The lock is held on an open file for the
process life, so the kernel drops it when the holder dies and no stale pidfile is
ever judged. The file stays on release, since unlinking it would race a waiting
opener, and it lives outside `system_logs/`, which the monitor tails.

**Display resilience.** Everything on screen is other branches' output, so every
dynamic value is escaped before it reaches Rich — a tailed line containing
`[/usr/bin]` is shown, not parsed. If a line still cannot be drawn, the failure
costs that one line: the display thread reports it (rate-limited, in plain
language) and keeps consuming. It is the queue's only consumer, and a consumer
that dies leaves the queue permanently full with nobody to empty it.

**Commons feed mode** (`monitor run commons`) is a different watcher, not a branch
filter — it renders live social activity in The Commons (posts, comments, votes,
reactions) read-only, instead of file/log events. `--logs` opts back out to tailing
the commons branch's technical logs. Feed mode adds two interactive commands of its
own: `filter <room>` (comma-separated, any case) and `filter clear`.

