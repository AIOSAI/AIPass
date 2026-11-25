# =================== AIPass ====================
# Name: test_docker.py
# Description: drone docker: the base Dockerfile, the argv per verb and option, names, refusals, exit 2
# Version: 1.1.0
# Created: 2026-11-24
# Modified: 2026-11-25
# =============================================

"""Tests for apps/modules/docker.py and the docker_handler it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(constant) — HELP, the help page's prose beyond the verbs it names
# sentry: no-test-needed(covered_elsewhere) — the ledger's bounded append, pinned in tests/test_deletion_log.py

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from aipass.drone.apps import drone as drone_app
from aipass.drone.apps.handlers import docker_handler
from aipass.drone.apps.modules import docker

ORIGIN = "git@github.com:AIOSAI/AIPass.git"
# The box user's home, as the Dockerfile makes it.
BOX = Path(os.sep, "home", "aipass").as_posix()


class FakeDocker:
    """Every subprocess.run, recorded and answered; no docker runs."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.info: tuple[int, str, str] = (0, "", "")
        self.image_cached = True
        self.stamp: str | None = None
        self.live: dict[str, str] = {}
        self.dockerfile = ""
        self.run_result: tuple[int, str, str] = (0, "c0ffee\n", "")
        self.exec_result: tuple[int, str, str] = (0, "", "")
        self.exec_raises = False
        self.start_dies = False
        self.auto_remove: set[str] = set()
        self.stop_result: tuple[int, str, str] | None = None
        self.rm_result: tuple[int, str, str] | None = None
        self.volumes: list[str] = []
        self.volume_rm: tuple[int, str, str] | None = None

    def __call__(self, argv, *args, **kwargs):
        argv = list(argv)
        self.calls.append(argv)
        answer = getattr(self, f"_{argv[1]}", None)
        rc, out, err = answer(argv) if answer else (0, "", "")
        return subprocess.CompletedProcess(argv, rc, out, err)

    def _info(self, argv: list[str]) -> tuple[int, str, str]:
        return self.info

    def _image(self, argv: list[str]) -> tuple[int, str, str]:
        stamp = self.stamp if self.stamp is not None else docker_handler.base_stamp("ubuntu:26.04")
        return (0, stamp + "\n", "") if self.image_cached else (1, "", "no such image")

    def _build(self, argv: list[str]) -> tuple[int, str, str]:
        self.dockerfile = Path(argv[-1], "Dockerfile").read_text(encoding="utf-8")
        return 0, "", ""

    def _remote(self, argv: list[str]) -> tuple[int, str, str]:
        return 0, ORIGIN + "\n", ""

    def _ps(self, argv: list[str]) -> tuple[int, str, str]:
        flt = argv[argv.index("--filter") + 1]
        if flt.startswith("name=^"):
            want = flt[len("name=^") :]
            if want.endswith("$"):
                return 0, "\n".join(n for n in self.live if n == want[:-1]), ""
            return 0, "\n".join(n for n in self.live if n.startswith(want)), ""
        return 0, "\n".join(f"{n}\t{s}" for n, s in self.live.items()), ""

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        if self.run_result[0] == 0:
            name = argv[argv.index("--name") + 1]
            self.live[name] = "running"
            if "--rm" in argv:
                self.auto_remove.add(name)
        return self.run_result

    def _exec(self, argv: list[str]) -> tuple[int, str, str]:
        if self.exec_raises:
            raise KeyboardInterrupt
        return self.exec_result

    def _start(self, argv: list[str]) -> tuple[int, str, str]:
        self.live[argv[2]] = "exited" if self.start_dies else "running"
        return 0, argv[2] + "\n", ""

    def _stop(self, argv: list[str]) -> tuple[int, str, str]:
        if self.stop_result is not None:
            return self.stop_result
        if argv[-1] in self.auto_remove:
            self.live.pop(argv[-1], None)
        else:
            self.live[argv[-1]] = "exited"
        return 0, argv[-1] + "\n", ""

    def _rm(self, argv: list[str]) -> tuple[int, str, str]:
        if self.rm_result is not None:
            return self.rm_result
        if argv[-1] not in self.live:
            return 1, "", f"Error response from daemon: No such container: {argv[-1]}"
        self.live.pop(argv[-1])
        return 0, argv[-1] + "\n", ""

    def _volume(self, argv: list[str]) -> tuple[int, str, str]:
        if argv[2] == "ls":
            return 0, "\n".join(self.volumes), ""
        if self.volume_rm is not None:
            return self.volume_rm
        return 0, "\n".join(argv[3:]), ""

    def runs(self) -> list[list[str]]:
        return [c for c in self.calls if c[:2] == ["docker", "run"]]

    def execs(self) -> list[list[str]]:
        return [c for c in self.calls if c[:2] == ["docker", "exec"]]

    def verbs(self) -> list[str]:
        return [c[1] for c in self.calls if c[1] in ("run", "exec", "start", "stop")]


