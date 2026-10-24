# =================== AIPass ====================
# Name: test_srt_resolve.py
# Version: 1.0.3
# Description: Regression tests for _srt_resolve.mjs candidate-list resolution
# Branch: hooks
# Created: 2026-08-01
# Modified: 2026-10-24
# =============================================

"""Tests for apps/modules/_srt_resolve.mjs, the resolver apps/modules/sandbox.py calls (DPLAN-0279)."""

# Real Node via subprocess (ESM); node's execPath prefix cannot be faked, so each test isolates one other mechanism.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(documentation) — the script's header comment, the documentation standard covers it
# seedgo: no-test-needed(generated) — the full-mode wrapped command resolve_bwrap_command returns; sandbox-runtime builds it
# seedgo: no-test-needed(stdlib) — subprocess.run's process launch, the stdlib's own

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_MJS = Path(__file__).resolve().parent.parent / "apps" / "modules" / "_srt_resolve.mjs"
_PKG_RELATIVE_ENTRY = Path("@anthropic-ai/sandbox-runtime/dist/index.js")
_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(_NODE is None, reason="requires a real node binary")

# POSIX layouts by design; on Windows the minimal envs also abort node (its CSPRNG needs SYSTEMROOT).
_posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX-layout scenario")

# A hang backstop, not a latency assertion: cold Windows runners are slow to start node.
_NODE_TIMEOUT_S = 60


def _make_package(node_modules_dir: Path) -> Path:
    """Create a fake @anthropic-ai/sandbox-runtime/dist/index.js under node_modules_dir."""
    entry = node_modules_dir / _PKG_RELATIVE_ENTRY
    entry.parent.mkdir(parents=True)
    entry.write_text("export const SandboxManager = {};\n", encoding="utf-8")
    return entry


def _fake_npm(bin_dir: Path, prints: str) -> None:
    """Write a stub `npm` on bin_dir that answers `npm root -g` with prints."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    npm = bin_dir / "npm"
    script = f'#!/bin/sh\nif [ "$1" = "root" ] && [ "$2" = "-g" ]; then\n  echo "{prints}"\nfi\n'
    npm.write_text(script, encoding="utf-8")
    npm.chmod(npm.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _node() -> str:
    assert _NODE is not None
    return _NODE


def _run_resolve(tmp_path: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_node(), str(_MJS), "--resolve"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=_NODE_TIMEOUT_S,
        check=False,
        cwd=str(tmp_path),
        env=env,
    )


class TestSrtResolveCandidates:
    """Regression coverage: candidate-list prefix discovery."""

    @_posix_only
    def test_npm_config_prefix_env_wins(self, tmp_path):
        """nvm-style layout: the environment names the prefix directly -- highest
        priority candidate, resolved without needing npm on PATH at all."""
        prefix = tmp_path / "nvm-prefix"
        entry = _make_package(prefix / "lib" / "node_modules")

        env = {"PATH": "/nonexistent", "npm_config_prefix": str(prefix)}
        result = _run_resolve(tmp_path, env)

        assert result.returncode == 0
        assert result.stdout.strip() == str(entry)

    @_posix_only
    def test_npm_root_g_used_when_no_env_prefix(self, tmp_path):
        """Debian/Ubuntu-style split-prefix layout: no env var, but `npm root -g`
        (queried directly, authoritative) reports the real /usr/local-style root."""
        npm_root = tmp_path / "usr-local" / "lib" / "node_modules"
        entry = _make_package(npm_root)

        bin_dir = tmp_path / "bin"
        _fake_npm(bin_dir, prints=str(npm_root))

        env = {"PATH": str(bin_dir)}
        result = _run_resolve(tmp_path, env)

        assert result.returncode == 0
        assert result.stdout.strip() == str(entry)

    @_posix_only
    def test_env_prefix_takes_priority_over_npm_root_g(self, tmp_path):
        """Candidate order: npm_config_prefix must win even when `npm root -g`
        would also resolve to something (and to something WITHOUT the package)."""
        prefix = tmp_path / "declared-prefix"
        entry = _make_package(prefix / "lib" / "node_modules")

        decoy_root = tmp_path / "decoy" / "lib" / "node_modules"
        decoy_root.mkdir(parents=True)
        bin_dir = tmp_path / "bin"
        _fake_npm(bin_dir, prints=str(decoy_root))

        env = {"PATH": str(bin_dir), "npm_config_prefix": str(prefix)}
        result = _run_resolve(tmp_path, env)

        assert result.returncode == 0
        assert result.stdout.strip() == str(entry)

    @_posix_only
    def test_missing_entirely_exits_nonzero_with_tried_candidates(self, tmp_path):
        """srt not installed anywhere a candidate looks: non-zero exit, no
        stdout, and the tried candidate paths listed on stderr (not silently
        exit-0)."""
        exec_path_prefix = Path(_node()).resolve().parent.parent
        real_candidates = [
            Path("/usr/local/lib/node_modules") / _PKG_RELATIVE_ENTRY,
            Path("/usr/lib/node_modules") / _PKG_RELATIVE_ENTRY,
            exec_path_prefix / "lib" / "node_modules" / _PKG_RELATIVE_ENTRY,
        ]
        for candidate in real_candidates:
            if candidate.exists():
                pytest.skip(f"{candidate} exists on this machine -- can't test the absent case")

        bin_dir = tmp_path / "bin"
        _fake_npm(bin_dir, prints="")  # npm present but reports nothing

        env = {"PATH": str(bin_dir)}
        result = _run_resolve(tmp_path, env)

        assert result.returncode != 0
        assert result.stdout == ""
        assert "not resolvable" in result.stderr
        assert "sandbox-runtime" in result.stderr

    def test_usage_error_on_full_mode_missing_args(self, tmp_path):
        """Full mode (config + command) still requires both args -- exit
        non-zero with a usage message, not a silent pass."""
        result = subprocess.run(
            [_node(), str(_MJS)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=_NODE_TIMEOUT_S,
            check=False,
            cwd=str(tmp_path),
        )

        assert result.returncode != 0
        assert "usage" in result.stderr
