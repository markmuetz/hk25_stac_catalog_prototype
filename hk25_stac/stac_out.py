"""Write the STAC tree with pystac.

Layout: ``catalog.json`` → branch Catalogs (simulations, observations, reanalyses, derived → <feature>-tracks) →
a Collection per model or product → Items. The tree is saved as SELF_CONTAINED: every link is relative and there are
no self links, so the same files work locally, on GitHub Pages or copied anywhere. (For absolute self links instead:
``normalize_hrefs(<site URL>/stac, ...)`` and ``save(CatalogType.ABSOLUTE_PUBLISHED, dest_href=stac_dir)`` here, and
``site.tree`` must map URLs back to the local folder. See the README.)

The generated ``by-experiment/`` views link to Items that already have a parent elsewhere. pystac would rewrite or move
Items reached by two paths when it saves, so the views are written afterwards, as plain JSON that only adds links.
"""

import json
import os
from collections import defaultdict

import pystac
from pystac.utils import str_to_datetime

from .util import EXT, GLOBAL_BBOX, STAC_VERSION

ROOT_ID, ROOT_TITLE = "km-scale-hk25-example", "HK25 catalogue as STAC (HK27 prototype)"
ROOT_DESC = "Example static STAC catalogue generated from the HK25 Intake catalogue."
BRANCH_DESCRIPTIONS = {
    "simulations": "Model output, one Collection per model.",
    "observations": "Observational products.",
    "reanalyses": "Reanalyses.",
    "derived": "Products derived from other datasets (e.g. feature tracks).",
    "MCS-tracks": "Mesoscale convective system tracks, one Collection per tracker.",
    "TC-tracks": "Tropical cyclone tracks, one Collection per tracker.",
}
BRANCH_ORDER = ["simulations", "observations", "reanalyses", "derived"]
HK25_LICENCE_PAGE = "https://digital-earths-global-hackathon.github.io/catalog/"


def to_item(d):
    """pystac Item from an ItemDraft."""
    props = dict(d.props)
    dt, start, end = (props.pop(k, None) for k in ("datetime", "start_datetime", "end_datetime"))
    exts = [EXT["alternate"], EXT["zarr"]]
    if any("cube:dimensions" in a for a in d.assets.values()):
        exts += [EXT["datacube"], EXT["cf"]]
    if "sci:doi" in props:
        exts.append(EXT["scientific"])
    if props["km_scale:product_type"] == "derived":
        exts.append(EXT["processing"])
        props["processing:software"] = {d.coll: "unknown"}
    item = pystac.Item(d.id, d.geometry, d.bbox, str_to_datetime(dt) if dt else None, props,
                       start_datetime=str_to_datetime(start) if start else None,
                       end_datetime=str_to_datetime(end) if end else None,
                       stac_extensions=sorted(set(exts)))
    for key, a in d.assets.items():
        a = dict(a)
        item.add_asset(key, pystac.Asset(a.pop("href"), title=a.pop("title", None), media_type=a.pop("type", None),
                                         roles=a.pop("roles", None), extra_fields=a))
    if props["license"] == "other" and props.get("km_scale:license_text"):
        item.add_link(pystac.Link("license", HK25_LICENCE_PAGE, title=props["km_scale:license_text"][:200]))
    for link in d.links:
        item.add_link(pystac.Link(link["rel"], link["href"], media_type=link.get("type"), title=link.get("title")))
    return item


def to_collection(coll, drafts):
    first = drafts[0]
    lic = {d.props["license"] for d in drafts}
    starts = sorted(d.props["start_datetime"] for d in drafts if d.props.get("start_datetime"))
    ends = sorted(d.props["end_datetime"] for d in drafts if d.props.get("end_datetime"))
    interval = [str_to_datetime(starts[0]) if starts else None, str_to_datetime(ends[-1]) if ends else None]
    summ = {"km_scale:experiment": sorted({d.props.get("km_scale:experiment") for d in drafts} - {None}),
            "km_scale:domain": sorted({d.props["km_scale:domain"] for d in drafts})}
    summ = {k: v for k, v in summ.items() if v}  # empty summaries are invalid STAC
    provs = sorted({p["name"] for d in drafts for p in d.props.get("providers", [])})
    return pystac.Collection(
        coll, f"{first.coll_title} datasets from the HK25 catalogue ({len(drafts)} Items).",
        pystac.Extent(pystac.SpatialExtent([GLOBAL_BBOX]), pystac.TemporalExtent([interval])),
        title=first.coll_title, license=lic.pop() if len(lic) == 1 else "other",
        providers=[pystac.Provider(n, roles=["producer"]) for n in provs] or None,
        summaries=pystac.Summaries(summ))


