#!/usr/bin/env python3

import csv
import os
import sys
import time
import struct
from pathlib import Path
from datetime import datetime, timezone

from smbus2 import SMBus, i2c_msg

import board
import adafruit_mcp4728


# -----------------------------
# MCP4728 DAC SETTINGS
# -----------------------------

MCP4728_ADDR = 0x60

# Internal 2.048 V reference with gain = 2 gives 0 to 4.096 V
DAC_FULL_SCALE = 4.096
DAC_MAX_RAW = 4095

MCP_LEVELS_FILE = Path(__file__).with_name("MCPleves.txt")


def read_thresholds_from_file(path=MCP_LEVELS_FILE):
    values = []

    with open(path, "r") as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            values.append(float(line))

    if len(values) != 4:
        raise ValueError(f"{path} must contain exactly 4 voltage values, got {len(values)}")

    for v in values:
        if v < 0 or v > DAC_FULL_SCALE:
            raise ValueError(f"Voltage {v} V outside 0-{DAC_FULL_SCALE} V range")

    return tuple(values)


THRESHOLDS_V = read_thresholds_from_file()


def volts_to_raw(volts):
    if volts < 0 or volts > DAC_FULL_SCALE:
        raise ValueError(f"Voltage {volts} V outside 0-{DAC_FULL_SCALE} V range")

    return int(round((volts / DAC_FULL_SCALE) * DAC_MAX_RAW))


def set_mcp4728_thresholds(thresholds_v=THRESHOLDS_V):
    i2c = board.I2C()
    dac = adafruit_mcp4728.MCP4728(i2c, address=MCP4728_ADDR)

    channels = [
        dac.channel_a,
        dac.channel_b,
        dac.channel_c,
        dac.channel_d,
    ]

    for ch, voltage in zip(channels, thresholds_v):
        ch.vref = adafruit_mcp4728.Vref.INTERNAL
        ch.gain = 2
        ch.raw_value = volts_to_raw(voltage)

    print(
        "MCP4728 thresholds set: "
        f"A={thresholds_v[0]:.3f} V, "
        f"B={thresholds_v[1]:.3f} V, "
        f"C={thresholds_v[2]:.3f} V, "
        f"D={thresholds_v[3]:.3f} V"
    )


# -----------------------------
# PICO PARTICLE COUNTER SETTINGS
# -----------------------------

PICO_ADDR = 0x17
I2C_BUS = 1

CHANNELS = [
    "A1", "A2", "A3", "A4",
    "B1", "B2", "B3", "B4",
]

CHANNEL_LABELS = [
    f"A1_{THRESHOLDS_V[0]:.3f}V",
    f"A2_{THRESHOLDS_V[1]:.3f}V",
    f"A3_{THRESHOLDS_V[2]:.3f}V",
    f"A4_{THRESHOLDS_V[3]:.3f}V",
    f"B1_{THRESHOLDS_V[0]:.3f}V",
    f"B2_{THRESHOLDS_V[1]:.3f}V",
    f"B3_{THRESHOLDS_V[2]:.3f}V",
    f"B4_{THRESHOLDS_V[3]:.3f}V",
]


def read_pico_totals(bus):
    read = i2c_msg.read(PICO_ADDR, 32)
    bus.i2c_rdwr(read)

    data = bytes(read)

    if len(data) != 32:
        raise RuntimeError(f"Expected 32 bytes from Pico, got {len(data)}")

    return struct.unpack("<8I", data)


def compute_deltas(new_counts, old_counts):
    return tuple((new - old) & 0xFFFFFFFF for new, old in zip(new_counts, old_counts))


# -----------------------------
# FILE / PRINT HELPERS
# -----------------------------

OUTPUT_DIR = Path.home() / "Documents" / "PD"
HEADER_EVERY = 20


def make_output_file():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    start_utc = datetime.now(timezone.utc)
    stamp = start_utc.strftime("%Y%m%d_%H%M%S")

    base = f"PD_AB_{stamp}"

    for idx in range(10000):
        path = OUTPUT_DIR / f"{base}_{idx:03d}.csv"
        try:
            # Exclusive creation prevents overwrite even if the clock resets.
            with path.open("x", newline="") as f:
                pass
            return path
        except FileExistsError:
            continue

    raise RuntimeError("Could not create a unique output file after 10000 attempts")


def print_terminal_header():
    print(
        f"{'t_s':>8} "
        + " ".join(f"{label:>12}" for label in CHANNEL_LABELS)
    )


def format_terminal_row(iso_utc, elapsed_s, deltas):
    return (
        f"{elapsed_s:8.3f} "
        + " ".join(f"{v:12d}" for v in deltas)
    )


# -----------------------------
# MAIN LOOP
# -----------------------------

def main():
    if len(sys.argv) != 3:
        print("Usage:")
        print("  python3 read_pd_AB.py TOTAL_TIME_S INTEGRATION_TIME_S")
        sys.exit(1)

    total_time_s = float(sys.argv[1])
    integration_time_s = float(sys.argv[2])

    if total_time_s <= 0:
        raise ValueError("TOTAL_TIME_S must be > 0")

    if integration_time_s <= 0:
        raise ValueError("INTEGRATION_TIME_S must be > 0")

    output_file = make_output_file()

    print(f"Output CSV: {output_file}")
    print(f"Total measurement time: {total_time_s:.3f} s")
    print(f"Integration time: {integration_time_s:.3f} s")

    set_mcp4728_thresholds()

    csv_header = ["unix_time", "iso_utc", "t_s"] + CHANNEL_LABELS

    with SMBus(I2C_BUS) as bus, output_file.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(csv_header)
        f.flush()
        os.fsync(f.fileno())

        # First measurement is only the baseline for the first valid delta.
        old_counts = read_pico_totals(bus)

        start_mono = time.monotonic()
        end_mono = start_mono + total_time_s

        print_terminal_header()

        row_count = 0
        sample_index = 1

        while True:
            target_mono = start_mono + sample_index * integration_time_s

            if target_mono > end_mono + 1e-9:
                break

            sleep_s = target_mono - time.monotonic()
            if sleep_s > 0:
                time.sleep(sleep_s)

            new_counts = read_pico_totals(bus)
            deltas = compute_deltas(new_counts, old_counts)
            old_counts = new_counts

            now_unix = time.time()
            now_utc = datetime.fromtimestamp(now_unix, timezone.utc)
            iso_utc = now_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            elapsed_s = time.monotonic() - start_mono

            writer.writerow([f"{now_unix:.6f}", iso_utc, f"{elapsed_s:.3f}", *deltas])
            f.flush()
            os.fsync(f.fileno())

            if row_count > 0 and row_count % HEADER_EVERY == 0:
                print_terminal_header()

            print(format_terminal_row(iso_utc, elapsed_s, deltas))

            row_count += 1
            sample_index += 1

    print(f"Finished. Saved CSV: {output_file}")


if __name__ == "__main__":
    main()
