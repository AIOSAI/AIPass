[<- Back to the README](../README.md)

# `drone docker` — disposable boxes that match this machine

**Branch** drone · **Code** `apps/modules/docker.py`, `apps/handlers/docker_handler.py`

`drone docker` makes throwaway containers for trying AIPass, or anything else, on a clean copy of
this machine's OS. One command makes a box and drops you into it; on exit the box is gone unless
you kept it. The flags and examples are `drone docker --help`.

---

## The verbs

| Verb | What it does |
|---|---|
| `bare` | A fresh image of this machine's OS with the base tools, no AIPass, a login shell |
| `local` | `bare` plus this checkout's committed HEAD, cloned and pip-installed; the working tree is mounted read-only at `/src` |
| `dev`, `main` | `bare` plus that branch cloned from origin on github, not from this checkout, and pip-installed |
| `list` | Its boxes: name, verb, age, running or stopped, kept or removed on exit; then one line per `aipass-login-*` volume, or `no login volumes` |
| `shell <name>` | Starts a kept box if it is stopped, opens a login shell in it, and stops it again when you leave |
| `rm <name>...`, `rm --all` | Stops, then removes its boxes; records each removal |
| `rm --login` | Removes the `aipass-login-*` volumes, which clears every sign-in (see Login volumes) |

`local` is the only verb that uses this checkout: it clones `file:///src` to `~/AIPass-src`, so
the box sees the committed HEAD, not uncommitted edits. `dev` and `main` clone with `--branch dev`
or `--branch main` from `https://github.com/OWNER/NAME`, where OWNER/NAME comes from the repo's own
`origin` remote (the same reading `drone @git` uses), so they hold what is pushed, not what is here.

After the clone, `local`, `dev` and `main` print the HEAD line and run
`~/aipass-venv/bin/pip install ~/AIPass-src`, so the `aipass` command is on PATH when the shell or
the `-- <command>` starts. That is all they install: the box has aipass and nothing else set up,
and the one line it prints is the user's first command:

```
aipass install --source ~/AIPass-src
```

A failed pip install prints `pip install of ~/AIPass-src failed` and the box still opens.

## The options

These apply to `bare`, `local`, `dev` and `main`:

| Option | Effect |
|---|---|
| `--keep` | The box stays after you exit (default: `--rm`); come back with `drone docker shell <name>` |
| `--with claude\|codex\|opencode` | Runs that CLI's vendor installer in the box before the shell, output visible; repeatable |
| `--mount <path>` | Binds a host directory read-only at `/mnt/<basename>`; repeatable |
| `--login` | Named volumes for the CLIs' sign-in directories (see the rules below) |
| `--image <ref>` | The base image; default is this machine's `ID:VERSION_ID` from `/etc/os-release` |
| `--rebuild` | Rebuilds the cached base image with `--no-cache` |
| `--name <name>` | Instead of `aipass-<verb>-<n>` |
| `-- <command>` | Runs that one command in the box instead of the shell |

A terminal on stdin gets `docker exec -it`; without one (a script, a pipe) the command runs without
a TTY, which is how `-- <command>` runs unattended.

A single argument after `--` is a shell script, as in `-- 'echo a; echo b'`. Multiple arguments
are shell-quoted individually, so `-- bash -c 'echo a b'` preserves the argument to `bash -c`.

## How a box runs

Every box, kept or not, runs the same four steps:

1. `docker run -d --init [--rm] --name <name> --label aipass.box=<verb> [volumes] <image> sleep infinity`.
   The box's own process is `sleep`, so it stays up until stopped; `--init` lets `docker stop` end
   it at once.
2. Only when that succeeds is the `created` row written. When docker refuses, its error is printed,
   no row is written, and drone exits with docker's code.
3. `docker exec [-it] <name> bash -lc <script>` runs the installers, the clone and then the shell or
   the `-- <command>`, attached to this terminal.
4. `docker stop -t 1 <name>`, always, even when the exec fails or is interrupted. A `--rm` box is
   then removed by docker and gets a `removed` row after a successful stop; a kept box is left stopped.
   A failed stop is logged and leaves the record open.

Because the box's own process is `sleep` and not the script, starting a kept box never re-runs a
one-shot `-- <command>`: a kept box can always be entered again. `shell <name>` starts a stopped
box, runs `docker exec -it <name> bash -l`, then stops it again, so the box is left as it was found.
A box that was already running is entered and left running. A box that does not stay up when started
(one made before this shape, whose own process was the script) is refused in one sentence that says
to remove it and make it again.

The creating command owns the box's lifetime: when it exits, it stops the box even if a second
terminal is still attached through `shell`. Concurrent sessions do not extend that lifetime.

**The exit code.** `bare`, `local`, `dev` and `main` exit with the exit code of the exec: the
`-- <command>`'s own code (`-- 'exit 7'` exits 7), or the shell's. When the box never starts, the
code is docker's (125 for a docker refusal).

