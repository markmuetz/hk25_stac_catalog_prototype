"""The source: the HK25 Intake catalogue, walked as catalogue -> dataset -> entry (one dataset at one site).

Everything HK25-specific lives here: the per-site YAML layout, Jinja ``urlpath`` templates, and the guesses needed
because HK25 has no product type, model or experiment fields. A store-driven HK27 source would replace this module.
"""

import itertools
from functools import cached_property

import jinja2
import yaml

from .model import ItemDraft
from .util import PLACEHOLDER_DATETIME, bbox_geometry, bounds_to_bbox, iso, map_license, to_href

# --- classification of HK25 ids (the HK25 catalogue has no product type or model field) -----------------------------
MODEL_PREFIXES = [  # (prefix, Collection id, title)
    ("um_", "UM", "Met Office Unified Model"),
    ("icon_", "ICON", "ICON"),
    ("ifs_", "IFS", "ECMWF IFS"),
    ("nicam_", "NICAM", "NICAM"),
    ("scream", "SCREAM", "E3SM SCREAM"),
    ("mpas_", "MPAS", "MPAS"),
    ("wrf_", "WRF", "WRF"),
    ("arp-gem", "ARP-GEM", "ARP-GEM"),
    ("casesm2", "CAS-ESM2", "CAS-ESM2"),
    ("ew_", "EarthWorks", "EarthWorks"),
]
OBSERVATIONS = {"CERES_EBAF": "CERES-EBAF", "IR_IMERG": "IMERG"}
REANALYSES = {"ERA5": "ERA5", "JRA3Q": "JRA3Q", "MERRA2": "MERRA2"}
DERIVED = {"tracking": ("mcs", "PyFLEXTRKR"), "tracking-d3hp003": ("mcs", "PyFLEXTRKR")}
REGIONAL_HINTS = ("Africa", "CTC", "SAmer", "SEA", "conus", "samerica")
GLOBAL_REGIONS = ("global", "glm", "none")  # HK25 `region` values meaning global ("glm": the UM's global model)


def classify(dsid):
    """Return (branch, collection_id, collection_title, product_type, extra properties)."""
    if dsid in OBSERVATIONS:
        return "observations", OBSERVATIONS[dsid], OBSERVATIONS[dsid], "observation", {}
    if dsid in REANALYSES:
        return "reanalyses", REANALYSES[dsid], REANALYSES[dsid], "reanalysis", {}
    if dsid in DERIVED:
        feature, tracker = DERIVED[dsid]
        return f"derived/{feature.upper()}-tracks", tracker, tracker, "derived", {"km_scale:feature": feature}
    for prefix, coll, title in MODEL_PREFIXES:
        if dsid.startswith(prefix):
            return "simulations", coll, title, "simulation", {}
    raise ValueError(f"unclassified id {dsid}")


def infer_experiment(dsid, meta):
    s = dsid.lower()
    if "p4k" in s:
        return "dyamond3-p4k"
    for e in ("dyamond1", "dyamond2", "dyamond3"):
        if e in s:
            return e
    start, end = str(meta.get("time_start", ""))[:10], str(meta.get("time_end", ""))[:10]
    if start and end and start <= "2020-01-20" and end >= "2021-02-28":  # covers the DYAMOND3 period
        return "dyamond3"
    return "other"


def infer_domain(dsid, meta):
    if str(meta.get("region", "global")).lower() not in GLOBAL_REGIONS or any(h in dsid for h in REGIONAL_HINTS):
        return "regional"
    return "global"


def media_type(url, driver):
    """(STAC media type, our format name) for an HK25 URL."""
    if url.startswith("reference::"):
        return "application/vnd.apache.parquet", "kerchunk"
    if driver == "netcdf" or url.endswith(".nc") or "*" in url and not url.rstrip("/").endswith(".zarr"):
        return "application/x-netcdf", "netcdf"
    return "application/vnd.zarr; version=2", "zarr"


def asset_keys(params, urls):
    """Asset key per URL: '<other params>.z<zoom>'; a second URL that is a static store gets 'static.z<zoom>'."""
    zoom = params.get("zoom")
    rest = [str(params[k]) for k in params if k != "zoom"]
    base = "_".join(rest) if rest else "data"
    z = f".z{zoom}" if zoom is not None else ""
    keys = []
    for i, u in enumerate(urls):
        if i == 0:
            keys.append(base + z)
        elif "static" in u:
            keys.append("static" + z)
        else:
            keys.append(f"{base}_part{i + 1}{z}")
    return keys


def apply_override(href, site, sites):
    """The href a site reads, after its endpoint overrides (from the site table)."""
    for a, b in (sites.get(site) or {}).get("endpoint_overrides", {}).items():
        if href.startswith(a):
            return b + href[len(a):]
    return href


class Hk25Entry:
    """One dataset as one site's ``main.yaml`` describes it."""

    def __init__(self, dsid, site, raw):
        self.id, self.site, self.raw = dsid, site, raw

    @property
    def driver(self):
        return self.raw.get("driver")

    @property
    def consolidated(self):
        return self.raw["args"].get("consolidated")

    @property
    def metadata(self):
        return self.raw.get("metadata") or {}

    def combinations(self):
        """Yield (params, [urls]) for every combination of allowed parameter values, as Intake would render them."""
        ps = self.raw.get("parameters") or {}
        names = list(ps)
        choices = [ps[p].get("allowed", [ps[p].get("default")]) for p in names]
        u = self.raw["args"]["urlpath"]
        us = u if isinstance(u, list) else [u]
        for combo in itertools.product(*choices):
            ctx = dict(zip(names, combo))
            yield ctx, [jinja2.Template(x).render(**ctx).strip() for x in us]

    @cached_property
    def urls_by_key(self):
        """{asset key: (url, params)} for this site."""
        d = {}
        for params, urls in self.combinations():
            for k, u in zip(asset_keys(params, urls), urls):
                d[k] = (u, params)
        return d


