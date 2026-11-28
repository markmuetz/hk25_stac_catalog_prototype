"""Prototype MCP server for the km-scale catalogue: search, describe and "how do I open this here".

Reads the catalogue's stac-geoparquet file (items.parquet) into an in-memory DuckDB table, and uses km_scale for the
choice of copy by location. Read-only; no server of ours: run it locally over stdio.

    uv run --group mcp python km_scale_mcp.py          # stdio, for an MCP client
    claude mcp add km-scale -- uv run --directory <this repo> --group mcp python km_scale_mcp.py

Environment:
- KM_SCALE_CATALOG        catalogue root (a build directory or URL); default: the published prototype.
- KM_SCALE_USER_LOCATION  the user's site (e.g. UK on JASMIN); default "online". Used by how_to_open.
- KM_SCALE_MCP_LOG        log file for tool calls (one JSON line each); "off" to disable.
                          Default ~/.km_scale/mcp_log.jsonl. Nothing is sent anywhere.
"""

import functools
import json
import os
import time
from collections import defaultdict
from pathlib import Path

PUBLISHED = "https://markmuetz.github.io/hk25_stac_catalog_prototype"
os.environ.setdefault("KM_SCALE_CATALOG", PUBLISHED)

import duckdb  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

import km_scale  # noqa: E402

CATALOG = os.environ["KM_SCALE_CATALOG"].rstrip("/")
km_scale.CATALOG = CATALOG  # in case km_scale was imported before KM_SCALE_CATALOG was set
LOG = os.environ.get("KM_SCALE_MCP_LOG", str(Path.home() / ".km_scale/mcp_log.jsonl"))

INSTRUCTIONS = """\
The km-scale (WCRP global km-scale hackathon) data catalogue: kilometre-scale simulations, reanalyses, observations
and derived products on HEALPix grids, stored as Zarr at several nodes (UK/JASMIN, EU/DKRZ, NERSC, ...).

Terms: a dataset is a STAC Item (e.g. one model run); it has assets, one per frequency and zoom, keyed "PT1H.z8".
Frequencies are ISO 8601 durations (PT15M, PT1H, PT3H, PT6H, P1D, P1M). Zoom is the HEALPix refinement level
(0 coarsest, ~1.6 km at z12; each step halves the cell size). Variable names are mostly CMIP-style (pr, tas, rlut,
ua); use find_variable to map a quantity ("precipitation") to names.

Typical flow: catalog_overview (vocabulary) -> find_variable / search_datasets -> describe_dataset -> how_to_open.
For anything the other tools don't cover, query_catalog runs read-only SQL on the whole catalogue.
"""

mcp = MCPServer("km-scale-catalog", instructions=INSTRUCTIONS)


# --- logging: one JSON line per tool call, local only ---
def logged(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        t0, error, out = time.time(), None, None
        try:
            out = fn(*args, **kwargs)
            return out
        except Exception as e:  # the agent sees the message (e.g. an unknown id, a SQL error) and can correct itself
            error = str(e.args[0]) if isinstance(e, KeyError) and e.args else str(e)
            raise ToolError(error) from e
        finally:
            if LOG != "off":
                rec = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": fn.__name__, "args": kwargs,
                       "ms": round(1000 * (time.time() - t0)), "error": error,
                       "n": len(out) if isinstance(out, list) else out.get("n") if isinstance(out, dict) else None}
                Path(LOG).parent.mkdir(parents=True, exist_ok=True)
                with open(LOG, "a") as f:
                    f.write(json.dumps(rec, default=str) + "\n")
    return wrapper


# --- the catalogue ---
@functools.cache
def db():
    con = duckdb.connect()
    con.execute(f"create table items as select * exclude (geometry) from '{CATALOG}/items.parquet'")
    con.execute("set global lambda_syntax = 'ENABLE_SINGLE_ARROW'")  # models write x -> f(x); DuckDB 2 wants lambda x: f(x)
    con.execute("set enable_external_access = false")  # query_catalog can't read files or URLs
    con.execute("set lock_configuration = true")
    return con


