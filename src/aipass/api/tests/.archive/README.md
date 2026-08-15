# Parked tests

## test_host_terminal_superseded_capture_lane.py

63 tests for the capture lane as briefed in DPLAN-0300 **Round 18**: poll
`tmux capture-pane`, render the text on the phone, send keys back through a
14-name allowlist.

Patrick superseded that design as the TERMINAL lane four minutes after it was
briefed (Round 18b/18c). The sentence is worth keeping because it is the whole
difference:

> repaint-polling shows a PICTURE of the room that updates.
> attach gives you THE ROOM.

**Parked, not archived — and the distinction is @devpulse's ruling (2026-08-14).**
These are not a record of a wrong turn. Capture is the OTHER answer to a question
attach does not answer: an attached room is a shell prompt with the operator's
credentials at it, so it is `operate` by its nature and has no reading half.
Capture is therefore the only path to a look-do-not-touch view under a **read**
token, and that is a real future. @baud's `--capture-room` / `--send-room` flags
stay in the shipped binary on the same ruling — the flag and these tests stand or
fall together.

They do not run today: they reference `verbs.read_pane`, `verbs.send_keys`,
`fleet.capture_room` and `fleet.send_room`, which were removed from the server
when the terminal lane was rebuilt as `WS /v1/room/attach` (see
`test_host_attach.py`). Reviving the lane means restoring those functions; these
tests then describe what the lane must do.

Several of their arguments outlived the design and are cited elsewhere:
refuse-never-trim on a scrollback cap, the `{ok, detail}` split between "the
mechanism said no" and "the mechanism was never reached", and the D0
source-reading check.

Tracked deliberately: the root `.gitignore` swallows `.archive/` by default, and
a selective whitelist was added so a fresh clone can revive this rather than find
a README claiming files that are not there — same species as c48b3c65, where that
bare rule recorded @memory's park as a pure deletion.

Parked 2026-08-14.