class Hk25Dataset:
    """One dataset id across every site that lists it."""

    def __init__(self, dsid, entries):
        self.id = dsid
        self.entries = entries  # site -> Hk25Entry

    @property
    def sites(self):
        return sorted(self.entries)

    @property
    def meta(self):
        """The fullest metadata block among the sites (HK25 keeps it in one copy, '# metadata in UK' in the others)."""
        return max((e.metadata for e in self.entries.values()), key=len)

    @property
    def default_site(self):
        return "online" if "online" in self.entries else self.sites[0]

    def _assets(self, sites_table, problems):
        first = next(iter(self.entries.values()))
        default = self.entries[self.default_site]
        assets = {}
        for key, (url, params) in default.urls_by_key.items():
            mt, fmt = media_type(url, first.driver)
            a = {"href": to_href(url), "type": mt, "roles": ["data"], "title": key}
            if fmt == "zarr" and first.consolidated is not None:
                a["zarr:consolidated"] = bool(first.consolidated)
            if fmt != "zarr":
                a["km_scale:format"] = fmt
            if "zoom" in params:
                a["km_scale:zoom"] = int(params["zoom"])
            alt = {}
            for site, e in self.entries.items():
                if site == self.default_site or key not in e.urls_by_key:
                    continue
                site_url = e.urls_by_key[key][0]
                if self.default_site == "online" and apply_override(url, site, sites_table) == site_url:
                    continue  # same objects through the site's own endpoint: covered by the site table
                alt[site] = {"href": to_href(site_url)}
            if alt:
                a["alternate"] = alt
            assets[key] = a
        for site, e in self.entries.items():  # keys present at a site but not at the default location
            for key in e.urls_by_key.keys() - assets.keys():
                problems.add(self.id, f"asset {key} only at {site}, not at {self.default_site}")
        return assets

    def draft(self, sites_table, vocab, problems):
        """The ItemDraft for this dataset, from the Intake metadata alone (stage 1)."""
        meta = self.meta
        branch, coll, coll_title, ptype, extra = classify(self.id)
        assets = self._assets(sites_table, problems)
        props = {
            "title": meta.get("title") or self.id,
            "description": (meta.get("summary") or "").strip() or None,
            "datetime": None,
            "start_datetime": iso(meta["time_start"]) if meta.get("time_start") else None,
            "end_datetime": iso(meta["time_end"]) if meta.get("time_end") else None,
            "license": map_license(meta.get("license")),
            "providers": [{"name": meta["institution"], "roles": ["producer"]}] if meta.get("institution") else None,
            "km_scale:product_type": ptype,
            "km_scale:experiment": infer_experiment(self.id, meta) if ptype == "simulation" else None,
            "km_scale:experiment_inferred": True if ptype == "simulation" else None,  # HK25 has no such field
            "km_scale:domain": infer_domain(self.id, meta),
            "km_scale:source_id": meta.get("source_id"),
            "km_scale:resolution": meta.get("resolution"),
            "km_scale:sites": self.sites,
            "km_scale:creators": meta.get("creator_name"),
            "km_scale:references": meta.get("references") or meta.get("citation"),
            "km_scale:license_text": meta.get("license") if map_license(meta.get("license")) == "other" else None,
            **extra,
        }
        if "online" not in self.entries:
            props["km_scale:site_only"] = self.sites
        if not props["start_datetime"] or not props["end_datetime"]:
            props["datetime"] = PLACEHOLDER_DATETIME  # replaced from the stores later if it can be
            props["km_scale:time_unknown"] = True
            props.pop("start_datetime"), props.pop("end_datetime")
            problems.add(self.id, "no time_start/time_end in metadata; placeholder datetime")
        if not props["license"]:
            props["license"] = "other"
            problems.add(self.id, "no licence in metadata")
        props = {k: v for k, v in props.items() if v is not None}
        draft = ItemDraft(self.id, branch, coll, coll_title, props, assets, meta)
        lon = [meta.get("geospatial_lon_min"), meta.get("geospatial_lon_max")]
        lat = [meta.get("geospatial_lat_min"), meta.get("geospatial_lat_max")]
        if props["km_scale:domain"] == "regional" and None not in lon + lat:
            draft.bbox = bounds_to_bbox({"lower_left_lat": lat[0], "upper_right_lat": lat[1],
                                         "lower_left_lon": lon[0], "upper_right_lon": lon[1]})
            draft.geometry = bbox_geometry(draft.bbox)
        for fld in ("product_type", "experiment", "domain", "feature"):  # controlled vocabulary check
            v = props.get(f"km_scale:{fld}")
            if v is not None and v not in vocab[fld]:
                problems.add(self.id, f"km_scale:{fld}={v!r} not in vocab")
        return draft


class Hk25Catalog:
    """The HK25 Intake catalogue: one ``<site>/main.yaml`` per site."""

    def __init__(self, root):
        self.root = root

    @cached_property
    def entries(self):
        """{dataset id: {site: Hk25Entry}}."""
        entries = {}
        for f in sorted(self.root.glob("*/main.yaml")):
            site = f.parent.name
            for dsid, raw in (yaml.safe_load(f.read_text()).get("sources") or {}).items():
                entries.setdefault(dsid, {})[site] = Hk25Entry(dsid, site, raw)
        return entries

    def datasets(self):
        return [Hk25Dataset(dsid, sites) for dsid, sites in sorted(self.entries.items())]
