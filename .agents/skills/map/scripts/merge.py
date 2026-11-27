# =================== AIPass ====================
# Name: merge.py
# Description: Merge the map skill's three passes into items.json for the page
# Version: 1.0.0
# Created: 2026-11-23
# Modified: 2026-11-23
# =============================================

"""Merge slice_*.json, an optional codex_result.json and r3/*.json into items.json.

python3 -I merge.py <dir> ["<title>"]. Without r3/ the second pass stays as
overlays (review[]); with r3/ they fold away and every row carries verified.
"""

import json
import sys
from pathlib import Path


def norm(group):
    """Lowercase a group name; a missing one goes to 'other'."""
    return str(group or "other").lower()


def load_slices(here):
    """Return (items, summaries) from the first-pass slice files, ids made unique."""
    items, summaries, seen = [], [], set()
    for p in sorted(here.glob("slice_*.json")):
        data = json.loads(p.read_text())
        label = f"First pass, slice {data.get('slice', p.stem)}"
        summaries.append({"slice": label, "summary": data.get("summary", "")})
        for it in data["items"]:
            if it["id"] in seen:
                it["id"] = it["id"] + "b"
            seen.add(it["id"])
            it["group"] = norm(it.get("group"))
            items.append(it)
    return items, summaries


def apply_second_pass(here, items, by_id, summaries):
    """Attach the second reader's corrections as overlays and append its missed rows."""
    codex_path = here / "codex_result.json"
    if not codex_path.exists():
        return
    codex = json.loads(codex_path.read_text())
    for c in codex.get("corrections", []):
        it = by_id.get(c["id"])
        if it is not None:
            it.setdefault("review", []).append({"field": c["field"], "should_be": c["should_be"], "why": c["why"]})
    for m in codex.get("missed", []):
        m["group"] = norm(m.get("group"))
        m["source"] = "codex"
        items.append(m)
        by_id[m["id"]] = m
    summaries.append({"slice": "Second pass", "summary": codex.get("summary", "")})


def apply_fix(it, fx):
    """Write one r3 fix onto a row; return True when a FLUFF? flag had to be kept."""
    reflagged = False
    for k, v in fx.items():
        if k == "r3":
            it["r3"] = f"{it['r3']} {v}" if it.get("r3") else v
        elif k == "note" and "FLUFF?" in str(it.get("note", "")) and "FLUFF?" not in v:
            it[k] = "FLUFF? " + v  # a rewrite never un-flags by accident; drop the flag on purpose, with an r3 line
            reflagged = True
        else:
            it[k] = v
    return reflagged


def apply_third_pass(r3_files, items, by_id):
    """Fold the mapper's r3 files in: adds, verifies, fixes with r3 lines, drops."""
    verified, dropped, fixed, added, reflagged = set(), {}, set(), [], []
    for p in r3_files:
        j = json.loads(p.read_text())
        for a in j.get("add", []):
            a["group"] = norm(a.get("group"))
            a.setdefault("source", "round3")
            items.append(a)
            by_id[a["id"]] = a
            added.append(a["id"])
            verified.add(a["id"])
        for i in j.get("verify", []):
            if i in by_id:
                verified.add(i)
            else:
                print("verify: unknown id", i, "in", p.name)
        for i, fx in j.get("fix", {}).items():
            it = by_id.get(i)
            if it is None:
                print("fix: unknown id", i, "in", p.name)
                continue
            if apply_fix(it, fx):
                reflagged.append(i)
            verified.add(i)
            fixed.add(i)
        for i, into in j.get("drop", {}).items():
            it = by_id.pop(i, None)
            if it is None:
                print("drop: unknown id", i, "in", p.name)
                continue
            items.remove(it)
            dropped[i] = into
    for it in items:
        it["verified"] = it["id"] in verified
        it.pop("review", None)
    merged = ", ".join(f"{k} into {v}" for k, v in dropped.items()) or "none"
    summary = (
        f"Every file of the target was read again by the mapper. {len(fixed)} rows were corrected, "
        f"{len(added)} added ({', '.join(added) or 'none'}) and {len(dropped)} merged into their twins ({merged}). "
        "The second pass's corrections are folded into the text. "
        "A 'Round 3' line under a row says what changed and where in the code."
    )
    return {"fixed": fixed, "added": added, "dropped": dropped, "reflagged": reflagged, "summary": summary}


def main():
    """Merge the passes found in sys.argv[1] and write items.json beside them."""
    here = Path(sys.argv[1])
    title = sys.argv[2] if len(sys.argv) > 2 else here.name
    items, summaries = load_slices(here)
    by_id = {it["id"]: it for it in items}
    apply_second_pass(here, items, by_id, summaries)
    r3_files = sorted((here / "r3").glob("*.json")) if (here / "r3").is_dir() else []
    third = apply_third_pass(r3_files, items, by_id) if r3_files else None
    if third:
        summaries.append({"slice": "Third pass", "summary": third["summary"]})
    groups = []
    for it in items:
        if it["group"] not in groups:
            groups.append(it["group"])
    out = {"title": title, "groups": groups, "items": items, "summaries": summaries}
    (here / "items.json").write_text(json.dumps(out, indent=1))
    flagged = sum(1 for i in items if "FLUFF?" in str(i.get("note", "")))
    counts = {g: sum(1 for i in items if i["group"] == g) for g in groups}
    if third:
        print(
            f"{len(items)} items; {flagged} flagged; {len(third['fixed'])} fixed; "
            f"{len(third['added'])} added; {len(third['dropped'])} dropped; {counts}"
        )
        print("unverified:", [i["id"] for i in items if not i["verified"]])
        print("reflagged (FLUFF? kept on a rewritten note):", third["reflagged"])
    else:
        print(f"{len(items)} items; {flagged} flagged; {counts}")


if __name__ == "__main__":
    main()
