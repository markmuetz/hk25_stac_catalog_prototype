"""Build a static STAC catalogue from the HK25 Intake catalogue: a prototype for the HK27 catalogue.

The build has three stages (``pipeline.py``):

1. **collect** (``hk25.py``): walk the HK25 Intake catalogue and turn each dataset into an ``ItemDraft``;
2. **probe** (``stores.py``, ``rules.py``): read each online store's metadata and apply the reading rules;
3. **write** (``stac_out.py``, ``site.py``): write the STAC tree with pystac, then the search page's files.
"""