def write_stac(drafts, stac_dir, vocab):
    """Write the tree under stac_dir. Returns {dataset id: Item path}."""
    root = pystac.Catalog(ROOT_ID, ROOT_DESC, title=ROOT_TITLE)
    by_branch = defaultdict(lambda: defaultdict(list))
    for d in drafts:
        by_branch[d.branch][d.coll].append(d)

    catalogs, tops = {}, {}

    def branch_catalog(branch):
        """The Catalog for a branch path such as 'derived/MCS-tracks', creating it and its parents as needed."""
        if branch not in catalogs:
            name = branch.split("/")[-1]
            cat = pystac.Catalog(branch.replace("/", "-"), BRANCH_DESCRIPTIONS.get(name, f"{name} datasets"),
                                 title=name)
            catalogs[branch] = cat
            if "/" in branch:
                branch_catalog(branch.rsplit("/", 1)[0]).add_child(cat)
            else:
                tops[branch] = cat
        return catalogs[branch]

    paths = {}
    for branch in sorted(by_branch):
        cat = branch_catalog(branch)
        for coll in sorted(by_branch[branch]):
            ds = sorted(by_branch[branch][coll], key=lambda d: d.id)
            c = to_collection(coll, ds)
            cat.add_child(c)
            for d in ds:
                c.add_item(to_item(d))
                paths[d.id] = os.path.join(stac_dir, branch, coll, d.id, f"{d.id}.json")
    for top in sorted(tops, key=lambda t: BRANCH_ORDER.index(t) if t in BRANCH_ORDER else 99):
        root.add_child(tops[top])

    root.normalize_hrefs(stac_dir, strategy=_FixedLayout(stac_dir, catalogs, by_branch))
    root.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)
    write_views(drafts, paths, stac_dir, vocab)
    return paths


class _FixedLayout(pystac.layout.HrefLayoutStrategy):
    """Our folder layout: <branch path>/catalog.json, <branch>/<coll>/collection.json, .../<id>/<id>.json."""

    def __init__(self, stac_dir, catalogs, by_branch):
        self.stac_dir = stac_dir
        self.cat_dir = {id(c): os.path.join(stac_dir, b) for b, c in catalogs.items()}
        self.coll_dir = {(b, c): os.path.join(stac_dir, b, c) for b in by_branch for c in by_branch[b]}

    def get_catalog_href(self, cat, parent_dir, is_root):
        return os.path.join(self.stac_dir if is_root else self.cat_dir[id(cat)], "catalog.json")

    def get_collection_href(self, col, parent_dir, is_root):
        branch = os.path.relpath(parent_dir, self.stac_dir)
        return os.path.join(self.coll_dir[(branch, col.id)], "collection.json")

    def get_item_href(self, item, parent_dir):
        return os.path.join(parent_dir, item.id, f"{item.id}.json")


def write_views(drafts, paths, stac_dir, vocab):
    """by-experiment/<experiment>/catalog.json: item links only; the Items stay where they are."""
    root_path = os.path.join(stac_dir, "catalog.json")
    rel = lambda frm, to: os.path.relpath(to, os.path.dirname(frm))
    by_exp = defaultdict(list)
    for d in drafts:
        if d.props.get("km_scale:experiment"):
            by_exp[d.props["km_scale:experiment"]].append(paths[d.id])

    def catalog(path, cid, title, desc, children=(), items=()):
        links = [{"rel": "root", "href": rel(path, root_path), "type": "application/json"},
                 {"rel": "parent", "href": rel(path, os.path.join(os.path.dirname(os.path.dirname(path)),
                                                                   "catalog.json")), "type": "application/json"}]
        links += [{"rel": "child", "href": rel(path, c), "type": "application/json"} for c in children]
        links += [{"rel": "item", "href": rel(path, i), "type": "application/geo+json"} for i in items]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"type": "Catalog", "stac_version": STAC_VERSION, "id": cid, "title": title,
                       "description": desc, "links": links}, f, indent=1)

    children = []
    for exp, ipaths in sorted(by_exp.items()):
        p = os.path.join(stac_dir, "by-experiment", exp, "catalog.json")
        catalog(p, f"by-experiment-{exp}", exp, vocab["experiment"][exp], items=sorted(ipaths))
        children.append(p)
    p = os.path.join(stac_dir, "by-experiment", "catalog.json")
    catalog(p, "by-experiment", "by experiment", "Generated views: links to Items, grouped by experiment.", children)
    with open(root_path) as f:
        root = json.load(f)
    root["links"].append({"rel": "child", "href": "./by-experiment/catalog.json", "type": "application/json",
                          "title": "by experiment"})
    with open(root_path, "w") as f:
        json.dump(root, f, indent=2)
