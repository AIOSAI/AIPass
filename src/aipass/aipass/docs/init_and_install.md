[<- Back to the README](../README.md)

# init and install

*`aipass install` brings AIPass onto a machine and ends at the doctor's report;
`aipass init` scaffolds and updates projects.*

`aipass --help` is the authority on the top-level surface, and each command's
own `--help` on its flags. This page carries what the help pages do not: what
each step does, the report it leaves, and the entry forms that route in the
code but no help page names.

## `aipass install` — one-command bootstrap

Five steps, each reported as it runs: resolve the home and fetch AIPass,
`setup.sh` (run with `--no-finish`, so the doctor and the report run once, in
the install's own process), verify the `drone` and `aipass` binaries and the
registry owner, phone face + baud-cli, and the Health check: the full doctor
with its fix step.

| Form | What it does |
|---|---|
| `install` | The whole bootstrap into the default home, ending at the report |
| `install --path DIR` / `--here` | Choose the install home |
| `install --source PATH\|URL` | Clone AIPass from this path or URL instead of the public repo (a local path clones its committed HEAD; for the install sandbox) |
| `install --non-interactive` | Headless: no questions, stdin closed for `setup.sh`, no pairing QR, the default home `~/AIPass` |
| `install --yes` | Consent to the machine changes up front: passed to the doctor's settings write, and `AIPASS_YES=1` exported to `setup.sh` |
| `install --finish` | The Health check and the report alone, no clone and no `setup.sh`; `setup.sh`'s tail calls it |
| `install --no-symlink` / `--force-symlink` | Control the global CLI symlinks |
| `install --force-global-home` | Allow installing into `/tmp`: unsafe, never the default |
| `install --no-baud` | Skip the phone face + baud-cli step |
| `install --baud-tag TAG` | The baud release to install, default latest |
| `install --dry-run` | Walk the steps, no side effects, no install lock |

The Health check is the one place the install may change the machine beyond
its own tree: the provider settings (hooks, env, permissions for Claude Code,
Codex and OpenCode). On a terminal the plan and its diff print and you are
asked once, `[y/N]`; `--yes` answers it up front. With no terminal, or under
`--non-interactive` without `--yes`, nothing is written and the row says so and names `aipass doctor --fix --yes`. A no prints
what will not work without the wiring and the command that wires it later,
`aipass doctor --fix`. See [`doctor.md`](doctor.md#the-provider-wiring-door).

The install then ends on its final screen and launches nothing:

- `AIPass installed at <home>`, then every doctor row that is not a pass,
  after the fix step, plus one `Setup` row per line `setup.sh` wrote to
  `<home>/.aipass/setup_attention.txt`. Each line reads
  `<severity>: <label>: <detail> -> <remediation>`.
- The report, overwritten each install, at
  `<home>/src/aipass/devpulse/dropbox/install_report.json`: `kind`
  (`aipass_install_report`), `version`, `written_at`, `home`, `aipass_version`,
  `user_name` (from `AIPASS_REGISTRY.json`), `outcome` (`installed` or
  `step_failed`), `failed_steps` (`[]`, or `["phone face"]`), the doctor's
  `pass`/`warn`/`error` counts, and the `attention` rows.
- One command that opens devpulse in its directory on that report:
  `cd <home>/src/aipass/devpulse && claude "Read dropbox/install_report.json: ..."`.
- A closing note: devpulse is the seat you talk to about projects; aipass is the
  machine concierge for host problems.

A report that cannot be written is an error and exit 1. A dry run prints where
the report would go and writes nothing.

The phone-face step fails loud. Offline, a private repo or a missing token
prints one line plus the retry command and the install carries on to the
Health check and the report; then, when the face was asked for (no `--no-baud`)
and did not install, an error row `phone face` names `aipass baud install`, the
final screen says a requested step failed, the report records
`"outcome": "step_failed"` and `"failed_steps": ["phone face"]`, and the install
exits 1. See
[`baud_phone_face.md`](baud_phone_face.md).

With the face in, the phone print runs after the Health check: bind, boot unit,
server, guide. Where no boot unit will bring the server up (no user systemd, a
unit that failed or could not be reached), the install starts it detached and
says so on the Server line. On a terminal, when the server answers on a tailnet
address, the print pauses: press Enter when the phone's camera is ready, and
only then does @api's pairing door mint a one-use code (label `phone`, scope
`operate`, five minutes); the block ends with its QR, its url and the expiry.
EOF or Ctrl-C at the pause is a stated skip. Otherwise, or when the door
refuses, and always under `--non-interactive` (what `install.sh` runs; it does
its own pause and pair), the print names
`drone @api host-api pair phone --scope operate` instead. A dry run mints and
starts nothing.

Code: [`apps/modules/install.py`](../apps/modules/install.py).

## `aipass init` — project scaffold and update

Bare `init` prints usage.

| Form | What it does |
|---|---|
| `init [target] [name]` | Scaffold AIPass files into `target` (default: the current directory); takes no flags |
| `init agent <name>` | Create an agent via `drone @spawn` |
| `init update [target]` | The scaffold-update plan, then apply it + owner-tier repo auth |
| `init update --dry-run` | Print the plan and write nothing — exit 0 current, exit 2 pending |
| `init update --json` | The same plan as a JSON document, for machines |
| `init run` | Refused, exit 1: there is no guided setup; the error names `aipass init [target] [name]` |

The update forms are the update ritual, and it has rules of its own — read
[`scaffold_update.md`](scaffold_update.md) before applying one. The routing is
in [`apps/modules/init_flow.py`](../apps/modules/init_flow.py).

Scaffolding itself lives in
[`apps/handlers/init/`](../apps/handlers/init) — `bootstrap.py`,
`git_auth.py`, `scaffold_manifest.py` — with the template text in
[`shared/scaffold_content.py`](../shared/scaffold_content.py), which is
stdlib-only because it loads before drone exists.

---

[← Back to the AIPASS README](../README.md)
