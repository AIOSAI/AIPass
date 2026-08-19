# Parked tests

Not an archive. `.archive/` is Patrick's disposal zone — always ignored,
cleaned without warning (his ruling, 2026-08-18) — so nothing that must
survive a clone may live there. This directory is TRACKED and ordinary.

Files here carry the house `(disabled)` suffix rather than a `test_` name, so
pytest's `python_files = test_*.py` never collects them. They are readable,
revivable, and cannot be mistaken for a suite that runs.

## host_terminal_capture_lane(disabled).py

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

Tracked deliberately, and that is the whole reason this moved. It lived in
`tests/.archive/` behind a selective `.gitignore` whitelist so a fresh clone
could revive it rather than find a README claiming files that are not there
(same species as c48b3c65, where the bare rule recorded @memory's park as a
pure deletion). Patrick's ruling of 2026-08-18 removed every `.archive/`
exception fleet-wide, which left this park ignored and untracked — a README
promising 63 tests nobody would receive. Rehomed here, tracked, same content,
renamed only to stay out of collection.

Parked 2026-08-14. Rehomed 2026-08-18.
