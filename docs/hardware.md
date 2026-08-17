# Hardware

The hardware is divided into an analog photodiode front end and a combined
comparator, threshold-DAC, power-control, and Pico interface board. Both are
KiCad 9 projects.

## Analog front end

Project directory: [`hardware/analog-front-end`](../hardware/analog-front-end)

The current design contains:

- one Hamamatsu S1223-01 photodiode (`D1`);
- a dual operational-amplifier stage (`IC1`);
- a REF3012 voltage reference (`U1`);
- transimpedance/filter/gain components;
- internal signals `OUTA` and `OUTB` and the connector output `OUT`;
- 5 V power and ground connections; and
- a routed two-layer, 1.6 mm PCB with 32 footprints.

The PCB connector mapping below is extracted from the current
`PC_Interstage.kicad_pcb` file. It is not a substitute for resolving the
schematic/PCB revision conflict.

| Connector | Pin 1 | Pin 2 | Pin 3 | Pin 4 |
|---|---|---|---|---|
| J1, J7, J8, J9 | GND | 5V0 | OUT | GND |
| J6 | GND | 5V0 | OUT | GND |
| J2, J3, J4, J5 | GND | — | — | — |

The schematic and PCB disagree on ten fitted values, including the op amp.
See [Known issues](known-issues.md#analog-front-end-revision-conflict).

## Comparator and Pico interface

Project directory:
[`hardware/comparator-pico-interface`](../hardware/comparator-pico-interface)

The board contains:

- two LM339 quad comparators (`U5`, `U6`);
- one MCP4728 four-channel threshold DAC (`U7`);
- one Raspberry Pi Pico module (`A1`);
- separate particle-detector and camera power switching;
- AP2112K 3.3 V regulators and TPS22917 load switches;
- two analog inputs, `PC_AO1` and `PC_AO2`;
- comparator outputs `A1`–`A4` and `B1`–`B4`; and
- a routed four-layer, 1.6 mm PCB.

The current schematic and PCB have matching component references and values.
This does not constitute ERC, DRC, or physical validation.

### Functional connections

| Function | Current PCB connection |
|---|---|
| Analog input A | J2 pin 2, `PC_AO1` |
| Analog input B | J3 pin 2, `PC_AO2` |
| Comparator A outputs | J12 pins 4, 3, 2, 1 = A1, A2, A3, A4 |
| Comparator B outputs | J13 pins 4, 3, 2, 1 = B1, B2, B3, B4 |
| DAC thresholds | J9 pins 2–5 = REFA, REFB, REFC, REFD |
| Raspberry Pi I2C | `RPI_SDA`, `RPI_SCL` |
| Pico supply | `5V_PC` to Pico VSYS |

### Main 12-pin interface connector

The current `J1` PCB mapping is:

| Pin | Signal | Pin | Signal |
|---:|---|---:|---|
| 1 | GND | 7 | CAM_Switch |
| 2 | AGND | 8 | 3V3 |
| 3 | AGND | 9 | RPI_SDA |
| 4 | 5V0_IN | 10 | RPI_SCL |
| 5 | 5V0_IN | 11 | 5V0_IN |
| 6 | PD_Switch | 12 | GND |

Confirm connector orientation and pin-one markings in KiCad before wiring.

## KiCad file roles

Each project contains:

| Extension/name | Purpose | Version-control guidance |
|---|---|---|
| `.kicad_sch` | Editable electrical schematic | Track |
| `.kicad_pcb` | Board layout, footprints, routing, and outline | Track |
| `.kicad_pro` | Project and design-rule settings | Track |
| `.kicad_prl` | User-local editor/session state | Do not add new copies |
| `fp-info-cache` | Generated footprint-library cache | Do not add new copies |
| `*-backups/` | KiCad automatic working backups | Prefer tagged releases instead |
| `*.lck` | Temporary editor lock | Never track |

## External libraries and models

The designs use custom `SamacSys_Parts` and `Payload` libraries. Footprint
geometry already placed on a PCB is embedded in the board file, but editing or
re-associating some parts may require the original libraries. Several 3D model
references use absolute Windows paths under `D:\JMDP\...`; these models will
not render on another machine until the paths or libraries are configured.

Before calling a revision reproducible, collect the custom symbols,
footprints, and redistributable 3D models into project-local libraries and
record the exact KiCad version used.

## Manufacturing checklist

Before ordering boards:

1. Select and record the authoritative analog-front-end revision.
2. Synchronize schematic symbols, values, and PCB footprints.
3. Confirm op-amp stability, photodiode polarity, feedback values, and supply
   range from component datasheets.
4. Verify every connector pinout and mating-part orientation.
5. Run KiCad ERC and DRC with KiCad 9.
6. Generate and inspect Gerbers, drill files, position files, and the BOM.
7. Record a hardware revision identifier on both the PCB and documentation.
8. Bench-test power rails and threshold voltages before installing detectors.
