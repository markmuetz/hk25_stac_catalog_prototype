"""Reading rules: how catalogue fields are filled from what the stores say about themselves.

Each rule names a field, its preferred attribute key and the alternates accepted for now, where the value goes, and
notes. The same objects drive the build and generate the key tables in METADATA.md (``metadata_tables``), so the
documentation can't drift from the code.

- ``Rule`` picks a value from a store's attributes (preferred key first, then the alternates; placeholders count as
  missing) and hands it to ``use``. Subclasses differ only in what ``use`` does with it.
- ``KeyRule`` fills a property if the source metadata left it empty: most fields need nothing more.
- ``AssetRule`` reads the store's structure (grid mapping, codecs) rather than its attributes, per asset.
- ``DatasetCheck`` runs after the rules, on what the data itself showed (time coordinates, footprint).

Precedence, everywhere: the source catalogue's metadata wins; store attributes fill what it lacks; values read from the
data (coordinates) fill what both lack.
"""

from datetime import datetime

from .util import (
    GLOBAL_BBOX,
    HEALPIX_DGGRS,
    bare_doi,
    bbox_geometry,
    bounds_to_bbox,
    iso,
    references,
    truthy,
)

PLACEHOLDERS = {"", "UNSET", "unset", "none", "None", "Created by xios", "NICAM data output"}


def present(v):
    return v is not None and str(v).strip() not in PLACEHOLDERS


class DatasetContext:
    """One dataset while the rules run: its draft, its stores' merged attributes, and what the rules did."""

    def __init__(self, draft, attrs, problems):
        self.draft, self.attrs, self.problems = draft, attrs, problems
        self.filled = []  # "property <- key", in the order filled
        self.used = {}    # rule field -> the attribute key the value came from

    @property
    def props(self):
        return self.draft.props

    def fill(self, prop, value, label):
        """Set a property only if the source metadata left it empty. Returns whether it was set."""
        if value and not self.props.get(prop):
            self.props[prop] = value
            self.filled.append(f"{prop} <- {label}")
            return True
        return False

    def report(self, rules):
        """Record which alternate names were used, and what was filled, as problems and on the Item."""
        pref = {r.field: r.preferred for r in rules}
        alt = [f"{fld}: {k} (preferred {pref[fld]})" for fld, k in self.used.items()
               if pref.get(fld) and k != pref[fld]]
        if alt:
            self.problems.add(self.draft.id, f"store uses alternate attribute names: {'; '.join(alt)}")
        if self.filled:
            self.props["km_scale:from_store"] = self.filled
            self.problems.add(self.draft.id, f"filled from store attributes: {', '.join(self.filled)}")


DF_REQUIRED, DF_RECOMMENDED, CATALOGUE = "data-forge: required", "data-forge: recommended", "catalogue only"


class Rule:
    """Read one field from a store's attributes."""

    def __init__(self, field, preferred, alternates=(), target="", notes="", required_by=CATALOGUE):
        self.field, self.preferred, self.alternates = field, preferred, tuple(alternates)
        self.target, self.notes, self.required_by = target, notes, required_by

    def keys(self):
        return tuple(k for k in (self.preferred, *self.alternates) if k)

    def pick(self, attrs):
        """(value, key used), or (None, None) if no key has a real value."""
        for k in self.keys():
            if present(attrs.get(k)):
                return attrs[k], k
        return None, None

    def apply(self, ctx):
        value, key = self.pick(ctx.attrs)
        if key is not None:
            ctx.used[self.field] = key
            self.use(ctx, value, key)

    def use(self, ctx, value, key):
        raise NotImplementedError

    def doc_row(self):
        alts = ", ".join(f"`{a}`" for a in self.alternates) or "none"
        pref = f"`{self.preferred}`" if self.preferred else "none"
        return [self.field, pref, alts, self.required_by, self.target, self.notes]


class KeyRule(Rule):
    """Fill `target` with the value, if the source metadata left it empty."""

    def use(self, ctx, value, key):
        ctx.fill(self.target.strip("`"), value, key)


class TitleRule(KeyRule):
    """Only replace a title that is just the dataset id."""

    def use(self, ctx, value, key):
        if ctx.props.get("title") == ctx.draft.id:
            ctx.props.pop("title")
            ctx.fill("title", value, key)


