# HK27 catalogue prototype: the HK25 catalogue as STAC

**Browse it:** https://markmuetz.github.io/hk27_catalog/

**A draft for comment. Nothing here is set in stone.** This is one person's prototype for the catalogue of the 2027
WCRP global km-scale hackathon (HK27), put together by Mark Muetzelfeldt with Claude (an AI assistant). It has not
been agreed with the HK27 catalogue group, and any of it may change. Comments and objections are welcome as GitHub
issues.

It converts the public HK25 Intake catalogue (https://github.com/digital-earths-global-hackathon/catalog) into a
static STAC catalogue, using the model proposed for HK27:

- **one catalogue, no per-site catalogues.** The default `href` is the online copy; genuinely separate copies are
  alternate assets keyed by site;
- **a site table** (`config/sites.yaml`) for rules that belong to a site's network, e.g. JASMIN's internal
  endpoint;
- **`km_scale`**, named by what each function returns: `open_dataset` (xarray), `open_datatree` (all zooms),
  `open_table` (pandas), `get_url` (anything). All take `location=` (where you are) and `source=` (force a copy);
  `where()` and the `km_scale_source`/`km_scale_copy` attrs show where data comes from;
- **datacube + cf** on each asset, generated from consolidated Zarr metadata, with levels and the first and last
  times read from the coarsest store;
- **hierarchy:** `simulations/`, `observations/`, `reanalyses/` and `derived/MCS-tracks/<tracker>/` Catalogs, with
  a Collection per model or product, and generated `by-experiment/` views that only link to Items;
- **a controlled vocabulary check** (`config/vocab.yaml`);
- **a flat `index.json` and a static search page:** facets, free text, a variable × dataset matrix, and per-dataset
  snippets and gridlook links.
  A tree of the catalogue hierarchy on the left, generated from the STAC links into `tree.json`, is the filter for
  product type and Collection. Its counts follow the other filters; `+n?` marks datasets whose variables couldn't be
  read. Selecting a Catalog or Collection shows its shared properties (licence, providers, period, summaries).
- **a page per Item** (`item.html#<id>`), like STAC Browser's, linked from each card in place of raw JSON:
  - breadcrumbs from the tree, the description (with basic markdown), licence, providers, creators, references;
  - a map of the footprint (Leaflet + OSM tiles);
  - time: start, end and length, the steps per frequency read from the stores, and a warning when the metadata's
    range disagrees with the data;
  - per frequency: format, zoom levels and cell counts, copies, an `open_dataset` snippet with a zoom selector,
    the `where()` table for every site, and dimension and variable tables (units, standard names, cell methods),
    with a filter box;
  - links to the Item JSON, the Collection JSON and gridlook.

## Run

```sh
git clone https://github.com/digital-earths-global-hackathon/catalog hk25   # CI pins d277f26
uv run build_catalog.py hk25 build                                   # ~20 s; reads ~930 online stores' metadata
uv run validate.py build                                             # core + extension JSON schemas
cd build && python3 -m http.server 8793 --bind 127.0.0.1             # then open http://127.0.0.1:8793/
```

`build/problems.txt` lists what the build found wrong with the source catalogue.

```python
import km_scale                                   # build/km_scale.py; KM_SCALE_CATALOG=<build dir or URL>
km_scale.get_url("um_glm_n2560_RAL3p3_tuned_hk26", "PT1H", 0, location="UK")   # JASMIN-internal URL, via the site table
ds = km_scale.open_dataset("um_glm_n2560_RAL3p3_tuned_hk26", "PT1H", 0)        # online copy; ds.attrs["km_scale_copy"]
km_scale.where("um_glm_n2560_RAL3p3", "PT1H", 1)                               # which copy each site would read
km_scale.search(experiment="dyamond3-p4k")
```

## HK25 vs HK27 layout

HK25 has one store per zoom, so assets here are keyed `<freq>.z<zoom>` (e.g. `PT1H.z8`), with `km_scale:zoom`.
HK27 stores will hold zoom groups, so assets would be keyed `<freq>` and list their refinement levels. That also
shrinks the STAC: here it's 6.2 MB, because each zoom's asset repeats its datacube.

## STAC extensions used (as of 2026-11-26)

From `EXT` in `build_catalog.py` and where each Item's `stac_extensions` is set. Collections declare none.

| Extension | Where | How |
|---|---|---|
| alternate-assets v1.2.0 | every Item | Genuinely separate copies at other sites (NERSC path, Waterpark mirror, ...) are `alternate` entries keyed by site name. The default `href` is the online copy |
| zarr v1.1.0 | every Item | `zarr:consolidated`, `zarr:zarr_format` |
| datacube v2.3.0 | Items whose Zarr metadata could be read (797 of 1139 assets) | Per asset (one per frequency and zoom), from consolidated metadata. The HEALPix cell dimension is an additional dimension with `type: "healpix"`: our own convention |
| cf v1.0.0 | with datacube | `cf:standard_name`, `cf:cell_methods` on `cube:variables` |
| processing v1.3.0 | derived MCS-tracks Items (PyFLEXTRKR) only | |

**Not used:**
- **storage:** the design proposes `storage:schemes`/`storage:refs`, translated by the helper into fsspec
  options; not built yet. The prototype instead puts fsspec options in a custom `km_scale:storage_options`
  field on the asset or alternate, and endpoint overrides (e.g. JASMIN's internal endpoint) in the site table
  (`config/sites.yaml`).
- **auth:** nothing yet; all HK25 online stores are public.
- **dggs** (proposed extension): not used. `type: "healpix"` and the `healpix:*` fields proposed in the design stand
  in for it. It is the natural replacement once settled, alongside the Zarr DGGS convention.

**Custom `km_scale:*` fields:** `zoom`, `format`, `storage_options`, `sites`, `site_only`, `reachable`,
`product_type`, `experiment`, `experiment_inferred`, `source_id`, `domain`, `resolution`, `creators`, `references`,
`license_text`, `feature`.

## Results (2026-11-18)

- **It works end to end.**
  - 58 Items in 16 Collections, with 1139 assets (797 with datacube). All 86 Catalogs, Collections and Items
    validate against the core and extension schemas.
  - `index.json` is 76 kB.
  - `km_scale.open_dataset` opened a UM store from a laptop.
  - `get_url()` gave the JASMIN-internal URL for UK, the filesystem path for NERSC, the online copy when a site
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
  - 11 datasets' metadata time ranges don't match their stores' time coordinates (by more than a day). Seven are UM v5
    runs (e.g. `um_SEA_km4p4_RAL3P3_n1280_GAL9_nest`: the metadata ends 2021-02-26, the data runs to 2021-04-01); the
    others are `arp-gem-1p3km`, `casesm2_10km_nocumulus`, `icon_d3hp003aug` and `icon_d3hp003feb`.
- **The experiment can't be inferred reliably.** HK25 has no experiment field (`experiment_id: hackathon`
  everywhere). Dates and names give a guess, marked `km_scale:experiment_inferred` on each Item. Several runs start
  on 1 Jan 2020, not on the DYAMOND3 start date. Producers need to set the experiment (the vocabulary plan).
- **Variable names differ across centres, and the matrix makes it obvious.** IFS uses GRIB short names (`2t`, `msl`,
  `10u`, `tp`) where others use CMIP names (`tas`, `psl`, `uas`, `pr`), and IMERG uses `precipitation`. A Tier 1
  coverage check would flag them at once.
- **A spec wrinkle:** the cf extension README allows `cf:cell_methods` as a plain string, but its v1.0.0 schema only
  accepts an array.

## Lessons from building it

**Source catalogue (HK25 Intake):**
- `urlpath` templates use full Jinja, including `{% with time_map = {...} %}` lookup tables. Rendering them with
  `jinja2.Template(...).render(**params)` for every allowed combination reproduces Intake exactly: 1931
  combinations across all nodes, with no rendering errors.
- `urlpath` lists mean "open these together": a static store as the second URL (UM v5), or 2D and 3D kerchunk
  parts (IFS). Each element needs its own asset (`static.z9`, `..._part2`).
- Intake parameters are independent lists, so an entry advertises the full cross product even when only some
  combinations exist. STAC assets list only what exists; probing every store is what exposes the gap.
- Parameter order varies, and zoom ranges differ per node (NERSC's copy of `um_glm_n2560_RAL3p3` has no z0). The
  resolver has to fall back to the online copy per asset, not per dataset.

**STAC schemas (validate early; the READMEs aren't enough):**
- datacube: vertical (`axis: z`) and additional dimensions need `values` or `extent`, so count alone fails.
  A custom `type: "healpix"` is accepted as an additional dimension.
- cf v1.0.0: `cf:cell_methods` must be an array, although the README shows a plain string.
- Collection `summaries` can't contain empty lists.
- An Item linked from a `by-experiment/` view is reached twice when walking the tree, so the validator has to
  deduplicate by id (each Item has one `parent`, but views add more links to it).
- `datetime: null` needs `start_datetime` and `end_datetime`. Items without a time range need a placeholder,
  flagged in `problems.txt`.

**Reading stores:**
- Fetching `.zmetadata` (v2) or `zarr.json` (v3) directly over HTTPS is enough for variables, units, standard
  names, dimensions and shapes: 930 stores in a few seconds with 48 threads. Coordinate values (levels, first and
  last time) need a real open: `xr.open_zarr` with zarr 3, on one store per frequency (87 opens).
- zarr 2 (`numcodecs`) failed to build under uv's default Python 3.14. Use zarr 3, which reads v2 stores fine,
  and pin Python <3.14 for now.
- float32 coordinates need `float(str(x))`, or the JSON carries noise (0.05000000074505806).
- Grid-mapping variables (`crs`) show up as data variables. Mark them `auxiliary` (no time dimension) and leave
  them out of the search index.
- HK25 UM stores use the dimension name `healpix_index`; HK27 will use `cell` with `standard_name = healpix_index`.

**Metadata:**
- Experiment can't be inferred: a "covers the DYAMOND3 period" rule tags 33 runs, but some start on 1 Jan 2020 and
  observations have no experiment at all. Only simulations get one, marked `km_scale:experiment_inferred`.
- Licence texts are free-form: the UM's "Crown Copyright … Non-Commercial Research Use only" maps to `other` and
  needs a `license` link; 27 datasets have none.

**Practical:**
- The README serves the page on port 8793; any free port works.
- The page needs HTTP (it fetches `index.json`), not `file://`.

## Licence

BSD 3-Clause (`LICENSE`). The catalogue metadata is generated from the HK25 Intake catalogue
(https://github.com/digital-earths-global-hackathon/catalog, BSD 3-Clause, © 2025 digital-earths-global-hackathon)
and from the data stores' own metadata. The datasets keep their own licences, as recorded on each Item.
