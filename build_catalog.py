"""Build the static STAC catalogue and search site from the HK25 Intake catalogue.

    uv run build_catalog.py <clone of digital-earths-global-hackathon/catalog> build/
    uv run build_catalog.py --metadata-doc      # regenerate the key tables in METADATA.md from the rules

HK25 stores are one store per zoom (HK27 will have zoom groups in one store), so assets are keyed
"<freq>.z<zoom>" here; HK27 would key them "<freq>" and record the zoom levels on the asset.
The code is in hk25_stac/ (see its __init__.py for the stages).
"""

import argparse
import re
from pathlib import Path

from hk25_stac.pipeline import build
from hk25_stac.rules import metadata_tables

HERE = Path(__file__).parent
START, END = "<!-- generated from hk25_stac/rules.py: start -->", "<!-- generated from hk25_stac/rules.py: end -->"


def update_metadata_doc(path=HERE / "METADATA.md"):
    text = path.read_text()
    new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: f"{START}\n{metadata_tables()}\n{END}",
                 text, flags=re.S)
    path.write_text(new)
    return new != text


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("hk25_root", type=Path, nargs="?")
    ap.add_argument("out", type=Path, nargs="?")
    ap.add_argument("--no-probe", action="store_true", help="skip reading the online stores")
    ap.add_argument("--metadata-doc", action="store_true", help="regenerate the tables in METADATA.md and exit")
    a = ap.parse_args()
    if a.metadata_doc:
        print("METADATA.md updated" if update_metadata_doc() else "METADATA.md already up to date")
    elif a.hk25_root and a.out:
        build(a.hk25_root.expanduser(), a.out, probe_stores=not a.no_probe)
    else:
        ap.error("give the HK25 catalogue clone and an output directory, or --metadata-doc")
