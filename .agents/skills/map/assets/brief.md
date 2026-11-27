# Brief: map one slice of <TARGET NAME>

You are a read-only investigator. You map what the code DOES today, in plain English, so the owner can decide what to keep and what to strip. You change nothing. No git commands (blocked anyway). No tests run. Read code, read docs, run `<ENTRY> --help` where useful. Never run a command that writes: <FORBIDDEN COMMANDS, each named; a creating or installing verb only with --dry-run>.

Target root: <TARGET ROOT>
Repo root:   <REPO ROOT> (<what else lives there that the target reaches: a setup script, a launcher, hooks>)
Entry points: <the installed command and what its --help lists>

## Output: one JSON file, nothing else

Write ONLY to the path given in your slice. Shape:

```json
{
  "slice": "A",
  "summary": "3-6 plain sentences: what this slice does, for whom, and anything that looks like user hand-holding fluff against the core path the owner named.",
  "items": [
    {
      "id": "A01",
      "group": "<one of the groups below>",
      "name": "<the command or action as a user would name it>",
      "kind": "command",
      "invoked_by": "user, terminal",
      "file": "apps/modules/example.py",
      "lines": 210,
      "does": "One or two plain sentences. What it does, in order, as a user sees it.",
      "touches": "what it writes or changes on disk or in the repo (or 'nothing, read-only')",
      "depends_on": "other items by id or name, external tools, other branches",
      "tested_by": "tests/test_example.py (count of tests if quick to see)",
      "note": "optional: smells, fluff, dead code, duplicate of X, interactive prompts, chatty output"
    }
  ]
}
```

Rules for items:
- One item per distinct ACTION a user or the system can trigger: each command, each flag that changes behaviour, each subcommand, each step of a multi-step flow (steps are separate items), each handler that does real work, each hook or schedule the target registers, each shared helper other branches import.
- `kind` is one of: command, flag, subcommand, step, handler, helper, hook, schedule, doc, config, test-support.
- `does` is plain English a non-programmer reads once. No code in it.
- `group` is a short lowercase word from this list: <GROUPS, e.g. install, doctor, init, project, shared, hooks, docs, json, tests>.
- Ids are your slice letter + two digits, in reading order.
- Cover EVERYTHING in your slice. Missing an item is worse than a thin one. 40-80 items per slice is normal.
- Interactive prompts, progress spinners, chatty banners, "ask the AI" flows, onboarding or tutorial steps: flag them in `note` with the word FLUFF? (with the question mark; the owner decides).
- Anything already retired (in .archive/, or a design note says so) goes in ONE item per retired thing with kind "doc" and group "retired", so the owner sees it is already gone.

Limits: read-only; touched nothing; no test runs; no full suite; no coverage. Finish by writing the JSON file and replying with its path and the item count. If the file is invalid JSON your work is lost, so validate it with `python3 -I -c "import json,sys; json.load(open(sys.argv[1]))" <path>` before you reply.
