"""The build: collect drafts from the source, probe the stores, write the catalogue and the site."""

import concurrent.futures as cf
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from . import rules
from .hk25 import Hk25Catalog
from .model import Problems
from .site import write_site
from .stac_out import write_stac
from .stores import datacube, store_for

HERE = Path(__file__).resolve().parent.parent


def load_config():
    sites = yaml.safe_load((HERE / "config/sites.yaml").read_text())
    vocab = yaml.safe_load((HERE / "config/vocab.yaml").read_text())
    return sites, vocab


def collect(hk25_root, sites, vocab, problems):
    """Stage 1: one ItemDraft per HK25 dataset, from the Intake metadata alone.

    Datasets whose stores are given by a glob (several stores under one pattern) are left out: a glob isn't one
    resource, so no STAC tool can open it. In HK27 each should be one store (or a virtual store over the pieces).
    """
    drafts = []
    for ds in Hk25Catalog(hk25_root).datasets():
        d = ds.draft(sites, vocab, problems)
        globs = [a["href"] for a in d.assets.values() if "*" in a["href"]]
        if globs:
            problems.add(d.id, f"excluded: {len(globs)} of {len(d.assets)} assets have a glob href (e.g. {globs[0]})")
            continue
        for key, a in d.assets.items():  # a glob copy at another site: leave that copy out
            for site in [s for s, alt in a.get("alternate", {}).items() if "*" in alt["href"]]:
                problems.add(d.id, f"{key}: copy at {site} left out (glob href {a['alternate'].pop(site)['href']})")
            if a.get("alternate") == {}:
                del a["alternate"]
        seen = {}
        for key, a in d.assets.items():  # e.g. a URL template that ignores one of its parameters
            if a["href"] in seen:
                problems.add(d.id, f"{key} has the same href as {seen[a['href']]} ({a['href']})")
            seen.setdefault(a["href"], key)
        drafts.append(d)
    return drafts


def probe(drafts, problems):
    """Stage 2: read every online store's metadata, apply the reading rules, check against the data.

    Returns the attribute usage counts: {rule field: {key used: number of datasets}}.
    """
    by_id = {d.id: d for d in drafts}
    stores = {(d.id, key): s for d in drafts for key, a in d.assets.items() if (s := store_for(a)) is not None}
    print(f"probing {len(stores)} online Zarr assets ...", file=sys.stderr)
    with cf.ThreadPoolExecutor(48) as ex:
        metas = dict(zip(stores, ex.map(lambda s: s.read_metadata(), stores.values())))

    # coordinate values: one store per (dataset, frequency), the coarsest zoom
    groups = defaultdict(list)
    for (dsid, key), m in metas.items():
        if m is not None:
            groups[(dsid, key.split(".")[0])].append((by_id[dsid].assets[key].get("km_scale:zoom", 0), key))
    first = {g: min(lst)[1] for g, lst in groups.items()}
    print(f"reading coordinates from {len(first)} stores ...", file=sys.stderr)
    with cf.ThreadPoolExecutor(16) as ex:
        coords = dict(zip(first, ex.map(lambda g: stores[(g[0], first[g])].read_coords(metas[(g[0], first[g])].dims),
                                        first)))

    for (dsid, key), m in metas.items():
        a = by_id[dsid].assets[key]
        if m is None:
            a["km_scale:reachable"] = False
            problems.add(dsid, f"{key} not reachable at {a['href']}")
            continue
        a["zarr:zarr_format"] = m.zarr_format
        if m.zarr_format == 3:
            a["type"] = "application/vnd.zarr; version=3"
        freq = key.split(".")[0].split("_")[0]
        a["cube:dimensions"], a["cube:variables"] = datacube(m, a.get("km_scale:zoom"), freq, by_id[dsid].meta,
                                                             coords.get((dsid, key.split(".")[0])))
        rules.apply_asset_rules(dsid, key, a, m, problems)

    # each dataset's store attributes, merged over its stores, coarsest zoom first
    attrs = defaultdict(dict)
    for (dsid, key), m in sorted(metas.items(), key=lambda kv: by_id[kv[0][0]].assets[kv[0][1]].get("km_scale:zoom", 0)):
        if m is not None:
            for k, v in m.attrs.items():
                attrs[dsid].setdefault(k, v)
    usage = defaultdict(Counter)
    for d in drafts:
        for fld, k in rules.apply_dataset_rules(d, attrs.get(d.id, {}), problems).items():
            usage[fld][k] += 1
        rules.apply_checks(d, problems)
    return {f: dict(c) for f, c in usage.items()}


def write(drafts, out, sites, vocab, problems, usage):
    """Stage 3: the STAC tree, then the site files."""
    if out.exists():
        shutil.rmtree(out)
    item_paths = write_stac(drafts, str((out / "stac").resolve()), vocab)
    return write_site(drafts, item_paths, out.resolve(), sites, problems, usage)


def build(hk25_root, out, probe_stores=True):
    sites, vocab = load_config()
    problems = Problems()
    drafts = collect(hk25_root, sites, vocab, problems)
    usage = probe(drafts, problems) if probe_stores else {}
    index = write(drafts, out, sites, vocab, problems, usage)
    n_assets = sum(len(d.assets) for d in drafts)
    n_cube = sum("cube:variables" in a for d in drafts for a in d.assets.values())
    n_coll = len({(d.branch, d.coll) for d in drafts})
    print(f"{len(drafts)} Items in {n_coll} Collections, {n_assets} assets ({n_cube} with datacube), "
          f"{len(problems)} problems (see problems.txt)", file=sys.stderr)
    print(Counter(e["experiment"] for e in index), file=sys.stderr)
