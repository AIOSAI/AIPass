# Autostart — the server comes back on its own

**Branch** api · **Code** `apps/handlers/host/autostart.py`, `apps/modules/host_serve.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

---

## Autostart — the server comes back on its own (2026-08-27)

@baud's phone face went dark this morning. `host_api_serve.log` showed normal
traffic and then silence — no traceback, no shutdown line, which is exactly what
a reboot looks like from inside a log. A detached server dies with the machine
and nothing brought it back; Patrick ruled that a face which waits for a human
after every reboot is wrong.

**It is a systemd user unit, not a loop in this tree, and the reason is the scar
already written into `lifetime.py`.** That module refuses on principle to
restart anything — because the fourteen death-and-restart cycles @baud read out
of a pane on 2026-08-19 came FROM a supervisor, a shell loop somebody typed.
Answering a missing supervisor with a second home-grown one repeats the mistake
with better manners. The alternative on the table was a `@daemon` check-and-start
entry, which keeps everything inside AIPass conventions and is exactly that
second supervisor: it can only notice a crash at poll granularity, it has no
concept of boot ordering, and it would have to reimplement "do not restart what
an operator deliberately stopped" — the one rule this lane cannot get wrong.
systemd is already running here, already owns boot, and already knows that rule.

So `autostart.py` supervises nothing. It **renders** a unit, **answers** whether
the supervisor is holding the server, and **asks** it to stop. Every decision
about starting, restarting and boot ordering belongs to systemd.

**`autostart` writes into the tree and installs nothing.** The unit lands in
`logs/` — gitignored, deliberately: it necessarily carries this machine's
absolute paths and this machine's bind address, and a file like that committed to
a public repo is either a hardcoded path or somebody else's broken install. The
command then prints the five host-side steps. Installing means writing under a
home directory and enabling something that outlives every session; that is
outside this tree and stays the operator's to run.

**Two things make this safe rather than merely automatic, and both used to fail
silently.**

`status` was lying by construction. A unit-managed server writes no record file,
and `running()` only ever read that record — so a perfectly healthy server was
reported as *"No detached server is running"*, at exactly the moment an operator
needs the opposite. It asks the supervisor FIRST now, and a reboot's stale record
can no longer outrank the live process. Every record carries an `owner`, because
the two cases need different commands from whoever reads it.

`stop` would have been a trap. Signalling a supervised pid directly leaves the
restart policy free to start it again, so the command prints success and the
server is back before anyone finishes reading. A supervised stop goes through
`systemctl --user stop`, which outranks `Restart=` by definition. The pid is then
re-checked rather than trusted — the supervisor *accepting* a stop and the
process *being gone* are two facts, and this branch has already been caught once
believing the first implies the second.

**The unit's own details are each a silent failure avoided.** `StandardOutput=`
and `StandardError=` are `append:`, not `file:` — `file:` truncates on every
start, so the first restart after an outage would destroy the evidence of the
outage, and appending to the same `host_api_serve.log` is what made this morning
diagnosable at all. `Restart=on-failure`, never `always`, so a cleanly refused
bind stays refused instead of spinning. `StartLimitIntervalSec`/`Burst` sit under
`[Unit]`: systemd moved them there in v230 and **ignores** the old `[Service]`
spelling rather than erroring, so a rate limit in the wrong section is an absence
wearing a config's clothes. The window is deliberately generous — 60 attempts,
5s apart, inside 10 minutes — because at boot this server can come up before
tailscaled has assigned the address it binds, and that failure is indistinguishable
from a fatal misconfiguration. Generous enough to outlast a slow network, still
finite, so an impossible bind ends as a unit in `failed` that says so rather than
retrying forever into a growing log.

**That window has never once fired, and this paragraph used to say why it would.**
It claimed a refused bind "exits non-zero immediately". It exits **`0`** — measured
2026-09-07 by running `serve` against an address this machine does not hold. The
unit is `Restart=on-failure`, so systemd sees `status=0/SUCCESS`, correctly declines
to restart, and the boot race this whole window was built to absorb ends with the
server quietly dead. The journal has it twice: `Started 12:19:10` → dead `12:19:16`,
and tailscaled reached `Running` at **12:19:22**, six seconds after the unit gave up
— one retry would have caught it. Same shape on 09-05 at 10:28. Two of the last six
boots, so the face goes dark after roughly one reboot in three and waits for a human,
which is the exact failure autostart exists to end. The cure is an exit code, not a
wider window; it is the `Known issues` exit-`0` item, and this is that item's real
cost. Reported to @devpulse 09-07, unfixed here because the exit-code lane is
blocked on Patrick's fleet-wide ruling.

The unit and `serve --detach` build their argv from one function, `serve_argv()`.
Two ways to start one server is how a fix lands in one of them and the other
keeps the bug — and the unit's copy is the one nobody re-reads, because it lives
in a file under somebody's home directory that this tree cannot see.

Lingering is reported, not assumed: without it a user unit waits for a login,
which on a headless reboot never comes — the exact failure this build exists to
end. It is set outside this tree and can be turned off by someone who never reads
this file.

---

**A probe that cannot answer is not a probe that answered "nothing" (2026-08-27).**
The Windows CI lane went red on this lane the day it shipped, and the failure was
worth more than the fix. `_systemctl` asks `is_supported()` before it runs
anything, so on a runner with no systemd the platform gate returned first and
every test that scripted `subprocess.run` never reached its mock. Five failed —
and **six more passed for the wrong reason**, because they assert `0` or
`(None, None)`, which is exactly what the untouched gate returns. Those six were
the real finding: a red test tells you it is broken, while a test that passes
without running its subject tells you nothing forever and looks like coverage
doing it.

Under it sat a live defect. `_systemctl` returned `None` for two different facts:
*this platform has no systemd*, and *this machine has one and it did not answer*.
Both became `supervised_pid() == 0`, "no unit is holding the server". **The
ruling, split in two because the question has two answers.** No systemd on the
platform still answers zero — a machine that cannot have a unit has no
uncertainty to report, so zero is the strongest available answer and `running()`
correctly falls through to the detached record, the only kind of server that can
exist there. But a probe that FAILED on a capable machine now raises
`SupervisorUnreachable`, because the tailnet host runs under a unit that writes
**no record file**: a swallowed probe sends `running()` down the record path and
prints "No server is running" about a server answering requests. Proven live
rather than argued — with the unit genuinely holding pid 227641, forcing the
probe to fail made the old path return `None`.

Each of the three callers wants that refusal: `status` says it cannot tell rather
than inventing an absence, `stop` will not signal into the dark where a restart
policy may undo it, and `serve` will not start a second listener on a port it
cannot see. Only `supervised_bind` swallows it, and only because the pid probe
has already established the verdict — losing the bind costs a status line its
address, not its truth.

---

---

[← api README](../README.md)
