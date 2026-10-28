"""Reconstruct actual train arrivals from the rolling prediction board.

The API publishes predictions, not arrivals, and carries no train identifier, so an
arrival has to be inferred from how the board changes between snapshots.

The method here tracks *predicted arrival time* rather than the countdown. For a given
train, `snapshot_ts + minutes` stays roughly constant while `minutes` ticks down, so a
stable ETA identifies one train across snapshots far more reliably than matching
decrements - which breaks as soon as WMATA revises a prediction or a snapshot is missed.

Two properties of the pilot data shape the implementation:

- Roughly half of all snapshots are re-captures: the collector fired twice per cycle,
  2-3 seconds apart, producing byte-identical boards. Those collapse into one cycle, or
  every train would be counted twice.
- A train leaves the board once it has gone. The last cycle showing `BRD` is therefore
  the arrival, with `ARR` and an expiring countdown as fallbacks.

Output is one row per tracked train. Rows where no arrival could be established are kept
with a null `arrival_ts` and `detection_rule="vanished"` so they stay auditable instead
of quietly disappearing from the counts.

Usage:  python src/reconstruct_arrivals.py
"""

import numpy as np
import pandas as pd

from common import ROOT, setup_logging

IN_PATH = ROOT / "data" / "processed" / "predictions_clean.parquet"
OUT_PATH = ROOT / "data" / "processed" / "arrival_events.parquet"

# Snapshots closer together than this are the same board captured twice.
CYCLE_GAP = pd.Timedelta("15s")
# How far a train's predicted arrival may legitimately drift between cycles.
ETA_TOLERANCE = pd.Timedelta("3min")
# A track not seen for this long has left the board.
TRACK_TIMEOUT = pd.Timedelta("150s")
# A track last seen still counting down from above this has not arrived.
VANISH_MINUTES = 3
# A cycle interval longer than this is a collection gap, not normal cadence.
GAP_THRESHOLD = pd.Timedelta("120s")

KEY = ["location_code", "group", "line", "destination_code"]


def collapse_cycles(df, logger):
    """Map each snapshot to a collection cycle, keeping one snapshot per cycle."""
    stamps = pd.Series(sorted(df.snapshot_ts.unique()))
    cycle_id = (stamps.diff() > CYCLE_GAP).cumsum()
    first_of_cycle = stamps.groupby(cycle_id).transform("first")
    keep = dict(zip(stamps, first_of_cycle))

    df = df[df.snapshot_ts.map(keep) == df.snapshot_ts].copy()
    logger.info(
        "collapsed %d snapshots into %d collection cycles (%d rows retained)",
        len(stamps), cycle_id.nunique(), len(df),
    )
    return df


def iter_cycles(observations):
    """Yield (cycle_ts, [observations]) for one key, in time order.

    Done by hand rather than with groupby: this runs once per key per cycle, and the
    groupby overhead dominated the runtime on a dataset this shape.
    """
    batch, current = [], None
    for obs in observations.itertuples():
        if obs.snapshot_ts != current:
            if batch:
                yield current, batch
            batch, current = [], obs.snapshot_ts
        batch.append(obs)
    if batch:
        yield current, batch


def track_key(observations, cycle_index):
    """Group one key's observations into per-train tracks by ETA stability."""
    tracks = []
    open_tracks = []

    for cycle_ts, cycle in iter_cycles(observations):
        idx = cycle_index[cycle_ts]
        open_tracks = [t for t in open_tracks if cycle_ts - t["last_seen"] <= TRACK_TIMEOUT]
        claimed = set()

        for obs in cycle:
            best, best_delta = None, ETA_TOLERANCE
            for i, t in enumerate(open_tracks):
                if i in claimed:
                    continue
                delta = abs(t["last_eta"] - obs.eta)
                if delta <= best_delta:
                    best, best_delta = i, delta

            if best is None:
                track = {
                    "first_seen": cycle_ts, "last_seen": cycle_ts,
                    "first_idx": idx, "last_idx": idx,
                    "last_eta": obs.eta, "n_obs": 1, "cycles_missed": 0,
                    "max_eta_jump": pd.Timedelta(0),
                    "last_minutes": obs.minutes, "car_count": obs.car_count,
                    "last_boarding": cycle_ts if obs.status == "boarding" else pd.NaT,
                    "last_arriving": cycle_ts if obs.status == "arriving" else pd.NaT,
                    "prev_seen": pd.NaT,
                }
                open_tracks.append(track)
                claimed.add(len(open_tracks) - 1)
                tracks.append(track)
            else:
                t = open_tracks[best]
                t["max_eta_jump"] = max(t["max_eta_jump"], obs.eta - t["last_eta"])
                t["cycles_missed"] += idx - t["last_idx"] - 1
                t["prev_seen"] = t["last_seen"]
                t["last_seen"] = cycle_ts
                t["last_idx"] = idx
                t["last_eta"] = obs.eta
                t["last_minutes"] = obs.minutes
                t["n_obs"] += 1
                if obs.status == "boarding":
                    t["last_boarding"] = cycle_ts
                elif obs.status == "arriving":
                    t["last_arriving"] = cycle_ts
                claimed.add(best)

    return tracks


