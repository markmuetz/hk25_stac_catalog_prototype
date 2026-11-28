"""Standard STAC extensions in place of our own fields: references, version, DGGS, projection."""

import pytest

from hk25_stac import rules
from hk25_stac.model import ItemDraft, Problems
from hk25_stac.stac_out import extensions, to_collection, to_item
from hk25_stac.util import EXT, references


@pytest.mark.parametrize("text, pubs, about", [
    ("https://doi.org/10.1002/qj.4781", [{"doi": "10.1002/qj.4781"}], []),
    ("https://doi.org/10.5194/gmd-18-33-2025, https://www.ecmwf.int/en/forecasts/x, https://fesom.de",
     [{"doi": "10.5194/gmd-18-33-2025"}], ["https://www.ecmwf.int/en/forecasts/x", "https://fesom.de"]),
    ("https://www.icon-model.org/", None, ["https://www.icon-model.org/"]),
    ("Zhang, H., et al., 2020. CAS-ESM version 2. JAMES, 12, e2020MS002210. https://doi.org/10.1029/2020MS002210",
     [{"citation": "Zhang, H., et al., 2020. CAS-ESM version 2. JAMES, 12, e2020MS002210. "
                   "https://doi.org/10.1029/2020MS002210", "doi": "10.1029/2020MS002210"}], []),
    ("The ARP-GEM2 Global Atmosphere Model (Geoffroy and Saint-Martin, 2025)",
     [{"citation": "The ARP-GEM2 Global Atmosphere Model (Geoffroy and Saint-Martin, 2025)"}], []),
    ("", None, []),
])
def test_references(text, pubs, about):
    got, links = references(text)
    assert got == pubs
    assert [l["href"] for l in links if l["rel"] == "about"] == about
    assert [l["href"] for l in links if l["rel"] == "describedby"] == [f"https://doi.org/{p['doi']}"
                                                                     for p in pubs or [] if "doi" in p]


def draft(assets=None, **props):
    p = {"title": "ds1", "license": "CC-BY-4.0", "km_scale:domain": "global", "km_scale:product_type": "simulation",
         "datetime": "2020-01-20T00:00:00Z", **props}
    return ItemDraft("ds1", "simulations", "UM", "UM", p, assets or {}, {})


def test_references_and_versions_from_store_attributes():
    d = draft()
    rules.apply_dataset_rules(d, {"references": "https://doi.org/10.1002/qj.4781", "citation": "Cite me.",
                                  "product_version": "v2", "processing_version": "1.3"}, Problems())
    p = d.props
    assert p["sci:publications"] == [{"doi": "10.1002/qj.4781"}] and p["sci:citation"] == "Cite me."
    assert p["version"] == "v2" and p["processing:version"] == "1.3"
    assert {"rel": "describedby", "href": "https://doi.org/10.1002/qj.4781", "title": "Publication",
            "type": "text/html"} in d.links


def test_extensions_follow_the_fields():
    assets = {"PT1H.z8": {"href": "https://x/a.zarr", "dggs:dggrs": "HEALPix", "dggs:refinement_level": 8,
                          "proj:code": "EPSG:4326", "zarr:consolidated": True,
                          "alternate": {"UK": {"href": "file:///a.zarr"}}}}
    got = extensions({"sci:citation": "x", "version": "v1"}, assets)
    assert got == sorted(EXT[e] for e in ("dggs", "projection", "zarr", "alternate", "scientific", "version"))
    assert extensions({}, {"k": {"href": "h"}}) == []


def test_item_and_collection_carry_dggs():
    d = draft({"PT1H.z8": {"href": "https://x/8.zarr", "dggs:dggrs": "HEALPix", "dggs:refinement_level": 8},
               "PT1H.z0": {"href": "https://x/0.zarr", "dggs:dggrs": "HEALPix", "dggs:refinement_level": 0}})
    item = to_item(d).to_dict()
    assert EXT["dggs"] in item["stac_extensions"]
    assert any(l["rel"].endswith("dggrs-definition") for l in item["links"])
    c = to_collection("UM", [d]).to_dict()
    assert c["summaries"]["dggs:refinement_level"] == [0, 8] and c["summaries"]["dggs:dggrs"] == ["HEALPix"]
    assert EXT["dggs"] in c["stac_extensions"]
