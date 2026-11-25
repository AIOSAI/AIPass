# =================== AIPass ====================
# Name: test_docker.py
# Description: drone docker: the base Dockerfile, the argv per verb and option, names, refusals, exit 2
# Version: 1.0.0
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
        self.live: dict[str, str] = {}
        self.dockerfile = ""

    def __call__(self, argv, *args, **kwargs):
        argv = list(argv)
        self.calls.append(argv)
        answer = getattr(self, f"_{argv[1]}", None)
        rc, out, err = answer(argv) if answer else (0, "", "")
        return subprocess.CompletedProcess(argv, rc, out, err)

    def _info(self, argv: list[str]) -> tuple[int, str, str]:
        return self.info

    def _image(self, argv: list[str]) -> tuple[int, str, str]:
        return (0 if self.image_cached else 1), "", ""

    def _build(self, argv: list[str]) -> tuple[int, str, str]:
        self.dockerfile = Path(argv[-1], "Dockerfile").read_text(encoding="utf-8")
        return 0, "", ""

    def _remote(self, argv: list[str]) -> tuple[int, str, str]:
        return 0, ORIGIN + "\n", ""

    def _ps(self, argv: list[str]) -> tuple[int, str, str]:
        flt = argv[argv.index("--filter") + 1]
        if flt.startswith("name=^"):
            prefix = flt[len("name=^") :]
            return 0, "\n".join(n for n in self.live if n.startswith(prefix)), ""
        return 0, "\n".join(f"{n}\t{s}" for n, s in self.live.items()), ""

    def runs(self) -> list[list[str]]:
        return [c for c in self.calls if c[:2] == ["docker", "run"]]


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


def script_of(argv: list[str]) -> str:
    return argv[argv.index("-lc") + 1]


class TestBaseImage:
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
        assert "aipass install" not in text and "claude" not in text.split("RUN mkdir")[0]

    def test_a_cached_base_is_not_rebuilt_and_rebuild_passes_no_cache(self, fake: FakeDocker) -> None:
        docker.run("bare", ["--image", "ubuntu:26.04", "--", "true"])
        assert not [c for c in fake.calls if c[:2] == ["docker", "build"]]
        docker.run("bare", ["--image", "ubuntu:26.04", "--rebuild", "--", "true"])
        build = next(c for c in fake.calls if c[:2] == ["docker", "build"])
        assert "--no-cache" in build

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
    def test_bare_runs_rm_labelled_named_with_a_login_shell(self, fake: FakeDocker) -> None:
        docker.run("bare", ["--image", "ubuntu:26.04"])
        assert fake.runs() == [
            [
                "docker",
                "run",
                "--rm",
                "--name",
                "aipass-bare-1",
                "--label",
                "aipass.box=bare",
                "aipass-base:ubuntu-26.04",
                "bash",
                "-lc",
                "exec bash -l",
            ]
        ]

    # A real pseudo-terminal, not a patched isatty; Windows has none.
    @pytest.mark.skipif(not hasattr(os, "openpty"), reason="no pseudo-terminals on this OS")
    def test_a_terminal_gets_it(self, fake: FakeDocker, monkeypatch: pytest.MonkeyPatch) -> None:
        main, follower = os.openpty()
        with os.fdopen(follower) as tty:
            monkeypatch.setattr(sys, "stdin", tty)
            docker.run("bare", ["--image", "ubuntu:26.04"])
        os.close(main)
        assert fake.runs()[0][2] == "-it"

    def test_local_mounts_the_repo_read_only_clones_head_and_never_installs(self, fake: FakeDocker) -> None:
        docker.run("local", ["--image", "ubuntu:26.04"])
        argv = fake.runs()[0]
        root = Path.cwd().resolve()
        assert argv[argv.index("-v") + 1] == f"{root}:/src:ro"
        lines = script_of(argv).splitlines()
        assert "git clone -q file:///src ~/AIPass-src" in lines
        assert "git -C ~/AIPass-src log -1 --oneline" in lines
        assert "echo '  aipass install --source /src'" in lines
        assert not [ln for ln in lines if ln.startswith(("aipass ", "pip", "python3 -m venv"))]
        assert lines[-1] == "exec bash -l"

    @pytest.mark.parametrize("verb", ["dev", "main"])
    def test_dev_and_main_clone_that_branch_from_origins_https_url(self, fake: FakeDocker, verb: str) -> None:
        docker.run(verb, ["--image", "ubuntu:26.04"])
        argv = fake.runs()[0]
        assert "-v" not in argv
        lines = script_of(argv).splitlines()
        assert f"git clone -q --branch {verb} https://github.com/AIOSAI/AIPass ~/AIPass-src" in lines
        assert "echo '  aipass install --source ~/AIPass-src'" in lines
        assert argv[argv.index("--name") + 1] == f"aipass-{verb}-1"

    def test_keep_drops_rm_and_is_recorded(self, fake: FakeDocker) -> None:
        docker.run("bare", ["--image", "ubuntu:26.04", "--keep"])
        assert "--rm" not in fake.runs()[0]
        assert ledger_rows()[-1]["kept"] is True

    def test_with_runs_the_vendor_installer_before_the_shell(self, fake: FakeDocker) -> None:
        docker.run("bare", ["--image", "ubuntu:26.04", "--with", "claude", "--with", "codex"])
        script = script_of(fake.runs()[0])
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

    def test_a_command_after_dashes_replaces_the_shell(self, fake: FakeDocker) -> None:
        docker.run("bare", ["--image", "ubuntu:26.04", "--", "whoami;", "python3 --version"])
        assert script_of(fake.runs()[0]) == "whoami; python3 --version"


class TestCredentialMounts:
    @pytest.mark.parametrize("target", [".ssh", ".config/opencode", ".claude/projects", "", ".config"])
    def test_a_credential_dir_inside_or_holding_one_is_refused(
        self,
        fake: FakeDocker,
        tmp_path: Path,
        capsys: pytest.CaptureFixture,
        target: str,
    ) -> None:
        home = tmp_path / "home"
        for rel in (".ssh", ".config/opencode", ".claude/projects"):
            (home / rel).mkdir(parents=True, exist_ok=True)
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
        row = ledger_rows()[-1]
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

    def test_its_own_box_is_stopped_then_removed_and_recorded(self, fake: FakeDocker) -> None:
        seed({"event": "created", "name": "aipass-dev-1", "verb": "dev"})
        fake.live = {"aipass-dev-1": "running"}
        assert docker.run("rm", ["aipass-dev-1"]) == 0
        assert [c[1:] for c in fake.calls if c[1] in ("stop", "rm")] == [
            ["stop", "aipass-dev-1"],
            ["rm", "aipass-dev-1"],
        ]
        assert ledger_rows()[-1]["event"] == "removed"

    def test_all_removes_only_its_live_boxes(self, fake: FakeDocker) -> None:
        seed(
            {"event": "created", "name": "aipass-bare-1", "verb": "bare"},
            {"event": "created", "name": "aipass-bare-2", "verb": "bare"},
        )
        fake.live = {"aipass-bare-1": "exited", "someone-else": "running"}
        assert docker.run("rm", ["--all"]) == 0
        assert [c[2] for c in fake.calls if c[1] == "rm"] == ["aipass-bare-1"]


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
        assert [c for c in fake.calls if c[1] in ("start", "exec")] == [
            ["docker", "start", "aipass-local-1"],
            ["docker", "exec", "-it", "aipass-local-1", "bash", "-l"],
        ]

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
