"""Minimal km_scale helper (prototype). Functions are named by what they return, not by storage format.

    import km_scale
    km_scale.get_url("um_glm_n2560_RAL3p3_tuned_hk26", freq="PT1H", zoom=0)       # -> (href, storage_options)
    ds = km_scale.open_dataset("um_glm_n2560_RAL3p3_tuned_hk26", freq="PT1H", zoom=0)   # -> xarray.Dataset
    dt = km_scale.open_datatree("um_glm_n2560_RAL3p3_tuned_hk26", freq="PT1H")    # -> xarray.DataTree, one node per zoom
    df = km_scale.open_table("<tracks id>", asset="tracks")                        # -> pandas.DataFrame
    km_scale.where("um_glm_n2560_RAL3p3_tuned_hk26", freq="PT1H", zoom=8)         # which copy each site would use

Every function takes the same two locality arguments (keewis, catalog#3):
- location=  where *you* are. Default: KM_SCALE_USER_LOCATION, set on each node's JupyterHub, else "online".
- source=    force a particular copy ("online" or a site name), overriding the automatic choice.

Where the data comes from is always visible (Gettelman, catalog#3):
- the returned object carries attrs["km_scale_source"] (the href) and attrs["km_scale_copy"] (which copy);
- where() shows the choice for every site without opening anything;
- a warning is raised when you are at a site but the data comes from a copy elsewhere (the slow case).

The catalogue root comes from KM_SCALE_CATALOG (a build directory or URL), defaulting to this file's directory.
"""

import functools
import json
import logging
import os
import urllib.request
import warnings
from pathlib import Path

log = logging.getLogger("km_scale")
CATALOG = os.environ.get("KM_SCALE_CATALOG", str(Path(__file__).parent))
ONLINE = "online"


class RemoteCopyWarning(UserWarning):
    """Data is being read from a copy away from the user's site."""


def _load(rel):
    if CATALOG.startswith(("http://", "https://")):
        with urllib.request.urlopen(f"{CATALOG.rstrip('/')}/{rel}") as r:
            return json.load(r)
    return json.loads((Path(CATALOG) / rel).read_text())


@functools.cache
def _index():
    return {e["id"]: e for e in _load("index.json")}


@functools.cache
def _sites():
    return _load("sites.json")


@functools.cache
def item(dsid):
    try:
        return _load(_index()[dsid]["item"])
    except KeyError:
        raise KeyError(f"unknown dataset {dsid!r}") from None


def _asset(dsid, freq, zoom=None, asset=None):
    it = item(dsid)
    key = asset or (f"{freq}.z{zoom}" if zoom is not None else freq)
    if key not in it["assets"]:
        raise KeyError(f"{dsid}: no asset {key!r}; available: {', '.join(sorted(it['assets']))}")
    return it, key, it["assets"][key]


def _user_location(location):
    return location or os.environ.get("KM_SCALE_USER_LOCATION", ONLINE)


def _choose(dsid, freq=None, zoom=None, asset=None, location=None, source=None):
    """Return (href, storage_options, copy) where copy names the copy used ('online' or a site)."""
    location = _user_location(location)
    it, key, a = _asset(dsid, freq, zoom, asset)
    alternates = a.get("alternate", {})
    site_only = it["properties"].get("km_scale:site_only")
    default_copy = site_only[0] if site_only else ONLINE

    if source:  # explicit choice of copy
        if source in alternates:
            copy, chosen = source, alternates[source]
        elif source == default_copy:
            copy, chosen = default_copy, a
        else:
            raise LookupError(f"{dsid} [{key}]: no copy at {source!r}; copies: "
                              f"{', '.join([default_copy, *alternates])}")
    elif location in alternates:
        copy, chosen = location, alternates[location]
    elif site_only and location not in site_only:
        raise LookupError(f"{dsid} is only available at {', '.join(site_only)} (you are at {location!r})")
    else:
        copy, chosen = default_copy, a

    href = chosen["href"]
    if copy == ONLINE:  # the user's site may reach the online copy by its own route (site table)
        for prefix, repl in (_sites().get(location) or {}).get("endpoint_overrides", {}).items():
            if href.startswith(prefix):
                href, copy = repl + href[len(prefix):], f"{ONLINE} via {location} endpoint"
    return href, chosen.get("km_scale:storage_options", {}), copy


