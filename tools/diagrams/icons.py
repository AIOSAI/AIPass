# =================== AIPass ====================
# Name: icons.py
# Description: Diagram kit icon set - white 4px line icons on an 88x88 tile
# Version: 1.0.0
# Created: 2026-10-19
# Modified: 2026-10-19
# =============================================

"""The icon set. Each function takes a colour and returns SVG markup for an 88x88 box.

The caller wraps the markup in a group that sets fill="none", a 4px stroke in the
same colour, and round caps and joins; an icon only spells out a fill where it
draws a solid shape. Each icon stays under 12 path elements.
"""

from __future__ import annotations

from typing import Callable


def person(c: str) -> str:
    """Head and shoulders."""
    return '<circle cx="44" cy="32" r="13"/><path d="M18 72c4-16 14-22 26-22s22 6 26 22"/>'


def chat(c: str) -> str:
    """A speech bubble with two lines of text."""
    return (
        '<path d="M20 22h48a8 8 0 0 1 8 8v22a8 8 0 0 1-8 8H40l-14 12V60h-6a8 8 0 0 1-8-8V30a8 8 0 0 1 8-8z"/>'
        '<path d="M30 37h28M30 47h18"/>'
    )


def folder(c: str) -> str:
    """A closed folder with a tab."""
    return '<path d="M16 30a6 6 0 0 1 6-6h16l8 8h20a6 6 0 0 1 6 6v26a6 6 0 0 1-6 6H22a6 6 0 0 1-6-6z"/>'


def agent(c: str) -> str:
    """The robot: head, two eyes, antenna, ears."""
    return (
        '<rect x="16" y="28" width="56" height="42" rx="12"/>'
        f'<circle cx="34" cy="49" r="5" fill="{c}" stroke="none"/>'
        f'<circle cx="54" cy="49" r="5" fill="{c}" stroke="none"/>'
        '<path d="M44 28V18M36 18h16M9 45v8M79 45v8"/>'
    )


def gear(c: str) -> str:
    """A hub with eight spokes inside a dashed ring."""
    return (
        '<circle cx="44" cy="44" r="10"/>'
        '<circle cx="44" cy="44" r="20" stroke-dasharray="5 5"/>'
        '<path d="M44 14v6M44 68v6M14 44h6M68 44h6"/>'
        '<path d="M65 23l-4 4M23 65l4-4M65 65l-4-4M23 23l4 4"/>'
    )


def document(c: str) -> str:
    """A page with a folded corner and two text lines."""
    return (
        '<path d="M24 14h28l14 14v44a4 4 0 0 1-4 4H24a4 4 0 0 1-4-4V18a4 4 0 0 1 4-4z"/>'
        '<path d="M52 14v14h14M30 46h28M30 58h20"/>'
    )


def envelope(c: str) -> str:
    """A closed envelope."""
    return '<rect x="14" y="24" width="60" height="42" rx="6"/><path d="M16 28l28 21 28-21"/>'


def inbox(c: str) -> str:
    """An in-tray with a dip in the front lip."""
    return '<path d="M14 50l10-28h40l10 28v16a4 4 0 0 1-4 4H18a4 4 0 0 1-4-4z"/><path d="M14 50h18l4 8h16l4-8h18"/>'


def sparkle(c: str) -> str:
    """A large four-point star and a small one, filled."""
    return (
        f'<path d="M42 14l7 19 19 7-19 7-7 19-7-19-19-7 19-7z" fill="{c}" stroke="none"/>'
        f'<path d="M66 54l3 8 8 3-8 3-3 8-3-8-8-3 8-3z" fill="{c}" stroke="none"/>'
    )


def database(c: str) -> str:
    """A stacked cylinder."""
    return (
        '<ellipse cx="44" cy="24" rx="22" ry="9"/>'
        '<path d="M22 24v38c0 5 10 9 22 9s22-4 22-9V24M22 43c0 5 10 9 22 9s22-4 22-9"/>'
    )


def shield(c: str) -> str:
    """A shield with a check mark."""
    return '<path d="M44 14l26 10v20c0 16-11 29-26 34-15-5-26-18-26-34V24z"/><path d="M32 44l9 9 16-18"/>'


def list_(c: str) -> str:
    """Four bulleted lines."""
    dots = "".join(f'<circle cx="16" cy="{y}" r="2.5" fill="{c}" stroke="none"/>' for y in (24, 38, 52, 66))
    return '<path d="M24 24h44M24 38h44M24 52h30M24 66h20"/>' + dots


def terminal(c: str) -> str:
    """A prompt box: window, chevron, cursor line."""
    return '<rect x="12" y="18" width="64" height="52" rx="8"/><path d="M24 36l10 8-10 8M42 54h18"/>'


def phone(c: str) -> str:
    """A handset with speaker slot and home bar."""
    return '<rect x="26" y="12" width="36" height="64" rx="8"/><path d="M39 21h10M38 66h12"/>'


def dashboard(c: str) -> str:
    """Three bars on a baseline."""
    return '<path d="M16 72h56M26 64V46M44 64V22M62 64V36"/>'


def clock(c: str) -> str:
    """A clock face with two hands."""
    return '<circle cx="44" cy="44" r="28"/><path d="M44 28v16l11 8"/>'


def brain(c: str) -> str:
    """Two lobes split down the middle."""
    return (
        '<path d="M44 18v52"/>'
        '<path d="M44 22c-6-6-20-3-20 8-9 3-9 18-1 22-2 10 9 17 21 12"/>'
        '<path d="M44 22c6-6 20-3 20 8 9 3 9 18 1 22 2 10-9 17-21 12"/>'
    )


ICONS: dict[str, Callable[[str], str]] = {
    "person": person,
    "chat": chat,
    "folder": folder,
    "agent": agent,
    "gear": gear,
    "document": document,
    "envelope": envelope,
    "inbox": inbox,
    "sparkle": sparkle,
    "database": database,
    "shield": shield,
    "list": list_,
    "terminal": terminal,
    "phone": phone,
    "dashboard": dashboard,
    "clock": clock,
    "brain": brain,
}


def icon_markup(name: str, colour: str) -> str:
    """The named icon wrapped in its stroke group, ready to place on an 88x88 box."""
    body = ICONS[name](colour)
    return (
        f'<g fill="none" stroke="{colour}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">{body}</g>'
    )


# =================== END AIPass ====================
