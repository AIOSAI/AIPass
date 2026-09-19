[<- Back to the README](../README.md)

# Why this branch is shaped the way it is

**Branch** api · **Code** `apps/` (the record behind the code)

---

*EVERY REFUSAL THIS BRANCH PRINTED REPORTED SUCCESS. A module returning True
from `handle_command` means "I recognised this command", never "it worked", and
`main()` returned 0 on any truthy route — so `drone @api validate` printed a red
cross for a missing key and exited 0, and `drone @api validate && <next>`
proceeded on the failure. Six commands were measured that way on 2026-08-28 and
the item sat open for twenty-six days waiting on a fleet ruling, because the fix
breaks any consumer that reads the code. The ruling came 09-07 — a refusal exits
non-zero and names the token or reason — and the cure is cli's existing
machinery rather than a new one of ours: `error()` already raised a
process-level failure flag that nothing here ever read. `main()` clears that
flag before routing (it is process-level, so a previous command or an imported
branch printing its own error would otherwise be read as OUR failure) and
resolves the exit from it: 1 unrecognised, 2 recognised-and-refused, 0 only when
nothing printed an error. All six now exit 2, measured; unknown-command stays 1;
`list-providers`, `stats`, `session`, `--help` and the bare introspection stay
0. All 63 `error()` call sites were read first, looking for one that prints a
failure and still succeeds overall — a per-item error inside a loop would have
started exiting 2 wrongly. There were none: this branch had already been using
`warning()` for "no tokens issued" and "no usage data" and reserving `error()`
for real refusals, which is the only reason a one-line seam was safe. The one
site that broke that rule was `revoke-token` on an unknown id, a yellow note
four lines below the `error()` its own sibling refusal used; it names the id
through the error channel now, because an operator scripting `revoke-token <id>
&& <next>` was being told a device was off when it was not.*

*THE BOARD WAS RED FOR THIS BRANCH IN THREE PLACES AND ONE OF THEM ONLY
EXISTED IN CI. seedgo scored the file lane's statics module with 4 unresolved
imports that a local audit could not see, and the reason is one line of shared
configuration: `pyrightconfig.json` carries `.venv/lib/python3.12/site-packages`
on extraPaths, a directory that exists on a developer's machine and nowhere
else. CI installs `.[dev,memory]` and never `[host]`, so `fastapi` and
`starlette` resolve here and vanish there. `statics.py` was the only host module
importing the extra WITHOUT the suppression header every other one carries —
server.py, attach.py and google/auth.py all have it — so it was the only one
that failed. Reproduced before it was fixed, by running the checker against an
empty environment and getting the same four, then re-run to zero: a fix for a
failure you cannot reproduce is a guess with good intentions.*

*THE PUMP MOVED OUT, because 1534 lines is over a 1500-line cap and the ping
lane is what pushed it there. `pump.py` now holds the bidirectional socket and
its two control verbs; `server.py` keeps the routes and dropped `asyncio` and
`json` with them, since the pump was the only thing here that used either. A cap
is only a good reason to move code that was already separable, and this was —
these functions take everything they touch as arguments, which is why they had
already survived one move. Three tests read their source and now read it from the
new file; one asserted on a logger that no longer lives in the same module, which
is exactly the kind of quiet disconnection a move like this can leave behind, and
it failed loudly instead. Eight mutations, all bitten, across both files.*

*AND THE STANDARDS CHECKER ASKED THE NEW MODULE WHY IT LOGGED NO OPERATIONS,
which was a fair question with a real answer. Every socket refusal on this
surface leaves a structured record EXCEPT one: typing into a read-only watch
happens after the socket is live, so it never passes the route's audit gate. It
logged a warning, closed 1008, and told the trail nothing. It records the room
and the session's own sentence now. The cheap way to satisfy that checker was a
token log line; the honest way was to find the gap it was pointing at.*

