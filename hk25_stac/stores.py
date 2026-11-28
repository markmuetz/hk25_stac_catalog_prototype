"""The data stores: reading their metadata, and turning it into datacube fields.

Metadata is read from the consolidated metadata documents directly (``.zmetadata`` for Zarr v2, ``zarr.json`` for v3):
one small HTTP GET per store, so ~930 stores take seconds. Coordinate values (first and last time, levels) need
decoding, so those come from xarray, opened once per frequency.

New kinds of store (kerchunk references, Parquet tables) would be further ``Store`` subclasses returned by
``store_for``; for now only online Zarr stores are read.
"""

import math
import re
from dataclasses import dataclass, field

from .util import HEALPIX_DGGRS_URI, fetch_json, iso

VERTICAL_NAMES = {"pressure", "plev", "level", "lev", "height", "depth", "pressure_level", "isobaricinhpa"}
DTYPES = {"<f4": "float32", "<f8": "float64", "<i4": "int32", "<i8": "int64", "|i1": "int8", "<i2": "int16",
          "|u1": "uint8", "<u2": "uint16", "|b1": "bool", "<M8[ns]": "datetime64[ns]"}


@dataclass(frozen=True)
class ArrayInfo:
    attrs: dict
    shape: list
    dtype: object  # str (v2 dtype or v3 data_type), or a dict for structured v3 types
    dims: list


@dataclass
class StoreMetadata:
    zarr_format: int
    arrays: dict                       # top-level array name -> ArrayInfo
    attrs: dict                        # the store's own (group) attributes
    codecs: set = field(default_factory=set)  # codec / compressor ids used by any array

    @property
    def dims(self):
        return {d for a in self.arrays.values() for d in a.dims}

    def dim_sizes(self):
        sizes = {}
        for a in self.arrays.values():
            for d, n in zip(a.dims, a.shape):
                sizes[d] = n
        return sizes

    def grid_mapping(self, name):
        """Attributes of the first array whose grid_mapping_name is `name`, or None."""
        return next((a.attrs for a in self.arrays.values() if a.attrs.get("grid_mapping_name") == name), None)

    # Attribute names on the grid mapping, as data-forge's validator (scripts/validate_healpix_zarr.py) accepts them
    NSIDE_ATTRS = ("healpix_nside",)
    LEVEL_ATTRS = ("refinement_level", "healpix_level", "zoom")
    ORDER_ATTRS = ("healpix_order", "indexing_scheme")
    ELLIPSOID_ATTR_SETS = (("semi_major_axis", "inverse_flattening"), ("semi_major_axis", "semi_minor_axis"),
                           ("reference_ellipsoid_name",))

    def healpix(self):
        """(refinement_level, indexing_scheme) from a HEALPix grid mapping, normalised, or None.

        The level is read from any of data-forge's level names, or from the nside. The scheme comes out as the
        catalogue's own vocabulary, ``nested`` or ``ring`` (as in xdggs); data-forge requires the store to say ``nest``.
        """
        gm = self.grid_mapping("healpix")
        if gm is None:
            return None
        level = next((gm[k] for k in self.LEVEL_ATTRS if gm.get(k) is not None), None)
        nside = next((gm[k] for k in self.NSIDE_ATTRS if gm.get(k) is not None), None)
        if level is None and nside is not None:
            level = int(round(math.log2(int(nside))))
        scheme = next((gm[k] for k in self.ORDER_ATTRS if gm.get(k) is not None), None)
        scheme = {"nest": "nested", "nested": "nested", "ring": "ring"}.get(str(scheme).lower(), scheme)
        return (int(level) if level is not None else None), scheme

    def ellipsoid(self):
        """The reference ellipsoid from a HEALPix grid mapping: the first of data-forge's attribute sets present,
        as a dict, or None if none is (the grid then looks spherical)."""
        gm = self.grid_mapping("healpix")
        if gm is None:
            return None
        for keys in self.ELLIPSOID_ATTR_SETS:
            if all(gm.get(k) is not None for k in keys):
                return {k: gm[k] for k in keys}
        return None


class Store:
    """A data store an asset points to."""

    def __init__(self, href):
        self.href = href.rstrip("/")

    def read_metadata(self):
        """StoreMetadata, or None if the store can't be reached."""
        raise NotImplementedError

    def read_coords(self, dims):
        """{dim: values} for small coordinates; first and last value for time."""
        return {}


