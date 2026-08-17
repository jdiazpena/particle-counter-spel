import time
import struct

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

THRESHOLDS_V = (0.5, 1.5, 2.5, 3.5)


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

    print("MCP4728 thresholds set:")
    print(f"  CH A = {thresholds_v[0]:.3f} V")
    print(f"  CH B = {thresholds_v[1]:.3f} V")
    print(f"  CH C = {thresholds_v[2]:.3f} V")
    print(f"  CH D = {thresholds_v[3]:.3f} V")
    print()


# -----------------------------
# PICO PARTICLE COUNTER SETTINGS
# -----------------------------

PICO_ADDR = 0x17
I2C_BUS = 1

CHANNELS = [
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
# MAIN LOOP
# -----------------------------

def main():
    set_mcp4728_thresholds()

    with SMBus(I2C_BUS) as bus:
        old_counts = read_pico_totals(bus)

        print("Initial Pico totals:")
        for name, value in zip(CHANNELS, old_counts):
            print(f"  {name}: {value}")
        print()

        while True:
            time.sleep(1)

            new_counts = read_pico_totals(bus)
            deltas = compute_deltas(new_counts, old_counts)
            old_counts = new_counts

            print("Totals:")
            for name, value in zip(CHANNELS, new_counts):
                print(f"  {name}: {value}")

            print("Deltas:")
            for name, value in zip(CHANNELS, deltas):
                print(f"  {name}: {value}")

            print()


if __name__ == "__main__":
    main()