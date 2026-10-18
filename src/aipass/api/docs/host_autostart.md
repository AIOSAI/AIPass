[<- Back to the README](../README.md)

# Autostart — the server comes back on its own

**Branch** api · **Code** `apps/handlers/host/autostart.py`, `apps/modules/host_serve.py`

---

## The boot unit

A detached server dies with the machine. A face that waits for a human after every
reboot is wrong, so a systemd user unit brings the server back.

**It is a systemd user unit, not a loop in this tree, because `lifetime.py` refuses
on principle to restart anything.** A restart loop is a supervisor, and answering a
missing supervisor with a home-grown one is the failure that refusal exists to
prevent. A `@daemon` check-and-start entry would be exactly that second supervisor:
it can only notice a crash at poll granularity, it has no concept of boot ordering,
and it would have to reimplement "do not restart what an operator deliberately
stopped" — the one rule this lane cannot get wrong. systemd is already running here,
already owns boot, and already knows that rule.

So `autostart.py` supervises nothing. It **renders** a unit, **answers** whether
the supervisor is holding the server, and **asks** it to stop. Every decision
about starting, restarting and boot ordering belongs to systemd.

**`autostart` writes into the tree and installs nothing.** The unit lands in
`logs/` — gitignored, deliberately: it necessarily carries this machine's
absolute paths and this machine's bind address, and a file like that committed to
a public repo is either a hardcoded path or somebody else's broken install. The
command then prints the five host-side steps. Installing means writing under a
home directory and enabling something that outlives every session; that is
outside this tree and stays the operator's to run — from the CLI. An installer
that calls the module's doors by name runs them instead (see the installer's
doors below).

**Two things make this safe rather than merely automatic.**

`status` asks the supervisor FIRST. A unit-managed server writes no record file, so
a status that read only the record would report a healthy server as *"No detached
server is running"*, and a reboot's stale record cannot outrank the live process.
Every record carries an `owner`, because the two cases need different commands from
whoever reads it.

`stop` goes through the supervisor. Signalling a supervised pid directly leaves the
restart policy free to start it again, so the command would print success and the
server would be back before anyone finished reading. A supervised stop goes through
`systemctl --user stop`, which outranks `Restart=` by definition. The pid is then
re-checked rather than trusted — the supervisor *accepting* a stop and the
process *being gone* are two facts.

**The unit's own details are each a silent failure avoided.** `StandardOutput=`
and `StandardError=` are `append:`, not `file:` — `file:` truncates on every
start, so the first restart after an outage would destroy the evidence of the
outage; both append to the same `host_api_serve.log`. `Restart=on-failure`, never
`always`. `StartLimitIntervalSec`/`Burst` sit under `[Unit]`: systemd moved them
there in v230 and **ignores** the old `[Service]` spelling rather than erroring, so
a rate limit in the wrong section is an absence wearing a config's clothes. The
window is deliberately generous — 60 attempts, 5s apart, inside 10 minutes — because
at boot this server can come up before tailscaled has assigned the address it binds,
and that failure is indistinguishable from a fatal misconfiguration. Generous enough
to outlast a slow network, still finite, so an impossible bind ends as a unit in
`failed` that says so rather than retrying forever into a growing log.

**A refused bind exits `1`, and that is what arms the window.** Under
`Restart=on-failure` a zero exit reads as success and is never retried, so a bind
refused because the address is not yet assigned must exit non-zero for the boot
race to be absorbed.

The unit and `serve --detach` build their argv from one function, `serve_argv()`.
Two ways to start one server is how a fix lands in one of them and the other
keeps the bug — and the unit's copy is the one nobody re-reads, because it lives
in a file under somebody's home directory that this tree cannot see.

**It names the home's server, not this process's.** A stranger's machine holds
aipass twice: the uv tool venv `aipass install` runs in, with no `[host]` extra,
and the AIPass home with its own `.venv`. A server spelled as this process would
run on the tool venv's python and die on *No module named fastapi*. `server_home()`
resolves the home as drone's `branch_interpreter` does (`resolve_aipass_home`). If
this copy lives inside it, or no home resolves, the server is this interpreter and
this branch. Otherwise it is `<home>/.venv`'s python and
`<home>/src/aipass/api/apps/api.py`, and the spawn's `cwd` and the unit's
`WorkingDirectory` are the home's api branch. A home missing either file refuses
with `LifetimeError` naming it; there is no fall back, because a server that starts
and dies is worse than a refusal.

Lingering is reported, not assumed: without it a user unit waits for a login,
which on a headless reboot never comes — the exact failure this build exists to
end. It is set outside this tree and can be turned off by someone who never reads
this file.

---

**A probe that cannot answer is not a probe that answered "nothing".**
`_systemctl` separates two facts: *this platform has no systemd*, and *this machine
has one and it did not answer*. No systemd on the platform answers zero — a machine
that cannot have a unit has no uncertainty to report, so zero is the strongest
available answer and `running()` correctly falls through to the detached record,
the only kind of server that can exist there. A probe that FAILED on a capable
machine raises `SupervisorUnreachable`, because the tailnet host runs under a unit
that writes **no record file**: a swallowed probe would send `running()` down the
record path and print "No server is running" about a server answering requests.

The tests set the `is_supported()` platform gate themselves, so a scripted
`subprocess.run` reaches its subject on a runner with no systemd; a test that passes without running
its subject looks like coverage and is none.

Each of the three callers wants that refusal: `status` says it cannot tell rather
than inventing an absence, `stop` will not signal into the dark where a restart
policy may undo it, and `serve` will not start a second listener on a port it
cannot see. Only `supervised_bind` swallows it, and only because the pid probe
has already established the verdict — losing the bind costs a status line its
address, not its truth.

---

## The installer's doors

**The CLI prints the steps; the module runs them for a caller that asks by name.**
A stranger running `aipass install` has consented to the install, so asking them to
paste two commands afterwards is a hand the phone does not need.
`apps/modules/host_api.py` publishes:

| Door | Does |
|---|---|
| `set_bind(host, port) -> dict` | `set-config --host --port` in-process: `validate_bind`, then the store. `{host, port, changed, previous}`; an unchanged bind is kept and **not rewritten**. Raises `BindRefused`, storing nothing |
| `autostart(host=None, port=None) -> dict` | `autostart_report` plus `rendered` and `running`. A unit the supervisor already runs is **not re-rendered** and keeps the bind it started with |
| `install_unit(dry_run=False) -> dict` | the first three steps: mkdir, copy into the user unit dir, `daemon-reload` |
| `enable_unit(dry_run=False) -> dict` | `enable --now`, then `loginctl enable-linger` only when lingering is not already on. Refused while a hand-started server holds the port |
| `receipt_path(label) -> Path` | where a token's receipt belongs, so the installer stops restating it |

Each run returns `{dry_run, ok, steps: [{step, ok, detail}]}` and stops at the
first failed step, which is the last entry. A dry run names every step with `ok`
None and runs none. The enable refusal is `ok` False, empty `steps`, and a
`refused` sentence naming the pid and the stop command. `AutostartUnsupported`,
`SupervisorUnreachable`, `LifetimeError` and `TokenError` are exported beside
`BindRefused`, so a caller catches the module's names.

---

[← api README](../README.md)
