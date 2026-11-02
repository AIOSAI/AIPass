[<- Back to the README](../README.md)

# Docs

Depth for the `CANARY` branch. The face is the [branch README](../README.md);
these pages are what it points at.

| Page | What it covers |
|------|----------------|
| [command_surface.md](command_surface.md) | Every routed form, the exit-code contract, subcommand help, and what the help pages were missing |
| [note_module.md](note_module.md) | The append-only note store: format, refusal, why it avoids the fleet json service, what its tests measure |
| [span_module.md](span_module.md) | The duration parser: the grammar, every refusal and why stdout stays empty, the JSON form, what its tests and mutants measure |
| [top_module.md](top_module.md) | The leaderboard reader: the file shape, the tie-break and why it is not insertion order, every refusal, what its tests and mutants measure |
| [testing.md](testing.md) | Running the suite, the conftest seam, what continuous integration actually runs |
| [branch_data.md](branch_data.md) | Everything this branch writes to disk: the json shim, `canary_json/`, `docs.local/`, `logs/`, archives |

The directory tree and the working gotchas live in the branch prompt,
`.aipass/aipass_local_prompt.md`, so they cannot disagree with themselves.

[<- Back to the branch README](../README.md)
