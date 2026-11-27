# Store attributes the catalogue reads: first draft (27 Nov 2026)

**A draft for comment, not an agreed standard.** This lists the attributes in a data store (Zarr global attributes, and
the grid-mapping variable) that the catalogue build reads, which name each should preferably use, and which other
names are accepted for now. It is meant as a starting point for HK27's list of required attributes, so that producers
can write what the catalogue needs and the catalogue can be generated from the stores rather than typed in.

Preferred names follow [ACDD 1.3](https://wiki.esipfed.org/Attribute_Convention_for_Data_Discovery_1-3) and
[CF](https://cfconventions.org/) where they have a name. Where neither does, the preferred name is our own choice and
is marked *(ours)*.

**How the build uses them** (`build_catalog.py`, `STORE_KEYS`):
- The Intake catalogue's metadata wins where it has a value; the store fills only what is missing.
- The preferred name is tried first, then the alternates in order. A value that is a known placeholder (`UNSET`,
  `Created by xios`, `NICAM data output`, empty) counts as missing.
- Each Item lists what was filled from the store in `km_scale:from_store` (e.g. `bbox <- regional_bounds`).
- `problems.txt` lists every dataset whose store uses an alternate name, with the preferred one, so producers can see
  what to change.

Counts are from a sample of the HK25 online stores: one store per frequency for each dataset, 87 readable stores from
41 datasets.

## Dataset-level attributes

| Catalogue field | Preferred key | Accepted alternates | Seen in HK25 (datasets) | Goes to |
|---|---|---|---|---|
| Title | `title` (ACDD) | none | 6, mostly placeholders | Item `title`, only if the Intake title is just the id |
| Description | `summary` (ACDD) | `description` | 13 `summary`, 5 `description` | Item `description` |
| Producer | `institution` (CF, ACDD) | none | 2 | `providers` (role `producer`) |
| Creators | `creator_name` (ACDD) | `creator` | 3 `creator` | `km_scale:creators` |
| Source | `source` (CF, ACDD) | none | 4 | `km_scale:source` |
| References | `references` (CF, ACDD) | `reference` | 1 each | `km_scale:references` (DOIs shown as links) |
| Acknowledgement | `acknowledgment` (ACDD spelling) | `acknowledgement` | 3 | `km_scale:acknowledgment` |
| DOI | `doi` *(ours)* | `DOI` | 1 (`DOI`) | `sci:doi` (scientific extension) and a `cite-as` link |
| Documentation | `documentation_url` *(ours)* | `Documentation`, `documentation` | 1 (`Documentation`) | an `about` link |
| Version | `product_version` (ACDD) | `version`, `processing_version` | 1 `version`, 13 `processing_version` | `km_scale:version` |
| Licence | `license` (CF, ACDD), ideally an SPDX id such as `CC-BY-4.0` | none | 1 (`CC-BY-NC-SA 4.0`, not an SPDX id) | `km_scale:license_text` when the Item's licence is `other` |
| Time range | `time_coverage_start`, `time_coverage_end` (ACDD) | none | 0 | `start_datetime`, `end_datetime` when the metadata lacks them. Failing that, the build reads the time coordinate |
| Footprint | `geospatial_lat_min`, `geospatial_lat_max`, `geospatial_lon_min`, `geospatial_lon_max` (ACDD) | `regional_bounds` or `bounds`: a dict with `lower_left_lat`, `lower_left_lon`, `upper_right_lat`, `upper_right_lon` | 1 ACDD (IMERG), 13 `regional_bounds`, 7 `bounds` | `bbox` and `geometry`. Longitudes in 0–360 are converted to −180–180. A band covering all longitudes becomes −180 to 180 |
| Regional flag | none: derive it from the footprint | `regional` (`True`) | 21 | `km_scale:domain: regional`, unless the footprint covers all longitudes (e.g. IMERG's 60°S–60°N band stays global) |
| Simulation name | `simulation` *(ours)* | none | 20 (UM) | `km_scale:simulation` |

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

## Grid mapping (the `crs` variable)

| Field | Preferred attribute | Accepted alternates | Seen in HK25 (stores) | Goes to |
|---|---|---|---|---|
| Grid type | `grid_mapping_name: healpix` | none | 83 of 87 | detects a HEALPix grid |
| Refinement level | `refinement_level` | `healpix_nside` (level = log2 nside) | 26 `refinement_level`; 83 `healpix_nside` | `healpix:refinement_level` on the asset; checked against the zoom in the store's name |
| Indexing scheme | `indexing_scheme: nested` | `healpix_order: nest` or `nested` | 26 `indexing_scheme`; 83 `healpix_order` (both spellings) | `healpix:indexing_scheme` on the asset, normalised to `nested` or `ring` |
| Ellipsoid | `reference_ellipsoid_name` (CF), or `earth_radius` for a sphere | none | 0 | not read yet. **Should be required for HK27**, since HK27 output is to be on the ellipsoidal HEALPix grid |

`refinement_level` and `indexing_scheme` are what the newer UM stores already write. `healpix_nside` and
`healpix_order` are accepted because every other store uses them.

## Read from the store's structure, not its attributes

- **Codecs:** an asset whose arrays use the `gribscan.rawgrib` codec (IFS stores that reference GRIB messages) gets
  `km_scale:requires: ["gribscan"]`. `xr.open_zarr` fails on these without gribscan installed.
- **Already read before this draft:** variables, units, `standard_name`, `long_name`, `cell_methods`, dimensions, and
  the time and vertical coordinates (datacube and cf extensions).

## Deliberately not copied

- **`history`, file paths (`initial_file`, `map_file`, `name`), user names (`logname`), host names, and tool versions
  (`CDI`, `CDO`, `NCO`)**: provenance for the producer, but noise in a catalogue, and sometimes personal.
- **`contact` and `creator_email`**: the catalogue doesn't publish personal email addresses. A project or institutional
  contact URL would be better.
- **`Conventions`**: worth checking against (e.g. require CF-1.x), but not useful as a catalogue field.
- **Model- or tool-specific attributes** such as `DOMAIN_*` (XIOS), GRIB keys, `hiopy::*` and `STASH`.
- **`latitiude_convention` and `longitude_convention`** (sic, UM): superseded by stating the footprint in −180 to 180.
