"""Which items no round-3 file has touched yet, plus duplicates and unknown ids."""

import glob
import json
import os
import sys

d = sys.argv[1]
items = json.load(open(os.path.join(d, "items.json"), encoding="utf-8"))
if isinstance(items, dict):
    items = items.get("items", list(items.values()))
seen: dict = {}
for f in sorted(glob.glob(os.path.join(d, "r3", "*.json"))):
    j = json.load(open(f, encoding="utf-8"))
    name = os.path.basename(f)
    for i in j.get("verify", []):
        seen.setdefault(i, []).append(name + ":v")
    for i in j.get("fix", {}):
        seen.setdefault(i, []).append(name + ":f")
    for i in j.get("drop", {}):
        seen.setdefault(i, []).append(name + ":d")
    for a in j.get("add", []):
        seen.setdefault(a["id"], []).append(name + ":a")
ids = {it["id"] for it in items}
adds = {k for k, v in seen.items() if any(x.endswith(":a") for x in v)}
dups = {k: v for k, v in seen.items() if len(v) > 1 and not (len(v) == 2 and k in adds)}
unknown = [k for k in seen if k not in ids and k not in adds]
left = [it for it in items if it["id"] not in seen]
print("items", len(items), "seen", len(seen), "left", len(left))
print("dups", dups)
print("unknown ids", unknown)
for it in left:
    print(it["id"], "|", it.get("group", ""), "|", it.get("name", "")[:60], "|", it.get("file", "")[:70])
