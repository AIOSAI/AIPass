# Docs

Tracked public reference for the `AIPASS` branch.

**This is the only one of the branch's four directories that rides the PR.** It is in
git's index, so anything written here ships to the public repo and strangers read it —
write accordingly. The other three (`docs.local/`, `dropbox/`, `artifacts/`) are
gitignored by design (`.gitignore` lines 55–58) and never leave this machine.

*Measured 2026-09-07 (FPLAN-0492 wave 6): `git ls-files` puts this README in the index
and the other three outside it.*

## The pages

One page per command group. The branch [README](../README.md) is the face; this is
the depth behind it.

| Page | What it covers |
|---|---|
| [init_and_install.md](init_and_install.md) | Every entry form of `install` and `init`, including the ones no help page names |
| [scaffold_update.md](scaffold_update.md) | The update ritual, the manifest hash rule, seeds, `.updateignore` |
| [doctor.md](doctor.md) | The seven groups, the flags, the provider wiring door, what it refuses |
| [help_chat.md](help_chat.md) | The keyword model behind `aipass help`, and `aipass read` |
| [trust_and_projects.md](trust_and_projects.md) | The enrolled hash, and `new` / `adopt` |
| [baud_phone_face.md](baud_phone_face.md) | Fetch, verify, unpack, swap, point — and every refusal |
| [admin_setup.md](admin_setup.md) | The admin lane: the five legs, the threat model, lighting it |
| [shared_contract.md](shared_contract.md) | `shared/`, the part of this branch @spawn imports |
| [known_issues.md](known_issues.md) | Open items, each verified against live code |
| [probe_hygiene.md](probe_hygiene.md) | How this branch probes the system without mutating it |
| [test_quality_tooling_research.md](test_quality_tooling_research.md) | Research: the test-quality tooling landscape |
| [test_suite_governance_research.md](test_suite_governance_research.md) | Research: governing a suite this size |

The two research reports are long-form and predate the page cap the rest of this
directory keeps to — read them with that in mind.
