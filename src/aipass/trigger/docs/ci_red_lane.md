[<- Back to the README](../README.md)

# The CI red lane

**Branch** trigger · **Code** `apps/modules/ci.py`, `apps/handlers/ci/`, `apps/handlers/events/ci_red.py`

A red CI run on dev wakes the branch that owns the failure. Its cure goes through one @seedgo
review and is pushed through drone's `ci-cure` door. @devpulse and the phone hear about each
step. A green run sends nothing. The verbs are in `drone @trigger ci --help`, and
`drone @trigger ci status` prints the ledger.

---

## Mechanism

1. **Poll.** `drone @trigger ci poll` runs as a command job from `.daemon/schedule.json`
   (`ci-poll`, every 10 minutes, no agent woken for the poll itself). It reads
   `drone @git run list` and records every dev run in the ledger. Only the **newest run per
   workflow** counts. An older red is marked `superseded` and never dispatched, and so is any
   of its cures still `queued` or `gated`: a run that a newer run (green or red) replaces
   closes its waiting cure with no dispatch. A cure whose owner is already awake keeps going.
   A new red is claimed in the same locked write (`triaging`, with a `claimed` stamp), so a
   second poll running at the same time skips it. A run whose log read fails is released for
   the next poll; a claim older than an hour belongs to a poll that died and is taken over.
2. **Triage.** For a new red, `drone @git run view <id> --log-failed` is read. The failing step
   is the one that carries `##[error]`. Owners come from the failing lines:
   - an audit line `<branch>: NN%` below 100 names that branch;
   - a `FAILED`/`ERROR` line holding `src/aipass/<branch>/` names that branch.
   A run that was cancelled or timed out, or that failed in a setup step (`Set up`, `Checkout`,
   `Initialize`, `Post`, `Run actions/`), is `infra`: one `red` feed event and no dispatch.
   A red that names no branch is `unowned`: @devpulse gets the excerpt by mail.
3. **Event.** The poll fires `ci_red` once per owner. The handler first counts the red in the
   escalation lane. Then it reports the red to the error registry (`error_type` `ci_red`,
   component = owner, message = workflow and step). So suppression, backoff and the digest
   apply to it the same way they apply to a repeating log error. Then medic's gates run, in
   medic's order, by calling the same functions in `error_detected.py`: medic enabled, branch
   not muted, registered citizen, suppression and backoff, then circuit breaker. A refusal goes
   to `logs/medic_suppressed.jsonl` and the cure becomes `gated`, with the refusal as its
   reason. Every poll fires `ci_red` again for each `gated` and `queued` cure. The gates run
   again and the refusal is logged once per poll, until a gate opens (the mute expires or is
   lifted, the breaker closes, the backoff ends) and the owner is dispatched. Only the first
   fire counts the red in the escalation lane and feeds the circuit breaker; a retry is not a
   new error. The handler claims the cure as `dispatching` under the ledger lock before the
   gates, so two fires at once wake the owner once; a `dispatching` claim older than an hour is
   retried like a `queued` one. Gate four still holds: an owner that is @devpulse is mailed and never woken.
4. **Owner.** The owner gets a dispatch: the mail, then a wake with @trigger as sender. The
   brief carries the run id, workflow, step, URL and failing lines. It says the owner has no
   git and asks for the owner reply shape below. When the owner exits, @trigger is woken back.
5. **Review.** On that wake-back the @trigger agent runs
   `drone @trigger ci reply <run_id> @<owner> "<reply body>"`. The verb parses the reply and
   reads `drone @git diff <files>`. Then it dispatches @seedgo once with the run id, the
   failing lines, the owner's note and the diff.
6. **Verdict.** On seedgo's wake-back the agent runs
   `drone @trigger ci verdict <run_id> @<owner> "<reply body>"`.
   - On `VERDICT: OK` the owner's bullet goes first under `## [Unreleased]` → `### Fixed` in the
     repo's `CHANGELOG.md`, and then the door runs:
     `drone @git ci-cure <run_id> @<owner> "fix(<owner>): <what>, run <id>" <files...> CHANGELOG.md`.
   - On `VERDICT: HELD`, or when the door does not push, @devpulse gets the diff and the reason,
     and `CHANGELOG.md` goes back to what it was.
7. **Proof.** A later poll finds the first run of the same workflow created after the push.
   That run is the proving run. @devpulse gets one `[CI PUSHED]` note naming it, with the owner's
   note and seedgo's lesson. When the proving run passes, the cure becomes `cured` and @devpulse
   gets one `[CI GREEN]` note. When it fails, the cure becomes `unproven` and the new red goes
   through the lane like any other red.

