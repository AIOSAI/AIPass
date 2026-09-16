# Known issues

**Branch** spawn
**Moved out of README.md** (DPLAN-0347, the layer contract).

Open defects and deliberate limits, each with what is actually known about it. Anything
fixed leaves this page; anything unmeasured says so.

---

## By design, and it costs something

- **`.py` files never auto-update.** A template `.py` change reaches a branch only through a
  dispatch to that branch, never through `drone @spawn update`. The alternative — the engine
  overwriting live code — is what destroyed branches before the rewrite (DPLAN-0199).
- **Markdown is reported, never written.** The same reasoning one layer up: a README or
  prompt diet is owner judgment. See [update_engine.md](update_engine.md).
- **The scaffold smoke test ships at birth and is never re-added.** In a branch with a real
  conftest it can only skip, so it cannot inform. Spawn's own copy moved to `tests/.archive/`
  for that reason; the template still ships it to newborns.

---

## Open

- **Two registry entry shapes.** `AIPASS_REGISTRY.json` holds UPPERCASE-relative and
  lowercase-absolute entries side by side. Cosmetic — every reader is case-insensitive and
  path-shape agnostic — but a reader comparing entries sees two conventions. Normalising is
  not this branch's call to make unilaterally; see
  [registry_and_repair.md](registry_and_repair.md).
- **A branch's own `tools/` is gitignored fleet-wide**, so verification utilities there are
  machine-local and diverge between checkouts. The **template's** `tools/` is explicitly
  un-ignored and does ship to newborns — a fix belongs in the template copy, where it can
  actually be committed.
- **A citizen minted into another project's tree** is outside the glob that gives the fleet
  its json-handler contract coverage, so it gets none from that suite. Stated rather than
  papered over; the newborn is otherwise complete.
- **The registry-owner protection layer is unreachable in the live fleet.** Delete's three
  layers all work, but the second can only be reached by a branch that is not already
  refused at the first. It is covered by unit tests against a synthetic registry, not by
  live behaviour. See [retire.md](retire.md).
- **Suite writes into live json directories.** Some tests reach real json directories rather
  than a tmp path, because the shim binds its root at import time. The fix belongs at the
  consuming module, not in the test.

---

## Measured once, not re-measured

Where this branch used to publish a dated score — the newborn's audit result, the trinity
score, a live command sweep — the honest version is the command that reproduces it. Mint a
throwaway citizen and run the audit against it; run the suite from both rootdirs; run the
context audit for the startup cost. See [tests_and_quality.md](tests_and_quality.md).

---

**Last Updated:** 2026-09-15
