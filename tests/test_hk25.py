from hk25_stac.hk25 import Hk25Entry, apply_override, asset_keys, classify, infer_domain, infer_experiment


def test_classify():
    assert classify("um_glm_n2560_RAL3p3")[:2] == ("simulations", "UM")
    assert classify("ERA5")[0] == "reanalyses"
    assert classify("tracking")[:4] == ("derived/MCS-tracks", "PyFLEXTRKR", "PyFLEXTRKR", "derived")


def test_domain():
    assert infer_domain("um_glm_n2560_RAL3", {"region": "glm"}) == "global"  # 'glm' is the UM's word for global
    assert infer_domain("um_SEA_km4p4", {}) == "regional"
    assert infer_domain("x", {"region": "Africa"}) == "regional"


def test_experiment():
    assert infer_experiment("um_glm_p4k", {}) == "dyamond3-p4k"
    assert infer_experiment("x", {"time_start": "2020-01-20", "time_end": "2021-03-01"}) == "dyamond3"
    assert infer_experiment("x", {}) == "other"


def test_asset_keys():
    assert asset_keys({"time": "PT1H", "zoom": 3}, ["a.zarr"]) == ["PT1H.z3"]
    assert asset_keys({"time": "PT1H", "zoom": 3}, ["a.zarr", "static.zarr"]) == ["PT1H.z3", "static.z3"]
    assert asset_keys({"zoom": 0}, ["a", "b"]) == ["data.z0", "data_part2.z0"]


def test_combinations_render_jinja():
    e = Hk25Entry("ds", "online", {"args": {"urlpath": "https://x/{{ time }}_z{{ zoom }}.zarr"},
                                   "parameters": {"time": {"allowed": ["PT1H", "PT3H"]}, "zoom": {"allowed": [0, 1]}}})
    assert sorted(e.urls_by_key) == ["PT1H.z0", "PT1H.z1", "PT3H.z0", "PT3H.z1"]
    assert e.urls_by_key["PT3H.z1"][0] == "https://x/PT3H_z1.zarr"


def test_site_override():
    sites = {"UK": {"endpoint_overrides": {"https://ext/": "http://int/"}}}
    assert apply_override("https://ext/a.zarr", "UK", sites) == "http://int/a.zarr"
    assert apply_override("https://other/a.zarr", "UK", sites) == "https://other/a.zarr"
