import pytest

from hk25_stac import rules
from hk25_stac.model import ItemDraft, Problems
from hk25_stac.stores import ArrayInfo, StoreMetadata, ZarrStore
from hk25_stac.util import GLOBAL_BBOX, bounds_to_bbox, iso


def draft(**props):
    p = {"title": "ds1", "license": "other", "km_scale:domain": "global", "km_scale:product_type": "simulation",
         "datetime": "2020-01-20T00:00:00Z", "km_scale:time_unknown": True, **props}
    return ItemDraft("ds1", "simulations", "UM", "UM", p, {}, {})


def run(d, attrs):
    problems = Problems()
    used = rules.apply_dataset_rules(d, attrs, problems)
    return used, problems.lines()


# --- footprint ---
@pytest.mark.parametrize("b, expected", [
    ({"lower_left_lat": -18, "lower_left_lon": 90, "upper_right_lat": 26, "upper_right_lon": 154}, [90, -18, 154, 26]),
    ({"lower_left_lat": -40, "lower_left_lon": 340, "upper_right_lat": 26, "upper_right_lon": 54}, [-20, -40, 54, 26]),
    ({"lower_left_lat": -30, "lower_left_lon": 274, "upper_right_lat": 14, "upper_right_lon": 334}, [-86, -30, -26, 14]),
    # a channel all the way round (0.02 to 359.98) is a full longitude band, not a sliver across the antimeridian
    ({"lower_left_lat": -40, "lower_left_lon": 0.02, "upper_right_lat": 26, "upper_right_lon": 359.98}, [-180, -40, 180, 26]),
    ({"lower_left_lat": -60, "lower_left_lon": 0, "upper_right_lat": 60, "upper_right_lon": 360}, [-180, -60, 180, 60]),
    # crossing the antimeridian keeps west > east
    ({"lower_left_lat": 0, "lower_left_lon": 170, "upper_right_lat": 10, "upper_right_lon": 190}, [170, 0, -170, 10]),
])
def test_bounds_to_bbox(b, expected):
    assert bounds_to_bbox(b) == expected


def test_bounds_from_string_repr():
    assert bounds_to_bbox("{'lower_left_lat': 0, 'lower_left_lon': 10, 'upper_right_lat': 5, 'upper_right_lon': 20}") \
        == [10, 0, 20, 5]


def test_acdd_bounds_preferred_over_alternates():
    d = draft()
    attrs = {"geospatial_lat_min": -10, "geospatial_lat_max": 10, "geospatial_lon_min": 0, "geospatial_lon_max": 20,
             "bounds": {"lower_left_lat": 0, "lower_left_lon": 0, "upper_right_lat": 1, "upper_right_lon": 1}}
    used, problems = run(d, attrs)
    assert d.bbox == [0, -10, 20, 10]
    assert used["Footprint"] == "geospatial_lat_min/max, geospatial_lon_min/max"
    assert not any("alternate" in p for p in problems)


@pytest.mark.parametrize("key", ["regional_bounds", "bounds"])
def test_alternate_bounds_accepted_and_reported(key):
    d = draft()
    attrs = {key: {"lower_left_lat": -18, "lower_left_lon": 90, "upper_right_lat": 26, "upper_right_lon": 154},
             "regional": "True"}
    used, problems = run(d, attrs)
    assert d.bbox == [90, -18, 154, 26] and d.geometry["type"] == "Polygon"
    assert d.props["km_scale:domain"] == "regional"
    assert any(f"Footprint: {key} (preferred geospatial" in p for p in problems)


def test_regional_band_round_the_globe_stays_global():
    d = draft()
    run(d, {"regional": True, "geospatial_lat_min": -60, "geospatial_lat_max": 60,
            "geospatial_lon_min": 0, "geospatial_lon_max": 360})
    assert d.props["km_scale:domain"] == "global" and d.bbox == [-180, -60, 180, 60]


def test_regional_flag_without_bounds_is_a_problem():
    d = draft()
    _, problems = run(d, {"regional": "True"})
    assert d.bbox == GLOBAL_BBOX
    assert "ds1: store says regional but gives no bounds" in problems


# --- generic keys ---
def test_preferred_then_alternate_and_placeholders():
    d = draft()
    used, problems = run(d, {"summary": "UNSET", "description": "A real description", "creator": "A. Person"})
    assert d.props["description"] == "A real description"  # placeholder in the preferred key counts as missing
    assert d.props["km_scale:creators"] == "A. Person"
    assert used["Description"] == "description" and used["Creators"] == "creator"


