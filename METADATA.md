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

| Field | Preferred key | Accepted alternates | Goes to | Notes |
|---|---|---|---|---|
| Title | `title` | none | Item `title` | Only if the source's title is just the id |
| Time range | `time_coverage_start`, `time_coverage_end` | none | `start_datetime`, `end_datetime` | Only if the source has no range. Failing both, the build reads the time coordinate |
| Description | `summary` | `description` | `description` |  |
| Creators | `creator_name` | `creator` | `km_scale:creators` |  |
| References | `references` | `reference` | `km_scale:references` | DOIs in it are shown as links |
| Source | `source` | none | `km_scale:source` |  |
| Acknowledgement | `acknowledgment` | `acknowledgement` | `km_scale:acknowledgment` | ACDD's spelling |
| Version | `product_version` | `version`, `processing_version` | `km_scale:version` | UM's `processing_version` may be a pipeline version rather than the dataset's |
| Simulation name | `simulation` | none | `km_scale:simulation` | Our own key (UM) |
| Producer | `institution` | none | `providers` (role `producer`) |  |
| Licence | `license` | none | `km_scale:license_text` | Kept only when the Item's licence is `other`. Ideally an SPDX id such as `CC-BY-4.0` |
| DOI | `doi` | `DOI` | `sci:doi` and a `cite-as` link | Our own key; the bare DOI, not a URL |
| Documentation | `documentation_url` | `Documentation`, `documentation` | an `about` link | Our own key |
| Footprint | `geospatial_lat_min`, `geospatial_lat_max`, `geospatial_lon_min`, `geospatial_lon_max` | `regional_bounds`, `bounds` | `bbox` and `geometry` | Alternates are a dict with `lower_left_lat`, `lower_left_lon`, `upper_right_lat`, `upper_right_lon`. Longitudes in 0–360 are converted to −180–180 |
| Regional flag | none | `regional` | `km_scale:domain: regional` | Read by the footprint rule. Prefer deriving it from the footprint; a footprint covering all longitudes (e.g. IMERG's 60°S–60°N band) stays global |

### Grid mapping and structure (per store)

| Field | Preferred key | Accepted alternates | Goes to | Notes |
|---|---|---|---|---|
| Grid type | `grid_mapping_name: healpix` | none | detects a HEALPix grid | On the grid-mapping (`crs`) variable |
| Refinement level, indexing scheme | `refinement_level` | `healpix_nside` | `healpix:refinement_level`, `healpix:indexing_scheme` on the asset | Also `indexing_scheme: nested` (alternate `healpix_order: nest` or `nested`), normalised to `nested` or `ring`. The level is checked against the zoom in the store's name |
| Ellipsoid | `reference_ellipsoid_name` | `earth_radius` | not read yet | **Should be required for HK27**: its output is to be on the ellipsoidal HEALPix grid. `earth_radius` for a sphere |
| Extra software | none | none | `km_scale:requires` on the asset | From the codecs the arrays use: `gribscan.rawgrib` (IFS stores referencing GRIB) needs gribscan |
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

`refinement_level` and `indexing_scheme` are what the newer UM stores already write. `healpix_nside` and
`healpix_order` are accepted because every other store uses them.

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
