# SUCHAI Particle Counter

This repository collects the hardware designs, Raspberry Pi Pico firmware, and
Raspberry Pi acquisition/postprocessing software used to build and operate a
prototype particle counter.

> **Project status:** prototype and research use. The repository is not yet a
> build-ready release. The plotting pipeline has a known altitude-column
> mismatch, and reproducible build/test environments have not yet been
> recorded. Review [Known issues](docs/known-issues.md) before manufacturing
> hardware or processing measurements.

## System overview

```text
S1223-01 photodiode
    -> analog front end
    -> four thresholds per detector (A and B)
    -> Raspberry Pi Pico pulse counters
    -> I2C
    -> Raspberry Pi Zero 2 acquisition
    -> CSV measurements
    -> TLE orbit propagation
    -> geographic and magnetic plots
```

The comparator board produces eight digital channels. `A1` through `A4` are
the four cumulative threshold outputs for detector A; `B1` through `B4` are
the corresponding outputs for detector B. The Pico counts their rising edges
and exposes eight cumulative 32-bit counters to the Raspberry Pi over I2C.

## Repository layout

```text
hardware/
  analog-front-end/             Photodiode amplifier/interstage KiCad project
  comparator-pico-interface/    Comparator, DAC, power, and Pico KiCad project
firmware/
  pico-particle-counter/        RP2040/Arduino pulse-counter firmware
software/
  raspberry-pi/                 Acquisition, orbit processing, and plotting
docs/
  hardware.md                   Boards, connectors, and signal mapping
  firmware.md                   Pico behavior, pin mapping, and I2C protocol
  raspberry-pi-software.md      Acquisition and postprocessing programs
  data-format.md                Measurement columns and derived products
  known-issues.md               Software, reproducibility, and portability limits
```

## Documentation

- [Hardware and wiring](docs/hardware.md)
- [Pico firmware](docs/firmware.md)
- [Raspberry Pi software](docs/raspberry-pi-software.md)
- [Data format](docs/data-format.md)
- [Known issues](docs/known-issues.md)

## Typical workflow

1. Review the schematics, run KiCad ERC/DRC, and assemble and verify the analog
   front end and comparator/interface boards.
2. Flash the Pico with
   [`pico_particle_counter.ino`](firmware/pico-particle-counter/pico_particle_counter.ino).
3. Connect the Pico and MCP4728 to the Raspberry Pi I2C bus.
4. Set the desired threshold voltages in
   [`MCPleves.txt`](software/raspberry-pi/MCPleves.txt).
5. Record detector A, detector B, or both using the corresponding acquisition
   script in [`software/raspberry-pi`](software/raspberry-pi).
6. Add suitable TLE files and run the orbit-cache postprocessor.
7. After addressing the documented `alt_km`/`alt` issue, generate geographic
   and magnetic-coordinate plots.

Detailed commands, paths, dependencies, and output descriptions are in the
linked documents. There is currently no published voltage-to-particle-energy
calibration, so threshold-difference products must not be described as
calibrated energy bins.

## Contributing changes

Keep hardware, firmware, and software revisions traceable. When changing a
board, record whether the schematic or PCB was the starting authority, update
both, run KiCad ERC/DRC, and document the tested physical revision. Avoid
committing KiCad lock/session/cache files or Python bytecode.

## License

No license has been added yet. Until the project owners select one, the files
should not be assumed to grant permission for redistribution or reuse.
