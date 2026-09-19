[<- Back to the README](../README.md)

# Nightly Rounds

How the nightly rounds job wakes one citizen a night for a maintenance turn, and what scope and budget apply to it.

---

The night watch doing its rounds (2026-09-10, DPLAN-0337 R2): one citizen a night, woken fresh on opus for a maintenance turn inside its own branch. Designed in August as DPLAN-0287, shipped disabled as `fleet-steward`, renamed `rounds` and switched on by the owner's ruling of 2026-09-10.

| Knob | Value |
|------|-------|
| Job | `@daemon/rounds`, type `rotation`, in daemon's `.daemon/schedule.json` |
| When | 05:00 window (+/-15 min — the first tick inside it fires, so about 04:45); `catch_up` off, a missed night is not woken late |
| Who | **Framework fleet only** — citizens whose branch lives under this install's `src/aipass/` (17 on 2026-09-10). `projects/*` residents and every external root are out, whatever their class. Alphabetical by email. `@devpulse` never; managers excluded (`include_managers: false`) |
| Wake | `fresh: true`, `model: opus`, `sender: @daemon`, `wake_back: false` |
| Busy target | Logged as a miss, pointer advances, that citizen gets its next turn in the cycle |

**Scope, by ruling.** The owner, 2026-09-10 21:47, marked very important: the rounds are AIPass maintaining its own agents. Vera keeps her own schedule, and the projects are nowhere near a trust stage. `ROSTER_SCOPE` in `apps/handlers/schedule/rotation.py` is a named rule applied inside `build_roster` before any passport is read. It is decided on the branch PATH, never on the tier label, which stays presentation-only. `drone @daemon rotation` prints it on its `Scope:` line. Pinned by `TestRoundsScope`: a temp install holding a framework branch, a projects resident and an external-root citizen, all declaring the same class, serves only the first.

**What a citizen does on its night:** inbox to zero; reconcile `.trinity` todos against reality; refresh and read its dashboard; review its logs; run its seedgo self-audit; do mailed-in work only if it sits in its own domain and fits one session; small fixes in its own branch, red-first.

**Budget, stated in the prompt:** never dispatch or wake another citizen; at most 2 sub-agents, sonnet or lower; never edit another branch; no fleet-wide investigations; anything out of lane is written down for @devpulse, not chased.

**The night's one artefact** is a single mail to @devpulse: health verdict, what it did, what it noticed, what it needs. There is no dispatch to reply to — a rounds wake is a session prompt, not a mail — and no APLAN step.

`drone @daemon rotation` shows the roster, whose night is next, and the last ten turns. Pinned by `TestShippedRoundsJob` (the stanza as shipped) and `TestRoundsNight` (a real tick at 05:01, wake caught at ai_mail's `wake_branch` seam).
