#!/usr/bin/env python3
"""
PD-only plotting helper functions.

This file is separated from Help_Functions_V3.py so the old LP/SUCHAI1
workflow stays untouched. It expects the postprocessed particle detector CSV
created by pd_build_orbit_cache.py / pd_build_orbit_cache_v2.py.
"""

import contextlib
import logging
import os
from pathlib import Path

# Keep Cartopy data in a known local cache on the RPi.
os.environ.setdefault("CARTOPY_DATA_DIR", str(Path.home() / "cartopy_data"))

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

import cartopy.crs as ccrs
import cartopy.feature as cfeature

import aacgmv2

logging.getLogger("aacgmv2").setLevel(logging.ERROR)


@contextlib.contextmanager
def _suppress_stderr(enabled=True):
    """
    AACGM-v2 can print failed-conversion messages near the magnetic equator.
    We keep NaNs, but hide the repeated stderr messages when requested.
    """
    if not enabled:
        yield
        return

    with open(os.devnull, "w") as devnull:
        with contextlib.redirect_stderr(devnull):
            yield


def _require_columns(df, columns, label="dataframe"):
    missing = [col for col in columns if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in {label}: {missing}")


def available_count_columns(df):
    """
    Return the particle-count products that exist in a postprocessed PD table.
    """
    preferred = [
        "particles_total",
        "counts_total",
        "thr1_total",
        "thr2_total",
        "thr3_total",
        "thr4_total",
        "bin1",
        "bin2",
        "bin3",
        "bin4",
        "count_A_thr1",
        "count_A_thr2",
        "count_A_thr3",
        "count_A_thr4",
        "count_B_thr1",
        "count_B_thr2",
        "count_B_thr3",
        "count_B_thr4",
    ]
    return [col for col in preferred if col in df.columns]


def make_pd_gdf_from_dataframe(df, count_col="particles_total"):
    """
    Convert a postprocessed PD table into a GeoDataFrame.

    Required input columns:
    unix_time, lat, lon, alt, and the selected count_col.

    The original columns are preserved, and a generic 'counts' column is added
    so older plotting logic still works.
    """
    _require_columns(df, ["unix_time", "lat", "lon", "alt", count_col], "PD table")

    out = df.copy()
    out = out.dropna(subset=["unix_time", "lat", "lon", "alt", count_col])

    out["times"] = pd.to_datetime(out["unix_time"], unit="s", origin="unix", utc=True)
    out["counts"] = pd.to_numeric(out[count_col], errors="coerce")
    out = out.dropna(subset=["counts"])

    out["geometry"] = [Point(x, y) for x, y in zip(out["lon"], out["lat"])]
    return gpd.GeoDataFrame(out, geometry="geometry", crs="EPSG:4326")


def set_counts_column(gdf, count_col):
    """
    Return a copy of gdf where the generic plotting column 'counts' is count_col.
    """
    if count_col not in gdf.columns:
        raise ValueError(f"Count column not found: {count_col}")

    out = gdf.copy()
    out["counts"] = pd.to_numeric(out[count_col], errors="coerce")
    return out.dropna(subset=["counts"])


def add_magnetic_coords(gdf, quiet=True, force=False):
    """
    Append AACGM-v2 magnetic coordinates and MLT.

    Output columns:
    mlat, mlon, mlt, foot_lat, foot_lon.

    Near the magnetic equator AACGM-v2 can be undefined. Those rows are kept
    with NaN magnetic coordinates instead of crashing.
    """
    needed = ["mlat", "mlon", "mlt", "foot_lat", "foot_lon"]
    if not force and all(col in gdf.columns for col in needed):
        return gdf.copy()

    mlats, mlons, mlts = [], [], []
    foot_lats, foot_lons = [], []

    for row in gdf.itertuples():
        dt = pd.to_datetime(row.times, utc=True).to_pydatetime().replace(tzinfo=None)
        alt_km = float(row.alt)

        try:
            with _suppress_stderr(quiet):
                mlat, mlon, mlt = aacgmv2.get_aacgm_coord(
                    float(row.lat),
                    float(row.lon),
                    alt_km,
                    dt,
                    method="ALLOWTRACE",
                )
        except Exception:
            mlat, mlon, mlt = np.nan, np.nan, np.nan

        mlats.append(mlat)
        mlons.append(mlon)
        mlts.append(mlt)

        if np.isfinite(mlat) and np.isfinite(mlon):
            try:
                with _suppress_stderr(quiet):
                    f_lat, f_lon, _ = aacgmv2.convert_latlon(
                        mlat,
                        mlon,
                        0.0,
                        dt,
                        method_code="A2G|ALLOWTRACE",
                    )
            except Exception:
                f_lat, f_lon = np.nan, np.nan
        else:
            f_lat, f_lon = np.nan, np.nan

        foot_lats.append(f_lat)
        foot_lons.append(f_lon)

    out = gdf.copy()
    out["mlat"] = np.array(mlats)
    out["mlon"] = np.array(mlons)
    out["mlt"] = np.array(mlts)
    out["foot_lat"] = np.array(foot_lats)
    out["foot_lon"] = np.array(foot_lons)
    return out


def classify_mlt_sector(gdf):
    """
    Add period column from MLT.

    Day   = 1 for 06 <= MLT < 18
    Night = 0 otherwise

    Rows with NaN MLT are left as NaN period.
    """
    out = gdf.copy()
    out["period"] = np.nan

    valid = np.isfinite(out["mlt"])
    day_cond = valid & (out["mlt"] >= 6) & (out["mlt"] < 18)
    night_cond = valid & ~day_cond

    out.loc[day_cond, "period"] = 1
    out.loc[night_cond, "period"] = 0
    return out


def load_pd_plot_table(input_csv, magnetic_cache_csv=None, rebuild_magnetic=False):
    """
    Load pd_measurements_with_position.csv and optionally reuse a magnetic cache.

    The magnetic cache avoids recalculating AACGM-v2 coordinates every time the
    plotting script is run. The cache is rebuilt when the input CSV is newer.
    """
    input_csv = Path(input_csv)
    if not input_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")

    if magnetic_cache_csv is not None:
        magnetic_cache_csv = Path(magnetic_cache_csv)
        cache_ok = (
            magnetic_cache_csv.exists()
            and magnetic_cache_csv.stat().st_mtime >= input_csv.stat().st_mtime
            and not rebuild_magnetic
        )
        if cache_ok:
            return pd.read_csv(magnetic_cache_csv)

    df = pd.read_csv(input_csv)
    _require_columns(df, ["unix_time", "lat", "lon", "alt"], str(input_csv))

    count_cols = available_count_columns(df)
    if not count_cols:
        raise ValueError(
            "No known count columns found. Expected particles_total, counts_total, "
            "thr*_total, bin*, or detector threshold columns."
        )

    default_count = "particles_total" if "particles_total" in df.columns else count_cols[0]
    gdf = make_pd_gdf_from_dataframe(df, count_col=default_count)
    gdf = add_magnetic_coords(gdf, quiet=True)
    gdf = classify_mlt_sector(gdf)

    out = pd.DataFrame(gdf.drop(columns="geometry"))

    if magnetic_cache_csv is not None:
        magnetic_cache_csv.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(magnetic_cache_csv, index=False)

    return out


def plot_particle_map(
    gdf,
    coord_type="geo",
    count_col="counts",
    count_label=None,
    title=None,
    cmap="viridis",
    marker_size=20,
    figsize=(12, 6),
    output="particle_map.png",
):
    """
    Plot one particle-count product on geo, magnetic, or footpoint coordinates.
    """
    if count_col not in gdf.columns:
        raise ValueError(f"Count column not found: {count_col}")

    df = gdf.dropna(subset=[count_col]).copy()
    if df.empty:
        print(f"No finite data for {count_col}")
        return

    if coord_type in ("geo", "foot"):
        fig, ax = plt.subplots(
            figsize=figsize,
            subplot_kw={"projection": ccrs.PlateCarree()},
        )
        ax.add_feature(cfeature.LAND, facecolor="lightgray")
        ax.add_feature(cfeature.OCEAN, facecolor="azure")
        ax.add_feature(cfeature.COASTLINE, linewidth=0.5)
        ax.add_feature(cfeature.BORDERS, linestyle=":")

        if coord_type == "geo":
            xs, ys = df.geometry.x, df.geometry.y
        else:
            df = df.dropna(subset=["foot_lon", "foot_lat"])
            xs, ys = df["foot_lon"], df["foot_lat"]

        scat = ax.scatter(
            xs,
            ys,
            c=df[count_col],
            cmap=cmap,
            s=marker_size,
            edgecolor="k",
            linewidth=0.2,
            transform=ccrs.PlateCarree(),
        )
        gl = ax.gridlines(
            draw_labels=True,
            linewidth=0.5,
            color="gray",
            alpha=0.3,
            linestyle="--",
        )
        gl.top_labels = False
        gl.right_labels = False

    elif coord_type == "mag":
        df = df.dropna(subset=["mlon", "mlat"])
        if df.empty:
            print(f"No finite magnetic coordinates for {count_col}")
            return

        fig, ax = plt.subplots(figsize=figsize)
        scat = ax.scatter(
            df["mlon"],
            df["mlat"],
            c=df[count_col],
            cmap=cmap,
            s=marker_size,
            edgecolor="k",
            linewidth=0.2,
        )
        ax.set_xlabel("Magnetic Longitude (°)")
        ax.set_ylabel("Magnetic Latitude (°)")

    else:
        raise ValueError("coord_type must be 'geo', 'foot', or 'mag'")

    cbar = fig.colorbar(scat, ax=ax, orientation="vertical", shrink=0.6)
    cbar.set_label(count_label or count_col)

    if title:
        ax.set_title(title)

    fig.tight_layout()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=300, bbox_inches="tight")
    plt.close(fig)


