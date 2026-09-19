[<- Back to the README](../README.md)

# Birth — how a citizen is minted

**Branch** spawn · **Code** `apps/modules/core.py`, `apps/handlers/` (`class_registry.py`,
`file_ops.py`, `placeholders.py`, `registry.py`, `meta_ops.py`, `mint_verify.py`,
`receipt_ops.py`, `adoption_ops.py`, `seed_ops.py`)

The verbs are in `drone @spawn --help`; the bare `drone @spawn` prints the live module
inventory. Everything below is what happens behind `create`.

---

## Citizen classes

Every branch belongs to a **citizen class**, which decides its template:

| Class | What it means |
|-------|---------------|
| `manager` | A project's first citizen — manages the project. ai_mail's wake-block keys on it: managers are emailed, never dispatched |
| `specialist` (default) | Every citizen minted after the first |

Both classes mint from the **one** template, `templates/citizen/` — the full three-layer
scaffold: `.trinity/`, `.aipass/`, `apps/` (modules and handlers including the json shim),
`tests/`, `docs/`, `logs/`. The class is a *behavioral* label in `identity.citizen_class`,
not a choice of scaffold shape (DPLAN-0319), which is why the template directory is named
for what it is rather than for a class.

**The class is decided at mint, not typed.** Citizen #1 of a project is born `manager`,
everyone after is `specialist`. An explicit class still wins if you pass one. The retired
names `aipass_framework`, `project_agent` and `builder` **refuse loudly** at every entry
point — they are never silently remapped, because a passport that quietly disagrees with
the value a caller typed is the exact drift the rename ends.

`admin` is permanently refused as a class or `--template` value — see
[registry_and_repair.md](registry_and_repair.md) for the ceremony that does grant it.

**Class is resolved from the passport, not guessed.** A leading positional is read as a
target path only when it is either a known class or carries an explicit path marker (a
separator, `~`, `.`/`..`, or `@`). A bare token with neither — `create wizard` — refuses by
name instead of silently making a branch called WIZARD in `./wizard` (APLAN-0007, fixed).

---

## The create pipeline (`_spawn_agent`, `core.py`)

1. **Resolve** — Extract the branch name from the target path and refuse a target that sits
   inside another citizen's tree (any parent holding `.trinity/passport.json`). An existing
   directory that already has a passport is **adopted** instead of refused (see Adoption).
2. **Lookup** — Resolve the citizen class to a template directory via `class_registry`.
3. **Credential** — Resolve the target project's registry credential (`metadata.id`)
   **before anything is written**. `load_registry` MINTS a fresh uuid4 when the registry
   file is **missing** — that is what a brand-new external project is, and it stops its
   first citizen inheriting AIPass's own id. A registry that **exists but will not parse**
   deliberately gets no mint (id-less schema plus a logged warning): that is a live project
   whose credential we failed to READ, and inventing a replacement would re-credential it
   and orphan every passport already carrying the real one. The resolved value is handed to
   `add_to_registry`, which adopts it **only when it is creating the registry file** — keyed
   off `registry_path.exists()` captured BEFORE the load, because a `load_registry` that
   always returns an id makes "is it already set?" useless as a guard.
4. **Copy** — Recursive copy of the class template to target (skips `__pycache__`).
5. **Rename** — Replace `{{BRANCH}}` in directory and file names.
6. **Replace** — Substitute all `{{PLACEHOLDER}}` patterns in file contents, including
   `{{CITIZEN_CLASS}}` (sourced from the create call, not a baked literal).
