"""Print the items whose file or name matches a substring. python3 -I show.py <dir> <substring> [full]"""

import json
import sys
from pathlib import Path

here = Path(sys.argv[1])
needle = sys.argv[2].lower()
full = len(sys.argv) > 3
data = json.loads((here / "items.json").read_text())
hits = [
    i for i in data["items"] if needle in str(i.get("file", "")).lower() or needle in str(i.get("name", "")).lower()
]
for i in hits:
    print(f"{i['id']} | {i['group']}/{i['kind']} | {i['name']} | {i.get('file', '')}")
    print(f"   does: {i['does']}")
    if full:
        if i.get("touches"):
            print(f"   touches: {i['touches']}")
        if i.get("depends_on"):
            print(f"   depends: {i['depends_on']}")
        if i.get("tested_by"):
            print(f"   tests: {i['tested_by']}")
    if i.get("note"):
        print(f"   note: {i['note']}")
    for r in i.get("review", []):
        print(f"   REVIEW {r['field']}: {r['should_be']}  [{r['why']}]")
print(len(hits), "items")