*A PHONE COULD NOT TELL A LIVE ROOM FROM A CORPSE. When a socket's peer
vanishes without a FIN — a tunnel dropped, a laptop slept, a NAT entry expired —
the browser keeps rendering the last frame it received and the operator believes
they are looking at a live terminal. uvicorn pings from this side every 20
seconds, so the SERVER always finds out; the JS WebSocket API exposes no ping at
all, so the phone had no round-trip of its own and never did. So the control
channel gained a second verb: `{"type":"ping"}` is answered `{"type":"pong"}`,
on the text channel it arrived on, because a pong on the binary channel is
indistinguishable from room output and would paint itself across the terminal.
It is inert by construction — nothing typed, nothing resized, nothing logged; a
liveness probe every few seconds is not an event, and recording it would bury
the two lines that are. An inbound pong is an unknown frame, deliberately: the
server pongs, it does not ping, and answering one would be two sockets shouting
at each other on the wire the operator's keystrokes share.*

*AND THE ROOM LANE WROTE DOWN ARRIVALS BUT NOT DEPARTURES. Thirteen attaches to
one room in three minutes, and the log could not say whether thirteen sockets
came and went or came and stayed — an arrival count alone cannot tell a
reconnect loop from an operator opening sheets. Every detach now names the room,
how long the socket lived, and the code it closed on. When the ROOM ends first
the field says `room ended` rather than `None`: that is a different detach from
any a client can cause, and a bare `None` reads as a logging bug rather than as
the fact it is. Both fixes are @baud's r5 diagnosis of an incident on the owner's
own seat, and neither is LIVE — the production server on 8787 still predates
them, along with the cache-control fixes below, until the restart window
@devpulse holds. Nine tests, six mutations, all bitten. The honest cost: +55
lines put `server.py` at 1533 against a 1500 cap, and the answer is a split
(the pump and its control handler are self-contained), not a trim.*

*Three findings arrived from other people's instruments in one night, and two
of them were the same defect wearing different clothes. THE PHONE FACE was
served with an etag, a last-modified and NO cache-control — which is not "do not
cache" but "guess", and RFC 9111's heuristic guess is ~10% of the age since
last-modified. The entry is un-hashed and NAMES the content-hashed bundles, so a
stale entry faithfully fetches OLD assets; the owner's first reload served a
round-3 bundle and cost an acceptance round a false FAIL. Every stable-named
file revalidates now, including `/phone.html` — the manifest's own start_url,
which a narrow fix would have left stale for every installed phone while the
typed URL looked fixed. `/assets` keeps its caching: a hashed name cannot go
stale. And `no-cache` only means "ask first" if this server ANSWERS conditional
requests, which it never did — starlette's FileResponse sets an etag and ignores
If-None-Match — so that got closed too, with starlette's own comparison rather
than a copy of it.*

*THE GIT LANE was re-asking a question it already had the answer to, 720 times
an hour. A phone polls every 5 seconds; for an external project whose branch
carries no passport, drone refuses the caller before the door runs, and every
poll spawned a subprocess that was never going to work and warned in three
places across two branches' logs. What is remembered is drone's ANSWER, never
drone's rule — checking for a passport here would be reimplementing another
branch's authentication and drifting from it in the worst direction. A 60-second
window means a root that gains a passport recovers on its own.*

*AND THE SERVER GAINED A LIFETIME. `serve` routed through drone is a child of
drone's exec timeout, so the tailnet server was dying on a twelve-hour schedule;
the restarts cost more than the downtime, because uvicorn's access log goes to
stdout, stdout was a tmux pane, and a day of access history scrolled out of a
bounded scrollback right when it was needed. `serve --detach` gives the process
its own session and its output an appended file, with `status` and `stop`
because shipping the first without them is a nicer way to make orphans. It does
NOT restart anything — a dead server that stays dead and says so is the honest
failure. The first live start/stop found a bug twenty-two mocked tests could
not: a reaped-but-not-waited child is a zombie, and `os.kill(pid, 0)` says yes
to a corpse.*

*`--out` became OPTIONAL, and that is a security fix rather than a
convenience. The rule was never "make the caller name a file", it was S49's
"never print the raw value" — and the mandatory flag defended it badly, because
its own example said `--out ~/pixel.token`. The owner found three raw bearer
receipts sitting in his home root on 2026-08-19, 43 bytes each, put there by
whoever read my help text and did what it said. The receipt lands beside the
hashed store now (`~/.secrets/aipass/host_api/<label>.token`, dir 0700, file
0600). That turns a free-form label into a FILENAME, which is the one thing it
could never reach before, so the label now goes through the same two-gate name
fence the routes use: refuse the sentence up front, check containment after
resolving. Refusing an existing receipt is the other half — the token it names
is still LIVE in the store, and truncating the file leaves a working credential
nobody holds and nobody thinks to revoke.*

