# Docs

Tracked public reference for the `API` branch — the depth that used to sit in the branch
README, one file per surface or handler group (DPLAN-0347, the layer contract). The README
is the face; these are what you open when something breaks.

| Doc | What it covers |
|---|---|
| [clients.md](clients.md) | The in-process Python API other branches import, and the contract registry |
| [host_api.md](host_api.md) | The Stage 0 host API: the bind rule, tokens, scopes, routes, the read cache |
| [host_surfaces.md](host_surfaces.md) | Scopes and verbs, the phone face, the fleet snapshot, the terminal socket, uploads |
| [host_autostart.md](host_autostart.md) | The systemd user unit, what it installs, and what it deliberately does not |
| [git_surface.md](git_surface.md) | The git reads the phone asks for: patch, changes, log, commit |
| [git_remote.md](git_remote.md) | The remote lane, its two fields, and why credentials never travel |
| [internals.md](internals.md) | Import safety without a working directory, and the settings conformance corpus |
| [decisions.md](decisions.md) | Why this branch is shaped the way it is — the incident record behind the code |
| [tech_debt.md](tech_debt.md) | Known issues, each with its measurement |
| [SECURITY.md](SECURITY.md) | The security posture of the host API and the credential store |

Work in progress, research and dated one-offs belong in `docs.local/`, not here: this
directory is committed, so write it as if it ships.