def _announce(dsid, href, copy, location, obj=None):
    location = _user_location(location)
    if location != ONLINE and not copy.startswith((location, f"{ONLINE} via {location}")):
        warnings.warn(f"{dsid}: you are at {location!r} but reading the {copy!r} copy ({href}); this may be slow",
                      RemoteCopyWarning, stacklevel=3)
    log.info("%s: reading %s copy at %s", dsid, copy, href)
    if obj is not None:
        obj.attrs["km_scale_source"] = href
        obj.attrs["km_scale_copy"] = copy
    return obj


def get_url(dsid, freq="PT1H", zoom=8, *, asset=None, location=None, source=None):
    """Return (href, storage_options) for the copy that would be used. Works for any asset type."""
    href, opts, _ = _choose(dsid, freq, zoom, asset, location, source)
    return href, opts


def where(dsid, freq="PT1H", zoom=8, *, asset=None):
    """Which copy each site would read, without opening anything: {site: (copy, href)}."""
    out = {}
    for site in _sites():
        try:
            href, _, copy = _choose(dsid, freq, zoom, asset, location=site)
            out[site] = (copy, href)
        except LookupError as e:
            out[site] = ("unavailable", str(e))
    return out


def open_dataset(dsid, freq="PT1H", zoom=8, *, asset=None, location=None, source=None, **kwargs):
    """Open gridded data as an xarray.Dataset, whatever the storage format (Zarr, NetCDF, kerchunk)."""
    import xarray as xr

    it, key, a = _asset(dsid, freq, zoom, asset)
    fmt = a.get("km_scale:format", "zarr")
    if fmt not in ("zarr", "netcdf", "kerchunk"):
        raise TypeError(f"{dsid} [{key}] is {fmt!r}, not gridded data; use open_table() or get_url()")
    href, opts, copy = _choose(dsid, freq, zoom, asset, location, source)
    if fmt == "netcdf":
        ds = xr.open_mfdataset(href, **kwargs)
    elif fmt == "kerchunk":
        ds = xr.open_dataset(href, engine="kerchunk", **kwargs)
    else:
        ds = xr.open_zarr(href, consolidated=a.get("zarr:consolidated"), storage_options=opts or None,
                          chunks=kwargs.pop("chunks", {}), **kwargs)
    return _announce(dsid, href, copy, location, ds)


def open_datatree(dsid, freq="PT1H", *, zooms=None, location=None, source=None, **kwargs):
    """Open every zoom level as an xarray.DataTree with nodes z0, z1, ... (HK27 stores: one store, zoom groups)."""
    import xarray as xr

    it = item(dsid)
    avail = sorted(a["km_scale:zoom"] for k, a in it["assets"].items()
                   if k.split(".")[0] == freq and "km_scale:zoom" in a)
    if not avail:
        raise KeyError(f"{dsid}: no zoom levels for {freq!r}")
    nodes = {f"z{z}": open_dataset(dsid, freq, z, location=location, source=source, **kwargs)
             for z in (zooms or avail)}
    dt = xr.DataTree.from_dict(nodes)
    dt.attrs["km_scale_source"] = {k: v.attrs["km_scale_source"] for k, v in nodes.items()}
    return dt


def open_table(dsid, asset, *, location=None, source=None, **kwargs):
    """Open tabular data (e.g. feature tracks) as a pandas.DataFrame."""
    import pandas as pd

    it, key, a = _asset(dsid, None, None, asset)
    href, opts, copy = _choose(dsid, asset=asset, location=location, source=source)
    t = a.get("type", "")
    if "parquet" in t:
        df = pd.read_parquet(href, storage_options=opts or None, **kwargs)
    elif "csv" in t:
        df = pd.read_csv(href, storage_options=opts or None, **kwargs)
    else:
        raise TypeError(f"{dsid} [{key}] has type {t!r}, not a table; use open_dataset() or get_url()")
    return _announce(dsid, href, copy, location, df)


def search(text="", **facets):
    """Filter the flat index, e.g. search(experiment="dyamond3-p4k", variables="rlut")."""
    out = []
    for e in _index().values():
        if text and text.lower() not in json.dumps(e).lower():
            continue
        ok = True
        for k, v in facets.items():
            val = e.get(k)
            ok &= (v in val) if isinstance(val, list) else (val == v)
        if ok:
            out.append(e["id"])
    return out