class ProvidersRule(KeyRule):
    def use(self, ctx, value, key):
        if not ctx.props.get("providers"):
            ctx.props["providers"] = [{"name": value, "roles": ["producer"]}]
            ctx.filled.append(f"providers <- {key}")


class LicenseTextRule(KeyRule):
    """Free-text licence, kept only when the SPDX licence is 'other' and no text is known yet."""

    def use(self, ctx, value, key):
        if ctx.props.get("license") == "other":
            ctx.fill("km_scale:license_text", str(value), key)


class DoiRule(KeyRule):
    """The bare DOI goes to sci:doi (scientific extension), with a cite-as link."""

    def use(self, ctx, value, key):
        doi = bare_doi(value)
        ctx.props["sci:doi"] = doi
        ctx.draft.links.append({"rel": "cite-as", "href": f"https://doi.org/{doi}"})
        ctx.filled.append(f"sci:doi <- {key}")


class ReferencesRule(KeyRule):
    """References -> sci:publications (DOIs and citations) and about links (other URLs), if the source had none."""

    def use(self, ctx, value, key):
        if ctx.props.get("sci:publications"):
            return
        pubs, links = references(value)
        if pubs:
            ctx.props["sci:publications"] = pubs
        ctx.draft.links += links
        ctx.filled.append(f"sci:publications <- {key}")


class DocumentationRule(KeyRule):
    def use(self, ctx, value, key):
        ctx.draft.links.append({"rel": "about", "href": str(value), "title": "Dataset documentation",
                                "type": "text/html"})
        ctx.filled.append(f"about link <- {key}")


class TimeCoverageRule(Rule):
    """Both ACDD time_coverage attributes, used only if the source metadata has no range."""

    START, END = "time_coverage_start", "time_coverage_end"

    def __init__(self, **kw):
        super().__init__("Time range", f"{self.START}, {self.END}", **kw)

    def pick(self, attrs):
        if present(attrs.get(self.START)) and present(attrs.get(self.END)):
            return (attrs[self.START], attrs[self.END]), self.preferred
        return None, None

    def use(self, ctx, value, key):
        if "start_datetime" not in ctx.props:
            ctx.props.update({"datetime": None, "start_datetime": iso(value[0]), "end_datetime": iso(value[1])})
            ctx.props.pop("km_scale:time_unknown", None)
            ctx.filled.append(f"start/end_datetime <- {self.START}/end")

    def doc_row(self):
        return [self.field, f"`{self.START}`, `{self.END}`", "none", self.required_by, self.target, self.notes]


class BoundsRule(Rule):
    """The footprint: ACDD's four geospatial_* attributes, or a lower_left/upper_right dict; plus the regional flag."""

    ACDD = ("geospatial_lat_min", "geospatial_lat_max", "geospatial_lon_min", "geospatial_lon_max")

    def __init__(self, regional, **kw):
        super().__init__("Footprint", "geospatial_lat_min/max, geospatial_lon_min/max", **kw)
        self.regional = regional  # the KeyRule for the regional flag, which this rule consumes

    def pick(self, attrs):
        if all(present(attrs.get(k)) for k in self.ACDD):
            lat0, lat1, lon0, lon1 = (attrs[k] for k in self.ACDD)
            return {"lower_left_lat": lat0, "upper_right_lat": lat1,
                    "lower_left_lon": lon0, "upper_right_lon": lon1}, self.preferred
        for k in self.alternates:
            if present(attrs.get(k)):
                return attrs[k], k
        return None, None

    def apply(self, ctx):
        reg_value, reg_key = self.regional.pick(ctx.attrs)
        if reg_key:
            ctx.used[self.regional.field] = reg_key
        value, key = self.pick(ctx.attrs)
        regional = truthy(reg_value)
        if key is None:
            if regional and ctx.props["km_scale:domain"] != "regional":
                ctx.problems.add(ctx.draft.id, "store says regional but gives no bounds")
            return
        ctx.used[self.field] = key
        try:
            bb = bounds_to_bbox(value)
        except (KeyError, ValueError, SyntaxError) as e:
            ctx.problems.add(ctx.draft.id, f"could not read bounds from {key}: {e}")
            return
        ctx.draft.bbox, ctx.draft.geometry = bb, bbox_geometry(bb)
        ctx.filled.append(f"bbox <- {key}")
        full_lon = bb[0] == -180.0 and bb[2] == 180.0
        if regional and not full_lon and ctx.props["km_scale:domain"] != "regional":
            ctx.props["km_scale:domain"] = "regional"
            ctx.filled.append("km_scale:domain <- regional")

    def doc_row(self):
        return [self.field, "`geospatial_lat_min`, `geospatial_lat_max`, `geospatial_lon_min`, `geospatial_lon_max`",
                ", ".join(f"`{a}`" for a in self.alternates), self.required_by, self.target, self.notes]