def rows(sql, params=()):
    cur = db().execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def clean(v):
    """Drop the nulls the Parquet schema adds (every asset struct has every field of every asset)."""
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [clean(x) for x in v]
    return v


@functools.cache
def assets_of(dsid):
    r = rows("select assets from items where id = ?", (dsid,))
    if not r:
        raise KeyError(f"unknown dataset {dsid!r}; use search_datasets to find ids")
    out = {}
    for key, a in clean(r[0]["assets"]).items():
        if not a:
            continue
        for f in ("cube:dimensions", "cube:variables"):
            if isinstance(a.get(f), str):
                a[f] = json.loads(a[f])
        out[key] = a
    return out


@functools.cache
def variable_table():
    """{variable: {dataset id: {unit, standard_name, long_name, frequencies}}} over the whole catalogue."""
    table = defaultdict(dict)
    for (dsid,) in db().execute("select id from items").fetchall():
        for key, a in assets_of(dsid).items():
            for v, c in a.get("cube:variables", {}).items():
                if c.get("type") != "data":
                    continue
                e = table[v].setdefault(dsid, {"unit": c.get("unit"), "standard_name": c.get("cf:standard_name"),
                                                "long_name": c.get("description"), "frequencies": set()})
                e["frequencies"].add(key.split(".")[0])
    return table


def summary(r):
    return {"id": r["id"], "title": r["title"], "type": r["km_scale:product_type"], "domain": r["km_scale:domain"],
            "experiment": r["km_scale:experiment"], "source_id": r["km_scale:source_id"],
            "time": [str(r["start_datetime"] or r["datetime"])[:10], str(r["end_datetime"] or "")[:10]],
            "frequencies": r["km_scale:frequencies"], "zooms": r["km_scale:zooms"], "sites": r["km_scale:sites"]}


# --- tools ---
@mcp.tool()
@logged
def catalog_overview() -> dict:
    """The catalogue's vocabulary and size: experiments, product types, domains, frequencies, zooms, sites, and the
    most common variables. Call this first to learn the valid values for search_datasets."""
    def counts(col, unnest=False):
        expr = f'unnest("{col}")' if unnest else f'"{col}"'
        return {str(k): n for k, n in db().execute(
            f"select {expr} as v, count(*) n from items group by v order by n desc").fetchall()}
    vt = variable_table()
    return {"n": rows("select count(*) n from items")[0]["n"], "catalogue": CATALOG,
            "experiments": counts("km_scale:experiment"), "product_types": counts("km_scale:product_type"),
            "domains": counts("km_scale:domain"), "frequencies": counts("km_scale:frequencies", True),
            "zooms": counts("km_scale:zooms", True), "sites": counts("km_scale:sites", True),
            "common_variables": dict(sorted(((v, len(d)) for v, d in vt.items()), key=lambda x: -x[1])[:40]),
            "n_variables": len(vt)}


