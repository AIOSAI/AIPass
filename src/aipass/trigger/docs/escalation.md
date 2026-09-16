# The escalation digest

**Branch** trigger · **Code** `apps/modules/escalation.py`, `apps/handlers/escalation.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

The verbs are in `drone @trigger escalation --help`. This page is what the lane counts, what
makes a signature, and every operator knob behind it.

---

Medic answers an error **once**: it dispatches the owning branch, then goes quiet — backoff, a mute, or a suppression keeps it quiet. That is correct for agents and blind for humans. An error still firing after its owner was told, or while a branch is muted, was invisible to the operator forever. Warnings were worse: they had **no escalation path at all**.

The escalation lane counts repetition and mails the operator when repetition means nothing got fixed:

> same signature, >= threshold occurrences inside the window → **one email** to the digest recipient → per-signature cooldown so the same noise cannot spam the mailbox

**Two tiers:**

| Tier | Covers | Escalates when |
|---|---|---|
| 1 — Warnings | Any repeating WARNING signature | Threshold crossed. Warnings have no dispatch path anywhere, so repetition alone is the signal |
| 2 — Errors past medic | ERROR signatures still recurring after medic acted | Owner already dispatched, branch muted, medic off, or no registered owner to dispatch to |

**Counting is unconditional; only sending is gated.** `record_error()` runs *before* every dispatch gate in `error_detected.py` — a mute stops re-dispatching, it must never stop the counting, or the repeat goes dark exactly when it matters most. A signature that never escalates is still fully auditable in the state file.

A deliberately **suppressed** fingerprint stays silent here too (compass #219 — a human already judged it benign), unless `escalate_suppressed` is turned on.

Digests are **email, never dispatch** (`auto_execute=False`). The default recipient `@devpulse` is a manager — wakes are blocked there, and the mail is meant to be read, not to spawn an agent.

**One signature, one message.** Digests are delivered with `upsert_key="escalation:<signature>"`, so a repeat *updates the existing message in place* — the counter climbs (`Updates: N`), the body refreshes to the latest numbers, read-state is preserved, and no notification fires. The key is the **signature**, never the rendered subject: the subject carries the repeat count and changes every digest, so keying on it would start a fresh thread each time. A digest that lands as an update is recorded as `upsert_action` in `logs/escalation.jsonl` and in the `escalation_digest_sent` operation, so an in-place update is auditable instead of looking like a digest that vanished. Cooldown semantics are unchanged — it now paces in-place updates rather than new mail, and `Digests sent` still counts every digest that left the branch. Closing the message ends the thread: the next digest creates a fresh one.

**What makes a signature.** `sha1(LEVEL|BRANCH|module|normalized_message)[:12]`. The message goes through the error registry's `normalize_message` (paths, timestamps, hashes, 3+ digit IDs), then through a second pass that is **local to this lane** — registry fingerprints keep their finer grain, so `errors list` and medic dispatch are untouched by anything here. That second pass collapses what varies between *repeats of one condition* rather than between errors:

| Collapsed | To | Why |
|---|---|---|
| Any standalone number, plus a short unit suffix (`20`, `1237ms`, `pid 4471`) | `<id>` | A climbing count or a duration is the same condition recurring. The suffix is load-bearing: there is no word boundary between digits and letters, so a bare `\b\d+\b` leaves `1237ms` alone |
| Registered citizen names, from `AIPASS_REGISTRY.json` (TTL-cached) | `<branch>` | "latest: log from SEEDGO" and "from PRAX" are one queue-full condition, not two |
| Any `@handle`, registered or not | `<branch>` | An unregistered name must not fragment what the registered ones unify |

The placeholder is `<id>` on purpose — the same token the registry normalizer emits for 3+ digits. A different token would make the two passes disagree at the 100 boundary, and `99 events` / `101 events` would keep minting separate signatures.

**Digest body carries the investigation:** signature, level, branch, module, occurrences in window, lifetime count, first/last seen, log file path, why it escalated, and the last N sample lines.

**Config knobs** — operator-editable, live in `trigger_json/custom_config/trigger.config.json` under `escalation` (S193 doctrine: the file on disk is runtime authority; `config_loader.DEFAULT_CONFIG` is only the regeneration seed):

| Knob | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Master switch — false records nothing, sends nothing |
| `digest_recipient` | `@devpulse` | Where digests land (email only, never a wake) |
| `warning_threshold` | `10` | WARNING occurrences in window before a digest |
| `error_threshold` | `5` | ERROR occurrences in window before a digest |
| `window_minutes` | `60` | Rolling window; older occurrences stop counting |
| `cooldown_minutes` | `360` | Per-signature silence after a digest fires |
| `sample_lines` | `3` | Sample log lines carried in the digest body |
| `max_signatures` | `500` | Cap on tracked signatures (least-recently-seen pruned) |
| `escalate_suppressed` | `false` | Escalate operator-suppressed fingerprints anyway |
| `watch_branch_log_warnings` | `true` | Parse WARNING lines out of branch logs |
| `ignore_branches` | `[]` | Branches never escalated (deliberate, like a volume mute) |

State lives at `trigger_json/escalation_state.json` — deliberately **not** a trio name (see [state_and_durability.md](state_and_durability.md)). The decision trail is `logs/escalation.jsonl` — `.jsonl`, not `.log`, so the branch watcher (which reads only `*.log`) cannot feed the lane its own output. It is written through `TrailLogger` (`apps/config.py`), the shared recursion-safe sink every trigger handler on the error path logs through; a write it cannot complete is counted on `.dropped` and surfaced as `Trail lines lost` in `escalation status` rather than discarded.


---

## Related

- [medic.md](medic.md) — the dispatch lane this one sits beside, and the mutes that never stop the counting
- [error_registry.md](error_registry.md) — the finer-grained fingerprints medic dispatches on
- [state_and_durability.md](state_and_durability.md) — why the decision trail is `.jsonl` and not `.log`
