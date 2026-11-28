# HK25 catalogue as STAC: a prototype for the HK27 catalogue

**Browse it:** https://markmuetz.github.io/hk25_stac_catalog_prototype/

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
- **the whole STAC tree** (`stac.html`): every Catalog, Collection and Item, walked from `stac/catalog.json` by its
  links, with the first two levels open. Selecting a node shows its JSON in a collapsible viewer, also open to two
  levels; links to other STAC files in the JSON select that node.
- **store attributes as metadata:** where the Intake metadata is missing something, the build fills it from the
  stores' own attributes: description, creators, source, references, DOI, documentation link, version, regional
  footprint, and the HEALPix grid mapping. Which keys, their preferred names and the accepted alternates are in
  [METADATA.md](METADATA.md), a first draft for HK27's required attributes.
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
uv run --group dev pytest -q                                         # unit tests (no network)
uv run build_catalog.py --metadata-doc                               # regenerate METADATA.md's key tables
```

## Querying the whole catalogue: stac-geoparquet

The build also writes every Item to one [stac-geoparquet](https://github.com/stac-utils/stac-geoparquet) file,
`items.parquet` (~3 MB), one row per Item, so the catalogue can be queried with standard tools and no server:

```python
import duckdb
duckdb.sql("""
    select id, start_datetime, end_datetime
    from 'https://markmuetz.github.io/hk25_stac_catalog_prototype/items.parquet'
    where list_contains("km_scale:variables", 'pr') and list_contains("km_scale:frequencies", 'PT1H')
""")
```

**`assets.parquet`** (our own table, not a STAC convention) has one row per asset: dataset, frequency, zoom. HK25's
asset keys mix several things into the "frequency" (`PT1H_inst`, `3D_PT1H`, `P1D_part2`, `data`, `static`), so they
are split into `frequency`, `time_method`, `levels` and `part`. Where the key has no frequency (`data`), it is
inferred from the time axis and `frequency_inferred` is set (ERA5, JRA3Q, MERRA2 and CERES come out monthly, IMERG
half-hourly). Each row also has the variables, vertical dimensions, time range and steps, href and the sites with
copies, so "which stores have hourly pr" is one filter:

```python
duckdb.sql("""
    select id, max(zoom) from 'https://markmuetz.github.io/hk25_stac_catalog_prototype/assets.parquet'
    where frequency = 'PT1H' and list_contains(variables, 'pr') group by id
""")
```

In `items.parquet`, two differences from the JSON Items, because Arrow makes a column per dictionary key: each asset's
`cube:dimensions` and `cube:variables` are JSON text, and the Items gain flat `km_scale:variables`,
`km_scale:frequencies` and `km_scale:zooms` lists for querying (`km_scale:zooms` collects the assets'
`dggs:refinement_level`). Not yet checked: whether STAC Browser reads the file.

## An MCP server for agents (prototype)

`km_scale_mcp.py` lets an AI agent (Claude Code, an IDE assistant, OpenCode with a local model) search the catalogue
and get code to open a dataset at the user's site. It is read-only and runs locally over stdio: it loads
`items.parquet` and `assets.parquet` into in-memory DuckDB tables, and uses `km_scale` to choose the copy. No server
of ours.

```sh
claude mcp add km-scale -e KM_SCALE_USER_LOCATION=UK -- \
    uv run -q --directory /path/to/this/repo --group mcp python km_scale_mcp.py