7. **Identity ids** — Mint the citizen's own UUID ONCE and use it twice: stamped into the
   passport as `citizenship.citizen_id` (the citizen's unique id, rendered by faces as the
   passport number) and written as the `registry_id` of its `branches[]` registry entry.
   Minting it at registration time instead would be too late — the passport is written
   before the registry, so the two copies would be different UUIDs for one citizen. Distinct
   from `citizenship.registry_id`, which is the id of the REGISTRY holding the citizen and is
   shared by every citizen in a project (the owner's ruling).
8. **Meta** — Generate `.spawn/.branch_meta.json`: the per-branch tracking file that maps
   each delivered file back to its **template file id** with a current SHA-256, matched by
   path first and content hash second. This is what lets `update` reason about a renamed or
   drifted file rather than diffing blind. Meta tabs load from @memory when available,
   degrading gracefully to empty when it is not.
9. **Verify** — Compare the minted tree against the template's own manifest
   (`.spawn/.template_registry.json`) and its on-disk contents. A file the template claims
   but the mint never produced REFUSES the create, names every missing path, and never
   reaches the registry — a gitignored template file once minted a citizen with an empty
   `artifacts/` and no `inbox.json` while printing "Agent created". Custom `--template`
   trees carry no manifest and are verified against their own contents only. The partial
   tree is deliberately left on disk for inspection.
10. **Receipt** — Stamp `.trinity/.template_version.json`: which trinity template version
    this citizen carries, in @memory's four-key shape (`template_versions`, `stamped`,
    `stamped_by: "spawn birth"`, `config_rendered`). The versions are read from the fleet's
    GOLD source (@memory's `templates/*.template.json` → `document_metadata.schema_version`),
    never from spawn's own seeds — reading the seeds would let a drifted copy mint a receipt
    claiming a version the fleet never issued, and the lie would score green. Shape copied,
    never imported: birth must not fail because another branch's package does not import. A
    gold source that cannot be read stamps NOTHING and surfaces the miss in
    `validation_issues` — a receipt naming an unverifiable version is worse than an absent
    one, but a citizen unborn because another branch's files are unreadable is worse than both.
11. **Registry** — Register in the target project's own `AIPASS_REGISTRY.json`. Placed after
    step 10 deliberately: a registered citizen always carries a receipt.
12. **Owner** — Ensure at least one citizen in that project carries `owner: true`.
13. **Validate** — Scan for any remaining `{{...}}` patterns.

---

## The birth contract — a newborn starts inside every cap

A newborn's startup files are measured against caps owned by other branches, and
`tests/test_birth_receipt.py` pins that the template stays under them: README against
@seedgo's published cap, the branch prompt against @hooks' `BRANCH_CHAR_BUDGET`,
`.trinity/` files and per-string length against @memory's `file_budgets`, and the dashboard
against @prax's budget. Every number is read from its owner at assert time; a cap copied
into the test as a literal fails the suite by design (DPLAN-0347).

The template also ships `DASHBOARD.local.json`, so a citizen is minted with its dashboard
already rendered. Birth depends on neither @flow nor @prax to create it, which is why
@flow's writer no longer creating a missing dashboard costs a newborn nothing.

What the newborn's own template carries is deliberately thin: the README is the face, the
branch prompt is breadcrumbs under a contract comment naming the cap's owner, and `docs/`
carries the convention that depth goes one file per module or handler group.

---

## Adoption (`create` against an existing directory)

1. **Fix** — Repair `registry_id` in the passport if stale (from registry recreation).
2. **Register** — Add to the project registry, then ensure the project has an owner.
3. **Receipt** — Stamp `.trinity/.template_version.json` **only if the directory has none**.
   Adoption fills a hole; it never restamps. A branch @memory's push already stamped carries
   `"memory push"`, and overwriting that with `"spawn birth"` would replace a true record of
   which lane last touched those files with a false one.
4. **Update** — Run the template update to sync scaffold files
   ([update_engine.md](update_engine.md)).

---

## Passport seeds

Each branch carries a tracked `.aipass/passport.seed.json` — the identity that ships with
the repository, with machine-local values stripped. `export-seeds` regenerates them from the
live passports (preview by default), and a mint can birth from a seed when one is present.
`tests/test_passport_seeds.py` pins the lane.

---

## Python API

```python
from aipass.spawn import spawn_agent

result = spawn_agent(
    "/path/to/new/agent",
    role="Data Analyst",
    purpose="Process incoming reports",
    traits="Precise, thorough"
)
# Returns on success: { success, branch_name, path, files_copied, dirs_created,
#                       files_skipped, renamed, registry_updated, registry_path,
#                       citizen_number, validation_issues }
# Returns on failure: { success: False, error, ...the same counters, zeroed }
```

---

## What a newborn scores

A citizen minted from `templates/citizen/` was measured against the CI gate and the trinity
checker and scored the floor on both. Those were one-day measurements; the way to know
today is to mint a throwaway citizen and run the audit against it rather than to trust a
number written here.

The starter suite that ships at birth (`tests/test_cli_routing.py`) is listed in the
template's `.spawn/.registry_ignore.json`: seedgo's architecture baseline treats every
template file as a structural requirement of **every** branch of that class, so adding one
without that entry drops existing branches below the gate. The exclusion is what keeps a
template addition from becoming a fleet-wide mandate.

A template test that pinned the json shim was archived when the fleet folded those
identities into a parametrised contract suite in @seedgo; the template stamped them into
every newborn, so keeping it would have regrown the twins one citizen at a time. A newborn
loses no coverage, because that suite discovers subjects by globbing the installed package
and the newborn ships the exact path it globs. The one gap, stated rather than papered over:
a citizen minted into ANOTHER project's tree is outside that glob and gets no contract
coverage from it. `tests/test_template_hygiene.py` pins the file's ABSENCE from the template.

---

**Last Updated:** 2026-09-15
