# Tests and quality — what is pinned, and how to measure it

**Branch** spawn · **Code** `tests/`, `.seedgo/bypass.json`
**Moved out of README.md** (DPLAN-0347, the layer contract).

Nothing here states a current score. The numbers move with the code, so this page names the
command that produces each one instead of a snapshot that starts rotting the day it is
written.

---

## How to measure

| Question | The command that answers it |
|---|---|
| Does the suite pass, and how many cases? | `pytest -q` from this directory, and again from the repository root — both rootdirs must agree |
| The CI shape | `pytest -q -p no:cacheprovider` |
| Standards score, violations, bypasses | `drone @seedgo audit aipass @spawn` |
| The honest score with every bypass off | `drone @seedgo audit aipass @spawn --no-bypass` |
| Which public functions have no test | `drone @seedgo test_map @spawn` |
| Startup cost against each layer's cap | `drone @seedgo audit context @spawn` |

A test count claimed in prose is a number with no owner. The AST count seedgo measures and a
`grep` for `def test_` disagree by a handful, because grep counts lines inside docstrings and
comments — which is how this branch's own README once carried two different totals in two
sections. One number, one method, produced live.

---

## What each test file pins

| File | Focus |
|------|-------|
| `test_lifecycle.py` | End-to-end spawn lifecycle workflows |
| `test_json_handler.py` | The shim's wiring to the fleet json service — the seam, the binding, the bool contract |
| `test_handlers.py` | Handler function behaviour and integration |
| `test_modules_gateway.py` | The modules-package gateway other branches import through |
| `test_passport_migration.py` | Passport 1.x → 2.0 fleet migration: order, drops, renames, idempotency |
| `test_passport_birth_schema.py` | The 2.0 block and key order on a newly minted passport |
| `test_regenerate_registry_ops.py` | Template registry regeneration |
| `test_update.py` | Update mechanics: the walk, the list policy, the passport heal, `.updateignore`, markdown drift |
| `test_citizen_classes.py` | Citizen class validation and template discovery |
| `test_file_ops.py` | File copy, rename, placeholder replacement |
| `test_cli_routing.py` | Command routing and argument parsing |
| `test_contracts.py` | Handler contracts and interface compliance |
| `test_spawn.py` | Basic CLI routing and help |
| `test_error_resilience.py` | Error handling and edge cases |
| `test_check_fix_identity.py` | Owner and identity check and fix |
| `test_admin_fence.py` | The admin grant ceremony and the permanent admin-class refusal |
| `test_owner_resolver.py` | Owner resolution and the `is_protected()` layers |
| `test_passport_drift.py` | Fleet passport drift canary |
| `test_template_hygiene.py` | Template content invariants |
| `test_output_streams.py` | stdout and stderr routing |
| `test_repair.py` | Structural repair and relocation |
| `test_citizen_id.py` | `citizen_id` minted once — passport and registry entry always agree |
| `test_registry_credential.py` | Credential mint asymmetry: a missing registry mints, an unreadable one never does |
| `test_json_durability.py` | Torn-write durability — atomic writes across every JSON and text path |
| `test_birth_receipt.py` | The birth receipt lane, the seed-vs-gold drift pins, the newborn budget contract, and that retirement carries the memories |
| `test_passport_seeds.py` | Passport seeds — the tracked identity that ships with the repository |
| `test_template_import_guard.py` | What a newborn's handler guard must survive on its first import |
| `test_conftest_fixtures.py` | Pins that this branch's own mocking fixtures reach the code they claim to mock |
| `conftest.py` | Fixtures: mock templates, registry protection |

---

## Conventions that keep the suite honest

- **The registry is protected.** A session fixture backs up and restores
  `AIPASS_REGISTRY.json`, because minting a citizen in a test writes to the real one.
- **A skip is a defect until proven otherwise.** A test that skips because a fixture is
  missing reports green while testing nothing; the cure is to assert both worlds — present
  pins the values, absent pins that the replacement is total.
- **A caps number is read from its owner**, never copied into a test. The newborn budget
  pins fail if a literal appears in the file.
- **Mutation before belief.** A pin is trusted once the code it names has been broken and
  the pin went red, with the byte-cache purged between runs so a stale `__pycache__` cannot
  answer for the mutant.

---

## Bypasses

`.seedgo/bypass.json` holds this branch's standards exemptions, each with a written reason.
The pure-utility handlers carry a `json_structure` bypass because they perform no operation
to log; the operation they inform is logged at the site that performs it. The list and the
reasons are read with the audit — a bypass whose reason no longer holds is a finding, not
furniture.

---

**Last Updated:** 2026-09-15
