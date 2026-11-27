from pathlib import Path

from build_catalog import END, START
from hk25_stac.rules import metadata_tables


def test_metadata_doc_in_sync_with_rules():
    """METADATA.md's key tables are generated from the rules: run `uv run build_catalog.py --metadata-doc`."""
    text = (Path(__file__).parent.parent / "METADATA.md").read_text()
    assert f"{START}\n{metadata_tables()}\n{END}" in text
