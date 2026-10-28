"""Expand the static GTFS feed into one row per scheduled arrival.

Three things about this feed drive the implementation (see reference/gtfs_notes.md):

- There is no calendar.txt. Service dates come straight from calendar_dates.txt, so
  service_id -> date is a direct mapping with no weekly patterns to expand.
- Times run past 24:00:00 (27:15:00 in the Oct 2026 feed) for post-midnight service.
  They are offsets from the service date, not clock times, so they are parsed as
  timedeltas rather than through pd.to_datetime.
- stop_times references platforms (PF_<LocationCode>_<1|2|C>), never stations, so the
  crosswalk joins on platform id.

Usage:  python src/build_schedule.py [path/to/gtfs.zip]
"""

import sys
import zipfile
from pathlib import Path

import pandas as pd

from build_crosswalk import LINE_CODES, latest_gtfs_zip, read
from common import ROOT, setup_logging

CROSSWALK_PATH = ROOT / "reference" / "station_crosswalk.csv"
OUT_PATH = ROOT / "data" / "processed" / "scheduled_arrivals.parquet"

# GTFS clock times are agency-local. Everything else in the project is UTC, so arrivals
# are converted on the way out.
AGENCY_TZ = "America/New_York"


def gtfs_time_to_offset(times):
    """HH:MM:SS as an offset from the service date, allowing HH >= 24."""
    parts = times.str.split(":", expand=True).astype(int)
    return (
        pd.to_timedelta(parts[0], unit="h")
        + pd.to_timedelta(parts[1], unit="m")
        + pd.to_timedelta(parts[2], unit="s")
    )


def service_dates(z):
    """service_id -> every date it runs.

    exception_type 1 is "service added on this date". With no calendar.txt there is no
    baseline schedule for a type 2 ("removed") to subtract from, so only type 1 is used.
    """
    cal = read(z, "calendar_dates.txt")
    added = cal[cal.exception_type == "1"]
    return pd.DataFrame({
        "service_id": added.service_id,
        "service_date": pd.to_datetime(added.date, format="%Y%m%d"),
    })


def build(zip_path, logger):
    z = zipfile.ZipFile(zip_path)

    trips = read(z, "trips.txt")[
        ["trip_id", "route_id", "service_id", "direction_id", "trip_headsign", "train_id"]
    ]
    stop_times = read(z, "stop_times.txt")[
        ["trip_id", "arrival_time", "stop_id", "stop_sequence"]
    ]
    dates = service_dates(z)

    logger.info(
        "loaded %d trips, %d stop times, %d service dates across %d service ids",
        len(trips), len(stop_times), len(dates), dates.service_id.nunique(),
    )

    # stop time -> trip -> every date that trip's service runs.
    sched = stop_times.merge(trips, on="trip_id").merge(dates, on="service_id")
    logger.info("expanded to %d scheduled arrivals", len(sched))

    local = sched.service_date + gtfs_time_to_offset(sched.arrival_time)
    # ambiguous=True takes the first (DST) pass through the repeated hour at fall-back;
    # the feed spans the 2026-11-01 transition, so this is not hypothetical.
    sched["scheduled_arrival_local"] = local
    sched["scheduled_arrival_utc"] = (
        local.dt.tz_localize(AGENCY_TZ, ambiguous=True, nonexistent="shift_forward")
        .dt.tz_convert("UTC")
    )

    crosswalk = pd.read_csv(CROSSWALK_PATH)[
        ["gtfs_platform_id", "location_code", "station_name", "platform_suffix"]
    ]
    sched = sched.merge(
        crosswalk, left_on="stop_id", right_on="gtfs_platform_id", how="left"
    )

    sched["line"] = sched.route_id.map(LINE_CODES)
    sched["stop_sequence"] = sched.stop_sequence.astype(int)
    sched["direction_id"] = sched.direction_id.astype(int)

    out = sched[[
        "service_date", "location_code", "station_name", "gtfs_platform_id",
        "platform_suffix", "line", "route_id", "direction_id", "trip_headsign",
        "trip_id", "train_id", "stop_sequence",
        "scheduled_arrival_local", "scheduled_arrival_utc",
    ]].sort_values(
        ["service_date", "location_code", "line", "direction_id", "scheduled_arrival_utc"]
    ).reset_index(drop=True)

    validate(out, logger)
    return out


def validate(out, logger):
    unresolved = out[out.location_code.isna()]
    if not unresolved.empty:
        raise ValueError(
            f"{len(unresolved)} scheduled arrivals at platforms missing from the "
            f"crosswalk: {sorted(unresolved.gtfs_platform_id.unique())[:5]} - "
            f"rebuild it with src/build_crosswalk.py"
        )

    unmapped = out[out.line.isna()]
    if not unmapped.empty:
        raise ValueError(f"route ids with no WMATA line code: {sorted(unmapped.route_id.unique())}")

    logger.info(
        "validated: %d arrivals, %d dates (%s to %s), %d stations, %d lines",
        len(out), out.service_date.nunique(),
        out.service_date.min().date(), out.service_date.max().date(),
        out.location_code.nunique(), out.line.nunique(),
    )


def main():
    logger = setup_logging("build_schedule")

    zip_path = Path(sys.argv[1]) if len(sys.argv) > 1 else latest_gtfs_zip()
    logger.info("building schedule from %s", zip_path.name)

    out = build(zip_path, logger)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)
    logger.info("wrote %d rows to %s", len(out), OUT_PATH.relative_to(ROOT))


if __name__ == "__main__":
    main()
