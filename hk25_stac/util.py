"""Small shared helpers and constants: no state, no I/O except ``fetch_json``."""

import ast
import json
import re
import urllib.error
import urllib.request

STAC_VERSION = "1.1.0"
EXT = {
    "datacube": "https://stac-extensions.github.io/datacube/v2.3.0/schema.json",
    "cf": "https://stac-extensions.github.io/cf/v1.0.0/schema.json",
    "alternate": "https://stac-extensions.github.io/alternate-assets/v1.2.0/schema.json",
    "zarr": "https://stac-extensions.github.io/zarr/v1.1.0/schema.json",
    "processing": "https://stac-extensions.github.io/processing/v1.3.0/schema.json",
    "scientific": "https://stac-extensions.github.io/scientific/v1.0.0/schema.json",
    "dggs": "https://stac-extensions.github.io/dggs/v0.1.0/schema.json",  # proposal; schema not yet published
    "projection": "https://stac-extensions.github.io/projection/v2.0.0/schema.json",
    "version": "https://stac-extensions.github.io/version/v1.2.0/schema.json",
}
# Which extension a field belongs to, by prefix (or the field name itself, for the version extension)
EXT_PREFIX = {"cube": "datacube", "cf": "cf", "alternate": "alternate", "zarr": "zarr", "processing": "processing",
              "sci": "scientific", "dggs": "dggs", "proj": "projection"}
VERSION_FIELDS = {"version", "deprecated", "experimental"}
HEALPIX_DGGRS = "HEALPix"  # the name in the DGGS extension's table (registered by OGC)
HEALPIX_DGGRS_URI = "https://www.opengis.net/def/dggrs/OGC/1.0/HEALPix"
GLOBAL_BBOX = [-180.0, -90.0, 180.0, 90.0]
GLOBAL_GEOM = {"type": "Polygon", "coordinates": [[[-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]]]}
PLACEHOLDER_DATETIME = "2020-01-20T00:00:00Z"  # STAC needs a time; used only when no range is known

SPDX = {
    "cc-by-4.0": "CC-BY-4.0", "cc by 4.0": "CC-BY-4.0", "cc-by 4.0": "CC-BY-4.0", "cc-by-sa-4.0": "CC-BY-SA-4.0",
    "cc0": "CC0-1.0", "cc-by-nc-4.0": "CC-BY-NC-4.0",
}


DOI = re.compile(r"(?:doi:\s*|https?://(?:dx\.)?doi\.org/)(10\.\d{4,9}/[^\s,;]+)", re.I)
URL = re.compile(r"^https?://\S+$")


def bare_doi(text):
    """A DOI with any doi: or https://doi.org/ prefix removed."""
    return re.sub(r"^(doi:\s*|https?://(dx\.)?doi\.org/)", "", str(text).strip(), flags=re.I).rstrip(".")


def references(text):
    """Free-text references -> (sci:publications, links), for the scientific extension.

    A list of URLs (comma or space separated) becomes one publication per DOI, plus an ``about`` link per other URL
    (model web pages). Anything else is one citation, with its DOI if it contains exactly one.
    """
    if not text or not str(text).strip():
        return None, []
    text = str(text).strip()
    tokens = [t.strip() for t in re.split(r"[,\s]+", text) if t.strip()]
    if tokens and all(URL.match(t) or t.lower().startswith("doi:") for t in tokens):
        pubs = [{"doi": bare_doi(t)} for t in tokens if DOI.match(t)]
        links = [{"rel": "about", "href": t, "title": "Model documentation", "type": "text/html"}
                 for t in tokens if not DOI.match(t)]
    else:
        dois = DOI.findall(text)
        pubs = [{"citation": text, **({"doi": dois[0].rstrip(".")} if len(dois) == 1 else {})}]
        links = []
    links += [{"rel": "describedby", "href": f"https://doi.org/{p['doi']}", "title": "Publication",
               "type": "text/html"} for p in pubs if "doi" in p]
    return pubs or None, links


def fetch_json(url, timeout=20):
    """GET a JSON document; None if it can't be fetched or parsed."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "stac-prototype"}),
                                    timeout=timeout) as r:
            return json.load(r)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def iso(t):
    """Normalise a date or datetime string to ISO 8601 with seconds and a Z."""
    t = str(t).strip().replace(" ", "T")
    if len(t) == 10:
        t += "T00:00:00"
    if re.fullmatch(r".*T\d\d:\d\d", t):
        t += ":00"
    return t if t.endswith("Z") else t + "Z"


def truthy(v):
    return v is True or str(v).strip().lower() in ("true", "1", "yes")


def map_license(text):
    """Free-text licence -> SPDX id, 'other' if not recognised, None if empty."""
    if not text:
        return None
    t = str(text).strip().lower()
    for k, v in SPDX.items():
        if t == k or t.startswith(k + " ") or t.startswith(k + ","):
            return v
    return "other"


def bounds_to_bbox(b):
    """{'lower_left_lat', 'lower_left_lon', 'upper_right_lat', 'upper_right_lon'} (any lon convention) -> STAC bbox.

    Longitudes are wrapped to -180..180. A box spanning (nearly) all longitudes becomes -180..180; a box that crosses
    the antimeridian keeps west > east, as STAC allows.
    """
    if isinstance(b, str):
        b = ast.literal_eval(b)
    s, n = float(b["lower_left_lat"]), float(b["upper_right_lat"])
    w, e = float(b["lower_left_lon"]), float(b["upper_right_lon"])
    span = (e - w) % 360
    if e - w >= 359 or span >= 359 or (span == 0 and e != w):
        return [-180.0, round(s, 4), 180.0, round(n, 4)]  # full longitude band (e.g. a tropical channel)
    wrap = lambda x: round(((x + 180) % 360) - 180, 4)
    return [wrap(w), round(s, 4), wrap(e), round(n, 4)]


def bbox_geometry(bb):
    """GeoJSON for a bbox: a Polygon, or a MultiPolygon split at the antimeridian."""
    w, s, e, n = bb
    box = lambda a, b: [[[a, s], [b, s], [b, n], [a, n], [a, s]]]
    if w <= e:
        return {"type": "Polygon", "coordinates": box(w, e)}
    return {"type": "MultiPolygon", "coordinates": [box(w, 180.0), box(-180.0, e)]}


def to_href(path):
    """A STAC href for a store path. A bare absolute path would be read as relative to the catalogue's own URL
    (``/data2/x.zarr`` -> ``https://<site>/data2/x.zarr``), so local paths get the ``file://`` scheme."""
    return "file://" + path if path.startswith("/") else path