@mcp.tool()
@logged
def search_datasets(variables: list[str] | None = None, frequency: str | None = None, zoom: int | None = None,
                    experiment: str | None = None, product_type: str | None = None, domain: str | None = None,
                    source_id: str | None = None, text: str | None = None, lon: float | None = None,
                    lat: float | None = None, start: str | None = None, end: str | None = None,
                    site: str | None = None, limit: int = 50) -> list[dict]:
    """Find datasets. All filters are optional and combine with AND.

    variables: every listed variable must be present (names as in find_variable, e.g. ["pr", "tas"]).
    frequency: e.g. "PT1H"; also matches variants such as "PT1H_inst", "PT1H_mean" and "3D_PT1H"; zoom: HEALPix level; experiment, product_type ("simulation", "reanalysis",
    "observation", "derived"), domain ("global" or "regional"), source_id (model): exact values from
    catalog_overview. text: case-insensitive match in id, title or description. lon/lat: the dataset's footprint
    must cover this point (degrees, lon in -180..180). start/end (YYYY-MM-DD): the dataset must overlap this period.
    site: a copy must exist at this site (e.g. "UK", "EU", "NERSC")."""
    where, p = [], []
    for v in variables or []:
        where.append('list_contains("km_scale:variables", ?)'); p.append(v)
    if frequency:  # HK25 keys add a suffix or prefix: PT1H_inst, PT6H_mean, 3D_PT1H, P1D_part2
        where.append("""len(list_filter("km_scale:frequencies",
                     lambda f: f = ? or f like ? escape '!' or f like ? escape '!')) > 0""")
        p += [frequency, frequency + "!_%", "%!_" + frequency]
    for col, val in (("km_scale:zooms", zoom), ("km_scale:sites", site)):
        if val is not None:
            where.append(f'list_contains("{col}", ?)'); p.append(val)
    for col, val in (("km_scale:experiment", experiment), ("km_scale:product_type", product_type),
                     ("km_scale:domain", domain), ("km_scale:source_id", source_id)):
        if val is not None:
            where.append(f'"{col}" = ?'); p.append(val)
    if text:
        where.append("(id ilike ? or title ilike ? or description ilike ?)"); p += [f"%{text}%"] * 3
    if lon is not None and lat is not None:
        where.append("(bbox.ymin <= ? and bbox.ymax >= ? and (case when bbox.xmin <= bbox.xmax "
                     "then bbox.xmin <= ? and bbox.xmax >= ? else bbox.xmin <= ? or bbox.xmax >= ? end))")
        p += [lat, lat, lon, lon, lon, lon]
    if end:
        where.append("coalesce(start_datetime, datetime) <= ?::timestamptz"); p.append(end)
    if start:
        where.append("coalesce(end_datetime, datetime) >= ?::timestamptz"); p.append(start)
    sql = "select * from items" + (" where " + " and ".join(where) if where else "") + " order by id limit ?"
    return [summary(r) for r in rows(sql, p + [limit])]


@mcp.tool()
@logged
def find_variable(query: str) -> list[dict]:
    """Map a quantity to variable names: matches the query (case-insensitive) against variable names, CF standard
    names and long names, e.g. "precipitation", "outgoing longwave", "rlut". Returns each matching variable with its
    units, standard name and the datasets that have it."""
    q = query.lower()
    out = []
    for v, by_ds in sorted(variable_table().items()):
        meta = next(iter(by_ds.values()))
        hay = " ".join(str(x) for e in by_ds.values() for x in (e["standard_name"], e["long_name"])).lower()
        if q == v.lower() or q in hay or (len(q) > 2 and q in v.lower()):
            units = sorted({str(e["unit"]) for e in by_ds.values()})
            out.append({"variable": v, "standard_name": meta["standard_name"], "long_name": meta["long_name"],
                        "units": units, "n_datasets": len(by_ds),
                        "datasets": {d: sorted(e["frequencies"]) for d, e in sorted(by_ds.items())}})
    return sorted(out, key=lambda e: -e["n_datasets"])[:30]


@mcp.tool()
@logged
def describe_dataset(dataset_id: str, include_variables: bool = True) -> dict:
    """Everything about one dataset: description, model, experiment, time range, footprint, licence, citation,
    providers, its assets (frequency/zoom, where copies are) and, optionally, its variables with units."""
    r = rows("select * from items where id = ?", (dataset_id,))
    if not r:
        raise KeyError(f"unknown dataset {dataset_id!r}; use search_datasets to find ids")
    r = clean(r[0])
    props = {k: v for k, v in r.items() if k not in ("assets", "links", "type", "stac_version", "stac_extensions")}
    props = {k: (str(v) if k.endswith("datetime") else v) for k, v in props.items()}
    links = [{"rel": l["rel"], "href": l["href"], "title": l.get("title")} for l in r.get("links", [])
             if l["rel"] in ("cite-as", "about", "license", "describedby")]
    assets, variables = {}, {}
    for key, a in assets_of(dataset_id).items():
        assets[key] = {"type": a.get("type"), "zoom": a.get("km_scale:zoom"),
                       "copies": ["default"] + sorted(k for k, v in (a.get("alternate") or {}).items() if v),
                       "time_steps": a.get("cube:dimensions", {}).get("time", {}).get("count")}
        for v, c in a.get("cube:variables", {}).items():
            if c.get("type") == "data":
                e = variables.setdefault(v, {"unit": c.get("unit"), "standard_name": c.get("cf:standard_name"),
                                             "long_name": c.get("description"), "frequencies": []})
                if key.split(".")[0] not in e["frequencies"]:
                    e["frequencies"].append(key.split(".")[0])
    out = {"properties": props, "links": links, "assets": assets,
           "item_json": f"{CATALOG}/{km_scale._index()[dataset_id]['item']}",
           "page": f"{CATALOG}/item.html#{dataset_id}"}
    if include_variables:
        out["variables"] = variables
    return out


