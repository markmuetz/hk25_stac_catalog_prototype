# /// script
# requires-python = ">=3.11"
# dependencies = ["pystac[validation]>=1.16"]
# ///
"""Validate every Catalog, Collection and Item in build/stac against the core and extension JSON schemas."""
import sys
from collections import Counter
from pathlib import Path
import pystac

root = pystac.Catalog.from_file(str(Path(sys.argv[1]) / "stac/catalog.json"))
n, errs, seen = Counter(), [], set()
def walk(obj):
    try:
        obj.validate(); n[type(obj).__name__] += 1
    except pystac.errors.STACValidationError as e:
        errs.append((obj.id, str(e).splitlines()[0][:300]))
    for c in obj.get_children():
        walk(c)
    for it in obj.get_items():
        if it.id in seen: continue       # Items linked from by-experiment views too: validate once
        seen.add(it.id)
        try:
            it.validate(); n["Item"] += 1
        except pystac.errors.STACValidationError as e:
            errs.append((it.id, str(e)))
walk(root)
print(dict(n), f"{len(errs)} invalid")
for e in errs[:10]: print(*e)
sys.exit(1 if errs else 0)
