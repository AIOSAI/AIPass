# Docs

Tracked public reference for the `hooks` branch — the **depth** layer of the DPLAN-0347 contract: one
file per module or handler group, each small enough for one read, each linked from the branch README,
opened when something breaks.

Work in progress, research and dated one-offs belong in `docs.local/`, not here. Anything on this
shelf is committed — write it as if it ships.

| File | What it covers |
|---|---|
| [wiring.md](wiring.md) | The two-tier hook model, every event and its wiring shape, entry names vs handler filenames, and what a new handler needs in provider settings |
| [engine.md](engine.md) | Dispatch, the merged output document, dynamic handler import, and the import-time working-directory rule |
| [project_config.md](project_config.md) | `hooks.json` and the project template, the trust hash and the re-enrol, the retired watchdog, and the release notice |
| [git_gate.md](git_gate.md) | The closed allow-list of raw git verbs, what it protects, and how a project disables it |
| [edit_gate.md](edit_gate.md) | The branch and project fences, the direction table, and the verified admin-seat exemption |
| [bash_writes.md](bash_writes.md) | The scripted lane: which write targets a shell command can be seen to name, what it deliberately misses, and both Windows path spellings |
| [trinity_memory_gate.md](trinity_memory_gate.md) | Memory writes: the shell refusal, the tripwire, and how a write is judged on what it authors |
| [testwrite_gate.md](testwrite_gate.md) | The ruling that agents do not create tests, the policy file, and the fail-closed reasoning |
| [prompt_injection.md](prompt_injection.md) | The injection caps and where each is read from, the loud fail-open, and the alert banners |
| [diagnostics.md](diagnostics.md) | The two log streams and the post-edit diagnostics block |
| [sandbox.md](sandbox.md) | The kernel filesystem boundary: policy generation, what is writable per role, and the launch seam |
| [boot_shim.md](boot_shim.md) | The one script in this branch that writes outside the repo |
| [known_issues.md](known_issues.md) | Open defects and stated-not-fixed items, each with its measurement |
| [cadence_investigation.md](cadence_investigation.md) | The per-turn injection counter: session keying, the execution model, and the fragility that was already true |
| [cadence_redo_brief.md](cadence_redo_brief.md) | The brief that rebuilt cadence after the suite modelled the wrong execution model — kept as the record of why the counter is deduped |

The live inventory of modules and commands is not written down here — it is `drone @hooks` and
`drone @hooks --help`, generated from code. The directory tree lives in the branch prompt
(`.aipass/aipass_local_prompt.md`), one place, so it cannot disagree with itself.
