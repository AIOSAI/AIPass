[<- Back to the README](../README.md)

# The test-write gate

**Branch** hooks · **Code** `apps/handlers/security/testwrite_gate.py`, `apps/modules/testgate_policy.py`, `apps/modules/testwrite_targets.py`

---

## The test-write gate — agents do not create tests right now

The owner ruled on 2026-09-01 (@devpulse `DPLAN-0323`) that agents are stripped of self-directed test
creation while @seedgo's `test_quality` v5 pack lands: the corpus being culled — tests written to
satisfy a checker rather than to pin a defect — regrows faster than a standards pack can cull it.
`security/testwrite_gate.py` is what stops the regrowth while the cull runs.

**Blocked:** *creation* of a pytest-collectable file (`test_*.py`, `*_test.py`, `conftest.py`) inside
a `tests/` tree, on **both** lanes — Edit/Write/MultiEdit/NotebookEdit and Bash (via the same
`bash_writes` parser the cross-project fence uses).

**Not blocked:** editing a test that already exists. An agent fixing a red test is doing legitimate
work; this ruling is about the corpus growing, not about freezing it. `block_test_edits` closes that
too — shipped `false`, but live rather than dormant, because a branch nobody has ever executed is not
a switch.

The policy is data, so later changes are field flips rather than rebuilds:

```jsonc
// <project>/.aipass/test_write_policy.json
{ "agent_test_writing": "off",   // "on" lifts it fleet-wide
  "allow": [],                   // one branch name here = the canary trial
  "block_test_edits": false,
  "note": "who ruled, and why" }
```

**Why its own file and not a key in `hooks.json`.** `hooks.json` is hash-enrolled in the trust
registry: every edit to it darks *every* hook for the project until a human re-runs `aipass trust`.
A switch meant to be flipped cannot live in a file whose every edit disables the engine that reads
it. Same directory, same walk-up, separate hash.

**The fail mode is closed** — for a missing policy *and* for an unreadable one. `bash_writes` allows
what it cannot parse, and that is right there for a reason that does not transfer: an unparseable
command taught the fence nothing *about that command*, so the policy question was never reached.
Here the file **is** the policy question, and "no answer" read as "allow" means the switch is
repealed by deleting one file. Two properties keep that survivable, and both have pins: the policy is
never read for a write that is not test-shaped (so ordinary work cannot be bricked), and writing the
policy file is not itself a test write (so the cure is always reachable from where you are).

The **admin seat** is checked *before* the policy read — through the same verified 5-leg grant rail
in `modules/admin_seat.py` that `edit_gate` uses — so cleanup work with the owner survives a broken
policy file. A crash inside the gate allows rather than walls: fail-closed covers a policy that could
not be *read*, not a defect that is ours.

**Naming a path is not writing it (1.2.0, 2026-09-19).** `bash_writes` reports every path an
interpreter is handed, which is the right breadth for `edit_gate`'s fence and the wrong breadth for
this gate's narrower question. Three seats were refused for commands that created nothing — @seedgo
for a one-liner that PRINTED a test path while measuring the fleet, @canary for a path literal in a
heredoc, this branch for both (devpulse DPLAN-0352). The reader now looks at the interpreter's OWN
text for a write verb, **in the grammar that text is written in** — `>` is a redirection in a shell
and a comparison in python — and appends `NO_WRITE_VERB` to the reason when it finds none. This gate
reads that marker and stands down; `edit_gate` ignores it and keeps the full breadth, because a path
an interpreter holds still cannot be told from one it writes.

The evidence is never claimed about text nobody read. An interpreter handed a **script file** keeps
the broad reading — the program is on disk, not in the command — and so does `awk`, whose program
arrives as a bare operand rather than behind `-c`/`-e` or a heredoc. Shelling out (`os.system`,
`subprocess`) counts as a write shape for the same reason: the verb is then inside a string this
parser does not read as code.

**What it deliberately does NOT catch** — published as data in `testwrite_targets.NOT_CAUGHT` and
printed by `drone @hooks testwrite`, so this list and the code cannot drift apart:

- a test file created outside any `tests/` directory — the gate reads the tree shape
- test data, fixtures and snapshots that are not `.py` (JSON corpora, `.txt` goldens)
- a new test appended *into* an existing test file — the deliberate cost of letting agents fix reds
- a test tree under a different directory name (`specs/`, `testing/`, `t/`)
- everything `bash_writes.NOT_CAUGHT` already lists, on the scripted lane
- a write made through a shape the write-verb vocabulary has no pattern for — the path is still
  reported, but without that evidence this gate stands down on it
- a file created by a process the command merely starts (a scaffolder, a generator)
- deletion or renaming of the policy file itself — this gate does not guard its own switch

**New projects inherit it.** `.aipass/project_hooks.json` — the template `aipass init` stamps —
carries the `testwrite_gate` entry, so the ruling is fleet-wide rather than AIPass-tree-wide.
`init` does **not** yet stamp a `test_write_policy.json`, so a freshly-created project lands on the
fail-closed missing-policy path; that refusal names the owner's ruling and the one-file opt-in, and
`TestTheProjectTemplateCarriesTheTestWriteGate` in `tests/test_live_config_timeouts.py` pins the
template entry against silent drift. Stamping a default policy is @aipass's call, not this branch's.

`registry_gate` is deliberately **not** in that template. It matches on filename shape alone
(`\w+_REGISTRY\.json$`) with no project-awareness, and its refusal hardcodes "use `drone @spawn`" —
correct inside AIPass, wrong advice for an unrelated project that happens to own its own
`FOO_REGISTRY.json`. That needs its own measurement, not a ride-along.

---

## Related

- [bash_writes.md](bash_writes.md) — the scripted lane this gate also reads
- [project_config.md](project_config.md) — the template entry that makes the ruling fleet-wide
