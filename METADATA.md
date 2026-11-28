# Store attributes the catalogue reads: first draft (27 Nov 2026)

**A draft for comment, not an agreed standard.** This lists the attributes in a data store (Zarr global attributes, and
the grid-mapping variable) that the catalogue build reads, which name each should preferably use, and which other
names are accepted for now.

**Validation belongs to [data-forge](https://github.com/km-scale/data-forge), and this catalogue builds on top of it.**
data-forge's validator (`scripts/validate_healpix_zarr.py`) is the gate every HK27 store passes, and it sets which
attributes are required or recommended. This file is not a second set of rules. It is the catalogue's reading list:
what the build reads, so the catalogue can be generated from the stores rather than typed in. Where the catalogue
needs something the validator doesn't yet require (e.g. `summary`, a regional footprint, experiment and model keys),
the aim is to ask for it to be added there.

Preferred names follow [ACDD 1.3](https://wiki.esipfed.org/Attribute_Convention_for_Data_Discovery_1-3) and
[CF](https://cfconventions.org/) where they have a name. Where neither does, the preferred name is our own choice, noted as "Our own key".

**How the build uses them** (the rules in `hk25_stac/rules.py`):
- The source catalogue's metadata (HK25 Intake) wins where it has a value. Store attributes fill only what is missing,
  and values read from the data (the time coordinate) fill what both lack.
- The preferred key is tried first, then the alternates in order. A value that is a known placeholder (`UNSET`,
  `Created by xios`, `NICAM data output`, empty) counts as missing.
- Each Item lists what was filled from the store in `km_scale:from_store` (e.g. `bbox <- regional_bounds`).
- `problems.txt` lists every dataset whose store uses an alternate key, with the preferred one, so producers can see
  what to change. `attribute_usage.json` (next to it on the site) counts how many datasets used each key.

## The keys

The tables between the markers are generated from the rules (`uv run build_catalog.py --metadata-doc`), and a test
fails if they drift. Edit the rules, not the tables.

<!-- generated from hk25_stac/rules.py: start -->
### Dataset-level attributes

| Field | Preferred key | Accepted alternates | Required by | Goes to | Notes |
|---|---|---|---|---|---|
| Title | `title` | none | data-forge: recommended | Item `title` | Only if the source's title is just the id |
| Time range | `time_coverage_start`, `time_coverage_end` | none | catalogue only | `start_datetime`, `end_datetime` | Only if the source has no range. Failing both, the build reads the time coordinate |
| Description | `summary` | `description` | catalogue only | `description` |  |
| Creators | `creator_name` | `creator` | catalogue only | `km_scale:creators` |  |
| References | `references` | `reference` | data-forge: recommended | `sci:publications`, and `about` links | A list of URLs gives one publication per DOI and an `about` link per other URL; other text is one citation |
| Source | `source` | none | data-forge: recommended | `km_scale:source` |  |
| Acknowledgement | `acknowledgment` | `acknowledgement` | catalogue only | `km_scale:acknowledgment` | ACDD's spelling |
| Version | `product_version` | `version` | catalogue only | `version` | The version extension's field |
| Processing version | `processing_version` | none | catalogue only | `processing:version` | The version of the processing chain (UM: the HEALPix pipeline), not of the dataset |
| Simulation name | `simulation` | none | catalogue only | `km_scale:simulation` | Our own key (UM) |
| Producer | `institution` | none | data-forge: recommended | `providers` (role `producer`) |  |
| Licence | `license` | none | data-forge: recommended | `km_scale:license_text` | Kept only when the Item's licence is `other`. Ideally an SPDX id such as `CC-BY-4.0` |
| DOI | `doi` | `DOI` | catalogue only | `sci:doi` and a `cite-as` link | Our own key; the bare DOI, not a URL |
| Documentation | `documentation_url` | `Documentation`, `documentation` | catalogue only | an `about` link | Our own key |
| Footprint | `geospatial_lat_min`, `geospatial_lat_max`, `geospatial_lon_min`, `geospatial_lon_max` | `regional_bounds`, `bounds` | catalogue only | `bbox` and `geometry` | Alternates are a dict with `lower_left_lat`, `lower_left_lon`, `upper_right_lat`, `upper_right_lon`. Longitudes in 0–360 are converted to −180–180 |
| Regional flag | none | `regional` | catalogue only | `km_scale:domain: regional` | Read by the footprint rule. Prefer deriving it from the footprint; a footprint covering all longitudes (e.g. IMERG's 60°S–60°N band) stays global |

### Grid mapping and structure (per store)

| Field | Preferred key | Accepted alternates | Required by | Goes to | Notes |
|---|---|---|---|---|---|
| Grid type | `grid_mapping_name: healpix` | none | data-forge: required | finds the grid mapping | On a grid-mapping variable (e.g. a scalar `crs`) |
| Refinement level | `refinement_level` | `healpix_level`, `zoom`, `healpix_nside` | data-forge: required | `dggs:refinement_level` and `dggs:dggrs: HEALPix` on the asset (DGGS extension) | Level from `healpix_nside` is log2(nside). The zoom in the store's name wins; a different level here is a problem. For a store holding several levels (HK27) it is the finest |
| Indexing scheme | `indexing_scheme: nest` | `healpix_order: nest` | data-forge: required | `dggs:indexing_scheme` on the asset (read with the level) | data-forge requires `nest`. The catalogue writes `nested` or `ring`, as xdggs does, and also reads `nested` (HK25 stores) |
| Ellipsoid | `reference_ellipsoid_name` | `semi_major_axis + inverse_flattening`, `semi_major_axis + semi_minor_axis` | data-forge: required | `proj:code` (WGS 84) or `proj:projjson` on the asset (projection extension); `km_scale:ellipsoid` for a name we can't map; `km_scale:spherical: true` if none is given | HK27 output is on the ellipsoidal HEALPix grid; data-forge reports a spherical grid as an error unless run with `--allow-spherical` |
| Extra software | none | none | catalogue only | `km_scale:requires` on the asset | From the codecs the arrays use: `gribscan.rawgrib` (IFS stores referencing GRIB) needs gribscan |
<!-- generated from hk25_stac/rules.py: end -->

**Preferred where there are alternates:**
- **Footprint: the four ACDD `geospatial_*` attributes.** They are a standard, flat (no nested dict to parse), and
  already used by IMERG. Write longitudes in −180 to 180, or say which convention is used. `regional_bounds` (newer UM
  stores) and `bounds` (older UM stores) are read for now.
- **Description: `summary`**, not `description`.
- **Creators: `creator_name`**, not `creator`.
- **References: `references`** (plural), as in CF and ACDD.
- **Version: `product_version`.** UM's `processing_version` (`v7`) is a processing-pipeline version. If that is what
  it means, it may deserve a field of its own rather than being read as the dataset's version.
- **DOI: `doi`**, the DOI on its own (`10.5067/...`), not a URL.

**Grid mapping: data-forge's names.** The grid rows follow data-forge's validator, which is what HK27 stores must
pass: the level as `refinement_level` (or `healpix_level`, `zoom`, or `healpix_nside`), the indexing scheme as
`nest` (in `indexing_scheme` or `healpix_order`), and an ellipsoid. HK25 stores mostly write `healpix_nside` and
`healpix_order`. The newer UM stores write `indexing_scheme: nested`, which the catalogue reads but data-forge's
validator rejects: HK27 stores should write `nest`. In the catalogue's own output the scheme is `nested` or `ring`,
as in xdggs.

The **Required by** column says whose rule it is: data-forge's validator (required or recommended), or only the
catalogue's need, to be raised with data-forge.

**Also read from the stores, before this draft:** variables, units, `standard_name`, `long_name`, `cell_methods`,
dimensions, and the time and vertical coordinates (datacube and cf extensions).

## Deliberately not copied

- **`history`, file paths (`initial_file`, `map_file`, `name`), user names (`logname`), host names, and tool versions
  (`CDI`, `CDO`, `NCO`)**: provenance for the producer, but noise in a catalogue, and sometimes personal.
- **`contact` and `creator_email`**: the catalogue doesn't publish personal email addresses. A project or institutional
  contact URL would be better.
- **`Conventions`**: worth checking against (e.g. require CF-1.x), but not useful as a catalogue field.
- **Model- or tool-specific attributes** such as `DOMAIN_*` (XIOS), GRIB keys, `hiopy::*` and `STASH`.
- **`latitiude_convention` and `longitude_convention`** (sic, UM): superseded by stating the footprint in −180 to 180.
