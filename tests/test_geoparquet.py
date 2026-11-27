import json

from hk25_stac.geoparquet import flatten


def test_flatten():
    item = {"properties": {}, "assets": {
        "PT1H.z8": {"km_scale:zoom": 8, "cube:variables": {"pr": {"type": "data"}, "crs": {"type": "auxiliary"}},
                    "cube:dimensions": {"time": {"type": "temporal"}}},
        "static.z8": {"km_scale:zoom": 8}}}
    d = flatten(item)
    p = d["properties"]
    assert p["km_scale:variables"] == ["pr"] and p["km_scale:frequencies"] == ["PT1H", "static"]
    assert p["km_scale:zooms"] == [8]
    assert json.loads(d["assets"]["PT1H.z8"]["cube:variables"])["pr"] == {"type": "data"}
    assert isinstance(item["assets"]["PT1H.z8"]["cube:variables"], dict)  # the original is untouched
