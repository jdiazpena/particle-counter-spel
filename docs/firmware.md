# Raspberry Pi Pico firmware

Firmware directory:
[`firmware/pico-particle-counter`](../firmware/pico-particle-counter)

The Arduino sketch uses the RP2040 PIO blocks to count pulses on eight inputs.
Four state machines on PIO0 count detector A, and four on PIO1 count detector
B. Interrupt handlers increment one 32-bit software counter per channel.

## Pin mapping

| Counter index | Channel | Pico GPIO | PIO/state machine |
|---:|---|---:|---|
| 0 | A1 | GP22 | PIO0 SM0 |
| 1 | A2 | GP21 | PIO0 SM1 |
| 2 | A3 | GP20 | PIO0 SM2 |
| 3 | A4 | GP19 | PIO0 SM3 |
| 4 | B1 | GP6 | PIO1 SM0 |
| 5 | B2 | GP8 | PIO1 SM1 |
| 6 | B3 | GP10 | PIO1 SM2 |
| 7 | B4 | GP12 | PIO1 SM3 |
| — | I2C SDA | GP4 | `Wire` slave interface |
| — | I2C SCL | GP5 | `Wire` slave interface |

The firmware disables internal pulls on all pulse inputs. The external circuit
must therefore provide valid logic levels and must not leave inputs floating.

## Counted event

Each PIO state machine performs this sequence:

```text
wait until input is low
wait until input is high
raise an interrupt and wait until it is cleared
repeat
```

One low-to-high transition is counted. A signal must return low before a later
pulse can be counted.

## I2C protocol

The Pico acts as an I2C slave:

| Property | Value |
|---|---|
| Address | `0x17` |
| SDA | GP4 |
| SCL | GP5 |
| Read length | 32 bytes |
| Payload | eight little-endian unsigned 32-bit totals |
| Channel order | A1, A2, A3, A4, B1, B2, B3, B4 |

The Raspberry Pi acquisition programs subtract successive snapshots using
modulo-2^32 arithmetic, so a single counter rollover is handled correctly.
The protocol has no command byte, version field, checksum, reset command, or
timestamp; the host timestamps each received snapshot.

## Source files

- [`pico_particle_counter.ino`](../firmware/pico-particle-counter/pico_particle_counter.ino)
  is the active Arduino sketch. It embeds the three PIO instructions directly.
- [`pulse_counter.pio`](../firmware/pico-particle-counter/pulse_counter.pio)
  is the readable PIO source representation.
- [`data/pulse_counter.pio`](../firmware/pico-particle-counter/data/pulse_counter.pio)
  is currently an identical duplicate. The sketch does not import either PIO
  file.

## Building and flashing

The repository does not yet pin an Arduino RP2040 core or toolchain version.
Until a tested version is recorded, use an Arduino environment that provides:

- `Arduino.h` and `Wire.h` for an RP2040/Pico target; and
- the Raspberry Pi Pico SDK hardware headers used by the sketch, including
  PIO, IRQ, GPIO, synchronization, and PIO instruction helpers.

Select the exact Raspberry Pi Pico target, compile the sketch, upload it over
USB, and confirm that the built-in LED produces a short flash approximately
once per second. Then verify I2C address `0x17` from the Raspberry Pi before
connecting live comparator outputs.

Record the tested board package, version, compiler, upload command, and Pico
model here when a reproducible firmware build is established.