```

| Tool | Does |
|---|---|
| `catalog_overview` | The vocabulary: experiments, product types, domains, frequencies, zooms, sites, common variables |
| `search_datasets` | Filter by variables, frequency, zoom (all in one store), experiment, product type, domain, model, text, a point, a period, a site |
| `find_assets` | Find stores by variables, frequency, time method, levels, zoom; finest zoom by default |
| `find_variable` | Map a quantity ("precipitation") to variable names, with each dataset's unit and frequencies |
| `describe_dataset` | One dataset: description, time, footprint, licence, citation links, assets and copies, variables |
| `how_to_open` | Which copy to read from the user's site, its URL, Python code, and what every other site would read |
| `query_catalog` | Read-only SQL on the `items` and `assets` tables, for anything else, with worked examples in its description. DuckDB can't read files or URLs from it |

Each tool call is appended to `~/.km_scale/mcp_log.jsonl` (tool, arguments, result count, error, time taken). It
stays on the user's machine; `KM_SCALE_MCP_LOG=off` turns it off. `KM_SCALE_CATALOG` points the server at another
build (default: the published site). `tests/test_mcp.py` calls each tool against a fresh build in CI.

## Validation

Store validation is [data-forge](https://github.com/km-scale/data-forge)'s job: its validator
(`scripts/validate_healpix_zarr.py`) decides which store attributes are required. This catalogue builds on top of it
and keeps no rules of its own for the stores. `validate.py` here checks only the STAC output. [METADATA.md](METADATA.md)
lists what the catalogue reads from the stores.

## Code layout

`build_catalog.py` is only the command line; the code is in `hk25_stac/`, in three stages (`pipeline.py`):

1. **Collect** (`hk25.py`): `Hk25Catalog` walks the Intake catalogue's per-site YAML; `Hk25Dataset` merges one id
   across sites; `Hk25Entry` renders one site's Jinja `urlpath`s for every parameter combination. Each dataset
   becomes an `ItemDraft` (`model.py`). Everything HK25-specific, including the guesses for product type, model and
   experiment, is in this module, so a store-driven HK27 source would replace only this.
2. **Probe** (`stores.py`, `rules.py`): a `Store` per asset (`ZarrStore` reads the consolidated metadata JSON
   directly, and coordinate values through xarray), then the **reading rules**. A `Rule` names a field, its
   preferred key, the accepted alternates and where the value goes. `KeyRule` covers most fields; subclasses handle
   those with logic (footprint, time range, DOI, title). `AssetRule`s read a store's structure (HEALPix grid mapping,
   codecs), and `DatasetCheck`s compare the metadata with what the data showed. The rules also generate
   [METADATA.md](METADATA.md)'s tables, so the documentation can't drift from the code.
3. **Write** (`stac_out.py`, `site.py`): the STAC tree with [pystac](https://github.com/stac-utils/pystac), then
   the search page's files. New kinds of store (kerchunk references, Parquet track tables) would be further `Store`
   subclasses; new fields, further rules.

**Links are relative, with no self links** (pystac's `SELF_CONTAINED`), so the same files work locally, on GitHub
Pages, or copied anywhere. STAC recommends absolute self links for published catalogues. Switching (tried, not
kept) takes, in `stac_out.write_stac`, `normalize_hrefs` with the site URL (`.../hk25_stac_catalog_prototype/stac`)
and `save(catalog_type=CatalogType.ABSOLUTE_PUBLISHED, dest_href=stac_dir)`. Also `site.tree`, which follows child links
on disk, would need to map the URL back to the local folder (a few lines). The pages and `km_scale` follow links as
given, so they need no change.
The `by-experiment/` views are written after pystac saves, as plain JSON: pystac would otherwise move or rewrite
Items reached by two paths.

`build/problems.txt` lists what the build found wrong with the source catalogue.

```python
import km_scale                                   # build/km_scale.py; KM_SCALE_CATALOG=<build dir or URL>
km_scale.get_url("um_glm_n2560_RAL3p3_tuned_hk26", "PT1H", 0, location="UK")   # JASMIN-internal URL, via the site table
ds = km_scale.open_dataset("um_glm_n2560_RAL3p3_tuned_hk26", "PT1H", 0)        # online copy; ds.attrs["km_scale_copy"]
km_scale.where("um_glm_n2560_RAL3p3", "PT1H", 1)                               # which copy each site would read
km_scale.search(experiment="dyamond3-p4k")
```

## HK25 vs HK27 layout

HK25 has one store per zoom, so assets here are keyed `<freq>.z<zoom>` (e.g. `PT1H.z8`), each with its own
`dggs:refinement_level`, as the DGGS extension recommends.

HK27 stores will hold zoom groups (`z0`…`zN` in one store, opened as a DataTree), so assets would be keyed `<freq>`.
For such a multiscale asset the DGGS extension says `dggs:refinement_level` is the **finest** level in it (e.g. 10),
and that the other levels are described in the file. That doesn't say which levels a store holds (all of 0–10, or
only some), so until [dggs#2](https://github.com/stac-extensions/dggs/issues/2) decides (a `dggs:refinement_levels`
list is being discussed), the asset would also carry our own `km_scale:refinement_levels` list, and the Collection
summary lists every level. Zoom groups also shrink the STAC: here it's 6.2 MB, because each zoom's asset repeats its
datacube.

## STAC extensions used (as of 2026-11-28)

From `EXT` in `hk25_stac/util.py`. `extensions()` in `hk25_stac/stac_out.py` sets each Item's `stac_extensions` from
the field names it actually uses. Collections declare only dggs (for their level summaries).

| Extension | Where | How |
|---|---|---|
| alternate-assets v1.2.0 | every Item | Genuinely separate copies at other sites (NERSC path, Waterpark mirror, ...) are `alternate` entries keyed by site name. The default `href` is the online copy, or the local path at the one site holding data with no online copy (`km_scale:site_only`). Local paths are `file://` URIs: a bare `/path` would be resolved against the catalogue's own URL. `km_scale` and the pages strip the scheme |
| zarr v1.1.0 | every Item | `zarr:consolidated`, `zarr:zarr_format` |
| datacube v2.3.0 | Items whose Zarr metadata could be read (797 of 989 assets) | Per asset (one per frequency and zoom), from consolidated metadata. The HEALPix cell dimension has `type: "dggs"`, `reference_system` (the OGC HEALPix URI) and `dggs:refinement_level`, as the DGGS extension describes; the `dggs` dimension type itself is still an open datacube PR ([#38](https://github.com/stac-extensions/datacube/pull/38)), so it validates as an additional dimension |
| dggs v0.1.0 (proposal) | HEALPix assets; Collection summaries | `dggs:dggrs: "HEALPix"`, `dggs:refinement_level` (the zoom, from the store's name; checked against the grid mapping), `dggs:indexing_scheme` (`nested`/`ring`, from the grid mapping), and a `dggrs-definition` link. Collections summarise the levels. The OGC HEALPix DGGRS that `dggs:dggrs` names is defined on the **WGS84 ellipsoid** with **its own textual zone ids**, so every HEALPix asset states `dggs:indexing_scheme` (`nested` unless the store says `ring`), and a spherical store differs from the definition: the extension then asks for the CRS in the projection fields, which isn't done yet (`km_scale:spherical` instead; see the note on the radius below the table). **The schema isn't published yet** (its URL is a 404): `validate.py` reads it from the extension's repository at a pinned commit |
| projection v2.0.0 | HEALPix assets whose store states an ellipsoid | `proj:code: EPSG:4326` for WGS 84, or `proj:projjson` built from the ellipsoid axes, as the DGGS extension asks for the figure of the Earth. No HK25 store states one, so none is written yet |
| cf v1.0.0 | with datacube | `cf:standard_name`, `cf:cell_methods` on `cube:variables` |
| processing v1.3.0 | derived MCS-tracks Items (PyFLEXTRKR); UM Items | `processing:software`; `processing:version` from the UM's `processing_version` (the HEALPix pipeline's version, not the dataset's) |
| scientific v1.0.0 | Items with a DOI, references or a citation | `sci:doi` plus a `cite-as` link; `sci:publications` from the references (one per DOI, with a `describedby` link; other URLs become `about` links; free text is one citation); HK25's `citation` field also goes to `sci:publications`: it names papers (model descriptions, the DYAMOND3 protocol), not how to cite the data. `sci:citation` ("how to cite the data") is left for HK27, which needs a data-citation attribute in its conventions |
| version v1.2.0 | Items whose store states a version (CERES) | `version`, from `product_version` or `version` |

**Spherical HK25 stores and the OGC definition:** the extension says a grid on a different figure from the DGGRS's ("e.g. HEALPix on a sphere") SHOULD give its CRS (`proj:code`/`proj:projjson`). The HK25 stores state no radius. On a sphere the radius doesn't move the cells in latitude and longitude, so a nominal sphere (e.g. R = 6 371 007 m, the GRS 1980 authalic sphere) would describe them correctly, but it is a value no store states. Not decided.

**Not used:**
- **storage** (v2, pilot): would carry nothing yet. Every href is `https://` or `file://`, which need no storage
  scheme, and no asset uses `km_scale:storage_options`. Adopt it when a store is given as `s3://` with a
  non-AWS endpoint (`custom-s3`, e.g. Waterpark's), with `storage:refs` on each copy. Site-internal routes (e.g.
  JASMIN's internal endpoint) stay in the site table (`config/sites.yaml`): they depend on where the user is,
  which the storage extension doesn't describe.
- **xarray-assets:** deprecated upstream ("too specific to xarray and Python"); zarr + storage + xpystac replace it.
- **auth:** nothing yet; all HK25 online stores are public.

**Custom `km_scale:*` fields:** `format`, `storage_options`, `sites`, `site_only`, `reachable`, `product_type`,
`experiment`, `experiment_inferred`, `source_id`, `domain`, `resolution`, `creators`, `license_text`, `feature`,
`time_from_data`, `time_unknown`, `source`, `acknowledgment`, `simulation`, `requires` (e.g. `["gribscan"]`),
`ellipsoid` (only for an ellipsoid name with no known EPSG code) and `spherical` (a HEALPix store that states no
figure of the Earth: a sphere of unstated radius, which no CRS field can express; all HK25 stores), and `from_store`
(which properties came from store attributes). Replaced on 28 Nov 2026 by standard fields: `zoom`
(`dggs:refinement_level`), `healpix:refinement_level` and `healpix:indexing_scheme` (dggs), `references`
(`sci:publications`), `version` (`version`, or `processing:version`), and `ellipsoid` where a CRS can be given
(projection).

## Results (2026-11-18)

**Since 27 Nov 2026, datasets whose stores are given by a glob are left out:** 13 HK25 datasets, all on node-local
paths (MPAS DYAMOND1–3, the SCREAM runs, WRF CONUS and South America, EarthWorks, `nicam_gl11_latlon`, `tracking`).
A glob is several stores, not one resource, so no STAC tool can open it. In HK27 each should be one store (pieces
concatenated, or as groups), or a virtual store over the pieces. A glob copy at another site (IR_IMERG at NERSC) is
left out the same way. Each is listed in `problems.txt`, and CI fails on any glob href. The catalogue is now 45 Items
in 13 Collections, 989 assets. The figures below are from before.

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
  - 27 datasets have no licence and 8 have no time range. For 5 of the 8 the build takes the range from the stores'
    time coordinates (`km_scale:time_from_data`); the other 3 are marked `km_scale:time_unknown` (Parquet tables, or
    stores whose metadata couldn't be read).
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
