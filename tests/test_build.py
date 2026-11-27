"""Checks on a built catalogue, if one is given (CI passes the build directory): KM_SCALE_BUILD=build pytest."""
import json
import os
from pathlib import Path

import pytest

BUILD = os.environ.get("KM_SCALE_BUILD")


@pytest.mark.skipif(not BUILD, reason="no build directory given (KM_SCALE_BUILD)")
def test_no_bare_local_paths():
    """Every local href has file://: a bare /path would resolve against the catalogue's URL."""
    bad = []
    for f in Path(BUILD, "stac").rglob("*.json"):
        d = json.loads(f.read_text())
        for k, a in d.get("assets", {}).items():
            for h in [a["href"], *(v["href"] for v in a.get("alternate", {}).values())]:
                if h.startswith("/"):
                    bad.append(f"{d['id']} {k}: {h}")
    assert not bad, bad[:5]


@pytest.mark.skipif(not BUILD, reason="no build directory given (KM_SCALE_BUILD)")
def test_no_glob_hrefs():
    """A glob is several stores, not one resource: such datasets are left out until they are one store."""
    bad = []
    for f in Path(BUILD, "stac").rglob("*.json"):
        d = json.loads(f.read_text())
        for k, a in d.get("assets", {}).items():
            for h in [a["href"], *(v["href"] for v in a.get("alternate", {}).values())]:
                if "*" in h:
                    bad.append(f"{d['id']} {k}: {h}")
    assert not bad, bad[:5]


@pytest.mark.skipif(not BUILD, reason="no build directory given (KM_SCALE_BUILD)")
def test_geoparquet_has_every_item_and_queries():
    import duckdb
    n_items = sum(1 for f in Path(BUILD, "stac").rglob("*.json")
                  if "by-experiment" not in f.parts and json.loads(f.read_text()).get("type") == "Feature")
    pq = str(Path(BUILD, "items.parquet"))
    assert duckdb.sql(f"select count(*) from '{pq}'").fetchall()[0][0] == n_items
    ids = {r[0] for r in duckdb.sql(f"""select id from '{pq}' where list_contains("km_scale:variables", 'pr')""").fetchall()}
    assert ids, "no Item with pr"


@pytest.mark.skipif(not BUILD, reason="no build directory given (KM_SCALE_BUILD)")
def test_strict_json():
    """No NaN or Infinity: they aren't JSON, and browsers' JSON.parse rejects them."""
    def reject(c):
        raise ValueError(f"non-JSON constant {c}")
    for f in Path(BUILD).rglob("*.json"):
        json.loads(f.read_text(), parse_constant=reject)
