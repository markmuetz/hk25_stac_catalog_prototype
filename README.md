# HK25 catalogue as STAC: an HK27 prototype

An experiment for the HK27 catalogue design (`hk27_planning/notes/catalogue-stac.md`). It converts the public HK25
Intake catalogue (https://github.com/digital-earths-global-hackathon/catalog) into a static STAC catalogue, using
the model proposed for HK27:

- **one catalogue, no per-site catalogues.** The default `href` is the online copy; genuinely separate copies are
  alternate assets keyed by site;
- **a site table** (`config/sites.yaml`) for rules that belong to a site's network, e.g. JASMIN's internal
  endpoint;
- **`km_scale.resolve` / `open_asset`** as the one way to open data;
- **datacube + cf** on each asset, generated from consolidated Zarr metadata, with levels and the first and last
  times read from the coarsest store;
- **hierarchy:** `simulations/`, `observations/`, `reanalyses/` and `derived/MCS-tracks/<tracker>/` Catalogs, with
  a Collection per model or product, and generated `by-experiment/` views that only link to Items;
- **a controlled vocabulary check** (`config/vocab.yaml`);
- **a flat `index.json` and a static search page:** facets, free text, a variable × dataset matrix, and per-dataset
  snippets and gridlook links.

## Run

```sh
uv run build_catalog.py ~/projects/external/hk25/catalog build      # ~20 s; reads ~930 online stores' metadata
uv run validate.py build                                             # core + extension JSON schemas
cd build && python3 -m http.server 8793 --bind 127.0.0.1             # then open http://127.0.0.1:8793/
```

`build/problems.txt` lists what the build found wrong with the source catalogue.

```python
import km_scale                                   # build/km_scale.py; KM_SCALE_CATALOG=<build dir or URL>
km_scale.resolve("um_glm_n2560_RAL3p3_tuned_hk26", "PT1H", 0, location="UK")   # JASMIN-internal URL, via the site table
ds = km_scale.open_asset("um_glm_n2560_RAL3p3_tuned_hk26", "PT1H", 0)          # online copy
km_scale.search(experiment="dyamond3-p4k")
```

## HK25 vs HK27 layout

HK25 has one store per zoom, so assets here are keyed `<freq>.z<zoom>` (e.g. `PT1H.z8`), with `km_scale:zoom`.
HK27 stores will hold zoom groups, so assets would be keyed `<freq>` and list their refinement levels. That also
shrinks the STAC: here it's 6.2 MB, because each zoom's asset repeats its datacube.

## Results (2026-11-18)

- **It works end to end.**
  - 58 Items in 16 Collections, with 1139 assets (797 with datacube). All 86 Catalogs, Collections and Items
    validate against the core and extension schemas.
  - `index.json` is 76 kB.
  - `km_scale.open_asset` opened a UM store from the Mac.
  - `resolve()` gave the JASMIN-internal URL for UK, the filesystem path for NERSC, the online copy when a site
    lacks a zoom, and "only available at NCAR" for site-only data.
- **The site table replaced every UK copy.** 486 assets of datasets held at both UK and online needed no UK
  alternate; one line in `sites.yaml` covers them. The alternates kept are genuinely separate copies: NERSC 184,
  Aus 48, JAPAN 46, EU 57, CN 30.
- **Probing the stores found real errors in the HK25 catalogue** (`problems.txt`, 177 lines):
  - `um_CTC_km4p4_RAL3P3_n2560_CoMA9_nest_hk26`: none of its 22 stores exist. The object store has only
    `prod/v7/CTC_km4p4_CoMA9_TBv1.n2560_CoMA9_hier_v2/` under `CTC`.
  - Parameter combinations advertised but with no store: `icon_d3hp003aug` and `icon_d3hp003feb` (36 each),
    `scream-dkrz` (33), and some IFS. Intake's free parameters can't express "these combinations only".
  - 27 datasets have no licence and 8 have no time range.
- **The experiment can't be inferred reliably.** HK25 has no experiment field (`experiment_id: hackathon`
  everywhere). Dates and names give a guess, marked `km_scale:experiment_inferred` on each Item. Several runs start
  on 1 Jan 2020, not on the DYAMOND3 start date. Producers need to set the experiment (the vocabulary plan).
- **Variable names differ across centres, and the matrix makes it obvious.** IFS uses GRIB short names (`2t`, `msl`,
  `10u`, `tp`) where others use CMIP names (`tas`, `psl`, `uas`, `pr`), and IMERG uses `precipitation`. A Tier 1
  coverage check would flag them at once.
- **A spec wrinkle:** the cf extension README allows `cf:cell_methods` as a plain string, but its v1.0.0 schema only
  accepts an array.