class ZarrStore(Store):
    """A Zarr store over HTTP(S), v2 or v3, with consolidated metadata."""

    def read_metadata(self):
        zm = fetch_json(self.href + "/.zmetadata")
        if zm is not None:
            return self._from_v2(zm.get("metadata", {}))
        zj = fetch_json(self.href + "/zarr.json")
        if zj is not None:
            return self._from_v3(zj)
        return None

    @staticmethod
    def _from_v2(meta):
        arrays, codecs = {}, set()
        for key, v in meta.items():
            if not key.endswith("/.zarray"):
                continue
            name = key[: -len("/.zarray")]
            codecs |= {c["id"] for c in [v.get("compressor"), *(v.get("filters") or [])]
                       if isinstance(c, dict) and "id" in c}
            if "/" in name:
                continue
            attrs = meta.get(f"{name}/.zattrs", {})
            arrays[name] = ArrayInfo(attrs, v.get("shape", []), v.get("dtype"), attrs.get("_ARRAY_DIMENSIONS", []))
        return StoreMetadata(2, arrays, meta.get(".zattrs", {}), codecs)

    @staticmethod
    def _from_v3(zj):
        nodes = (zj.get("consolidated_metadata") or {}).get("metadata", {})
        arrays = {name: ArrayInfo(v.get("attributes", {}), v.get("shape", []), v.get("data_type"),
                                  v.get("dimension_names") or [])
                  for name, v in nodes.items() if v.get("node_type") == "array" and "/" not in name}
        codecs = {c.get("name") for v in nodes.values() for c in v.get("codecs") or [] if isinstance(c, dict)} - {None}
        return StoreMetadata(3, arrays, zj.get("attributes", {}), codecs)

    def read_coords(self, dims):
        import numpy as np
        import xarray as xr
        try:
            ds = xr.open_zarr(self.href, consolidated=True, decode_times=True, chunks=None)
        except Exception:
            return {}
        out = {}
        for d in dims:
            if d not in ds.coords and d not in ds.variables:
                continue
            c = ds[d]
            if c.ndim != 1:
                continue
            try:
                if np.issubdtype(c.dtype, np.datetime64):
                    v = c.values[[0, -1]] if c.size > 1 else c.values
                    out[d] = [str(np.datetime_as_string(x, unit="s")) + "Z" for x in v]
                elif c.size <= 1000 and np.issubdtype(c.dtype, np.number) and np.isfinite(c.values).all():
                    # non-finite values (e.g. ICON's NaN `crs` coordinate) aren't valid JSON: index range instead
                    # str(): float32 values without noise (0.05, not 0.05000000074505806)
                    out[d] = [float(str(x)) if np.issubdtype(c.dtype, np.floating) else int(x) for x in c.values]
            except Exception:
                pass
        return out


def store_for(asset):
    """The Store an asset points to, if it is one we can read, else None."""
    href = asset["href"]
    if href.startswith("http") and asset.get("km_scale:format") is None and "*" not in href:
        return ZarrStore(href)
    return None


def datacube(meta, zoom, freq, source_meta, coords=None):
    """(cube:dimensions, cube:variables) for one store, from its metadata plus any coordinate values read."""
    coords = coords or {}
    sizes = meta.dim_sizes()
    dims = {}
    for d, n in sizes.items():
        attrs = meta.arrays[d].attrs if d in meta.arrays else {}
        sn = attrs.get("standard_name", "")
        if d == "time" or sn == "time":
            o = {"type": "temporal", "count": n}
            if coords.get(d):
                o["extent"] = [coords[d][0], coords[d][-1]]  # from the data
            elif source_meta.get("time_start") and source_meta.get("time_end"):
                o["extent"] = [iso(source_meta["time_start"]), iso(source_meta["time_end"])]
            if freq and re.fullmatch(r"P(T\d+[HM]|\d+[DM])", str(freq)):
                o["step"] = freq
        elif zoom is not None and n == 12 * 4 ** int(zoom):
            hp = meta.healpix()
            level, scheme = hp if hp else (int(zoom), None)
            src = "from the store's grid mapping" if hp else "assumed: no healpix grid mapping in the store"
            o = {"type": "dggs", "reference_system": HEALPIX_DGGRS_URI, "dggs:refinement_level": level,
                 "extent": [0, n - 1], "count": n,
                 "description": f"HEALPix {scheme or 'nested'}, refinement level {level} ({src})"}
            if scheme:
                o["dggs:indexing_scheme"] = scheme
        elif d.lower() in VERTICAL_NAMES or sn in ("air_pressure", "height", "depth", "model_level_number"):
            o = {"type": "spatial", "axis": "z", "count": n}
        else:
            o = {"type": "other", "count": n}
        if o["type"] in ("spatial", "other"):
            if coords.get(d):
                o["values"] = coords[d]
            else:
                o["extent"] = [0, n - 1]  # index range: no coordinate values in the store
                o["description"] = "index (no coordinate values in store)"
        if attrs.get("units") and o["type"] != "temporal":
            o["unit"] = attrs["units"]
        dims[d] = o
    variables = {}
    for name, a in meta.arrays.items():
        if name in sizes:
            continue
        v = {"dimensions": list(a.dims), "type": "data" if len(a.dims) > 1 or "time" in a.dims else "auxiliary"}
        for src, dst in (("units", "unit"), ("long_name", "description"), ("standard_name", "cf:standard_name")):
            if a.attrs.get(src):
                v[dst] = a.attrs[src]
        if a.attrs.get("cell_methods"):
            v["cf:cell_methods"] = [a.attrs["cell_methods"]]  # array form: the cf v1.0.0 schema rejects a string
        if isinstance(a.dtype, str):
            v["data_type"] = DTYPES.get(a.dtype, a.dtype)
        variables[name] = v
    return dims, variables