# --- asset rules: the store's structure ---------------------------------------------------------------------------
class AssetRule:
    """Read something from one store's structure onto its asset."""

    def __init__(self, field, preferred, alternates=(), target="", notes="", required_by=DF_REQUIRED):
        self.field, self.preferred, self.alternates = field, preferred, tuple(alternates)
        self.target, self.notes, self.required_by = target, notes, required_by

    def apply(self, dsid, key, asset, meta, problems):
        raise NotImplementedError

    def doc_row(self):
        alts = ", ".join(f"`{a}`" for a in self.alternates) or "none"
        return [self.field, f"`{self.preferred}`" if self.preferred else "none", alts, self.required_by, self.target,
                self.notes]


class HealpixGridRule(AssetRule):
    def apply(self, dsid, key, asset, meta, problems):
        hp = meta.healpix()
        if not hp:
            return
        level, scheme = hp
        asset["dggs:dggrs"] = HEALPIX_DGGRS
        if scheme:
            asset["dggs:indexing_scheme"] = scheme
        named = asset.get("dggs:refinement_level")  # from the store's name (the source catalogue wins)
        if named is None and level is not None:
            asset["dggs:refinement_level"] = level
        elif named is not None and level is not None and level != named:
            problems.add(dsid, f"{key} grid mapping says refinement level {level}, store name says zoom {named}")


class ReadElsewhere(AssetRule):
    """A row for a key that another rule reads (the grid type, the indexing scheme): documents it, does nothing."""

    def apply(self, dsid, key, asset, meta, problems):
        pass


class EllipsoidRule(AssetRule):
    """The figure of the Earth the HEALPix grid is on, as a CRS (projection extension), as the DGGS extension asks.

    WGS 84 by name -> ``proj:code: EPSG:4326``; ellipsoid axes -> ``proj:projjson``. A name we
    don't know stays as ``km_scale:ellipsoid``; no figure at all -> ``km_scale:spherical: true`` (a sphere of unstated
    radius, which no CRS field can express).
    """

    def apply(self, dsid, key, asset, meta, problems):
        if meta.grid_mapping("healpix") is None:
            return
        ell = meta.ellipsoid()
        crs = ellipsoid_crs(ell) if ell else None
        if crs:
            asset.update(crs)
        elif ell:
            asset["km_scale:ellipsoid"] = ell
        else:
            asset["km_scale:spherical"] = True


def ellipsoid_crs(ell):
    """{proj:code} or {proj:projjson} for a grid mapping's ellipsoid attributes, or None if it can't be expressed."""
    name = str(ell.get("reference_ellipsoid_name", "")).replace("-", " ").strip().upper()
    if name in ("WGS 84", "WGS84"):
        return {"proj:code": "EPSG:4326"}
    if "semi_major_axis" in ell and "inverse_flattening" in ell:
        figure = {"name": "unnamed", "semi_major_axis": float(ell["semi_major_axis"]),
                  "inverse_flattening": float(ell["inverse_flattening"])}
    elif "semi_major_axis" in ell and "semi_minor_axis" in ell:
        figure = {"name": "unnamed", "semi_major_axis": float(ell["semi_major_axis"]),
                  "semi_minor_axis": float(ell["semi_minor_axis"])}
    else:
        return None
    axes = [{"name": "Geodetic latitude", "abbreviation": "Lat", "direction": "north", "unit": "degree"},
            {"name": "Geodetic longitude", "abbreviation": "Lon", "direction": "east", "unit": "degree"}]
    return {"proj:code": None, "proj:projjson": {
        "$schema": "https://proj.org/schemas/v0.7/projjson.schema.json", "type": "GeographicCRS",
        "name": "unknown", "datum": {"type": "GeodeticReferenceFrame", "name": "unknown", "ellipsoid": figure},
        "coordinate_system": {"subtype": "ellipsoidal", "axis": axes}}}


