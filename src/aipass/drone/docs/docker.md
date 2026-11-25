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
| `list` | Its boxes: name, verb, age, running or stopped, kept or removed on exit |
| `shell <name>` | Starts a kept box if it is stopped, then opens a login shell in it |
| `rm <name>...`, `rm --all` | Stops, then removes its boxes; records each removal |

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

A terminal on stdin gets `docker run -it`; without one (a script, a pipe) the box runs without a
TTY, which is how `-- <command>` runs unattended.

## The base image

Each base ref has one cached image, `aipass-base:<ref>` with `:` and `/` turned into `-` (this
host: `aipass-base:ubuntu-26.04`). It is built from a Dockerfile written to a temporary directory:
the base, `apt-get install` of python3, python3-venv, python3-pip, git, curl, ca-certificates,
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
deletion record: name, verb, image, created, kept, mounts. A removal appends a `removed` row.

`list`, `shell` and `rm` act only on a name that has a row and a live container carrying the label.
Anything else is refused as `drone docker did not make <name>`; no other container on the machine
is ever listed, entered, stopped or removed.

## The two rules

1. **No host credentials enter a box.** `--mount` refuses `~/.claude`, `~/.codex`,
   `~/.config/opencode`, `~/.secrets` and `~/.ssh`, any directory inside one, and any directory
   that holds one (your home, `~/.config`). A missing path is refused by name.
2. **`--login` is the only state carried between boxes.** It mounts three named volumes,
   `aipass-login-claude`, `aipass-login-codex` and `aipass-login-opencode`, at `~/.claude`,
   `~/.codex` and `~/.config/opencode` in the box, so a sign-in made in one box serves the next.
   It never binds the host's own directories.

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
