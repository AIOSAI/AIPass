# Docker Dev-Verify Checklist

The dev container (`aipass-test:latest`) exists to test the CURRENT DEV BRANCH as a
cold machine: real GitHub clone, one-command install, no local state. The runner is
`tests/docker_dev_verify.sh`; this file is the contract for what a run must prove.

**Discipline (Patrick's rules, 2026-08-28):**
- Trust nothing — pytest green is NEVER proof; the container measures reality.
- Focus the target test, then have an independent sub-agent verify the same claim.
- Iterate: run → fix → push → run again. The script clones from GitHub, so every
  fix must be PUSHED to dev before a re-run can see it.
- When a check goes red, find the one root cause before counting the reds
  (one bootstrap refusal once cascaded into 8 FAILs).

## Run it

```
docker run --rm -v "$AIPASS_HOME/tests/docker_dev_verify.sh":/verify.sh:ro \
  aipass-test:latest bash /verify.sh
```

## The checks

### Phase 1 — clone
- [ ] `git clone -b dev` from GitHub succeeds; HEAD printed (verify it is the
      commit you think you are testing).

### Phase 2 — install
- [ ] `./aipass install` exits 0 on a cold machine, non-interactive.
- [ ] Registry generated (18 branches), branch bootstrap completes, no traceback.

### Phase 3 — provider settings (`~/.claude/settings.json`)
- [ ] Exists; SessionStart wired to the bridge with timeout 30.
- [ ] `AIPASS_HOME` in settings env.
- [ ] UserPromptSubmit ≥ 6 entries; PreCompact EXACTLY 8 (exact on purpose —
      drift canary for the installer's rendered hook set; update when hooks
      legitimately change).

### Phase 4 — project hook config
- [ ] `.aipass/hooks.json` + `project_hooks.json` carry SessionStart cadence_reset.

### Phase 5 — cadence live-fire
- [ ] startup → turn -1; resume writes no state; tier0/navmap periods 5/5.

### Phase 6 — misroute guidance
- [ ] `drone aipass`, `drone @aipass`, `aipass @drone`: guide, never crash.

### Phase 7 — passports built as intended (SEEDS, TDPLAN-0017)
- [ ] 18/18 branches with a tracked `.aipass/passport.seed.json` got a live
      `.trinity/passport.json` minted FROM THE SEED (not a blank template).
- [ ] Every stamp `citizenship.seed.sha256` == sha256 of the seed file bytes.
- [ ] Every `citizenship.registry_id` == the fresh registry's `metadata.id`.
- [ ] `identity` block byte-equal to the seed's (the soul ships verbatim).
- [ ] devpulse: `citizen_class` = manager, admin `class_extension` intact.
- [ ] `citizen_id` unique across the fleet (fresh uuid4 per branch, per machine).

### Phase 7b — idempotency (verified by independent audit 2026-08-28)
- [ ] A SECOND install in the same container changes zero `.trinity` json bytes,
      prints "exists (skipped)" for all 18, leaves AIPASS_REGISTRY.json
      byte-identical. Run the second pass as `bash setup.sh --no-chat` or with
      `AIPASS_HOME` exported — the `./aipass` launcher post-install forwards to
      the Python wizard, which without a tty and without `$AIPASS_HOME` prompts
      for a home and cancels on EOF (environment fact: setup.sh exports it to
      ~/.bashrc, which a non-login audit shell never sources). Known wart, @aipass
      lane: `aipass install --non-interactive` resolves to DEFAULT_HOME (~/AIPass)
      and ignores the clone you are standing in; `--here` is the flag that does
      the expected thing.

### Phase 8 — memory files (.trinity)
- [ ] `local.json` + `observations.json` exist for every seeded branch, valid JSON.
- [ ] No unreplaced `{PLACEHOLDER}` residue anywhere in them. (Keep this grep
      scoped to memory files: spawn's PASSPORT legitimately contains the prose
      "Replace all {{PLACEHOLDER}} patterns" in what_i_do — it comes verbatim
      from the seed and trips a naive `\{[A-Z_]+\}` scan if widened.)
- [ ] `*_meta` cap lines rendered (the `⟦ … ⟧` text from @memory's tab renderer —
      if missing, the memory extra failed to import during bootstrap and the
      ImportError fallback silently rendered nothing).

### Phase 9 — doctor
- [ ] `aipass doctor` runs to completion, no traceback.
- [ ] Output printed in full into the run log — READ it, don't count it.
      Compare against a local `aipass doctor` run: cold-machine reds must be the
      HONEST ones (no git identity, no API keys, admin lane dark = correct
      fail-closed) and none of the stale-bookkeeping species (entry_rid_stale /
      no_owner means the reconcile step regressed).

## After a green run
- [ ] Fire an independent sub-agent (opus/sonnet, never fable) to re-run the
      container and verify the passport/memory claims from scratch — the run
      that produced the green does not get to be its own verifier.
- [ ] Only then report satisfaction; Patrick does his live tests after that.