class CodecRule(AssetRule):
    """Flag stores that need extra software to open, from the codecs their arrays use."""

    NEEDS = {"gribscan.rawgrib": "gribscan"}

    def apply(self, dsid, key, asset, meta, problems):
        needs = sorted({pkg for codec, pkg in self.NEEDS.items() if codec in meta.codecs})
        if needs:
            asset["km_scale:requires"] = needs


# --- checks on what the data showed --------------------------------------------------------------------------------
class DatasetCheck:
    def apply(self, draft, problems):
        raise NotImplementedError


class TimeFromData(DatasetCheck):
    """No range in any metadata: take it from the stores' time coordinates (earliest start, latest end)."""

    def apply(self, draft, problems):
        p = draft.props
        if "start_datetime" in p:
            return
        ext = [d["extent"] for a in draft.assets.values() for d in a.get("cube:dimensions", {}).values()
               if d["type"] == "temporal" and d.get("extent")]
        if not ext:
            return
        start, end = min(e[0] for e in ext), max(e[1] for e in ext)
        p.update({"datetime": None, "start_datetime": start, "end_datetime": end, "km_scale:time_from_data": True})
        p.pop("km_scale:time_unknown", None)
        problems.replace(draft.id, "no time_start/time_end in metadata; placeholder datetime",
                         f"no time_start/time_end in metadata; range taken from the stores ({start} to {end})")


class TimeConsistency(DatasetCheck):
    """HK25's fail-on-mismatch rule, applied to contents: metadata range vs each frequency's time coordinate."""

    def apply(self, draft, problems):
        p = draft.props
        if "start_datetime" not in p or p.get("km_scale:time_from_data"):
            return
        t_ = lambda x: datetime.fromisoformat(x.replace("Z", "+00:00"))
        seen = set()
        for key, a in draft.assets.items():
            freq = key.split(".")[0]
            t = next((d for d in a.get("cube:dimensions", {}).values() if d["type"] == "temporal" and "extent" in d),
                     None)
            if not t or freq in seen:
                continue
            seen.add(freq)
            off = max(abs((t_(t["extent"][0]) - t_(p["start_datetime"])).days),
                      abs((t_(t["extent"][1]) - t_(p["end_datetime"])).days))
            if off > 1:
                problems.add(draft.id, f"{freq} data run {t['extent'][0]} to {t['extent'][1]}, metadata says "
                                       f"{p['start_datetime']} to {p['end_datetime']}")


class RegionalFootprint(DatasetCheck):
    def apply(self, draft, problems):
        if draft.props["km_scale:domain"] == "regional" and draft.bbox == GLOBAL_BBOX:
            problems.add(draft.id, "regional, but no bounds in the metadata or the store; footprint left global")


# --- the rule set ----------------------------------------------------------------------------------------------------
REGIONAL = KeyRule("Regional flag", None, ["regional"], "`km_scale:domain: regional`",
                   "Read by the footprint rule. Prefer deriving it from the footprint; a footprint covering all "
                   "longitudes (e.g. IMERG's 60°S–60°N band) stays global")