def plot_particle_data(
    gdf,
    date_range=None,
    outside_range=None,
    threshold=None,
    period=None,
    coord_type="geo",
    count_col="counts",
    count_label=None,
    title_prefix=None,
    **plot_kwargs,
):
    """
    Filter data then call plot_particle_map.
    """
    if count_col not in gdf.columns:
        raise ValueError(f"Count column not found: {count_col}")

    df = gdf.copy()

    if date_range is not None and outside_range is not None:
        raise ValueError("Specify either date_range or outside_range, not both")

    if date_range is not None:
        start = pd.to_datetime(date_range.start, utc=True)
        stop = pd.to_datetime(date_range.stop, utc=True)
        df = df[(df["times"] >= start) & (df["times"] <= stop)]
        if df.empty:
            print(f"No data in {start}->{stop}")
            return

    if outside_range is not None:
        start = pd.to_datetime(outside_range.start, utc=True)
        stop = pd.to_datetime(outside_range.stop, utc=True)
        df = df[(df["times"] < start) | (df["times"] > stop)]
        if df.empty:
            print(f"No data outside {start}->{stop}")
            return

    if threshold is not None:
        df = df[df[count_col] > threshold]
        if df.empty:
            print(f"No points with {count_col} > {threshold}")
            return

    if period is not None:
        if isinstance(period, str):
            target = 1 if period.lower() == "day" else 0
        else:
            target = int(period)

        df = df[df["period"] == target]
        if df.empty:
            print(f"No points with period == {target} for {count_col}")
            return

    parts = []
    if title_prefix:
        parts.append(str(title_prefix))
    parts.append(count_label or count_col)
    if date_range is not None:
        parts.append(f"{date_range.start}->{date_range.stop}")
    if outside_range is not None:
        parts.append(f"outside {outside_range.start}->{outside_range.stop}")
    if threshold is not None:
        parts.append(f">{threshold}")
    if period is not None:
        parts.append("Day" if target == 1 else "Night")
    parts.append(coord_type)

    title = " | ".join(parts)

    plot_particle_map(
        df,
        coord_type=coord_type,
        count_col=count_col,
        count_label=count_label,
        title=title,
        **plot_kwargs,
    )


