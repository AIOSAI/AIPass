[<- Back to the README](../README.md)

# The kv module

A key/value store: `kv store.txt set colour red` files a value, and the run
after it reads the value back. `apps/modules/kv.py` routes, counts arguments and
prints; `apps/handlers/kv/store.py` reads the file, rewrites it, and owns every
refusal that is about the store rather than about the command line.

It exists as a test subject, not as a feature. Built to a dispatched contract
(@devpulse, 2026-09-20) whose interesting half is that this is the first canary
command that **writes**: the questions worth answering are what a refused call
leaves on disk, what happens to a store the command cannot parse, and which of
the caller's own words are allowed to look like flags.

## The verbs

| Form | What happens |
|------|--------------|
| `kv FILE set KEY VALUE` | Files the value. Prints nothing, exits 0. Creates the store if it is not there |
| `kv FILE get KEY` | Prints that value and a newline. Nothing else reaches stdout |
| `kv FILE delete KEY` | Removes the pair. Prints nothing, exits 0 |
| `kv FILE list` | Every pair as the key, one tab, the value — sorted by key |
| `kv --json FILE list` | The same pairs as one JSON object, in the same order |
| `kv` | The module's short map, exit 0. `kv --help` is the full page |

Setting a key that is already there replaces its value **where it already
sits** — the file keeps insertion order, and only `list` sorts.

## The store

Plain UTF-8 text, one pair per line: the key, a single tab, then the value,
terminated by `\n`. Keys are unique.

```
colour	red
size	big
```

- **`list` sorts by key in ascending code point order** — the order `sorted()`
  gives, so `Z` comes before `a` and no locale or case folding is involved.
- **A missing final newline is read, and repaired by the next write.** This file
  may be somebody else's; an unterminated last line is how half the world's text
  files end.
- **A CRLF store reads the same as an LF one.** One trailing carriage return per
  line is a line ending, not data.
- **Deleting the last pair leaves an empty file, not a missing one.** An empty
  store is a store: `list` prints nothing and exits 0.

## The rulings

Six places where the contract was silent, each decided once and written where a
reader of the code will hit it. The full reasoning lives in the handler
docstring; these are the decisions and what each one costs.

**A store that is not on disk is refused, not treated as empty.** `set` creates
the file — the contract says so — but `get`, `delete` and `list` all refuse
`store not found`. The alternative, reading a missing file as an empty store,
means a typo in a path prints nothing and exits 0, and this branch exists to
catch exactly that species of silence. It matches `table/aligner.py`, which
already refuses a missing table rather than reading it as an empty one.
*The cost:* a caller who wants "empty or absent, I do not mind" has to check
first.

**A carriage return is refused in a KEY and in a VALUE, and one on the end of a
line is stripped when reading.** The contract names the tab and the newline
only. Without the strip, every value in a store written on Windows comes back
with a stray byte on the end; with the strip and no refusal, a value that
genuinely ended in a carriage return would come back silently shortened.
Refusing the character on the way in means the strip can only ever affect a
foreign write. *The cost:* a value holding a carriage return cannot be stored
here at all, and the refusal says so.

**Only `\n` ends a line.** `str.splitlines()` also breaks on a vertical tab, a
form feed and ` `. Those are ordinary characters inside a value somebody
stored on purpose, so splitting on them would turn one pair into two unreadable
lines. The read uses `split("\n")`. *The cost:* none that has shown up; a store
written with `\r` alone as its line ending is not read as lines.

**A duplicate key in the file is refused, naming both lines.** Last-wins or
first-wins silently drops a pair somebody else wrote. This command never writes
a duplicate, so one can only arrive from a foreign write — which is exactly when
a caller needs to be told rather than quietly corrected.

**An empty VALUE is stored; an empty KEY stays refused.** `k<tab>` is still a
key, a tab and a value, and it round-trips. The contract refuses the empty key
by name, and a line starting with the tab would put the store's only structure
in its first byte.

**`--json` is a flag in first position only; a help flag is one anywhere.** The
contract spells the JSON form `kv --json FILE list`, and after that first word
every argument is the caller's own text — `kv store.txt set --json red` files a
key named `--json` rather than switching format. Reading it as a flag anywhere
would never do the wrong thing quietly (stripped out of a data position it
leaves `set` with one operand, which refuses), so the narrow reading costs
nothing and keeps a caller's own word storable.

A help flag is the opposite case. `kv store.txt set --help colour` is somebody
who does not know the verb yet, and storing a pair in answer to a question is
exactly the harm @seedgo's `help_flag_safety` standard was written for — it
exists because `drone @memory rollover push --help` once performed the reset it
was asked to describe. So `--help` and `-h` explain from any position, like
every other module in this branch. *The cost:* a key or a value spelled
`--help` or `-h` cannot be set or looked up from the command line. The bare word
`help` stays in first position, because `help` is a plausible value.

