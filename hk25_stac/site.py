"""The search page's files: a flat index of Items, the hierarchy tree, the site table, problems and the pages."""

import json
import shutil
from pathlib import Path

from .geoparquet import write_assets_table, write_geoparquet

HERE = Path(__file__).resolve().parent.parent
PAGES = ["index.html", "item.html", "stac.html"]


def gridlook(d):
    """A store for the gridlook viewer: global data only, the reachable online store nearest zoom 7."""
    if d.props["km_scale:domain"] != "global":
        return None
    cands = [(abs(a.get("dggs:refinement_level", 99) - 7), k, a) for k, a in d.assets.items()
             if a["href"].startswith("http") and a.get("km_scale:reachable", True) and a.get("km_scale:format") is None
             and not k.startswith("static")]
    return min(cands)[2]["href"] if cands else None


def index_entry(d, item_path, out):
    p = d.props
    return {
        "id": d.id, "title": p["title"], "collection": d.coll, "branch": d.branch, "path": f"{d.branch}/{d.coll}",
        "product_type": p["km_scale:product_type"], "experiment": p.get("km_scale:experiment"),
        "domain": p["km_scale:domain"], "source_id": p.get("km_scale:source_id"),
        "resolution": p.get("km_scale:resolution"), "start": p.get("start_datetime"),
        "end": p.get("end_datetime"), "time_from_data": p.get("km_scale:time_from_data", False),
        "license": p["license"], "license_text": p.get("km_scale:license_text"),
        "sites": p["km_scale:sites"], "site_only": p.get("km_scale:site_only"), "frequencies": d.frequencies,
        "zooms": d.zooms, "variables": d.data_variables, "description": (p.get("description") or "")[:600],
        "item": str(Path(item_path).relative_to(out)), "gridlook": gridlook(d),
    }


def tree(out):
    """The hierarchy for the page's tree filter, read back from the saved STAC links (by-experiment views left out)."""
    stac = (out / "stac").resolve()

    def node(path):
        d = json.loads(path.read_text())
        n = {"id": d["id"], "title": d.get("title") or d["id"], "type": d["type"],
             "path": str(path.parent.relative_to(stac)), "href": str(path.relative_to(out.resolve())),
             "description": d.get("description")}
        for k in ("license", "summaries", "providers", "extent"):
            if k in d:
                n[k] = d[k]
        kids = [(path.parent / l["href"]).resolve() for l in d["links"] if l["rel"] == "child"]
        n["children"] = [node(c) for c in kids if "by-experiment" not in str(c)]
        return n
    return node(stac / "catalog.json")


def write_site(drafts, item_paths, out, sites, problems, usage):
    index = [index_entry(d, item_paths[d.id], out) for d in sorted(drafts, key=lambda d: (d.branch, d.coll, d.id))]
    (out / "index.json").write_text(json.dumps(index, indent=0))
    (out / "tree.json").write_text(json.dumps(tree(out), indent=0))
    shutil.copy(HERE / "config/sites.yaml", out / "sites.yaml")
    (out / "sites.json").write_text(json.dumps(sites, indent=1))
    (out / "problems.txt").write_text("\n".join(problems.lines()) + "\n")
    (out / "attribute_usage.json").write_text(json.dumps(usage, indent=1, sort_keys=True))
    write_geoparquet(item_paths.values(), out / "items.parquet")
    write_assets_table(item_paths.values(), out / "assets.parquet")
    for page in PAGES:
        shutil.copy(HERE / "page" / page, out / page)
    shutil.copy(HERE / "km_scale.py", out / "km_scale.py")
    return index
