"""All Items in one stac-geoparquet file (items.parquet), for querying without a server.

One row per Item (https://github.com/stac-utils/stac-geoparquet). Two changes from the JSON Items, both because Arrow
makes a column per dictionary key:
- each asset's ``cube:dimensions`` and ``cube:variables`` (keyed by dimension and variable name) are stored as JSON
  text;
- flat lists ``km_scale:variables`` (data variables), ``km_scale:frequencies`` and ``km_scale:zooms`` (the assets'
  ``dggs:refinement_level`` values) are added to the properties, so the common questions are plain column queries.

    duckdb.sql("select id from 'items.parquet' where list_contains(\"km_scale:variables\", 'pr')")

Also a flat table, assets.parquet, with one row per asset (dataset, frequency, zoom): our own file, not a STAC
convention. HK25's asset keys mix several things into the "frequency" (PT1H_inst, 3D_PT1H, P1D_part2, data), so they
are split into columns here; a frequency missing from the key is inferred from the time axis.

    duckdb.sql("select id, zoom from 'assets.parquet' where frequency = 'PT1H' and list_contains(variables, 'pr')")
"""

import copy
import json
import re
from datetime import datetime

CUBE_FIELDS = ("cube:dimensions", "cube:variables")


def flatten(item):
    """A copy of an Item's JSON, as stored in the Parquet file."""
    d = copy.deepcopy(item)
    variables, freqs, zooms = set(), set(), set()
    for key, a in d["assets"].items():
        freqs.add(key.split(".")[0])
        if "dggs:refinement_level" in a:
            zooms.add(a["dggs:refinement_level"])
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


# --- one row per asset ---
DURATION = re.compile(r"^P(T\d+[HMS]|\d+[DWMY])$")
STEPS = {"PT15M": 900, "PT30M": 1800, "PT1H": 3600, "PT3H": 10800, "PT6H": 21600, "P1D": 86400,
         "P1M": 30.44 * 86400, "P1Y": 365.25 * 86400}
NOT_VERTICAL = {"time", "cell", "crs"}


def parse_key(key):
    """An HK25 asset key, split: "3D_PT1H.z8" -> frequency PT1H, levels 3D, zoom 8; "static" -> frequency fixed."""
    name, _, z = key.partition(".z")
    out = {"frequency": None, "time_method": None, "levels": None, "part": None,
           "zoom": int(z) if z.isdigit() else None}
    for tok in name.split("_"):
        if DURATION.match(tok):
            out["frequency"] = tok
        elif tok in ("inst", "mean", "min", "max", "sum"):
            out["time_method"] = tok
        elif tok in ("2D", "3D"):
            out["levels"] = tok
        elif tok.startswith("part"):
            out["part"] = tok
        elif tok == "static":
            out["frequency"] = "fixed"
    return out


def infer_frequency(time_dim):
    """The nearest standard step to the time axis's mean spacing (within 10%), or None."""
    if not time_dim:
        return None
    if time_dim.get("step"):
        return time_dim["step"]
    n, ext = time_dim.get("count"), time_dim.get("extent") or [None, None]
    if not n or n < 2 or None in ext:
        return None
    t0, t1 = (datetime.fromisoformat(t.replace("Z", "+00:00")) for t in ext)
    dt = (t1 - t0).total_seconds() / (n - 1)
    best = min(STEPS, key=lambda k: abs(STEPS[k] - dt))
    return best if abs(STEPS[best] - dt) <= 0.1 * STEPS[best] else None


def asset_rows(item):
    p = item["properties"]
    default_copy = (p.get("km_scale:site_only") or ["online"])[0]
    for key, a in sorted(item["assets"].items()):
        dims = a.get("cube:dimensions", {})
        variables = a.get("cube:variables", {})
        row = {"id": item["id"], "collection": item.get("collection"), "asset": key, **parse_key(key)}
        row["frequency_inferred"] = False
        if row["frequency"] is None and (f := infer_frequency(dims.get("time"))):
            row["frequency"], row["frequency_inferred"] = f, True
        if row["zoom"] is None:
            row["zoom"] = a.get("dggs:refinement_level")
        time = dims.get("time", {})
        row.update({
            "variables": sorted(v for v, c in variables.items() if c.get("type") == "data"),
            "vertical_dims": sorted(d for d, c in dims.items() if d not in NOT_VERTICAL and c.get("type") not in ("dggs", "healpix")),
            "n_time": time.get("count"), "time_start": (time.get("extent") or [None, None])[0],
            "time_end": (time.get("extent") or [None, None])[1],
            "type": a.get("type"), "format": a.get("km_scale:format", "zarr" if "zarr" in a.get("type", "") else None),
            "href": a["href"], "copies": [default_copy] + sorted(s for s, v in a.get("alternate", {}).items() if v),
            "product_type": p.get("km_scale:product_type"), "domain": p.get("km_scale:domain"),
            "experiment": p.get("km_scale:experiment"), "source_id": p.get("km_scale:source_id"),
        })
        yield row


def write_assets_table(item_paths, path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = [r for p in sorted(item_paths) for r in asset_rows(json.loads(open(p).read()))]
    pq.write_table(pa.Table.from_pylist(rows), str(path))
    return len(rows)