@mcp.tool()
@logged
def how_to_open(dataset_id: str, frequency: str = "PT1H", zoom: int | None = None,
                location: str | None = None) -> dict:
    """How to open a dataset at the user's site: which copy to read, its URL or path, and Python code to open it.

    frequency and zoom pick the asset (zoom defaults to the finest available). location is the user's site (e.g.
    "UK" on JASMIN, "EU" on Levante); default: KM_SCALE_USER_LOCATION, else "online". Also returns which copy every
    other site would read."""
    assets = assets_of(dataset_id)
    if zoom is None:
        zs = [a["km_scale:zoom"] for k, a in assets.items() if k.split(".")[0] == frequency and "km_scale:zoom" in a]
        if not zs:
            raise KeyError(f"{dataset_id}: no assets at {frequency!r}; available: {', '.join(sorted(assets))}")
        zoom = max(zs)
    loc = location or os.environ.get("KM_SCALE_USER_LOCATION", km_scale.ONLINE)
    href, opts, copy = km_scale._choose(dataset_id, frequency, zoom, location=loc)
    note = None
    if loc != km_scale.ONLINE and not copy.startswith((loc, f"{km_scale.ONLINE} via {loc}")):
        note = f"You are at {loc!r} but the nearest copy is {copy!r}: reading it may be slow."
    code = (f"import km_scale  # KM_SCALE_USER_LOCATION={loc}\n"
            f"ds = km_scale.open_dataset({dataset_id!r}, freq={frequency!r}, zoom={zoom})\n\n"
            f"# or directly with xarray:\nimport xarray as xr\n"
            f"ds = xr.open_zarr({href!r}" + (f", storage_options={opts!r}" if opts else "") + ")")
    return {"location": loc, "copy": copy, "href": href, "storage_options": opts, "note": note, "code": code,
            "other_sites": {s: c for s, (c, _) in km_scale.where(dataset_id, frequency, zoom).items()}}


@mcp.tool()
@logged
def query_catalog(sql: str) -> dict:
    """Run a read-only SQL (DuckDB) query on table `items`, one row per dataset, for questions the other tools don't
    answer (counts, comparisons, unusual filters). Quote property names, which contain colons:
    "km_scale:variables" (list), "km_scale:frequencies" (list), "km_scale:zooms" (list), "km_scale:experiment",
    "km_scale:product_type", "km_scale:domain", "km_scale:source_id", "km_scale:sites" (list), plus id, title,
    description, license, collection, start_datetime, end_datetime, bbox (struct xmin/ymin/xmax/ymax), assets
    (struct of assets; cube:* fields are JSON text). Results are capped at 200 rows."""
    s = sql.strip().rstrip(";")
    if not s.lower().startswith(("select", "with")):
        raise ValueError("only SELECT or WITH queries")
    cur = db().cursor().execute(f"select * from ({s}) limit 201")
    cols = [c[0] for c in cur.description]
    data = [[str(x) if not isinstance(x, (int, float, str, bool, type(None), list)) else x for x in r]
            for r in cur.fetchall()]
    return {"n": min(len(data), 200), "truncated": len(data) > 200, "columns": cols, "rows": data[:200]}


@mcp.resource("km-scale://sites")
def sites() -> str:
    """The site table: each node's name and description."""
    return json.dumps(km_scale._sites(), indent=1)


if __name__ == "__main__":
    mcp.run()
