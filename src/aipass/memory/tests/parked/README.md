# tests/parked/ — code that is kept, not run

A park is a tracked home for code we deliberately stopped running but may want back.

**Why here and not `.archive/`.** Patrick's ruling, 2026-08-18, fleet-wide: `.archive/` is
always ignored, no exceptions, and it is his disposal zone — cleaned without warning. Bytes
kept there do not ship in a clone and are not safe from cleaning, so "parked, revivable" said
about an `.archive/` directory is a promise only this machine is keeping. Both parks below
moved out of `.archive/` that night, byte-identical. @api set the pattern.

**The `(disabled)` suffix.** Every `.py` in here is named `something(disabled).py`. That is
the house convention for code that is present but must not run, and it is load-bearing twice
over: the name is not a valid dotted path, so nothing can import it by accident; and pytest
collects `test_*.py`, so the four archived TEST files in `unwired_handlers_20260813/` would
otherwise be collected and run against code that left the tree. Strip the suffix to get the
name the file had, and must have again, on revival.

| Park | Ruling | What it holds | Revival condition (dated) |
|---|---|---|---|
| `symbolic_20260814/` | Patrick, 2026-08-14 — park the symbolic fragments tier, revivable; the active piece is Compass | 9 implementation files, 0 test units. Pinned by `tests/test_symbolic_parked.py`, which fails if any of them goes missing. | **2026-08-14, open.** Revives when the AUDN deduplicator records what a `Delete` verdict removed and why — the Agent Memory Atlas finding that parked it — and a live lane needs fragments back. Compass is the curated-truth piece until then. |
| `unwired_handlers_20260813/` | Owner call, 2026-08-13 — three handlers with no caller anywhere; wire-it-or-archive-it, all three archived | 5 implementation files + the 105 test units that covered them. | **2026-08-13, open.** Revives when a caller appears for any of `learnings`, `manager`/vectorize or `storage`. The park is the wiring: the tests come back with the handler they cover, not before. |
| `dead_template_lane_20260827/` | DPLAN-0318 marker 7, item 3 — `push-templates` / `diff-templates` scanned a pre-`.trinity` layout where zero real matches were possible | `pusher`, `differ`, the 67 test units that pinned them, and the fleet-side ledger the lane wrote. Retired, not revivable as-is. | **2026-08-27, none — kept as evidence, not for revival.** No plan revives this lane. It stays TRACKED for one measured reason: the live refusal points readers here by name (`tests/test_templates_lane.py::test_the_refusal_says_where_the_handlers_went` asserts the string `dead_template_lane_20260827` reaches the caller), and a path into an ignored directory is a refusal that lies. It moves only if that message stops naming it. |

**Why these conditions are written down (2026-09-08, FPLAN-0508 wave 8).** A park with no
dated condition is indistinguishable from a directory someone forgot. The rule the fleet
settled on: a park either carries a dated revival condition here, or it belongs in
`.archive/`. The third park carries no revival condition and is kept anyway — that is a
stated exception with a pin behind it, not an omission.

Each park's own `README.md` carries its evidence and its revival steps.

**Not parks:** the `recovery_*` directories still under `.archive/` are point-in-time
snapshots, not code we intend to revive. They stay disposable, which is what `.archive/` is
now for.
