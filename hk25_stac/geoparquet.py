"""All Items in one stac-geoparquet file (items.parquet), for querying without a server.

One row per Item (https://github.com/stac-utils/stac-geoparquet). Two changes from the JSON Items, both because Arrow
makes a column per dictionary key:
- each asset's ``cube:dimensions`` and ``cube:variables`` (keyed by dimension and variable name) are stored as JSON
  text;
- flat lists ``km_scale:variables`` (data variables), ``km_scale:frequencies`` and ``km_scale:zooms`` are added to
  the properties, so the common questions are plain column queries.

    duckdb.sql("select id from 'items.parquet' where list_contains(\"km_scale:variables\", 'pr')")
"""

import copy
import json

CUBE_FIELDS = ("cube:dimensions", "cube:variables")


def flatten(item):
    """A copy of an Item's JSON, as stored in the Parquet file."""
    d = copy.deepcopy(item)
    variables, freqs, zooms = set(), set(), set()
    for key, a in d["assets"].items():
        freqs.add(key.split(".")[0])
        if "km_scale:zoom" in a:
            zooms.add(a["km_scale:zoom"])
        variables |= {v for v, c in a.get("cube:variables", {}).items() if c.get("type") == "data"}
        for f in CUBE_FIELDS:
            if f in a:
                a[f] = json.dumps(a[f])
    d["properties"].update({"km_scale:variables": sorted(variables), "km_scale:frequencies": sorted(freqs),
                            "km_scale:zooms": sorted(zooms)})
    return d


def write_geoparquet(item_paths, path):
    import stac_geoparquet.arrow as sga

    items = [flatten(json.loads(open(p).read())) for p in sorted(item_paths)]
    sga.to_parquet(sga.parse_stac_items_to_arrow(items), str(path))
    return len(items)