def resolve_arrival(track):
    """Pick the arrival timestamp and record which rule produced it."""
    if pd.notna(track["last_boarding"]):
        return track["last_boarding"], "last_boarding"
    if pd.notna(track["last_arriving"]):
        return track["last_arriving"], "last_arriving"
    if track["last_minutes"] <= VANISH_MINUTES:
        return track["last_eta"], "countdown_expired"
    return pd.NaT, "vanished"


def reconstruct(df, logger):
    df = df[
        (df.service_class == "revenue")
        & ~df.is_last_train
        & df.status.isin(["countdown", "arriving", "boarding"])
        & df.destination_code.notna()
    ].copy()
    logger.info("reconstructing from %d revenue observations", len(df))

    df["eta"] = df.snapshot_ts + pd.to_timedelta(df.minutes, unit="m")
    df = df.sort_values(["snapshot_ts", "minutes"])

    cycles = pd.Series(sorted(df.snapshot_ts.unique()))
    cycle_index = {ts: i for i, ts in enumerate(cycles)}
    # Index i means "a collection gap sits between cycle i and cycle i+1". A track is
    # unreliable if a gap falls inside it, ends it, or starts it - in all three cases a
    # train could have arrived unobserved.
    gap_after = set(np.flatnonzero(cycles.diff().shift(-1) > GAP_THRESHOLD))
    logger.info("%d collection gaps over %s between cycles", len(gap_after), GAP_THRESHOLD)

    rows = []
    for key, observations in df.groupby(KEY, sort=False):
        for track in track_key(observations, cycle_index):
            arrival_ts, rule = resolve_arrival(track)
            rows.append({
                **dict(zip(KEY, key)),
                "arrival_ts": arrival_ts,
                "detection_rule": rule,
                "first_seen_ts": track["first_seen"],
                "last_seen_ts": track["last_seen"],
                "n_observations": track["n_obs"],
                "cycles_missed": track["cycles_missed"],
                "car_count": track["car_count"],
                "arrival_uncertainty_s": (
                    (track["last_seen"] - track["prev_seen"]).total_seconds()
                    if pd.notna(track["prev_seen"]) else np.nan
                ),
                "max_eta_jump_s": track["max_eta_jump"].total_seconds(),
                "gap_affected": any(
                    track["first_idx"] - 1 <= i <= track["last_idx"] for i in gap_after
                ),
            })

    out = pd.DataFrame(rows).sort_values(
        ["location_code", "group", "line", "destination_code", "arrival_ts"]
    ).reset_index(drop=True)

    summarize(out, logger)
    return out


def summarize(out, logger):
    arrived = out[out.arrival_ts.notna()]
    logger.info(
        "tracks: %d | arrivals: %d | vanished: %d",
        len(out), len(arrived), len(out) - len(arrived),
    )
    logger.info("detection rule: %s", out.detection_rule.value_counts().to_dict())
    logger.info(
        "observations per track: median %.0f, single-observation tracks %d",
        out.n_observations.median(), int((out.n_observations == 1).sum()),
    )
    logger.info(
        "flags: affected by a collection gap %d | missed >=1 cycle %d",
        int(out.gap_affected.sum()), int((out.cycles_missed > 0).sum()),
    )
    if not arrived.empty:
        logger.info(
            "arrivals span %s to %s across %d stations",
            arrived.arrival_ts.min(), arrived.arrival_ts.max(),
            arrived.location_code.nunique(),
        )


def main():
    logger = setup_logging("reconstruct_arrivals")

    df = pd.read_parquet(IN_PATH)
    out = reconstruct(collapse_cycles(df, logger), logger)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)
    logger.info("wrote %d rows to %s", len(out), OUT_PATH.relative_to(ROOT))


if __name__ == "__main__":
    main()