*The name fence gained ROOTS (FPLAN-0443). It answered exactly one kind of
word — a citizen name — which is why the phone could only ever stand in
agent-land; it answers four now (`branch`, `home`, `project`, `aipass`) and
`GET /v1/roots` publishes the roster so the face renders what the server
holds rather than a list it guessed. The widening is the roster and not the
rule: the client still sends a NAME, the server still resolves it, and the
same containment runs under all four. A request that names no root gets the
branch answer it always got, key for key.*

*The read lane came OFF the event loop (DPLAN-0305). Every route was
`async def` and none of them awaited anything, so each blocking body — a
90ms `baud --snapshot`, a git exec, a registry walk — held the single
worker's loop and the whole phone froze behind it, terminal socket included.
The 18 routes that do work are plain `def` now and run in the threadpool;
`/v1/ping` and `/v1/whoami` stay async because they hold no blocking work,
and the write routes stay async DELIBERATELY — the loop is their only
serialization until settings grows a lock. The snapshot is coalesced (one
exec per question per 1.5s, and one exec per stampede, so `/v1/fleet` and
`/v1/rooms` stop paying twice for the same read), the registry is pinned
once at boot instead of re-walked per lookup, and the audit trail's caller
detection fetches ONE frame rather than building the whole stack. The find
while measuring: the socket pump used asyncio's default executor, which
sizes itself to eight threads on this host — the ninth terminal connected,
authenticated, and then silently never pumped. Its own pool now, and the cap
is a sentence instead of a blank screen.*

*The perf round's own tests then went red in CI, and three of the four were
tests measuring their runner rather than their subject. The caller-detection
pin demanded the name `test_host_perf` and got `conftest`, because the
repo-root conftest WRAPS `log_operation` to keep parallel runs off shared
files — so the caller of `log_operation` really is that wrapper. Measured
before blaming the change: `inspect.stack()[2]` returns the same frame, so
the old implementation named `conftest` too and this test was simply the
first thing in the tree ever to look. That pin no longer exists here: it
compared api's own `_get_caller_module_name` against an `inspect.stack()` walk,
and DPLAN-0325 replaced both with prax's one service on 09-04, so the comparison
has no subject in this tree. Section 4 of `test_host_perf.py` is archived
verbatim under `tests/.archive/deleted_2026-09-04_test_host_perf_caller_detection.py`,
and its two surviving claims moved into seedgo's fleet contract. The TTL test failed on
Windows only because `time.monotonic` advances there in ~15.6ms steps, so two
reads landed on one tick and `0.0 > 0.0` is false; it drives its own clock
now and sleeps not at all. The pump's POSIX-only machinery patches the
module-level `pty` name rather than an attribute on it (`pty` is None on
Windows), and the one test that genuinely needs SIGHUP skips where SIGHUP
does not exist — honestly, because `open_attach` refuses on that platform
long before a session exists to hang up. Verified against a probe that hides
`pty` and deletes `signal.SIGHUP`: 1463 pass, 36 POSIX skips, one of them
mine.*

*The park gained a real barrier on @memory's proof: `(disabled)` is a naming
habit and dropping the `test_` prefix is what actually keeps a file out of
collection — so `tests/parked/` now carries `collect_ignore_glob` and a pin
that drops a deliberately `test_`-named intruder in to prove it holds.*

*The gateway_boundary line is answered by a bypass entry with its own
retirement clause (no owner door exists at @aipass yet, ruling pending), so
the audit reads 100 with the standing exception on the record rather than
hidden.*

*The two long-standing exceptions before that are gone rather than
documented: the attach route's nesting went when the room resolution and the
PTY pump moved out of the app factory — both already took everything they
used as arguments, so there was never a closure holding them in — and
`settings.py`'s silent catches went when each one was given the honest answer
it was hiding (an unreadable settings file is a fault, not a blank document).*

---

[← api README](../README.md)