def path_with_docker(tmp_path: Path) -> str:
    """A PATH holding one executable named docker, so the product's which() finds it for real."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "docker"
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(0o755)
    return str(bin_dir)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeDocker:
    fake = FakeDocker()
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setenv("PATH", path_with_docker(tmp_path))
    project = tmp_path / "project"
    project.mkdir()
    (project / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return fake


def ledger_rows() -> list[dict]:
    return [json.loads(line) for line in docker_handler.ledger_path().read_text(encoding="utf-8").splitlines()]


def seed(*rows: dict) -> None:
    for row in rows:
        docker_handler.record(row)


PIP_INSTALL = "~/aipass-venv/bin/pip install -q ~/AIPass-src || echo 'pip install of ~/AIPass-src failed'"


def script_of(argv: list[str]) -> str:
    return argv[argv.index("-lc") + 1]


class TestBaseImage:
    def test_a_digest_base_builds_with_a_valid_cache_tag(self, fake: FakeDocker) -> None:
        fake.image_cached = False
        image = "ubuntu@sha256:" + "a" * 64
        assert docker.run("bare", ["--image", image, "--", "true"]) == 0
        build = next(c for c in fake.calls if c[:2] == ["docker", "build"])
        assert build[build.index("-t") + 1] == "aipass-base:ubuntu-sha256-" + "a" * 64
        assert fake.dockerfile.startswith(f"FROM {image}\n")

    def test_a_missing_base_is_built_from_the_spec_dockerfile(self, fake: FakeDocker) -> None:
        fake.image_cached = False
        assert docker.run("bare", ["--image", "ubuntu:26.04", "--", "true"]) == 0
        build = next(c for c in fake.calls if c[:2] == ["docker", "build"])
        assert "--no-cache" not in build
        assert build[build.index("-t") + 1] == "aipass-base:ubuntu-26.04"
        text = fake.dockerfile
        assert text.startswith("FROM ubuntu:26.04\n")
        pkgs = "python3 python3-venv python3-pip git curl ca-certificates nodejs npm tmux ripgrep jq".split()
        assert set(pkgs) <= set(text.split())
        assert "useradd -m -s /bin/bash aipass" in text
        assert "git config --system --add safe.directory '*'" in text
        assert "USER aipass\n" in text and f"WORKDIR {BOX}\n" in text
        assert f"ENV PATH={BOX}/.local/bin:{BOX}/aipass-venv/bin:{BOX}/.opencode/bin:$PATH" in text
        assert f"python3 -m venv {BOX}/aipass-venv" in text
        assert f"export PATH={BOX}/.local/bin:{BOX}/aipass-venv/bin:{BOX}/.opencode/bin:$PATH" in text
        assert "aipass install" not in text and "claude" not in text.split("RUN mkdir")[0]

    def test_a_cached_base_is_not_rebuilt_and_rebuild_passes_no_cache(self, fake: FakeDocker) -> None:
        docker.run("bare", ["--image", "ubuntu:26.04", "--", "true"])
        assert not [c for c in fake.calls if c[:2] == ["docker", "build"]]
        docker.run("bare", ["--image", "ubuntu:26.04", "--rebuild", "--", "true"])
        build = next(c for c in fake.calls if c[:2] == ["docker", "build"])
        assert "--no-cache" in build

    def test_a_cached_base_built_from_an_older_dockerfile_is_rebuilt(self, fake: FakeDocker) -> None:
        fake.stamp = "0123456789ab"
        docker.run("bare", ["--image", "ubuntu:26.04", "--", "true"])
        build = next(c for c in fake.calls if c[:2] == ["docker", "build"])
        assert "--no-cache" not in build
        assert build[build.index("--label") + 1] == f"aipass.base={docker_handler.base_stamp('ubuntu:26.04')}"

    def test_the_default_base_is_this_machines_os_release(
        self, fake: FakeDocker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        release = tmp_path / "os-release"
        release.write_text('NAME="Debian"\nID=debian\nVERSION_ID="13"\n', encoding="utf-8")
        monkeypatch.setattr(docker_handler, "OS_RELEASE", release)
        assert docker.run("bare", []) == 0
        assert "aipass-base:debian-13" in fake.runs()[0]

    def test_a_non_apt_base_is_refused_by_name_before_docker_runs(
        self, fake: FakeDocker, capsys: pytest.CaptureFixture
    ) -> None:
        assert docker.run("bare", ["--image", "alpine:3.20"]) == 1
        err = capsys.readouterr().err
        assert "alpine:3.20" in err and "apt" in err
        assert fake.calls == []


class TestRunArgv:
    def test_bare_runs_sleep_detached_then_execs_a_login_shell_then_stops(self, fake: FakeDocker) -> None:
        docker.run("bare", ["--image", "ubuntu:26.04"])
        assert fake.runs() == [
            "docker run -d --init --rm --name aipass-bare-1 --label aipass.box=bare "
            "aipass-base:ubuntu-26.04 sleep infinity".split()
        ]
        assert fake.execs() == [["docker", "exec", "aipass-bare-1", "bash", "-lc", "exec bash -l"]]
        assert fake.verbs() == ["run", "exec", "stop"]
        assert fake.calls[-1] == ["docker", "stop", "-t", "1", "aipass-bare-1"]

    def test_the_exec_exit_code_is_the_commands_result_and_the_box_is_stopped(self, fake: FakeDocker) -> None:
        fake.exec_result = (7, "", "")
        assert docker.run("bare", ["--image", "ubuntu:26.04", "--", "exit 7"]) == 7
        assert fake.verbs()[-1] == "stop"

    def test_an_interrupted_exec_still_stops_the_box(self, fake: FakeDocker) -> None:
        fake.exec_raises = True
        with pytest.raises(KeyboardInterrupt):
            docker.run("bare", ["--image", "ubuntu:26.04", "--", "true"])
        assert fake.verbs() == ["run", "exec", "stop"]

    def test_a_failed_run_writes_no_row_execs_nothing_and_returns_dockers_code(
        self, fake: FakeDocker, capsys: pytest.CaptureFixture
    ) -> None:
        fake.run_result = (125, "", "docker: Error response from daemon: no space left")
        assert docker.run("bare", ["--image", "ubuntu:26.04", "--", "true"]) == 125
        assert "no space left" in capsys.readouterr().err
        assert fake.verbs() == ["run"]
        assert not docker_handler.ledger_path().exists()

    def test_the_row_is_written_after_run_succeeds_and_before_exec(
        self, fake: FakeDocker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[str] = []
        real = docker_handler.record
        monkeypatch.setattr(docker_handler, "record", lambda row: (seen.append(" ".join(fake.verbs())), real(row)))
        docker.run("bare", ["--image", "ubuntu:26.04", "--", "true"])
        assert seen == ["run", "run exec stop"]

    # A real pseudo-terminal, not a patched isatty; Windows has none.
    @pytest.mark.skipif(not hasattr(os, "openpty"), reason="no pseudo-terminals on this OS")
    def test_a_terminal_gets_it(self, fake: FakeDocker, monkeypatch: pytest.MonkeyPatch) -> None:
        main, follower = os.openpty()
        with os.fdopen(follower) as tty:
            monkeypatch.setattr(sys, "stdin", tty)
            docker.run("bare", ["--image", "ubuntu:26.04"])
        os.close(main)
        assert fake.execs()[0][2] == "-it"
        assert "-it" not in fake.runs()[0]

    def test_local_mounts_the_repo_read_only_clones_head_and_pip_installs_it(self, fake: FakeDocker) -> None:
        docker.run("local", ["--image", "ubuntu:26.04"])
        argv = fake.runs()[0]
        root = Path.cwd().resolve()
        assert argv[argv.index("-v") + 1] == f"{root}:/src:ro"
        lines = script_of(fake.execs()[0]).splitlines()
        clone = lines.index("git clone -q file:///src ~/AIPass-src")
        assert "git -C ~/AIPass-src log -1 --oneline" in lines
        assert lines.index(PIP_INSTALL) > clone
        assert "echo '  aipass install --source ~/AIPass-src'" in lines
        assert not [ln for ln in lines if ln.startswith("aipass ")]
        assert lines[-1] == "exec bash -l"

    def test_bare_installs_nothing(self, fake: FakeDocker) -> None:
        docker.run("bare", ["--image", "ubuntu:26.04"])
        assert "pip install" not in script_of(fake.execs()[0])

    @pytest.mark.parametrize("verb", ["dev", "main"])
    def test_dev_and_main_clone_that_branch_from_origins_https_url(self, fake: FakeDocker, verb: str) -> None:
        docker.run(verb, ["--image", "ubuntu:26.04"])
        argv = fake.runs()[0]
        assert "-v" not in argv
        lines = script_of(fake.execs()[0]).splitlines()
        clone = lines.index(f"git clone -q --branch {verb} https://github.com/AIOSAI/AIPass ~/AIPass-src")
        assert lines.index(PIP_INSTALL) > clone
        assert "echo '  aipass install --source ~/AIPass-src'" in lines
        assert argv[argv.index("--name") + 1] == f"aipass-{verb}-1"

    def test_keep_drops_rm_and_is_recorded(self, fake: FakeDocker) -> None:
        docker.run("bare", ["--image", "ubuntu:26.04", "--keep"])
        assert "--rm" not in fake.runs()[0]
        assert ledger_rows()[-1]["kept"] is True

    def test_with_runs_the_vendor_installer_before_the_shell(self, fake: FakeDocker) -> None:
        docker.run("bare", ["--image", "ubuntu:26.04", "--with", "claude", "--with", "codex"])
        script = script_of(fake.execs()[0])
        assert "curl -fsSL https://claude.ai/install.sh | bash || echo 'install of claude failed'" in script
        assert "npm install -g @openai/codex || echo 'install of codex failed'" in script
        assert script.index("claude.ai") < script.index("exec bash -l")

    def test_with_an_unknown_cli_is_refused(self, fake: FakeDocker, capsys: pytest.CaptureFixture) -> None:
        assert docker.run("bare", ["--with", "vim"]) == 1
        assert "--with vim refused" in capsys.readouterr().err
        assert fake.runs() == []

    def test_mount_binds_read_only_under_mnt(self, fake: FakeDocker, tmp_path: Path) -> None:
        data = tmp_path / "data"
        data.mkdir()
        docker.run("bare", ["--image", "ubuntu:26.04", "--mount", str(data)])
        argv = fake.runs()[0]
        assert argv[argv.index("-v") + 1] == f"{data.resolve()}:/mnt/data:ro"

    def test_login_mounts_named_volumes_and_never_a_host_dir(self, fake: FakeDocker) -> None:
        docker.run("bare", ["--image", "ubuntu:26.04", "--login"])
        argv = fake.runs()[0]
        vols = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
        assert vols == [
            f"aipass-login-claude:{BOX}/.claude",
            f"aipass-login-codex:{BOX}/.codex",
            f"aipass-login-opencode:{BOX}/.config/opencode",
        ]
        assert not [v for v in vols if v.startswith(("/", "~"))]

    def test_name_overrides_and_is_still_recorded(self, fake: FakeDocker) -> None:
        docker.run("bare", ["--image", "ubuntu:26.04", "--name", "trial"])
        assert fake.runs()[0][fake.runs()[0].index("--name") + 1] == "trial"
        assert ledger_rows()[-1]["name"] == "trial"

    @pytest.mark.parametrize("bad", ["Bad Name!", "-lead", ".dot", "a/b", ""])
    def test_a_name_docker_would_refuse_exits_2_before_any_call_or_row(
        self, fake: FakeDocker, capsys: pytest.CaptureFixture, bad: str
    ) -> None:
        assert docker.run("bare", ["--name", bad, "--", "echo ran"]) == 2
        assert "^[a-zA-Z0-9][a-zA-Z0-9_.-]*$" in capsys.readouterr().err
        assert fake.calls == []
        assert not docker_handler.ledger_path().exists()

    def test_a_live_containers_name_is_taken_and_its_row_untouched(
        self, fake: FakeDocker, capsys: pytest.CaptureFixture
    ) -> None:
        seed({"event": "created", "name": "aipass-dup-e2e", "verb": "bare", "kept": True})
        before = docker_handler.ledger_path().read_text(encoding="utf-8")
        fake.live = {"aipass-dup-e2e": "exited"}
        assert docker.run("bare", ["--image", "ubuntu:26.04", "--name", "aipass-dup-e2e", "--", "true"]) == 2
        assert "aipass-dup-e2e is taken" in capsys.readouterr().err
        assert fake.runs() == []
        assert docker_handler.ledger_path().read_text(encoding="utf-8") == before

    def test_a_recorded_name_with_no_container_is_taken(self, fake: FakeDocker, capsys: pytest.CaptureFixture) -> None:
        seed({"event": "created", "name": "night-claude", "verb": "dev", "kept": True})
        assert docker.run("bare", ["--image", "ubuntu:26.04", "--name", "night-claude", "--", "true"]) == 2
        assert "night-claude is taken" in capsys.readouterr().err
        assert fake.runs() == []
        assert len(ledger_rows()) == 1

    def test_a_similar_live_name_does_not_take_this_one(self, fake: FakeDocker) -> None:
        fake.live = {"trial-2": "running", "xtrial": "running"}
        assert docker.run("bare", ["--image", "ubuntu:26.04", "--name", "trial", "--", "true"]) == 0

    def test_a_command_after_dashes_replaces_the_shell(self, fake: FakeDocker) -> None:
        docker.run("bare", ["--image", "ubuntu:26.04", "--", "whoami; python3 --version"])
        assert script_of(fake.execs()[0]) == "whoami; python3 --version"

    def test_a_multiword_command_preserves_the_bash_c_argument(self, fake: FakeDocker) -> None:
        assert docker.run("bare", ["--image", "ubuntu:26.04", "--", "bash", "-c", "echo a b"]) == 0
        assert script_of(fake.execs()[0]) == "bash -c 'echo a b'"

    def test_a_nonkept_name_is_reusable_after_its_removed_row(self, fake: FakeDocker) -> None:
        args = ["--image", "ubuntu:26.04", "--name", "reusable", "--", "true"]
        assert docker.run("bare", args) == 0
        assert [(row["event"], row["name"]) for row in ledger_rows()] == [
            ("created", "reusable"),
            ("removed", "reusable"),
        ]
        assert docker.run("bare", args) == 0
        assert len(fake.runs()) == 2

    def test_a_failed_stop_leaves_the_name_record_open(self, fake: FakeDocker) -> None:
        fake.stop_result = (1, "", "permission denied")
        assert docker.run("bare", ["--image", "ubuntu:26.04", "--", "true"]) == 0
        assert [row["event"] for row in ledger_rows()] == ["created"]


class TestCredentialMounts:
    @pytest.mark.parametrize("use_target", [False, True])
    def test_a_symlinked_credential_path_and_its_target_are_refused(
        self, fake: FakeDocker, tmp_path: Path, capsys: pytest.CaptureFixture, use_target: bool
    ) -> None:
        target = tmp_path / "credentials"
        target.mkdir()
        link = tmp_path / "home" / ".aws"
        link.symlink_to(target, target_is_directory=True)
        assert docker.run("bare", ["--mount", str(target if use_target else link)]) == 1
        assert "host credentials never enter a box" in capsys.readouterr().err
        assert fake.calls == []

    @pytest.mark.parametrize(
        "target",
        [
            ".ssh",
            ".config/opencode",
            ".claude/projects",
            "",
            ".config",
            ".config/gh",
            ".git-credentials",
            ".netrc",
            ".aws",
            ".gnupg",
            ".docker",
            ".kube",
            ".aws/nested",
            ".config/gh/nested",
        ],
    )
    def test_a_credential_dir_inside_or_holding_one_is_refused(
        self,
        fake: FakeDocker,
        tmp_path: Path,
        capsys: pytest.CaptureFixture,
        target: str,
    ) -> None:
        home = tmp_path / "home"
        for rel in (
            ".ssh",
            ".config/opencode",
            ".claude/projects",
            ".config/gh/nested",
            ".aws/nested",
            ".gnupg",
            ".docker",
            ".kube",
        ):
            (home / rel).mkdir(parents=True, exist_ok=True)
        for rel in (".git-credentials", ".netrc"):
            (home / rel).touch()
        assert docker.run("bare", ["--image", "ubuntu:26.04", "--mount", str(home / target)]) == 1
        assert "host credentials never enter a box" in capsys.readouterr().err
        assert fake.runs() == []

    def test_a_missing_path_is_refused_by_name(
        self, fake: FakeDocker, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        missing = tmp_path / "nope"
        assert docker.run("bare", ["--image", "ubuntu:26.04", "--mount", str(missing)]) == 1
        err = capsys.readouterr().err
        assert missing.name in err and "refused: no such path" in err


class TestNames:
    def test_the_next_number_is_past_every_recorded_and_live_box_of_that_verb(self, fake: FakeDocker) -> None:
        seed(
            {"event": "created", "name": "aipass-bare-1", "verb": "bare"},
            {"event": "created", "name": "aipass-bare-2", "verb": "bare"},
            {"event": "created", "name": "aipass-dev-9", "verb": "dev"},
        )
        fake.live = {"aipass-bare-5": "exited"}
        docker.run("bare", ["--image", "ubuntu:26.04"])
        argv = fake.runs()[0]
        assert argv[argv.index("--name") + 1] == "aipass-bare-6"
        row = next(row for row in ledger_rows() if row["name"] == "aipass-bare-6")
        assert (row["event"], row["name"], row["verb"], row["image"]) == (
            "created",
            "aipass-bare-6",
            "bare",
            "ubuntu:26.04",
        )


class TestRm:
    def test_a_name_it_did_not_make_is_refused_and_docker_untouched(
        self, fake: FakeDocker, capsys: pytest.CaptureFixture
    ) -> None:
        fake.live = {"postgres": "running"}
        assert docker.run("rm", ["postgres"]) == 1
        assert "drone docker did not make postgres" in capsys.readouterr().err
        assert not [c for c in fake.calls if c[1] in ("stop", "rm")]

    def test_a_recorded_name_without_our_label_is_refused(
        self, fake: FakeDocker, capsys: pytest.CaptureFixture
    ) -> None:
        seed({"event": "created", "name": "postgres", "verb": "bare"})
        assert docker.run("rm", ["postgres"]) == 1
        assert not [c for c in fake.calls if c[1] in ("stop", "rm")]

    def test_its_own_box_is_force_removed_and_recorded(self, fake: FakeDocker) -> None:
        seed({"event": "created", "name": "aipass-dev-1", "verb": "dev"})
        fake.live = {"aipass-dev-1": "running"}
        assert docker.run("rm", ["aipass-dev-1"]) == 0
        assert [c[1:] for c in fake.calls if c[1] in ("stop", "rm")] == [
            ["rm", "-f", "aipass-dev-1"],
        ]
        assert ledger_rows()[-1]["event"] == "removed"

    def test_all_removes_only_its_live_boxes(self, fake: FakeDocker) -> None:
        seed(
            {"event": "created", "name": "aipass-bare-1", "verb": "bare"},
            {"event": "created", "name": "aipass-bare-2", "verb": "bare"},
        )
        fake.live = {"aipass-bare-1": "exited", "someone-else": "running"}
        assert docker.run("rm", ["--all"]) == 0
        assert [c[-1] for c in fake.calls if c[1] == "rm"] == ["aipass-bare-1"]

    def test_a_running_auto_removed_box_is_removed_successfully(self, fake: FakeDocker) -> None:
        seed({"event": "created", "name": "auto-box", "verb": "bare", "kept": False})
        fake.live["auto-box"] = "running"
        fake.auto_remove.add("auto-box")
        assert docker.run("rm", ["auto-box"]) == 0
        assert "auto-box" not in fake.live
        row = ledger_rows()[-1]
        assert (row["event"], row["name"]) == ("removed", "auto-box")

    @pytest.mark.parametrize(
        "result, expected",
        [
            ((1, "", "Error response from daemon: No such container: trial"), 0),
            ((1, "", "permission denied"), 1),
        ],
    )
    def test_only_an_already_gone_box_counts_as_removed(
        self, fake: FakeDocker, capsys: pytest.CaptureFixture, result: tuple[int, str, str], expected: int
    ) -> None:
        seed({"event": "created", "name": "trial", "verb": "bare"})
        fake.live["trial"] = "running"
        fake.rm_result = result
        assert docker.run("rm", ["trial"]) == expected
        assert ledger_rows()[-1]["event"] == ("removed" if expected == 0 else "created")
        if expected:
            assert "permission denied" in capsys.readouterr().err


class TestShellAndList:
    def test_shell_refuses_a_foreign_name(self, fake: FakeDocker, capsys: pytest.CaptureFixture) -> None:
        fake.live = {"postgres": "running"}
        assert docker.run("shell", ["postgres"]) == 1
        assert "drone docker did not make postgres" in capsys.readouterr().err
        assert not [c for c in fake.calls if c[1] in ("start", "exec")]

    def test_shell_starts_a_stopped_box_then_execs_a_login_shell(self, fake: FakeDocker) -> None:
        seed(
            {
                "event": "created",
                "name": "aipass-local-1",
                "verb": "local",
                "kept": True,
            }
        )
        fake.live = {"aipass-local-1": "exited"}
        assert docker.run("shell", ["aipass-local-1"]) == 0
        assert [c for c in fake.calls if c[1] in ("start", "exec", "stop")] == [
            ["docker", "start", "aipass-local-1"],
            ["docker", "exec", "-it", "aipass-local-1", "bash", "-l"],
            ["docker", "stop", "-t", "1", "aipass-local-1"],
        ]
        assert fake.live["aipass-local-1"] == "exited"

    def test_shell_refuses_in_a_sentence_when_start_leaves_it_down(
        self, fake: FakeDocker, capsys: pytest.CaptureFixture
    ) -> None:
        seed({"event": "created", "name": "aipass-bare-e2e", "verb": "bare", "kept": True})
        fake.live = {"aipass-bare-e2e": "exited"}
        fake.start_dies = True
        assert docker.run("shell", ["aipass-bare-e2e"]) == 1
        assert "aipass-bare-e2e does not stay up when started" in capsys.readouterr().err
        assert fake.execs() == []

    def test_shell_into_a_running_box_leaves_it_running(self, fake: FakeDocker) -> None:
        seed({"event": "created", "name": "aipass-bare-3", "verb": "bare"})
        fake.live = {"aipass-bare-3": "running"}
        assert docker.run("shell", ["aipass-bare-3"]) == 0
        assert fake.verbs() == ["exec"]

    def test_list_shows_its_live_boxes_and_counts_the_gone(
        self, fake: FakeDocker, capsys: pytest.CaptureFixture
    ) -> None:
        seed(
            {
                "event": "created",
                "name": "aipass-dev-1",
                "verb": "dev",
                "kept": True,
                "created": 0,
            },
            {
                "event": "created",
                "name": "aipass-bare-1",
                "verb": "bare",
                "kept": False,
                "created": 0,
            },
        )
        fake.live = {"aipass-dev-1": "exited", "postgres": "running"}
        assert docker.run("list", []) == 0
        out = capsys.readouterr().out
        assert "aipass-dev-1" in out and "stopped" in out and "kept" in out
        assert "postgres" not in out
        assert "1 earlier box(es) gone" in out
        assert "no login volumes" in out

    def test_list_names_each_login_volume(self, fake: FakeDocker, capsys: pytest.CaptureFixture) -> None:
        fake.volumes = ["aipass-login-claude", "aipass-login-codex"]
        assert docker.run("list", []) == 0
        out = capsys.readouterr().out
        assert "login volume  aipass-login-claude" in out and "login volume  aipass-login-codex" in out
        assert "no login volumes" not in out


class TestLoginVolumes:
    def test_rm_login_removes_only_the_aipass_login_volumes_and_records_it(self, fake: FakeDocker) -> None:
        fake.volumes = ["aipass-login-claude", "aipass-login-opencode", "aipass-login-other"]
        assert docker.run("rm", ["--login"]) == 0
        assert [c for c in fake.calls if c[1] == "volume" and c[2] != "ls"] == [
            ["docker", "volume", "rm", "aipass-login-claude", "aipass-login-opencode"]
        ]
        row = ledger_rows()[-1]
        assert (row["event"], row["volumes"]) == ("login_removed", ["aipass-login-claude", "aipass-login-opencode"])

    def test_dockers_refusal_of_a_volume_in_use_passes_through(
        self, fake: FakeDocker, capsys: pytest.CaptureFixture
    ) -> None:
        fake.volumes = ["aipass-login-claude"]
        fake.volume_rm = (1, "", "Error response from daemon: remove aipass-login-claude: volume is in use")
        assert docker.run("rm", ["--login"]) == 1
        assert "volume is in use" in capsys.readouterr().err
        assert not docker_handler.ledger_path().exists()

    def test_rm_login_with_none_says_so(self, fake: FakeDocker, capsys: pytest.CaptureFixture) -> None:
        assert docker.run("rm", ["--login"]) == 0
        assert "no login volumes to remove" in capsys.readouterr().out


class TestDockerMissing:
    def test_absent_docker_says_so_and_exits_2(
        self,
        fake: FakeDocker,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("PATH", str(tmp_path / "home"))
        assert docker.run("bare", ["--image", "ubuntu:26.04"]) == 2
        assert "docker is not installed here" in capsys.readouterr().err
        assert fake.calls == []

    def test_a_down_daemon_says_so_and_exits_2(self, fake: FakeDocker, capsys: pytest.CaptureFixture) -> None:
        fake.info = (
            1,
            "",
            "Cannot connect to the Docker daemon at unix:///var/run/docker.sock.",
        )
        assert docker.run("list", []) == 2
        assert "the docker daemon is not running" in capsys.readouterr().err
        assert fake.runs() == []

    def test_permission_denied_passes_dockers_error_and_the_usermod_line(
        self, fake: FakeDocker, capsys: pytest.CaptureFixture
    ) -> None:
        fake.info = (
            1,
            "",
            "permission denied while trying to connect to the docker API",
        )
        assert docker.run("bare", ["--image", "ubuntu:26.04"]) == 2
        err = capsys.readouterr().err
        assert "permission denied while trying to connect" in err
        assert "sudo usermod -aG docker $USER" in err


class TestDroneRoute:
    def test_drone_docker_routes_and_refuses_a_foreign_rm(
        self,
        fake: FakeDocker,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["drone", "docker", "rm", "not-ours"])
        assert drone_app.main() == 1
        assert "drone docker did not make not-ours" in capsys.readouterr().err

    def test_drone_help_lists_docker(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        monkeypatch.setattr(sys, "argv", ["drone", "--help"])
        assert drone_app.main() == 0
        assert "docker <verb>" in capsys.readouterr().out

    def test_docker_help_keeps_its_brackets(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """The help prints with markup on; escape() keeps its literal brackets. Mutant: escape() dropped from a row."""
        monkeypatch.setattr(sys, "argv", ["drone", "docker", "--help"])
        assert drone_app.main() == 0
        out = capsys.readouterr().out
        assert "drone docker <verb> [options] [-- <command>]" in out
        assert "must match ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$" in out
        assert "Examples:" in out
