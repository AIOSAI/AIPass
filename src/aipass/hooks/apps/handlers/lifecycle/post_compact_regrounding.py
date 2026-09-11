# =================== AIPass ====================
# Name: post_compact_regrounding.py
# Version: 2.0.0
# Description: Mid-turn grounding backstop after compaction, budgeted per fire (PostToolUse, DPLAN-0276, #752)
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-07-31
# Modified: 2026-09-10
# =============================================

"""Re-grounds the agent after compaction even when no UserPromptSubmit arrives.

Cadence's reset_counter() (called from PreCompact) only takes effect on the
NEXT UserPromptSubmit — but that event does not fire during long autonomous
tool-call loops, only PostToolUse does. PreCompact/PostCompact stdout is never
shown to Claude (debug log only), so neither can inject grounding directly.
PostToolUse's hookSpecificOutput.additionalContext IS shown to Claude, and
fires on every tool call — this consumes the same post-compact signal there
instead of waiting for a UserPromptSubmit that may not come for a long time.

ONE FIRE MUST STAY UNDER THE DISPLAY LIMIT (issue #752). Until 2026-09-10 this
joined branch + identity + kernel + navmap into one additionalContext of about
21,500 chars. Claude Code persists any hook additionalContext longer than
10,000 chars to a file and shows the agent a 2,000-char preview, so the agent
got the header and a sliver of the kernel, and the branch prompt never landed.
The limit was measured, not assumed, two ways on 2026-09-10:

 - read from the installed binary (Claude Code 2.1.267): the hook-output
   persister ``Fme(e, n, r, {threshold: o = sgr})`` returns the text untouched
   when ``e.length <= o``, with ``sgr = 1e4``; additionalContext is passed
   with the default threshold, and the preview constant is ``EBe = 2000``.
   ``e.length`` is a JS string length, i.e. UTF-16 code units, which is the
   unit REGROUP_FIRE_BUDGET is counted in.
 - corroborated from 1,609 hook attachments across every transcript on this
   machine (2.1.207 to 2.1.267): the largest PostToolUse additionalContext
   shown inline was 2,424 chars and the smallest persisted one 12,148; the
   smallest persisted hook stdout was 10,221, while navmap's ~7,900 lands
   inline every cadence fire.

So the re-ground is packed into parts, each at most REGROUP_FIRE_BUDGET, and
handed out one part per PostToolUse in priority order — branch prompt (with
the manager release notice at its head), identity, kernel, navmap — so that
if anything is ever lost it is the least important tail. The parts ride the
cadence regroup token: the first fire consumes it and queues the rest, a real
UserPromptSubmit cancels what is left (the cadence turn-0 path then delivers
every loader as its own injection), and a new compaction starts over.
"""

import importlib
import json

from aipass.prax.apps.modules.logger import system_logger as logger

#: Claude Code 2.1.267 persists hook additionalContext above 10,000 UTF-16
#: units and shows a 2,000-char preview (see the module docstring for how that
#: was measured). 9,000 leaves 10% margin for a future lower limit and is the
#: hard ceiling for every fire this handler emits, headers and markers included.
REGROUP_FIRE_BUDGET = 9000

_SILENT = {"stdout": "", "exit_code": 0}
_SEP = "\n\n"


def _cc_len(text: str) -> int:
    """Length the way Claude Code measures it: UTF-16 code units, not code points."""
    return len(text.encode("utf-16-le")) // 2


def _first_header(total: int, instruction: str) -> str:
    """The full header for part 1: what happened, the memory rule, the active instruction."""
    lines = [
        f"[POST-COMPACT RE-GROUND 1/{total} — mid-turn backstop, DPLAN-0276]",
        "Compaction happened without a following UserPromptSubmit, so cadence-based "
        "grounding didn't fire yet. Re-grounding now via PostToolUse.",
    ]
    if total > 1:
        lines.append(
            f"It arrives in {total} parts over your next tool calls, most important first "
            "(branch, identity, kernel, navmap) — each part fits the hook display limit."
        )
    lines.append(
        "Reminder: .trinity sessions[]/key_learnings[] are NEWEST-FIRST — insert new "
        "entries at index 0 with number = max existing + 1, never append at the tail."
    )
    return "\n".join(lines) + "\n\n" + instruction.rstrip("\n")


def _next_header(index: int, total: int) -> str:
    return f"[POST-COMPACT RE-GROUND {index}/{total} — continued, DPLAN-0276]"


def _load_sections(hook_data: dict) -> list[tuple[str, str]]:
    """Every non-empty grounding section, in the order the agent must not lose them.

    Branch first: it carries the seat's own rules (sign-in, memory discipline,
    caps) and is the one section no other injection repeats mid-turn. The
    manager release notice (DPLAN-0335 leg 2) opens the branch section rather
    than trailing the payload, so it lands in part 1 on every seat. It is built
    only once there is grounding to carry it — the two reads it costs are not
    spent on a regroup that has nothing to say.
    """
    grounding_content = importlib.import_module("aipass.hooks.apps.modules.grounding_content")
    loaders = (
        ("branch", grounding_content.load_branch),
        ("identity", grounding_content.load_identity),
        ("kernel", grounding_content.load_kernel),
        ("navmap", grounding_content.load_navmap),
    )
    sections: list[tuple[str, str]] = []
    for label, loader in loaders:
        try:
            content = loader(hook_data)
        except Exception as exc:
            logger.info("[HOOKS] post_compact_regrounding: %s load failed: %s", label, exc)
            content = ""
        if content and content.strip():
            sections.append((label, content.strip("\n")))
    if not sections:
        return []

    try:
        release_notice = importlib.import_module("aipass.hooks.apps.modules.release_notice")
        notice = release_notice.build_notice(hook_data)
    except Exception as exc:
        logger.info("[HOOKS] post_compact_regrounding: release notice failed: %s", exc)
        notice = ""
    if notice:
        if sections[0][0] == "branch":
            sections[0] = ("branch+notice", notice + _SEP + sections[0][1])
        else:
            sections.insert(0, ("notice", notice))
    return sections


