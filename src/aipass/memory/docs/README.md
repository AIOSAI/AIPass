# Docs

Tracked public reference for the `memory` branch — the **depth** layer of the DPLAN-0347 contract:
one file per module or handler group, each small enough for one read, each linked from the branch
README, opened when something breaks.

Work in progress, research and dated one-offs belong in `docs.local/`, not here. Anything on this
shelf is committed — write it as if it ships.

| File | What it covers |
|---|---|
| [rollover_pipeline.md](rollover_pipeline.md) | The rollover engine: the pipeline, normalization, the safety valve, the newest-first guardrail, the one definition of the fleet and the external tier |
| [trinity_standard.md](trinity_standard.md) | The entry shape and the write gate: the closed field shape, `unknown_field` and `field_over_cap`, authored-versus-carried, the char caps, the renderer and the per-branch receipt |
| [trinity_push.md](trinity_push.md) | The push lane: vectorize → verify → prune, what counts as non-canonical, todos to the backlog, the scope and the two gates |
| [todos_and_backlog.md](todos_and_backlog.md) | The sticky-note pad and its backlog file — the roll, the restore, and why a non-canonical restore is refused |
| [todos_v2_shape_contract.md](todos_v2_shape_contract.md) | The todos v2 shape contract in full: the entry rules, the tab string, the `next #N` derivation, the backlog schema and the high-water floor |
| [config_verbs.md](config_verbs.md) | The rollover limit verbs, the keep-count ceiling computed from the file budgets, and the `--json` machine surface |
| [templates_and_tabs.md](templates_and_tabs.md) | The gold templates, the bump site, and the `*_meta` state tabs written into every memory file |
| [vector_search.md](vector_search.md) | The vector lane: subprocess isolation, `vectorize_and_store`, anchored plan-ID matching |
| [cli_surface.md](cli_surface.md) | How this branch's CLI behaves: exit codes on an unknown argument, help flags, `watch` as a module, and why a correct refusal must not become a runaway log |
| [quality_and_proof.md](quality_and_proof.md) | How this branch's suite is judged, what a parked test costs, and why dead code is archived rather than deleted |
| [known_issues.md](known_issues.md) | Known issues, each with the measurement behind it |

The live inventory of modules and commands is not written down here — it is `drone @memory` and
`drone @memory --help`, generated from code.
