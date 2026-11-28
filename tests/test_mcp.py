"""The MCP server's tools, called in-process against a fresh build: KM_SCALE_BUILD=build pytest tests/test_mcp.py"""
import os

import pytest

BUILD = os.environ.get("KM_SCALE_BUILD")
pytestmark = pytest.mark.skipif(not BUILD, reason="set KM_SCALE_BUILD to a build directory")
pytest.importorskip("mcp")


@pytest.fixture(scope="module")
def m():
    os.environ["KM_SCALE_CATALOG"] = os.path.abspath(BUILD)
    os.environ["KM_SCALE_MCP_LOG"] = "off"
    import km_scale_mcp
    return km_scale_mcp


def test_overview(m):
    o = m.catalog_overview()
    assert o["n"] > 30 and "PT1H" in o["frequencies"] and "pr" in o["common_variables"]


def test_search(m):
    ids = [r["id"] for r in m.search_datasets(variables=["pr"], frequency="PT1H", domain="global")]
    assert "um_glm_n2560_RAL3p3" in ids and "icon_d3hp003" in ids  # icon only has PT1H_inst
    # UM has ta (3D) only 3-hourly, beside hourly 2D stores: one store must have both
    assert "um_glm_n2560_RAL3p3" not in [r["id"] for r in m.search_datasets(variables=["ta"], frequency="PT1H")]
    assert "um_glm_n2560_RAL3p3" in [r["id"] for r in m.search_datasets(variables=["ta"], frequency="PT3H")]
    regional = [r["id"] for r in m.search_datasets(lon=20, lat=0, domain="regional")]
    assert regional and all(i.startswith("um_") for i in regional)


def test_find_variable_and_describe(m):
    pr = m.find_variable("precipitation")[0]
    assert pr["variable"] == "pr" and "PT1H" in pr["datasets"]["um_glm_n2560_RAL3p3"]["frequencies"]
    assert pr["datasets"]["um_glm_n2560_RAL3p3"]["unit"]
    d = m.describe_dataset("um_glm_n2560_RAL3p3")
    assert "PT1H.z8" in d["assets"] and d["variables"]["pr"]["unit"]


def test_how_to_open(m):
    r = m.how_to_open("um_glm_n2560_RAL3p3", frequency="PT1H", zoom=8, location="UK")
    assert r["asset"] == "PT1H.z8" and r["copy"] == "online via UK endpoint" and "open_dataset" in r["code"]
    r = m.how_to_open("icon_d3hp003", frequency="PT1H")  # finest zoom; inst and mean both match
    assert r["asset"] == "PT1H_inst.z11" and r["other_matching_assets"] == ["PT1H_mean.z11"]
    assert m.how_to_open("ERA5", frequency="P1M")["asset"].startswith("data.")  # frequency inferred
    with pytest.raises(m.ToolError, match="no store matches"):
        m.how_to_open("ERA5", frequency="PT1H")


def test_find_assets(m):
    rows = m.find_assets(variables=["pr"], frequency="PT1H", time_method="mean")
    assert {r["id"] for r in rows} == {"arp-gem-1p3km", "arp-gem-2p6km"}
    assert all(r["zoom"] == max(x["zoom"] for x in rows if x["id"] == r["id"]) for r in rows)
    every_zoom = m.find_assets(dataset_id="um_glm_n2560_RAL3p3", frequency="PT1H", finest_only=False)
    assert len(every_zoom) > 5


def test_sql_examples_run(m):
    examples = m.query_catalog.__doc__.split("Examples:")[1].split("--")[1:]
    for e in examples:
        assert m.query_catalog(" ".join(e.split("\n", 1)[1].split()))["n"] > 0


def test_query_catalog_is_read_only(m):
    assert m.query_catalog("select count(*) from items")["rows"][0][0] > 30
    assert m.query_catalog('select len(list_filter("km_scale:zooms", x -> x > 8)) from items')["n"]
    for bad in ["drop table items", "select * from read_text('/etc/hosts')"]:
        with pytest.raises(m.ToolError):
            m.query_catalog(bad)
    with pytest.raises(m.ToolError, match="unknown dataset"):
        m.describe_dataset("nope")
