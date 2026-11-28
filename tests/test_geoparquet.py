import json

import pytest

from hk25_stac.geoparquet import asset_rows, flatten, infer_frequency, parse_key


def test_flatten():
    item = {"properties": {}, "assets": {
        "PT1H.z8": {"dggs:refinement_level": 8, "cube:variables": {"pr": {"type": "data"}, "crs": {"type": "auxiliary"}},
                    "cube:dimensions": {"time": {"type": "temporal"}}},
        "static.z8": {"dggs:refinement_level": 8}}}
    d = flatten(item)
    p = d["properties"]
    assert p["km_scale:variables"] == ["pr"] and p["km_scale:frequencies"] == ["PT1H", "static"]
    assert p["km_scale:zooms"] == [8]
    assert json.loads(d["assets"]["PT1H.z8"]["cube:variables"])["pr"] == {"type": "data"}
    assert isinstance(item["assets"]["PT1H.z8"]["cube:variables"], dict)  # the original is untouched


@pytest.mark.parametrize("key, expected", [
    ("PT1H.z8", ("PT1H", None, None, None, 8)),
    ("PT1H_inst.z11", ("PT1H", "inst", None, None, 11)),
    ("3D_PT1H.z5", ("PT1H", None, "3D", None, 5)),
    ("P1D_part2.z3", ("P1D", None, None, "part2", 3)),
    ("static.z2", ("fixed", None, None, None, 2)),
    ("data", (None, None, None, None, None)),
])
def test_parse_key(key, expected):
    r = parse_key(key)
    assert (r["frequency"], r["time_method"], r["levels"], r["part"], r["zoom"]) == expected


@pytest.mark.parametrize("dim, expected", [
    ({"step": "PT3H", "count": 5}, "PT3H"),
    ({"count": 1008, "extent": ["1940-01-01T00:00:00Z", "2023-12-01T00:00:00Z"]}, "P1M"),  # ERA5 monthly
    ({"count": 52609, "extent": ["2019-01-01T00:00:00Z", "2022-01-01T00:00:00Z"]}, "PT30M"),  # IMERG
    ({"count": 1, "extent": ["2020-01-01T00:00:00Z", "2020-01-01T00:00:00Z"]}, None),
    ({"count": 7, "extent": ["2020-01-01T00:00:00Z", "2020-01-01T10:00:00Z"]}, None),  # 100 min: no standard step
    ({}, None),
])
def test_infer_frequency(dim, expected):
    assert infer_frequency(dim) == expected


def test_asset_rows():
    item = {"id": "ds1", "collection": "c", "properties": {"km_scale:domain": "global"}, "assets": {
        "data.z4": {"href": "https://x/a.zarr", "type": "application/vnd.zarr; version=2", "dggs:refinement_level": 4,
                    "alternate": {"UK": {"href": "file:///a.zarr"}},
                    "cube:dimensions": {"time": {"type": "temporal", "count": 25,
                                                 "extent": ["2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z"]},
                                        "cell": {"type": "dggs"}, "level": {"type": "spatial"}},
                    "cube:variables": {"pr": {"type": "data"}, "lat": {"type": "auxiliary"}}}}}
    (r,) = asset_rows(item)
    assert (r["frequency"], r["frequency_inferred"], r["zoom"]) == ("PT1H", True, 4)
    assert r["variables"] == ["pr"] and r["vertical_dims"] == ["level"] and r["copies"] == ["online", "UK"]
    assert r["format"] == "zarr" and r["n_time"] == 25
