# Measurement and processed data

## Raw measurement CSV

The acquisition scripts write one row per integration window.

### Common columns

| Column | Meaning | Unit/format |
|---|---|---|
| `unix_time` | Host time when the snapshot was read | Unix seconds, UTC |
| `iso_utc` | Human-readable host timestamp | ISO 8601 UTC |
| `t_s` | Elapsed monotonic time since acquisition start | seconds |

### Counter columns

Channel names encode detector, threshold number, and configured voltage. For
example, `A1_0.450V` is detector A at threshold 1 with a 0.450 V DAC setting.

An AB file contains eight count columns in this order:

```text
A1, A2, A3, A4, B1, B2, B3, B4
```

Values are counts observed during the integration window, not the Pico's raw
cumulative totals. The acquisition program computes:

```text
window_count = (new_total - previous_total) modulo 2^32
```

Threshold channels are cumulative discriminator products. A particle counted
above threshold 4 is normally also counted by thresholds 1, 2, and 3. Adding
all thresholds would therefore count the same event multiple times.

## Normalized count products

The orbit-cache postprocessor creates consistent columns even when an input
file contains only detector A or only detector B.

| Column | Definition |
|---|---|
| `count_A_thrN` | Detector A count at threshold N; zero if absent |
| `count_B_thrN` | Detector B count at threshold N; zero if absent |
| `thrN_total` | `count_A_thrN + count_B_thrN` |
| `particles_total` | `thr1_total` |
| `counts_total` | Backward-compatible alias of `particles_total` |
| `counts_A_total` | `count_A_thr1` |
| `counts_B_total` | `count_B_thr1` |
| `counts_raw_threshold_sum` | Sum of all four threshold totals; diagnostic only |
| `thresholdN_v` | Voltage parsed from the raw channel name |

`counts_raw_threshold_sum` must not be interpreted as a number of independent
particles.

## Approximate differential bins

The postprocessor derives:

```text
bin1 = max(thr1_total - thr2_total, 0)
bin2 = max(thr2_total - thr3_total, 0)
bin3 = max(thr3_total - thr4_total, 0)
bin4 = max(thr4_total, 0)
```

These are threshold intervals. They are not calibrated particle-energy bands
unless a detector-response and voltage-to-energy calibration is supplied.

## Provenance columns

| Column | Meaning |
|---|---|
| `detector_mode` | `A`, `B`, `AB`, or `UNKNOWN` |
| `source_file` | Original acquisition CSV path |
| `unix_time_key` | Unix timestamp normalized to six decimal places for joining |

The original raw channel columns are retained for debugging.

## Orbit columns

| Column | Meaning | Unit |
|---|---|---|
| `lat` | Geodetic latitude | degrees |
| `lon` | Geodetic longitude | degrees |
| `alt_km` | Geodetic altitude | kilometres |
| `jd` | Observation time | Julian date |
| `tle_epoch` | Epoch text from the selected TLE | TLE format |
| `tle_epoch_jd` | Selected TLE epoch | Julian date |
| `tle_file` | Source catalog path | text |
| `tle_hash` | SHA-1 identifier of the selected TLE pair | hexadecimal |
| `sgp4_error` | SGP4 status code | integer |
| `sgp4_error_text` | Description when propagation fails | text |

The plot helper currently expects `alt` rather than `alt_km`; this is a known
pipeline incompatibility, not a second documented altitude field.

## Plot-ready magnetic columns

The plotting helper is intended to add:

| Column | Meaning |
|---|---|
| `times` | Parsed UTC timestamp |
| `mlat` | AACGM magnetic latitude |
| `mlon` | AACGM magnetic longitude |
| `mlt` | Magnetic local time |
| `foot_lat`, `foot_lon` | Geographic coordinates of the magnetic footpoint |
| `period` | `1` for 06:00–18:00 MLT, `0` otherwise |

AACGM conversion can be undefined for some positions, especially near the
magnetic equator. Those rows are retained with missing magnetic coordinates.
