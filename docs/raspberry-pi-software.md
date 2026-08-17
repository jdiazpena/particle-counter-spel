# Raspberry Pi software

Software directory: [`software/raspberry-pi`](../software/raspberry-pi)

The software has three stages: acquire counter snapshots, attach orbital
position to each timestamp, and produce geographic/magnetic plots.

## Platform assumptions

The acquisition programs assume:

- a Raspberry Pi with I2C bus 1 enabled;
- Pico I2C slave address `0x17`;
- MCP4728 DAC address `0x60` on the same bus;
- permission to access `/dev/i2c-1`; and
- writable `~/Documents/PD` and `~/Documents/PD_post` directories.

The code imports the following non-standard Python packages:

| Purpose | Packages/modules |
|---|---|
| I2C acquisition | `smbus2`, Adafruit Blinka (`board`), `adafruit_mcp4728` |
| Tables/numerics | `numpy`, `pandas` |
| Orbit propagation | `sgp4`, `astropy` |
| Mapping | `matplotlib`, `geopandas`, `shapely`, `cartopy`, `aacgmv2` |

No supported OS image, Python version, or dependency lock file is currently
provided. Install these in a virtual environment appropriate to the selected
Raspberry Pi OS, then record the tested versions before deployment.

## Threshold configuration

[`MCPleves.txt`](../software/raspberry-pi/MCPleves.txt) contains exactly four
threshold voltages, one per line. The current values are:

```text
0.45
1.0
1.55
2.1
```

The A and B acquisition scripts use this file and apply the same four DAC
thresholds to both detectors. Values must remain between 0 and 4.096 V.

`read_particle_counter.py` is an older diagnostic exception: it uses hardcoded
0.5, 1.5, 2.5, and 3.5 V thresholds instead of the file.

## Acquisition programs

Run commands from `software/raspberry-pi` so local configuration and helper
imports are easy to find.

### Both detectors

```bash
python3 read_pd_AB.py TOTAL_TIME_S INTEGRATION_TIME_S
```

For example, the following requests ten minutes of data in one-second
integration windows:

```bash
python3 read_pd_AB.py 600 1
```

It writes all eight channel deltas to a uniquely named
`~/Documents/PD/PD_AB_*.csv` file. Each row is flushed and synchronized to
storage.

### Detector A only

```bash
python3 read_pd_A.py TOTAL_TIME_S INTEGRATION_TIME_S
```

This saves only A1–A4 as `PD_A_only_*.csv`.

### Detector B only

```bash
python3 read_pd_B.py TOTAL_TIME_S INTEGRATION_TIME_S
```

This saves only B1–B4 as `PD_B_only_*.csv`.

### Live diagnostic

```bash
python3 read_particle_counter.py
```

This continuously prints cumulative totals and one-second deltas. It does not
write CSV data and uses its own hardcoded DAC thresholds. Stop it with
`Ctrl+C`.

## Orbit-position processing

[`pd_build_orbit_cache.py`](../software/raspberry-pi/pd_build_orbit_cache.py)
uses hardcoded directories:

| Path | Purpose |
|---|---|
| `~/Documents/PD` | Input `PD*.csv` measurement files |
| `~/TLE` | Input two-line element catalog files |
| `~/TLE/finals2000A.all` | Optional offline Earth-orientation data |
| `~/Documents/PD_post` | Cache, joined output, and runtime report |

Run:

```bash
python3 pd_build_orbit_cache.py
```

The program accepts TLE files containing either two-line pairs or a satellite
name followed by a two-line pair. For each measurement timestamp it selects
the nearest TLE epoch, propagates with SGP4, transforms TEME coordinates to an
Earth-fixed position, and stores latitude, longitude, and altitude.

The cache avoids repeating propagation unless a timestamp is new, its position
is missing, or an updated TLE catalog changes the nearest TLE.

Expected outputs are:

- `pd_orbit_cache.csv`;
- `pd_measurements_with_position.csv`; and
- `pd_orbit_cache_runtime.txt`.

## Plotting

[`plot_pd_particles.py`](../software/raspberry-pi/plot_pd_particles.py) expects
`~/Documents/PD_post/pd_measurements_with_position.csv`, builds an AACGM
magnetic-coordinate cache, and writes PNG figures under
`~/Documents/PD_post/figures_PD`.

Intended command:

```bash
python3 plot_pd_particles.py
```

The current producer writes `alt_km`, while the plotting helper expects `alt`.
Consequently this step is known to fail without a separately authorized code
fix or a manually adapted input table. See [Known issues](known-issues.md).

The plots include geographic coordinates, AACGM magnetic coordinates,
magnetic footpoints, day/night magnetic-local-time subsets, cumulative
threshold products, and approximate threshold-difference bins.