def test_source_metadata_wins():
    d = draft(description="From Intake")
    run(d, {"summary": "From the store"})
    assert d.props["description"] == "From Intake"


def test_title_only_replaces_bare_id():
    d = draft()
    run(d, {"title": "A proper title"})
    assert d.props["title"] == "A proper title"
    d2 = draft(title="Intake title")
    run(d2, {"title": "A proper title"})
    assert d2.props["title"] == "Intake title"


def test_doi_cleaned_and_linked():
    d = draft()
    run(d, {"DOI": "https://doi.org/10.5067/ABC"})
    assert d.props["sci:doi"] == "10.5067/ABC"
    assert {"rel": "cite-as", "href": "https://doi.org/10.5067/ABC"} in d.links


def test_time_coverage_fills_missing_range():
    d = draft()
    run(d, {"time_coverage_start": "2020-01-20", "time_coverage_end": "2021-02-28"})
    assert d.props["start_datetime"] == "2020-01-20T00:00:00Z" and d.props["datetime"] is None
    assert "km_scale:time_unknown" not in d.props


def test_from_store_recorded():
    d = draft()
    run(d, {"source": "CAM"})
    assert d.props["km_scale:from_store"] == ["km_scale:source <- source"]


# --- asset rules ---
def meta(gm=None, codecs=()):
    arrays = {"crs": ArrayInfo({"grid_mapping_name": "healpix", **(gm or {})}, [], "<i4", [])} if gm is not None else {}
    return StoreMetadata(2, arrays, {}, set(codecs))


@pytest.mark.parametrize("gm, expected", [
    ({"healpix_nside": 1, "healpix_order": "nest"}, (0, "nested")),
    ({"healpix_nside": 256, "healpix_order": "nested"}, (8, "nested")),
    ({"refinement_level": 9, "indexing_scheme": "nested", "healpix_nside": 512}, (9, "nested")),
    ({"healpix_nside": 4, "healpix_order": "ring"}, (2, "ring")),
])
def test_healpix_normalised(gm, expected):
    assert meta(gm).healpix() == expected


def test_healpix_level_checked_against_zoom():
    problems, asset = Problems(), {"km_scale:zoom": 3}
    rules.apply_asset_rules("ds1", "PT1H.z3", asset, meta({"healpix_nside": 4, "healpix_order": "nest"}), problems)
    assert asset["healpix:refinement_level"] == 2
    assert "refinement level 2, store name says zoom 3" in problems.lines()[0]


def test_gribscan_flag():
    asset = {}
    rules.apply_asset_rules("ds1", "k", asset, meta(None, {"gribscan.rawgrib"}), Problems())
    assert asset["km_scale:requires"] == ["gribscan"]


# --- checks ---
def test_time_from_data():
    d = draft()
    d.assets = {"PT1H.z0": {"cube:dimensions": {"time": {"type": "temporal", "extent": ["2020-01-01T00:00:00Z",
                                                                                          "2020-12-31T00:00:00Z"]}}}}
    problems = Problems()
    problems.add("ds1", "no time_start/time_end in metadata; placeholder datetime")
    rules.apply_checks(d, problems)
    assert d.props["km_scale:time_from_data"] and d.props["end_datetime"] == "2020-12-31T00:00:00Z"
    assert "range taken from the stores" in problems.lines()[0]


# --- store reading ---
def test_zarr_v2_and_v3_metadata():
    v2 = ZarrStore._from_v2({".zattrs": {"title": "t"},
                             "pr/.zarray": {"shape": [10, 12], "dtype": "<f4", "compressor": {"id": "blosc"}},
                             "pr/.zattrs": {"_ARRAY_DIMENSIONS": ["time", "cell"], "units": "kg m-2 s-1"}})
    assert v2.zarr_format == 2 and v2.arrays["pr"].dims == ["time", "cell"] and v2.codecs == {"blosc"}
    v3 = ZarrStore._from_v3({"attributes": {"title": "t"}, "consolidated_metadata": {"metadata": {
        "pr": {"node_type": "array", "shape": [10, 12], "data_type": "float32", "dimension_names": ["time", "cell"],
               "codecs": [{"name": "bytes"}, {"name": "zstd"}], "attributes": {}}}}})
    assert v3.zarr_format == 3 and v3.dim_sizes() == {"time": 10, "cell": 12} and v3.codecs == {"bytes", "zstd"}


def test_iso():
    assert iso("2020-01-20") == "2020-01-20T00:00:00Z"
    assert iso("2020-01-20 06:00") == "2020-01-20T06:00:00Z"