def calculate_saa_centroid(
    gdf,
    date_range=None,
    outside_range=None,
    threshold=None,
    period=None,
    coord_type="geo",
    count_col="counts",
):
    """
    Calculate weighted centroid using the selected count column.
    """
    if count_col not in gdf.columns:
        raise ValueError(f"Count column not found: {count_col}")

    df = gdf.copy()

    if date_range is not None and outside_range is not None:
        raise ValueError("Specify either date_range or outside_range, not both")

    if date_range is not None:
        start = pd.to_datetime(date_range.start, utc=True)
        stop = pd.to_datetime(date_range.stop, utc=True)
        df = df[(df["times"] >= start) & (df["times"] <= stop)]

    if outside_range is not None:
        start = pd.to_datetime(outside_range.start, utc=True)
        stop = pd.to_datetime(outside_range.stop, utc=True)
        df = df[(df["times"] < start) | (df["times"] > stop)]

    if threshold is not None:
        df = df[df[count_col] > threshold]

    if period is not None:
        if isinstance(period, str):
            target = 1 if period.lower() == "day" else 0
        else:
            target = int(period)
        df = df[df["period"] == target]

    if coord_type == "geo":
        lat_col, lon_col = "lat", "lon"
    elif coord_type == "mag":
        lat_col, lon_col = "mlat", "mlon"
    elif coord_type == "foot":
        lat_col, lon_col = "foot_lat", "foot_lon"
    else:
        raise ValueError("coord_type must be 'geo', 'foot', or 'mag'")

    df = df.dropna(subset=[lat_col, lon_col, count_col])
    if df.empty:
        print(f"No data found for centroid calculation: {count_col}, {coord_type}")
        return None

    weights = df[count_col]
    total_weight = weights.sum()
    if total_weight <= 0:
        print(f"Total weight is zero for centroid calculation: {count_col}")
        return None

    return {
        "type": coord_type,
        "period": period,
        "count_col": count_col,
        "lat": (df[lat_col] * weights).sum() / total_weight,
        "lon": (df[lon_col] * weights).sum() / total_weight,
        "total_counts": total_weight,
        "n_points": len(df),
    }
