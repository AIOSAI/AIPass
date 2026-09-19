[<- Back to the README](../README.md)

# init and install

*The two setup doors: `aipass install` brings AIPass onto a machine,
`aipass init` walks a human through configuring it.*

`aipass --help` is the authority on the top-level surface, and each command's
own `--help` on its flags. This page carries what the help pages do not: the
entry forms that route in the code, and which of them the help text still
misses.

## `aipass install` — one-command bootstrap

Clone, `setup.sh`, hooks, the phone face, then a concierge welcome chat. Five
steps, each reported as it runs.

| Form | What it does |
|---|---|
| `install` | The whole bootstrap into the default home |
| `install --path DIR` / `--here` | Choose the install home |
| `install --non-interactive` | Headless — no prompts, no chat |
| `install --no-chat` / `--chat-only` | Install without the chat, or the chat alone |
| `install --no-symlink` / `--force-symlink` | Control the global CLI symlinks |
| `install --force-global-home` | Allow installing into `/tmp` — unsafe, deliberately not advertised |
| `install --no-baud` | Skip the phone face + baud-cli step |
| `install --dry-run` | Walk the steps, no side effects |

The phone-face step is best-effort: offline, a private repo or a missing token
prints one line plus the retry command and the install carries on. See
[`baud_phone_face.md`](baud_phone_face.md).

Code: [`apps/modules/install.py`](../apps/modules/install.py).

## `aipass init` — guided setup

Bare `init` prints usage; it does **not** start the setup. `init run` walks the
ten stages — welcome, system detect, profile, style questions, tool choice,
first agent, ping sweep, smoke test, handoff, done — and every stage saves its
answer, so the run is resumable.

| Form | What it does |
|---|---|
| `init run` | The guided setup, resumable |
| `init run --non-interactive` | CI/headless run |
| `init run --name/--cli/--style/--template <v>` | Pre-fill a stage answer |
| `init run --dry-run` | Walk all stages, write nothing |
| `init --list` | List the available project templates |
| `init <template>` | The guided setup with that template pre-selected, e.g. `init python` |
| `init <path> [name]` | Scaffold AIPass files into an existing path |
| `init agent <name>` | Create an agent via `drone @spawn` |
| `init update [target]` | The scaffold-update plan, then apply it + owner-tier repo auth |
| `init update --dry-run` | Print the plan and write nothing — exit 0 current, exit 2 pending |
| `init update --json` | The same plan as a JSON document, for machines |

The last three are the update ritual, and it has rules of its own — read
[`scaffold_update.md`](scaffold_update.md) before applying one.

A bare template name, `init <path>`, and `init agent` all route in
[`apps/modules/init_flow.py`](../apps/modules/init_flow.py) but are absent from
`init --help`, as is the `--style` flag that `init run` accepts.

Scaffolding itself lives in
[`apps/handlers/init/`](../apps/handlers/init) — `bootstrap.py`,
`git_auth.py`, `scaffold_manifest.py` — with the template text in
[`shared/scaffold_content.py`](../shared/scaffold_content.py), which is
stdlib-only because it loads before drone exists.

---

[← Back to the AIPASS README](../README.md)
