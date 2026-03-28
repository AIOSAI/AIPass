# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: CLI Routing Tests for Drone (adapted from universal template)
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-03-27
# =============================================

"""
CLI Routing Tests for Drone

Drone's CLI entry point is apps/drone.py (not cli_handler.py).
This file tests print_help, print_introspection, and short_help (-h)
using drone.py's functions directly.

Covers the 2 missing CLI routing items:
  - short_help (CR-002)
  - print_help (CR-007)
"""

import sys
from unittest.mock import patch

import pytest


def test_print_help(capsys: pytest.CaptureFixture[str]) -> None:  # CR-007
    """print_help() runs without error and produces stdout output."""
    from aipass.drone.apps.drone import print_help

    print_help()
    captured = capsys.readouterr()
    assert len(captured.out) > 0, "print_help() must produce output"


def test_print_introspection(capsys: pytest.CaptureFixture[str]) -> None:  # CR-008
    """print_introspection() runs without error and produces stdout output."""
    from aipass.drone.apps.drone import print_introspection

    print_introspection()
    captured = capsys.readouterr()
    assert len(captured.out) > 0, "print_introspection() must produce output"


def test_short_help() -> None:  # CR-002
    """drone -h flag triggers help and exits cleanly."""
    from aipass.drone.apps.drone import main

    with patch.object(sys, "argv", ["drone", "-h"]):
        result = main()
    assert result == 0, "drone -h must return exit code 0"
