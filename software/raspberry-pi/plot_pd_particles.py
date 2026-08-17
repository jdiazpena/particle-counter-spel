#!/usr/bin/env python3
"""
PD-only plotting script.

Expected input:
    ~/Documents/PD_post/pd_measurements_with_position.csv

Expected producer:
    pd_build_orbit_cache.py / pd_build_orbit_cache_v2.py

Outputs:
    ~/Documents/PD_post/figures_PD/*.png
    ~/Documents/PD_post/figures_PD/runtime_*.txt
"""

import atexit
import os
import time
from datetime import datetime
from pathlib import Path

# Must be set before importing the helper, because the helper imports Cartopy.
CARTOPY_DATA_DIR = Path.home() / "cartopy_data"
CARTOPY_DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("CARTOPY_DATA_DIR", str(CARTOPY_DATA_DIR))

import pandas as pd

from Help_Functions_PD import (
    available_count_columns,
    load_pd_plot_table,
    make_pd_gdf_from_dataframe,
    plot_particle_data,
)


# -----------------------------
# PATHS
# -----------------------------

POST_DIR = Path.home() / "Documents" / "PD_post"
INPUT_CSV = POST_DIR / "pd_measurements_with_position.csv"
MAG_CACHE_CSV = POST_DIR / "pd_measurements_plot_ready.csv"

FIGURE_DIR = POST_DIR / "figures_PD"
FIGURE_DIR.mkdir(parents=True, exist_ok=True)


def figure_path(filename):
    return str(FIGURE_DIR / filename)


# -----------------------------
# PLOTTING CONFIG
# -----------------------------

# Integral threshold products. These are cumulative discriminator counts.
THRESHOLD_PRODUCTS = [
    ("thr1_total", "Threshold 1 total"),
    ("thr2_total", "Threshold 2 total"),
    ("thr3_total", "Threshold 3 total"),
    ("thr4_total", "Threshold 4 total"),
]

# Approximate differential threshold bins.
# These are not true calibrated energy bins unless the voltage-energy calibration is known.
BIN_PRODUCTS = [
    ("bin1", "Bin 1: thr1-thr2"),
    ("bin2", "Bin 2: thr2-thr3"),
    ("bin3", "Bin 3: thr3-thr4"),
    ("bin4", "Bin 4: >thr4"),
]

TOTAL_PRODUCT = ("particles_total", "Total particles")

# Use None to plot everything, or set a number like 100 for thresholded plots.
TOTAL_THRESHOLD = 100
ENERGY_THRESHOLD = None

# Set this to True if you want many figures. False keeps the first run faster.
PLOT_MAG_AND_FOOT_FOR_EACH_ENERGY = True


# -----------------------------
# RUNTIME REPORT
# -----------------------------

SCRIPT_START = time.perf_counter()
SCRIPT_START_WALL = datetime.now()


def save_runtime_report():
    elapsed_s = time.perf_counter() - SCRIPT_START
    elapsed_min = elapsed_s / 60.0

    timestamp = SCRIPT_START_WALL.strftime("%Y%m%d_%H%M%S")
    runtime_file = FIGURE_DIR / f"runtime_{timestamp}.txt"

    with open(runtime_file, "w") as f:
        f.write("PD plotting runtime report\n")
        f.write(f"Start time: {SCRIPT_START_WALL.isoformat(timespec='seconds')}\n")
        f.write(f"Elapsed seconds: {elapsed_s:.2f}\n")
        f.write(f"Elapsed minutes: {elapsed_min:.2f}\n")
        f.write(f"Input CSV: {INPUT_CSV}\n")
        f.write(f"Magnetic cache CSV: {MAG_CACHE_CSV}\n")
        f.write(f"Figure directory: {FIGURE_DIR}\n")


atexit.register(save_runtime_report)


# -----------------------------
# HELPERS
# -----------------------------


def safe_name(text):
    return (
        text.lower()
        .replace(" ", "_")
        .replace(":", "")
        .replace(">", "gt")
        .replace("-", "_")
    )


def make_gdf_for_count(df, count_col):
    gdf = make_pd_gdf_from_dataframe(df, count_col=count_col)

    # Reuse magnetic columns already cached by load_pd_plot_table().
    for col in ["mlat", "mlon", "mlt", "foot_lat", "foot_lon", "period"]:
        if col in df.columns:
            gdf[col] = df.loc[gdf.index, col]

    return gdf