## The two-awake cap

At most two citizens are awake. The count comes from ai_mail's public
`outstanding_dispatches()`: the distinct targets of open dispatches, leaving out rows whose
monitor is known dead (`monitor_alive: false`) and overdue rows. When the register cannot be
read, the cap counts as full. A wake that would be the third is queued in the ledger, as
`queued` for an owner or `review_queued` for seedgo, and the next poll sends it. The @trigger
agent on a wake-back counts as awake. The owner wake and the seedgo wake come one after the
other, so the lane never holds two wakes at once.

## Ledger

`trigger_json/ci_ledger.json` is written with `atomic_write_json` under `json_file_lock`
(`ci_ledger.lock`). It is not named like `<module>_<config|data|log>.json` because the fleet
json service regenerates files with those names.

```json
{"version": 1,
 "runs":  {"<run_id>": {"workflow", "event", "title", "created", "status", "conclusion",
                        "verdict": "running|triaging|green|red|infra|unowned|superseded",
                        "triaged", "claimed", "step", "url"}},
 "cures": {"<run_id>@<owner>": {"run_id", "owner", "workflow", "step", "lines", "url",
                        "fingerprint", "state", "reason", "updated", "claimed",
                        "files", "changelog", "note", "diff", "verdict", "lesson",
                        "sha", "pushed_at", "proving_run"}}}
```

A cure's states are `dispatching`, `queued`, `gated`, `dispatched`, `emailed` (@devpulse as owner),
`replied`, `review_queued`, `reviewing`, `held`, `pushed`, `cured`, `unproven` and
`superseded`. An unreadable ledger raises: `ci` exits with an error, and the event handler
records a warning.

## Event payload

`ci_red` takes `run_id` (required), `workflow`, `step`, `owner`, `lines` (a list, or one string
split on newlines) and `url`. With no `owner` and no `lines`, the handler triages the run
itself. That is why `drone @trigger fire ci_red run_id=<id>` walks the whole lane for a real red.
Firing a cure again runs the gates again while it is `queued` or `gated`, and does nothing once
it has left those states.

## Reply shapes

**Owner**, to the `[CI RED] run <id> @<owner>` mail. Each label goes on its own line:

```
FILES:
src/aipass/<owner>/path.py
CHANGELOG:
- **One line for Unreleased** (@<owner>; files and versions)
NOTE:
What was wrong and why the cure is right.
```

The run is held when the reply has no `FILES:` block, when the block is empty, or when a path
is outside `src/aipass/<owner>/` and is not `CHANGELOG.md`.

**Seedgo**, to the `[CI REVIEW] run <id> @<owner>` mail. The first line must be `VERDICT: OK` or
`VERDICT: HELD`. On HELD the next lines give the reason. The rest is the checker lesson, which
goes to @devpulse in the pushed note. A reply in any other shape is refused and changes nothing.

## Notifications

Feed events use `kind` `system`, `source` `ci`, and
`extra = {run_id, workflow, step, owner, url, state}`. `state` is one of `red`, `dispatched`,
`pushed`, `green`, `held` or `unowned`. The title is one line of at most 120 characters.

| Moment | Feed | Mail |
|---|---|---|
| Red with an owner | `red`, then `dispatched` | owner's dispatch |
| Infra red | `red` | — |
| Unowned red | `unowned` | @devpulse, the excerpt |
| Seedgo asked | `dispatched` | @seedgo's dispatch |
| Held | `held` | @devpulse, diff and reason |
| Pushed | `pushed` | @devpulse once the proving run exists |
| Green after a cure | `green` | @devpulse, once |
| First-time green | — | — |

## Limits

- `drone @git diff` does not show untracked files, so the diff seedgo reviews leaves out a new
  file the cure adds.
- `projects/*` paths name no owner. Such a red is unowned.
- A `gated` cure waits for its gate. A 24h build mute holds it for up to 24h; `medic unmute @<owner>` sends it on the next poll.
- The poll reads only what `drone @git run list` returns (gh's newest 20 runs).
- The event path logs only to `logs/ci_lane.jsonl` and never through prax. The `ci` verbs log
  through prax at WARNING and below.

---

## Related

- [medic.md](medic.md) — the gates this lane reuses
- [events.md](events.md) — every event on the bus
- [state_and_durability.md](state_and_durability.md) — atomic writes, locks, and the trio names the ledger avoids