DATASET_RULES = [
    TitleRule("Title", "title", [], "Item `title`", "Only if the source's title is just the id", required_by=DF_RECOMMENDED),
    TimeCoverageRule(target="`start_datetime`, `end_datetime`",
                     notes="Only if the source has no range. Failing both, the build reads the time coordinate"),
    KeyRule("Description", "summary", ["description"], "`description`"),
    KeyRule("Creators", "creator_name", ["creator"], "`km_scale:creators`"),
    ReferencesRule("References", "references", ["reference"], "`sci:publications`, and `about` links",
                   "A list of URLs gives one publication per DOI and an `about` link per other URL; other text is one "
                   "citation", required_by=DF_RECOMMENDED),
    KeyRule("Citation", "citation", [], "`sci:citation`", "How to cite the data (ACDD has no such key; CF-style)"),
    KeyRule("Source", "source", [], "`km_scale:source`", required_by=DF_RECOMMENDED),
    KeyRule("Acknowledgement", "acknowledgment", ["acknowledgement"], "`km_scale:acknowledgment`",
            "ACDD's spelling"),
    KeyRule("Version", "product_version", ["version"], "`version`", "The version extension's field"),
    KeyRule("Processing version", "processing_version", [], "`processing:version`",
            "The version of the processing chain (UM: the HEALPix pipeline), not of the dataset"),
    KeyRule("Simulation name", "simulation", [], "`km_scale:simulation`", "Our own key (UM)"),
    ProvidersRule("Producer", "institution", [], "`providers` (role `producer`)", required_by=DF_RECOMMENDED),
    LicenseTextRule("Licence", "license", [], "`km_scale:license_text`",
                    "Kept only when the Item's licence is `other`. Ideally an SPDX id such as `CC-BY-4.0`",
                    required_by=DF_RECOMMENDED),
    DoiRule("DOI", "doi", ["DOI"], "`sci:doi` and a `cite-as` link", "Our own key; the bare DOI, not a URL"),
    DocumentationRule("Documentation", "documentation_url", ["Documentation", "documentation"], "an `about` link",
                      "Our own key"),
    BoundsRule(REGIONAL, alternates=["regional_bounds", "bounds"], target="`bbox` and `geometry`",
               notes="Alternates are a dict with `lower_left_lat`, `lower_left_lon`, `upper_right_lat`, "
                     "`upper_right_lon`. Longitudes in 0–360 are converted to −180–180"),
    REGIONAL,
]

ASSET_RULES = [
    ReadElsewhere("Grid type", "grid_mapping_name: healpix", [], "finds the grid mapping",
                  "On a grid-mapping variable (e.g. a scalar `crs`)"),
    HealpixGridRule("Refinement level", "refinement_level", ["healpix_level", "zoom", "healpix_nside"],
                    "`dggs:refinement_level` and `dggs:dggrs: HEALPix` on the asset (DGGS extension)",
                    "Level from `healpix_nside` is log2(nside). The zoom in the store's name wins; a different level "
                    "here is a problem. For a store holding several levels (HK27) it is the finest"),
    ReadElsewhere("Indexing scheme", "indexing_scheme: nest", ["healpix_order: nest"],
                  "`dggs:indexing_scheme` on the asset (read with the level)",
                  "data-forge requires `nest`. The catalogue writes `nested` or `ring`, as xdggs does, and also reads "
                  "`nested` (HK25 stores)"),
    EllipsoidRule("Ellipsoid", "reference_ellipsoid_name",
                  ["semi_major_axis + inverse_flattening", "semi_major_axis + semi_minor_axis"],
                  "`proj:code` (WGS 84) or `proj:projjson` on the asset (projection extension); `km_scale:ellipsoid` "
                  "for a name we can't map; `km_scale:spherical: true` if none is given",
                  "HK27 output is on the ellipsoidal HEALPix grid; data-forge reports a spherical grid as an error "
                  "unless run with `--allow-spherical`"),
    CodecRule("Extra software", None, [], "`km_scale:requires` on the asset",
              "From the codecs the arrays use: `gribscan.rawgrib` (IFS stores referencing GRIB) needs gribscan",
              required_by=CATALOGUE),
]

DATASET_CHECKS = [RegionalFootprint(), TimeFromData(), TimeConsistency()]


def apply_dataset_rules(draft, attrs, problems):
    """Run every dataset rule on one draft; returns {rule field: key used} for the usage counts."""
    ctx = DatasetContext(draft, attrs, problems)
    for rule in DATASET_RULES:
        if rule is not REGIONAL:  # consumed by the footprint rule
            rule.apply(ctx)
    ctx.report(DATASET_RULES)
    return ctx.used


def apply_asset_rules(dsid, key, asset, meta, problems):
    for rule in ASSET_RULES:
        rule.apply(dsid, key, asset, meta, problems)


def apply_checks(draft, problems):
    for check in DATASET_CHECKS:
        check.apply(draft, problems)


def metadata_tables():
    """The two key tables for METADATA.md, generated from the rules."""
    def table(head, rows):
        out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        out += ["| " + " | ".join(c or "" for c in r) + " |" for r in rows]
        return "\n".join(out)
    head = ["Field", "Preferred key", "Accepted alternates", "Required by", "Goes to", "Notes"]
    return ("### Dataset-level attributes\n\n" + table(head, [r.doc_row() for r in DATASET_RULES]) +
            "\n\n### Grid mapping and structure (per store)\n\n" + table(head, [r.doc_row() for r in ASSET_RULES]))
