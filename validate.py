"""Validate every Catalog, Collection and Item in build/stac against the core and extension JSON schemas."""
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

import pystac
import pystac.validation

from hk25_stac.util import EXT

# The DGGS extension is a proposal with no published schema yet (its URL gives 404): read it from the repository,
# pinned to a commit, under the URL the Items declare.
DGGS_SCHEMA = ("https://raw.githubusercontent.com/stac-extensions/dggs/"
               "996527a1f119366d9ddb660e9e8d5ae0e7cbf88c/json-schema/schema.json")
validator = pystac.validation.JsonSchemaSTACValidator()
with urllib.request.urlopen(DGGS_SCHEMA, timeout=30) as r:
    validator.schema_cache[EXT["dggs"]] = json.load(r)
pystac.validation.set_validator(validator)

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
