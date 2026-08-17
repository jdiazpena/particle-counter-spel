#!/usr/bin/env python3
"""
Post-process particle detector CSVs and build/update an orbit position cache.

This script is meant to be run later, after read_pd_A.py, read_pd_B.py,
or read_pd_AB.py have produced CSV files.

It does three things:
  1) Reads every particle detector CSV in PD_DATA_DIR.
  2) Builds/updates a cached timestamp -> lat/lon/alt CSV using TLEs in TLE_DIR.
  3) Writes a joined particle-detector + position CSV for later plotting.

The expensive TLE propagation is only done for:
  - new measurement timestamps not already in the cache
  - cached timestamps whose nearest TLE changed because new TLEs were added
  - cached timestamps with missing lat/lon/alt
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from sgp4.api import Satrec, WGS84, SGP4_ERRORS
from astropy.time import Time
from astropy.coordinates import TEME, ITRS, CartesianDifferential, CartesianRepresentation
from astropy import units as u
from astropy.utils import iers
from astropy.utils.iers import IERS_A


# -----------------------------
# HARDCODED PATHS
# -----------------------------

PD_DATA_DIR = Path.home() / "Documents" / "PD"
TLE_DIR = Path.home() / "TLE"
POST_DIR = Path.home() / "Documents" / "PD_post"

ORBIT_CACHE_CSV = POST_DIR / "pd_orbit_cache.csv"
JOINED_OUTPUT_CSV = POST_DIR / "pd_measurements_with_position.csv"
RUNTIME_REPORT_TXT = POST_DIR / "pd_orbit_cache_runtime.txt"

# If this is True, old cached rows are recomputed when a newer TLE catalogue
# changes which TLE is closest to that measurement timestamp.
REFINE_IF_NEAREST_TLE_CHANGED = True

# Optional high-precision EOP file. Put it here if you want the same style
# as the old TLE_functions.py workflow:
#   $HOME/TLE/finals2000A.all
EOP_FILE = TLE_DIR / "finals2000A.all"


# -----------------------------
# TIME / TLE HELPERS
# -----------------------------

def setup_iers_offline() -> None:
    """Avoid Astropy trying to download EOP files on the RPi."""
    iers.conf.auto_download = False

    if EOP_FILE.exists():
        iers.conf.iers_table = IERS_A.open(EOP_FILE)
        print(f"Using EOP file: {EOP_FILE}")
    else:
        print(f"EOP file not found: {EOP_FILE}")
        print("Continuing with Astropy's available offline IERS table.")


def jday(year: int, mon: int, day: int, hr: int, minute: int, sec: float) -> float:
    jd0 = (
        367.0 * year
        - 7.0 * (year + ((mon + 9.0) // 12.0)) * 0.25 // 1.0
        + 275.0 * mon // 9.0
        + day
        + 1721013.5
    )
    utc = ((sec / 60.0 + minute) / 60.0 + hr)
    return jd0 + utc / 24.0


def unix_to_julian(unix_time_s: np.ndarray) -> np.ndarray:
    return 2440587.5 + np.asarray(unix_time_s, dtype=float) / 86400.0


def tle_epoch_to_julian(tle_epoch: str) -> float:
    year = int(tle_epoch[:2])
    day_of_year = int(tle_epoch[2:5])
    fraction_of_day = float("0" + tle_epoch[5:])

    # This assumes 20xx, which is fine for the current SUCHAI files.
    # If you ever process 1990s TLEs, this needs the standard TLE pivot rule.
    base_date = jday(2000 + year, 1, 0, 0, 0, 0)
    return base_date + day_of_year + fraction_of_day


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TLEEntry:
    file: str
    line1: str
    line2: str
    epoch: str
    epoch_jd: float
    tle_hash: str


def read_tle_catalog(tle_dir: Path) -> list[TLEEntry]:
    """
    Read all TLE pairs from text files in TLE_DIR.

    Accepts either:
      line 1
      line 2

    or:
      satellite name
      line 1
      line 2
    """
    if not tle_dir.exists():
        raise FileNotFoundError(f"TLE directory does not exist: {tle_dir}")

    entries: list[TLEEntry] = []
    tle_files = sorted(
        p for p in tle_dir.rglob("*")
        if p.is_file() and p.name != EOP_FILE.name
    )

    for path in tle_files:
        with path.open("r", errors="replace") as f:
            lines = [line.strip() for line in f if line.strip()]

        i = 0
        while i < len(lines):
            if lines[i].startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
                line1 = lines[i]
                line2 = lines[i + 1]
                parts = re.split(r"\s+", line1)

                if len(parts) < 4:
                    print(f"Skipping malformed TLE line in {path}: {line1}")
                    i += 1
                    continue

                epoch = parts[3]
                epoch_jd = tle_epoch_to_julian(epoch)
                tle_hash = sha1_text(line1 + "\n" + line2)

                entries.append(
                    TLEEntry(
                        file=str(path),
                        line1=line1,
                        line2=line2,
                        epoch=epoch,
                        epoch_jd=epoch_jd,
                        tle_hash=tle_hash,
                    )
                )
                i += 2
            else:
                i += 1

    if not entries:
        raise RuntimeError(f"No valid TLE pairs found in {tle_dir}")

    entries = sorted(entries, key=lambda x: x.epoch_jd)
    print(f"Loaded {len(entries)} TLE pairs from {tle_dir}")
    print(f"TLE range JD: {entries[0].epoch_jd:.6f} to {entries[-1].epoch_jd:.6f}")
    return entries


def nearest_tle_indices(jd_obs: np.ndarray, tle_jd: np.ndarray) -> np.ndarray:
    """Return the index of the nearest TLE epoch for every observation JD."""
    jd_obs = np.asarray(jd_obs, dtype=float)
    tle_jd = np.asarray(tle_jd, dtype=float)

    right = np.searchsorted(tle_jd, jd_obs, side="left")
    left = np.clip(right - 1, 0, len(tle_jd) - 1)

    d_left = np.abs(jd_obs - tle_jd[left])
    d_right = np.where(
        right < len(tle_jd),
        np.abs(jd_obs - tle_jd[np.clip(right, 0, len(tle_jd) - 1)]),
        np.inf,
    )

    return np.where(d_right < d_left, right, left)


# -----------------------------
# PARTICLE DETECTOR CSV HELPERS
# -----------------------------

def find_pd_files(pd_dir: Path) -> list[Path]:
    if not pd_dir.exists():
        raise FileNotFoundError(f"Particle detector directory does not exist: {pd_dir}")

    files = sorted(pd_dir.rglob("PD*.csv"))
    files = [p for p in files if p.is_file()]

    if not files:
        raise RuntimeError(f"No PD*.csv files found in {pd_dir}")

    return files


def channel_columns(df: pd.DataFrame, prefix: str) -> list[str]:
    """Return raw channel columns such as A1_0.500V or B4_3.500V."""
    pattern = re.compile(rf"^{prefix}[1-4]_.*V$")
    return [c for c in df.columns if pattern.match(c)]


def channel_number(col: str) -> int | None:
    """Extract the discriminator number from a column name such as A3_2.500V."""
    match = re.match(r"^[AB]([1-4])_", col)
    if not match:
        return None
    return int(match.group(1))


def channel_threshold_v(col: str) -> float | None:
    """Extract the threshold voltage from a column name such as A3_2.500V."""
    match = re.match(r"^[AB][1-4]_([0-9.]+)V$", col)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def channel_map(df: pd.DataFrame, prefix: str) -> dict[int, str]:
    """Map threshold number 1..4 to its raw CSV column for one detector."""
    out: dict[int, str] = {}

    for col in channel_columns(df, prefix):
        n = channel_number(col)
        if n is None:
            continue

        if n in out:
            raise ValueError(
                f"Found multiple {prefix}{n} columns: {out[n]} and {col}. "
                "This script expects one voltage label per threshold per file."
            )

        out[n] = col

    return out


def numeric_channel_or_zero(df: pd.DataFrame, col: str | None) -> pd.Series:
    """Return one raw channel as int64, or zeros if that detector/channel is absent."""
    if col is None:
        return pd.Series(np.zeros(len(df), dtype=np.int64), index=df.index)

    return pd.to_numeric(df[col], errors="coerce").fillna(0).astype(np.int64)


def threshold_voltage_for_row(a_map: dict[int, str], b_map: dict[int, str], thr: int) -> float:
    """
    Return threshold voltage for a threshold number.

    A and B should match because both detectors use the same DAC thresholds.
    If both exist and disagree, keep A but print a warning.
    """
    values = []

    if thr in a_map:
        values.append(("A", channel_threshold_v(a_map[thr])))
    if thr in b_map:
        values.append(("B", channel_threshold_v(b_map[thr])))

    values = [(det, val) for det, val in values if val is not None]

    if not values:
        return np.nan

    if len(values) == 2 and abs(values[0][1] - values[1][1]) > 1e-9:
        print(
            f"WARNING: threshold {thr} voltage mismatch: "
            f"{values[0][0]}={values[0][1]} V, {values[1][0]}={values[1][1]} V. "
            f"Using {values[0][1]} V."
        )

    return float(values[0][1])


def add_normalized_count_columns(df: pd.DataFrame, a_map: dict[int, str], b_map: dict[int, str]) -> pd.DataFrame:
    """
    Add physically meaningful particle count columns.

    The raw channels are cumulative discriminator thresholds, not independent bins.
    Therefore:
      - A and B are added only at the same threshold.
      - Different thresholds are not summed as separate particles.
      - particles_total is the lowest-threshold total.
      - bin1..bin4 are approximate threshold intervals.
    """
    df = df.copy()

    for thr in range(1, 5):
        a_col = a_map.get(thr)
        b_col = b_map.get(thr)

        a_counts = numeric_channel_or_zero(df, a_col)
        b_counts = numeric_channel_or_zero(df, b_col)

        df[f"count_A_thr{thr}"] = a_counts
        df[f"count_B_thr{thr}"] = b_counts
        df[f"thr{thr}_total"] = (a_counts + b_counts).astype(np.int64)
        df[f"threshold{thr}_v"] = threshold_voltage_for_row(a_map, b_map, thr)

    # Lowest threshold is the best estimate of total particles above detection threshold.
    df["particles_total"] = df["thr1_total"].astype(np.int64)

    # Keep counts_total as a backwards-compatible alias for old plotting scripts.
    # It is now physically interpreted as particles_total, not a sum over thresholds.
    df["counts_total"] = df["particles_total"].astype(np.int64)

    # Optional diagnostic: the old wrong total, useful only for debugging.
    df["counts_raw_threshold_sum"] = (
        df["thr1_total"] + df["thr2_total"] + df["thr3_total"] + df["thr4_total"]
    ).astype(np.int64)

    # Approximate differential threshold bins.
    # Clip at zero in case noise/timing produces non-monotonic threshold counts.
    df["bin1"] = (df["thr1_total"] - df["thr2_total"]).clip(lower=0).astype(np.int64)
    df["bin2"] = (df["thr2_total"] - df["thr3_total"]).clip(lower=0).astype(np.int64)
    df["bin3"] = (df["thr3_total"] - df["thr4_total"]).clip(lower=0).astype(np.int64)
    df["bin4"] = df["thr4_total"].clip(lower=0).astype(np.int64)

    return df


def read_one_pd_file(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"unix_time": "string", "iso_utc": "string"})

    if "unix_time" not in df.columns:
        raise ValueError(f"Missing unix_time column in {path}")

    if "iso_utc" not in df.columns:
        raise ValueError(f"Missing iso_utc column in {path}")

    df["unix_time"] = pd.to_numeric(df["unix_time"], errors="coerce")
    df = df.dropna(subset=["unix_time"]).copy()

    a_map = channel_map(df, "A")
    b_map = channel_map(df, "B")

    a_cols = [a_map[i] for i in sorted(a_map)]
    b_cols = [b_map[i] for i in sorted(b_map)]

    if a_cols and b_cols:
        detector_mode = "AB"
    elif a_cols:
        detector_mode = "A"
    elif b_cols:
        detector_mode = "B"
    else:
        detector_mode = "UNKNOWN"

    # Convert existing raw channel columns to numeric. Bad values become zero.
    for col in a_cols + b_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(np.int64)

    df = add_normalized_count_columns(df, a_map, b_map)

    # Backwards-compatible detector totals, but now they are detector totals above threshold 1.
    df["counts_A_total"] = df["count_A_thr1"].astype(np.int64)
    df["counts_B_total"] = df["count_B_thr1"].astype(np.int64)

    df["detector_mode"] = detector_mode
    df["source_file"] = str(path)
    df["unix_time_key"] = df["unix_time"].map(lambda x: f"{float(x):.6f}")

    keep_cols = [
        "unix_time_key",
        "unix_time",
        "iso_utc",
        "t_s",
        "detector_mode",
        "counts_A_total",
        "counts_B_total",
        "counts_total",
        "particles_total",
        "counts_raw_threshold_sum",
        "count_A_thr1",
        "count_A_thr2",
        "count_A_thr3",
        "count_A_thr4",
        "count_B_thr1",
        "count_B_thr2",
        "count_B_thr3",
        "count_B_thr4",
        "thr1_total",
        "thr2_total",
        "thr3_total",
        "thr4_total",
        "bin1",
        "bin2",
        "bin3",
        "bin4",
        "threshold1_v",
        "threshold2_v",
        "threshold3_v",
        "threshold4_v",
        "source_file",
    ]

    # Keep original raw channel columns too, because later debugging may need them.
    keep_cols += a_cols + b_cols
    keep_cols = [c for c in keep_cols if c in df.columns]

    return df[keep_cols]


def read_all_pd_measurements(pd_dir: Path) -> pd.DataFrame:
    files = find_pd_files(pd_dir)
    print(f"Found {len(files)} particle detector CSV files")

    frames = []
    for path in files:
        try:
            frames.append(read_one_pd_file(path))
        except Exception as exc:
            print(f"Skipping {path}: {exc}")

    if not frames:
        raise RuntimeError("No readable particle detector CSV files")

    df = pd.concat(frames, ignore_index=True, sort=False)
    df = df.sort_values("unix_time").reset_index(drop=True)

    print(f"Read {len(df)} measurement rows")
    print(f"Unique timestamps: {df['unix_time_key'].nunique()}")
    return df


# -----------------------------
# ORBIT PROPAGATION
# -----------------------------

def propagate_one_tle_vectorized(entry: TLEEntry, unix_times: np.ndarray) -> pd.DataFrame:
    """Propagate one TLE for many unix timestamps using sgp4_array + Astropy."""
    unix_times = np.asarray(unix_times, dtype=float)
    t = Time(unix_times, format="unix", scale="utc")

    sat = Satrec.twoline2rv(entry.line1, entry.line2, WGS84)
    error_codes, teme_p, teme_v = sat.sgp4_array(t.jd1, t.jd2)

    lat = np.full(len(unix_times), np.nan, dtype=float)
    lon = np.full(len(unix_times), np.nan, dtype=float)
    alt_km = np.full(len(unix_times), np.nan, dtype=float)
    sgp4_error = np.array(error_codes, dtype=int)
    sgp4_error_text = np.array(["" for _ in unix_times], dtype=object)

    good = sgp4_error == 0

    for code in sorted(set(sgp4_error[~good])):
        sgp4_error_text[sgp4_error == code] = SGP4_ERRORS.get(int(code), f"SGP4 error {code}")

    if np.any(good):
        p = teme_p[good]
        v = teme_v[good]
        tg = t[good]

        teme_position = CartesianRepresentation(
            p[:, 0] * u.km,
            p[:, 1] * u.km,
            p[:, 2] * u.km,
        )
        teme_velocity = CartesianDifferential(
            v[:, 0] * u.km / u.s,
            v[:, 1] * u.km / u.s,
            v[:, 2] * u.km / u.s,
        )
        teme = TEME(teme_position.with_differentials(teme_velocity), obstime=tg)
        itrs_geo = teme.transform_to(ITRS(obstime=tg))
        location = itrs_geo.earth_location

        lon[good] = location.geodetic.lon.value
        lat[good] = location.geodetic.lat.value
        alt_km[good] = location.geodetic.height.to_value(u.km)

    return pd.DataFrame(
        {
            "unix_time": unix_times,
            "unix_time_key": [f"{x:.6f}" for x in unix_times],
            "iso_utc": Time(unix_times, format="unix", scale="utc").to_value("isot"),
            "jd": unix_to_julian(unix_times),
            "lat": lat,
            "lon": lon,
            "alt_km": alt_km,
            "tle_epoch": entry.epoch,
            "tle_epoch_jd": entry.epoch_jd,
            "tle_file": entry.file,
            "tle_hash": entry.tle_hash,
            "sgp4_error": sgp4_error,
            "sgp4_error_text": sgp4_error_text,
        }
    )


def propagate_positions(unix_times: np.ndarray, tle_entries: list[TLEEntry]) -> pd.DataFrame:
    """Propagate many timestamps by grouping them by nearest TLE."""
    unix_times = np.asarray(unix_times, dtype=float)

    if len(unix_times) == 0:
        return pd.DataFrame()

    jd_obs = unix_to_julian(unix_times)
    tle_jd = np.array([e.epoch_jd for e in tle_entries], dtype=float)
    nearest = nearest_tle_indices(jd_obs, tle_jd)

    frames = []
    unique_tle_indices = np.unique(nearest)
    total_groups = len(unique_tle_indices)

    for group_number, tle_idx in enumerate(unique_tle_indices, start=1):
        idx = np.flatnonzero(nearest == tle_idx)
        entry = tle_entries[int(tle_idx)]
        group_times = unix_times[idx]

        print(
            f"Propagating {len(group_times)} timestamps "
            f"with TLE {group_number}/{total_groups} "
            f"epoch={entry.epoch}"
        )

        frames.append(propagate_one_tle_vectorized(entry, group_times))

    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values("unix_time").reset_index(drop=True)
    return out


# -----------------------------
# CACHE MANAGEMENT
# -----------------------------

def load_orbit_cache(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path, dtype={"unix_time_key": "string", "tle_hash": "string"})

    if "unix_time_key" not in df.columns:
        df["unix_time_key"] = pd.to_numeric(df["unix_time"], errors="coerce").map(lambda x: f"{float(x):.6f}")

    return df


def current_nearest_tle_hashes(unix_times: np.ndarray, tle_entries: list[TLEEntry]) -> np.ndarray:
    jd_obs = unix_to_julian(unix_times)
    tle_jd = np.array([e.epoch_jd for e in tle_entries], dtype=float)
    nearest = nearest_tle_indices(jd_obs, tle_jd)
    hashes = np.array([tle_entries[int(i)].tle_hash for i in nearest], dtype=object)
    return hashes


def choose_times_to_compute(measurements: pd.DataFrame, cache: pd.DataFrame, tle_entries: list[TLEEntry]) -> np.ndarray:
    unique = measurements[["unix_time_key", "unix_time"]].drop_duplicates("unix_time_key").copy()
    unique = unique.sort_values("unix_time")

    if cache.empty:
        print("No existing orbit cache. All unique timestamps need propagation.")
        return unique["unix_time"].to_numpy(dtype=float)

    cached_keys = set(cache["unix_time_key"].astype(str))
    missing = unique[~unique["unix_time_key"].astype(str).isin(cached_keys)]

    compute_keys = set(missing["unix_time_key"].astype(str))

    print(f"Cached timestamps: {len(cached_keys)}")
    print(f"New timestamps not in cache: {len(missing)}")

    if REFINE_IF_NEAREST_TLE_CHANGED:
        needed_cols = {"unix_time", "unix_time_key", "tle_hash", "lat", "lon", "alt_km"}
        if needed_cols.issubset(cache.columns):
            cached_unique = cache.drop_duplicates("unix_time_key").copy()
            current_hashes = current_nearest_tle_hashes(cached_unique["unix_time"].to_numpy(dtype=float), tle_entries)
            old_hashes = cached_unique["tle_hash"].astype(str).to_numpy()

            changed_tle = cached_unique[old_hashes != current_hashes]
            missing_position = cached_unique[
                cached_unique[["lat", "lon", "alt_km"]].isna().any(axis=1)
            ]

            for key in changed_tle["unix_time_key"].astype(str):
                compute_keys.add(key)
            for key in missing_position["unix_time_key"].astype(str):
                compute_keys.add(key)

            print(f"Cached timestamps whose nearest TLE changed: {len(changed_tle)}")
            print(f"Cached timestamps with missing position: {len(missing_position)}")
        else:
            print("Existing cache lacks required columns for TLE-change check. Only new timestamps will be added.")

    to_compute = unique[unique["unix_time_key"].astype(str).isin(compute_keys)]
    to_compute = to_compute.sort_values("unix_time")

    return to_compute["unix_time"].to_numpy(dtype=float)


def atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(path)


def update_orbit_cache(measurements: pd.DataFrame, tle_entries: list[TLEEntry]) -> pd.DataFrame:
    cache = load_orbit_cache(ORBIT_CACHE_CSV)
    times_to_compute = choose_times_to_compute(measurements, cache, tle_entries)

    if len(times_to_compute) > 0:
        print(f"Timestamps to propagate now: {len(times_to_compute)}")
        new_positions = propagate_positions(times_to_compute, tle_entries)

        if cache.empty:
            updated = new_positions
        else:
            recomputed_keys = set(new_positions["unix_time_key"].astype(str))
            cache_kept = cache[~cache["unix_time_key"].astype(str).isin(recomputed_keys)]
            updated = pd.concat([cache_kept, new_positions], ignore_index=True, sort=False)
    else:
        print("No TLE propagation needed. Orbit cache is already up to date.")
        updated = cache

    updated = updated.drop_duplicates("unix_time_key", keep="last")
    updated = updated.sort_values("unix_time").reset_index(drop=True)
    atomic_write_csv(updated, ORBIT_CACHE_CSV)
    print(f"Orbit cache written: {ORBIT_CACHE_CSV}")
    print(f"Orbit cache rows: {len(updated)}")

    return updated


def write_joined_measurement_file(measurements: pd.DataFrame, orbit_cache: pd.DataFrame) -> None:
    keep_orbit_cols = [
        "unix_time_key",
        "lat",
        "lon",
        "alt_km",
        "jd",
        "tle_epoch",
        "tle_epoch_jd",
        "tle_file",
        "tle_hash",
        "sgp4_error",
        "sgp4_error_text",
    ]
    keep_orbit_cols = [c for c in keep_orbit_cols if c in orbit_cache.columns]

    joined = measurements.merge(
        orbit_cache[keep_orbit_cols],
        on="unix_time_key",
        how="left",
        validate="many_to_one",
    )

    joined = joined.sort_values("unix_time").reset_index(drop=True)
    atomic_write_csv(joined, JOINED_OUTPUT_CSV)

    print(f"Joined measurement file written: {JOINED_OUTPUT_CSV}")
    print(f"Joined rows: {len(joined)}")


def write_runtime_report(start_perf: float, measurements: pd.DataFrame, orbit_cache: pd.DataFrame) -> None:
    elapsed_s = time.perf_counter() - start_perf

    text = []
    text.append("PD orbit cache runtime report")
    text.append(f"Finished UTC: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    text.append(f"Elapsed seconds: {elapsed_s:.2f}")
    text.append(f"Elapsed minutes: {elapsed_s / 60.0:.2f}")
    text.append(f"PD_DATA_DIR: {PD_DATA_DIR}")
    text.append(f"TLE_DIR: {TLE_DIR}")
    text.append(f"ORBIT_CACHE_CSV: {ORBIT_CACHE_CSV}")
    text.append(f"JOINED_OUTPUT_CSV: {JOINED_OUTPUT_CSV}")
    text.append(f"Measurement rows: {len(measurements)}")
    text.append(f"Unique measurement timestamps: {measurements['unix_time_key'].nunique()}")
    text.append(f"Orbit cache rows: {len(orbit_cache)}")

    RUNTIME_REPORT_TXT.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_REPORT_TXT.write_text("\n".join(text) + "\n")
    print(f"Runtime report written: {RUNTIME_REPORT_TXT}")


# -----------------------------
# MAIN
# -----------------------------

def main() -> None:
    start_perf = time.perf_counter()

    POST_DIR.mkdir(parents=True, exist_ok=True)
    setup_iers_offline()

    measurements = read_all_pd_measurements(PD_DATA_DIR)
    tle_entries = read_tle_catalog(TLE_DIR)

    orbit_cache = update_orbit_cache(measurements, tle_entries)
    write_joined_measurement_file(measurements, orbit_cache)
    write_runtime_report(start_perf, measurements, orbit_cache)


if __name__ == "__main__":
    main()