def plot_standard_set(gdf, count_col, label, prefix, threshold=None):
    """
    Same plot family as the older script:
    geo, mag, foot, and optional day/night cuts.
    """
    base_kwargs = dict(cmap="plasma", marker_size=25)

    plot_particle_data(
        gdf,
        count_col=count_col,
        count_label=label,
        coord_type="geo",
        threshold=threshold,
        output=figure_path(f"{prefix}_geo.png"),
        **base_kwargs,
    )

    plot_particle_data(
        gdf,
        count_col=count_col,
        count_label=label,
        coord_type="mag",
        threshold=threshold,
        output=figure_path(f"{prefix}_mag.png"),
        **base_kwargs,
    )

    plot_particle_data(
        gdf,
        count_col=count_col,
        count_label=label,
        coord_type="foot",
        threshold=threshold,
        output=figure_path(f"{prefix}_foot.png"),
        **base_kwargs,
    )

    plot_particle_data(
        gdf,
        count_col=count_col,
        count_label=label,
        coord_type="geo",
        threshold=threshold,
        period="day",
        figsize=(14, 7),
        output=figure_path(f"{prefix}_day_geo.png"),
        **base_kwargs,
    )

    plot_particle_data(
        gdf,
        count_col=count_col,
        count_label=label,
        coord_type="geo",
        threshold=threshold,
        period="night",
        figsize=(14, 7),
        output=figure_path(f"{prefix}_night_geo.png"),
        **base_kwargs,
    )


# -----------------------------
# MAIN
# -----------------------------


def main():
    print(f"Reading: {INPUT_CSV}")
    df = load_pd_plot_table(
        INPUT_CSV,
        magnetic_cache_csv=MAG_CACHE_CSV,
        rebuild_magnetic=False,
    )

    count_cols = available_count_columns(df)
    print("Available count columns:")
    for col in count_cols:
        print(f"  - {col}")

    # Total particle plots.
    total_col, total_label = TOTAL_PRODUCT
    if total_col not in df.columns:
        if "counts_total" in df.columns:
            total_col = "counts_total"
            total_label = "Total particles"
        else:
            raise ValueError("No particles_total or counts_total column found")

    gdf_total = make_gdf_for_count(df, total_col)

    plot_standard_set(
        gdf_total,
        count_col=total_col,
        label=total_label,
        prefix="01_particles_total_all",
        threshold=None,
    )

    if TOTAL_THRESHOLD is not None:
        plot_standard_set(
            gdf_total,
            count_col=total_col,
            label=f"{total_label} > {TOTAL_THRESHOLD}",
            prefix=f"02_particles_total_gt{TOTAL_THRESHOLD}",
            threshold=TOTAL_THRESHOLD,
        )

    # Threshold and bin products.
    products = THRESHOLD_PRODUCTS + BIN_PRODUCTS

    for idx, (count_col, label) in enumerate(products, start=3):
        if count_col not in df.columns:
            print(f"Skipping missing count product: {count_col}")
            continue

        gdf = make_gdf_for_count(df, count_col)
        prefix_base = f"{idx:02d}_{safe_name(count_col)}"

        plot_particle_data(
            gdf,
            count_col=count_col,
            count_label=label,
            coord_type="geo",
            threshold=ENERGY_THRESHOLD,
            cmap="plasma",
            marker_size=25,
            output=figure_path(f"{prefix_base}_geo.png"),
        )

        if PLOT_MAG_AND_FOOT_FOR_EACH_ENERGY:
            plot_particle_data(
                gdf,
                count_col=count_col,
                count_label=label,
                coord_type="mag",
                threshold=ENERGY_THRESHOLD,
                cmap="plasma",
                marker_size=25,
                output=figure_path(f"{prefix_base}_mag.png"),
            )

            plot_particle_data(
                gdf,
                count_col=count_col,
                count_label=label,
                coord_type="foot",
                threshold=ENERGY_THRESHOLD,
                cmap="plasma",
                marker_size=25,
                output=figure_path(f"{prefix_base}_foot.png"),
            )

    print(f"Finished. Figures saved in: {FIGURE_DIR}")


if __name__ == "__main__":
    main()
