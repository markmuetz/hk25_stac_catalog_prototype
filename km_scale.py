"""Minimal km_scale helper (prototype): one way to open catalogue data.

    import km_scale
    km_scale.resolve("um_glm_n2560_RAL3p3_tuned_hk26", freq="PT1H", zoom=0)      # -> (href, storage_options)
    ds = km_scale.open_asset("um_glm_n2560_RAL3p3_tuned_hk26", freq="PT1H", zoom=0)

The user's site comes from KM_SCALE_USER_LOCATION (default "online"), or location=. The catalogue root comes from
KM_SCALE_CATALOG (a local build directory or a URL), defaulting to this file's directory.
"""

import functools
import json
import logging
import os
import urllib.request
from pathlib import Path

log = logging.getLogger("km_scale")
CATALOG = os.environ.get("KM_SCALE_CATALOG", str(Path(__file__).parent))


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


def _asset_key(it, freq, zoom):
    key = f"{freq}.z{zoom}" if zoom is not None else freq
    if key not in it["assets"]:
        have = sorted(it["assets"])
        raise KeyError(f"{it['id']}: no asset {key!r}; available: {', '.join(have)}")
    return key


def resolve(dsid, freq="PT1H", zoom=8, location=None):
    """Return (href, storage_options) for the best copy at the user's site. Two key lookups on the cached Item."""
    location = location or os.environ.get("KM_SCALE_USER_LOCATION", "online")
    it = item(dsid)
    asset = it["assets"][_asset_key(it, freq, zoom)]
    site_only = it["properties"].get("km_scale:site_only")
    alt = asset.get("alternate", {}).get(location)
    if alt:
        return alt["href"], alt.get("km_scale:storage_options", {})
    if site_only and location not in site_only:
        raise LookupError(f"{dsid} is only available at {', '.join(site_only)} (you are at {location!r})")
    href = asset["href"]
    for a, b in (_sites().get(location) or {}).get("endpoint_overrides", {}).items():
        if href.startswith(a):
            href = b + href[len(a):]
    return href, asset.get("km_scale:storage_options", {})


def open_asset(dsid, freq="PT1H", zoom=8, location=None, **kwargs):
    """Open one asset with xarray. Records the chosen copy in ds.attrs['km_scale_source']."""
    import xarray as xr

    href, opts = resolve(dsid, freq, zoom, location)
    it = item(dsid)
    asset = it["assets"][_asset_key(it, freq, zoom)]
    log.info("%s: using %s", dsid, href)
    if asset.get("km_scale:format") == "netcdf":
        ds = xr.open_mfdataset(href, **kwargs)
    elif asset.get("km_scale:format") == "kerchunk":
        ds = xr.open_dataset(href, engine="kerchunk", **kwargs)
    else:
        ds = xr.open_zarr(href, consolidated=asset.get("zarr:consolidated"), storage_options=opts or None,
                          chunks=kwargs.pop("chunks", {}), **kwargs)
    ds.attrs["km_scale_source"] = href
    return ds


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
