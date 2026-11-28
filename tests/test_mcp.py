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
    regional = [r["id"] for r in m.search_datasets(lon=20, lat=0, domain="regional")]
    assert regional and all(i.startswith("um_") for i in regional)


def test_find_variable_and_describe(m):
    assert m.find_variable("precipitation")[0]["variable"] == "pr"
    d = m.describe_dataset("um_glm_n2560_RAL3p3")
    assert "PT1H.z8" in d["assets"] and d["variables"]["pr"]["unit"]


def test_how_to_open(m):
    r = m.how_to_open("um_glm_n2560_RAL3p3", "PT1H", 8, location="UK")
    assert r["copy"] == "online via UK endpoint" and "open_dataset" in r["code"]


def test_query_catalog_is_read_only(m):
    assert m.query_catalog("select count(*) from items")["rows"][0][0] > 30
    assert m.query_catalog('select len(list_filter("km_scale:zooms", x -> x > 8)) from items')["n"]
    for bad in ["drop table items", "select * from read_text('/etc/hosts')"]:
        with pytest.raises(m.ToolError):
            m.query_catalog(bad)
    with pytest.raises(m.ToolError, match="unknown dataset"):
        m.describe_dataset("nope")