def _split_to_fit(text: str, room: int) -> tuple[str, str]:
    """Longest whole-line prefix of *text* within *room* units, and the rest.

    Falls back to a hard character cut only when not even one line fits, so a
    section is split between lines wherever a line boundary exists.
    """
    lines = text.split("\n")
    taken = 0
    size = 0
    for i, line in enumerate(lines):
        add = _cc_len(line) + (1 if i else 0)
        if size + add > room:
            break
        size += add
        taken = i + 1
    if taken:
        return "\n".join(lines[:taken]), "\n".join(lines[taken:])
    cut = room
    while cut > 0 and _cc_len(text[:cut]) > room:
        cut -= 1
    return text[:cut], text[cut:]


_CONT_TAIL = "\n[… continued in the next re-ground part]"
_CONT_HEAD = "[… continued from the previous re-ground part]\n"


class _Fire:
    """One part under construction: its text pieces and the section labels it carries."""

    def __init__(self, header: str) -> None:
        self.parts = [header]
        self.labels: list[str] = []

    def size_with(self, body: str | None = None) -> int:
        """Claude Code length of this part as it stands, or with *body* joined on."""
        return _cc_len(_SEP.join(self.parts if body is None else [*self.parts, body]))

    def add(self, body: str, label: str) -> None:
        """Join *body* to this part and record which section it came from."""
        self.parts.append(body)
        self.labels.append(label)

    def text(self) -> str:
        """The part exactly as it is sent: header and bodies, blank-line separated."""
        return _SEP.join(self.parts)


def _pack(
    sections: list[tuple[str, str]], instruction: str, budget: int = REGROUP_FIRE_BUDGET
) -> list[tuple[str, str]]:
    """Pack *sections* into parts of at most *budget* units: order kept, nothing dropped.

    Returns (text, labels) per part. A section that fits the current part joins
    it; one that does not, but would fit a fresh part, starts one, so sections
    stay whole wherever they can; one larger than a whole part is split between
    lines and carried into the next. Headers name the part count, and the
    count's own header line can shift the packing, so it re-packs until the
    count it prints is the count it produced.
    """
    total = 1
    fires = _pack_once(sections, instruction, budget, total)
    for _ in range(3):
        if len(fires) == total:
            break
        total = len(fires)
        fires = _pack_once(sections, instruction, budget, total)
    return [(fire.text(), ",".join(fire.labels)) for fire in fires]


def _pack_once(sections: list[tuple[str, str]], instruction: str, budget: int, total: int) -> list[_Fire]:
    fires = [_Fire(_first_header(total, instruction))]
    for label, text in sections:
        pending, continued = text, False
        while pending:
            current = fires[-1]
            head_mark = _CONT_HEAD if continued else ""
            tag = f"{label}(cont)" if continued else label
            body = head_mark + pending
            if current.size_with(body) <= budget:
                current.add(body, tag)
                break
            fresh = _Fire(_next_header(len(fires) + 1, total))
            if current.labels and fresh.size_with(body) <= budget:
                fires.append(fresh)
                continue
            room = budget - current.size_with() - _cc_len(_SEP) - _cc_len(head_mark) - _cc_len(_CONT_TAIL)
            if room <= 0:
                if not current.labels:
                    raise ValueError(f"re-ground budget {budget} cannot hold a part header")
                fires.append(fresh)
                continue
            head, pending = _split_to_fit(pending, room)
            current.add(head_mark + head + _CONT_TAIL, tag)
            continued = True
            fires.append(_Fire(_next_header(len(fires) + 1, total)))
    return [fire for fire in fires if fire.labels]


def handle(hook_data: dict) -> dict:
    """Inject the next budgeted part of the post-compact re-ground, if one is due."""
    try:
        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        part = cadence.pop_regroup_part(hook_data)
        if part is None:
            if not cadence.consume_regroup_pending(hook_data):
                return _SILENT
            index = 1
        else:
            index = part[0]
    except Exception as exc:
        logger.info("[HOOKS] post_compact_regrounding: cadence check failed: %s", exc)
        return _SILENT

    try:
        grounding_content = importlib.import_module("aipass.hooks.apps.modules.grounding_content")
        sections = _load_sections(hook_data)
        if not sections:
            return _SILENT

        fires = _pack(sections, grounding_content.STARTUP_REGROUND_INSTRUCTION)
        if index == 1 and len(fires) > 1:
            cadence.queue_regroup_parts(len(fires), hook_data)
        if index > len(fires):
            return _SILENT

        context, labels = fires[index - 1]
        cadence.log_regroup_fire(labels, index, len(fires), context, REGROUP_FIRE_BUDGET, hook_data)
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": context,
            }
        }
        return {"stdout": json.dumps(result), "exit_code": 0, "sound": "post compact reground"}

    except Exception as exc:
        logger.info("[HOOKS] post_compact_regrounding: unexpected error: %s", exc)
        return _SILENT
