# Known issues and release blockers

This document records problems observed in the current repository. It does not
claim that the electrical design or scientific method has been fully reviewed.

## Plotting altitude mismatch

`pd_build_orbit_cache.py` produces `alt_km`, but `Help_Functions_PD.py`
requires `alt` and attempts to access `row.alt`. The intended joined output
therefore does not satisfy the plotting helper's schema.

This requires a code decision: either standardize on `alt_km` throughout or
rename it to `alt` while clearly preserving kilometre units. Code changes are
outside the documentation/reorganization change represented here.

## Missing reproducible environments

- No Python dependency or lock file is present.
- No supported Raspberry Pi OS/Python versions are recorded.
- No Arduino RP2040 core/toolchain version is recorded.
- No automated tests or hardware-in-the-loop checks are present.
- No CI workflow validates Python syntax or documentation links.

## KiCad portability

- Custom `SamacSys_Parts` and `Payload` libraries are not included as
  project-local libraries.
- Several 3D models refer to absolute Windows paths.
- The repository already contains tracked `.kicad_prl`, `fp-info-cache`, lock,
  and automatic-backup files. These are local/generated artifacts and may
  create noisy changes or disclose workstation-specific state.
- KiCad ERC and DRC reports are not included.

## Naming and stale references

- `MCPleves.txt` likely means `MCP_levels.txt`. It cannot be renamed without
  changing three acquisition scripts that reference it.
- Comments mention `pd_build_orbit_cache_v2.py`, which is not in the repository.
- The A-only and B-only usage messages mention filenames ending in `_only.py`,
  but the committed scripts are `read_pd_A.py` and `read_pd_B.py`.
- Two identical `pulse_counter.pio` files exist, and the Arduino sketch embeds
  its PIO instructions rather than importing either one.

## Threshold inconsistency

The primary acquisition scripts load 0.45, 1.0, 1.55, and 2.1 V from
`MCPleves.txt`. The live diagnostic `read_particle_counter.py` instead programs
0.5, 1.5, 2.5, and 3.5 V. Measurements must record which program and thresholds
were used.

## Missing project information

The repository still needs:

- an approved hardware revision and validation status;
- a BOM with manufacturer part numbers and substitutions;
- assembly photographs and connector-orientation diagrams;
- a detector calibration procedure and calibration data;
- representative raw and processed example data;
- expected plots for a known dataset;
- operating limits and electrical safety notes;
- contributor/citation information; and
- an explicit software/hardware/documentation license.

## Recommended release gate

Before labeling a version build-ready:

1. update each PCB from its authoritative schematic;
2. run and archive ERC/DRC results;
3. build and bench-test both boards;
4. pin and test the Pico and Raspberry Pi environments;
5. resolve the altitude schema mismatch;
6. run a complete acquisition-to-plot test with sample data;
7. add BOM, calibration, and expected results; and
8. tag the exact tested hardware, firmware, and software revision together.