This ruling was made the other way first and withdrawn. The first version
protected caller data everywhere, which reads well until the position being
protected is on a command that writes.

## The write

A `set` or a `delete` rewrites the whole file, so the write is the part that can
lose data. Three things guard it:

1. **The existing store is parsed first.** A store that will not parse refuses
   before the file is opened for writing. A command that "repairs" a file it
   cannot read has destroyed whatever was actually in it.
2. **The new content is written to a temporary file in the same directory and
   moved over the old one.** A reader during a write sees one whole version or
   the other, never half of each. Same directory on purpose: a move across
   filesystems is a copy, and a copy is interruptible.
3. **The mode is carried over.** An existing store keeps the permissions it had;
   a new one gets what the umask would have given it. Measured 2026-09-20:
   without that correction the first store landed `0600`, because that is what
   `tempfile` creates — quietly more private than the caller's own shell makes a
   file.

A missing parent directory is a refusal. Creating the file is in the contract;
building a directory tree is not.

## The refusals

Every one of them exits 2, prints the reason to stderr, and writes **nothing**
to stdout. This command's stdout is a value somebody is about to use, so a
half-answer printed beside a refusal would be read as the value.

| Input | Refused as |
|-------|-----------|
| `kv --json` | no FILE given |
| `kv FILE` | no verb given (one of: set, get, delete, list) |
| `kv FILE frobnicate` | *'frobnicate'* is not a kv verb |
| `kv FILE set KEY` | set with no VALUE (key *KEY*) |
| `kv FILE set` | set needs a KEY and a VALUE (neither given) |
| `kv FILE get` / `delete` | *verb* needs a KEY |
| any verb with a word too many | too many arguments for *verb* (then: *extra*) |
| `--json` on set, get or delete | --json is only for list, not *verb* |
| an empty key | KEY is empty |
| a key or value holding a tab, newline or carriage return | KEY/VALUE contains *a tab* (…) |
| `get` or `delete` naming a key that is not there | no such key: *'k'* in *path* |
| a store that is not on disk | store not found: *path* |
| a directory, or a file that will not open | cannot read *path* (*reason*) |
| a file with a byte that is not UTF-8 | not valid UTF-8, with the byte offset |
| a line with no tab, or with more than one | line *n* is not a key, a tab and a value (*no tab* / *k tabs*) |
| a line starting with the tab | line *n* has an empty key |
| the same key on two lines | line *n* repeats the key *'k'* (first on line *m*) |
| `set` into a directory that is not there | cannot write *path*: the directory *dir* is not there |

The key is checked before the file is opened, so `get` with a key holding a tab
is refused as an unstorable key rather than as a missing one — the store could
not have been holding it.

## The refusal trail

Every refusal in the handler goes through one `_refuse()`, which records
`kv_refused` with its reason on the json operation trail before raising. The
refusals worth counting are the ones nobody was watching: a duplicate key on
line 400 of a store written by something else is the interesting half of this
command, and a reason that only ever reached a terminal is one nobody can count
afterwards.

## Why list writes to stdout directly

The contract says the key, **a single tab**, and the value. The shared `@cli`
console renders through rich, which expands a tab to the next 8-column tab stop:
`console.print("a\tb")` puts `a` and seven spaces on the line (measured
2026-09-20). So `list` and `get` write to `sys.stdout` and the JSON form with
them, which keeps all three forms carrying exactly what the store holds.
Refusals and help keep the shared console, so this branch's error contract is
unchanged.

## What the tests actually measure

91 tests in `tests/test_kv.py`, driven through the entry point's `main()` with
real module discovery, so the exit codes asserted are the ones drone hands a
caller. Three of them exist because this command writes:

- **The bytes on disk**, not just what comes back out. `set` then `get` would
  pass on a store that kept its pairs in JSON, in reverse, or in memory. The
  line format is read raw, with the tab counted.
- **What a refused call leaves behind.** A store that will not parse comes out
  of a refused `set` byte for byte unchanged; a delete of a key that is not
  there leaves the file alone; a refused `set` does not half-create the file.
- **A single tab.** An assertion that only looked for the key and the value
  would pass on the space-padded version.

25 mutants were run against the pair, all 25 killed — including the four worth
naming, because each one is a real bug that looks like a tidy-up: `splitlines()`
for `split("\n")` (a value with a vertical tab in it becomes two broken lines),
`console.print` for the direct write (the tab becomes spaces), treating `--json`
as a flag wherever it appears (a key named `--json` stops being storable), and
gating help at the first argument only (`set --help colour` writes instead of
explaining). The umask correction has a mutant too: pinned to `0600`, the
created store is measurably more private than the caller's own files.

[<- Back to the branch README](../README.md)