## The base image

Each base ref has one cached image, `aipass-base:<ref>` with characters outside ASCII letters,
digits, `_`, `.` and `-` turned into `-`, including the `@` and `:` in digest-pinned references (this
host: `aipass-base:ubuntu-26.04`). It is built from a Dockerfile written to a temporary directory:
the base, `apt-get install` of python3, python3-venv, python3-pip, pipx (so the README's
`pipx install aipass` runs in a `bare` box as a stranger would run it), git, curl, ca-certificates,
nodejs, npm, tmux, ripgrep and jq, a user `aipass` with a home,
`git config --system --add safe.directory '*'`, then `USER aipass`, `WORKDIR /home/aipass` and an
empty venv at `~/aipass-venv`. PATH holds `~/.local/bin`, `~/aipass-venv/bin` and
`~/.opencode/bin`, set both as the image's `ENV` and in `~/.profile`, because a login shell's
`/etc/profile` resets PATH. `NPM_CONFIG_PREFIX` is `~/.local`, so `npm install -g` works without
root. The image carries no AIPass and no CLI.

The image carries the label `aipass.base=<digest of the Dockerfile text>`. A cached image is reused
only while its label matches the Dockerfile drone would write now; when drone's Dockerfile
changes, or with `--rebuild` (which adds `--no-cache`), the base is built again.

The image installs with apt, so a base whose image name is not `ubuntu` or `debian` is refused by
name before docker is called.

## Names and the record

Every box is named `aipass-<verb>-<n>`, where n is one past the highest number for that verb among
the recorded boxes and the containers docker holds. Every box carries the label
`aipass.box=<verb>` and a row in `<project>/.ai_central/docker_boxes.jsonl`, beside drone's
deletion record: name, verb, image, created, kept, mounts. A removal appends a `removed` row,
including automatic removal after a non-kept run, so an explicit name can be used again.

`rm` uses `docker rm -f`, which stops and removes a running box in one call. If a known box
disappears between the ownership check and removal, Docker's `No such container:` result also
closes its record; other failures are printed and leave its record open.

`--name` must match docker's own rule, `^[a-zA-Z0-9][a-zA-Z0-9_.-]*$`. Any other name is refused
in one line naming the rule, exit 2, before any docker call or ledger row.

A name, given or generated, that is already a container (`docker ps -a`, exact match) or a box on
record and not removed is refused, exit 2, for example
`aipass-dup-e2e is taken: a box by that name exists; pick another --name or drone docker rm it`.
So a reused name never overwrites another box's row.

`list`, `shell` and `rm` act only on a name that has a row and a live container carrying the label.
Anything else is refused as `drone docker did not make <name>`; no other container on the machine
is ever listed, entered, stopped or removed.

## The two rules

1. **No host credentials enter a box.** `--mount` refuses `~/.claude`, `~/.codex`,
   `~/.config/opencode`, `~/.secrets`, `~/.ssh`, `~/.config/gh`, `~/.git-credentials`, `~/.netrc`,
   `~/.aws`, `~/.gnupg`, `~/.docker` and `~/.kube`, any path inside one, and any directory
   that holds one (your home, `~/.config`). Both the requested path and each credential path
   are resolved first, so a symlink and its credential target are both refused. A missing path
   is refused by name.
2. **`--login` is the only state carried between boxes.** It mounts three named volumes,
   `aipass-login-claude`, `aipass-login-codex` and `aipass-login-opencode`, at `~/.claude`,
   `~/.codex` and `~/.config/opencode` in the box, so a sign-in made in one box serves the next.
   It never binds the host's own directories.

## Login volumes

`drone docker list` ends with the `aipass-login-*` volumes docker holds, one name per line (no
size: measuring it is not cheap), or `no login volumes`.

`drone docker rm --login` is how a sign-in is cleared. It runs `docker volume rm` on
`aipass-login-claude`, `aipass-login-codex` and `aipass-login-opencode`, those that exist, and
writes a `login_removed` row naming the volumes removed. Docker refuses to remove a volume a
container still uses, kept or running; that refusal is the right result, and drone prints docker's
error and exits nonzero. Remove or leave the box that holds it, then run `rm --login` again.

## When docker cannot answer

Docker not installed, or its daemon down: one line naming which, exit 2. A permission error on the
docker socket prints docker's own error and the fix,
`sudo usermod -aG docker $USER`, exit 2.

## The vendor installers

`--with` runs the same three lines aipass's provider installer uses:

```
curl -fsSL https://claude.ai/install.sh | bash
npm install -g @openai/codex
curl -fsSL https://opencode.ai/v2/install | bash
```

aipass does not export them through its package front door, so drone keeps one copy in
`docker_handler.INSTALLERS` that mirrors aipass's `provider_choice.py`. A change there is a change
here too.
