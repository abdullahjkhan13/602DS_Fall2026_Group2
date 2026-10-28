"""Normalize raw prediction snapshots into one analysis-ready table.

Four properties of the raw board drive this, all measured on the Oct 2026 pilot:

- `Min` mixes a minute countdown with status tokens (`ARR`, `BRD`, `---`), so the numeric
  value and the status are split into separate columns rather than coerced.
- `Line` carries two non-line placeholders: `No` for non-revenue "No Passenger" trains
  and `--` for trains with no line assigned yet. Both are genuine board entries, not
  corruption, so they are classified rather than dropped - but neither is revenue service
  and both should be excluded before headways are computed.
- `DestinationCode` is missing on ~49% of rows. The cause is not data loss: WMATA
  abbreviates the destination name on exactly those rows (`Shady Grv` for `Shady Grove`)
  and omits the code. `DestinationName` is never missing, so the code is recovered from
  it and the recovery is flagged.
- `LAST TRAIN` appears as a destination. It marks the night's final train, not a station.

Usage:  python src/clean_predictions.py
"""

import glob

import pandas as pd

from common import RAW_DIR, ROOT, setup_logging

OUT_PATH = ROOT / "data" / "processed" / "predictions_clean.parquet"

MIN_STATUS = {"ARR": "arriving", "BRD": "boarding", "---": "no_prediction"}

NON_REVENUE_LINES = {"No": "no_passenger", "--": "unassigned"}

# WMATA's abbreviated destination spellings, which are the rows where it also omits
# DestinationCode. Codes verified against reference/station_crosswalk.csv.
DESTINATION_ALIASES = {
    "SHADY GRV": "A15",
    "BRANCH AV": "F11",
    "NEWCRLTON": "D13",
    "NEW CRLTON": "D13",
    "MT VERN SQ": "E01",
    "MTVERN SQ": "E01",
    "MT VERNON SQ": "E01",
    "VIENNA": "K08",
}

LAST_TRAIN_NAMES = {"LASTTRAIN", "LAST TRAIN"}


def normalize_name(names):
    return names.str.upper().str.strip().str.replace(r"\s+", " ", regex=True)


def load_raw(logger):
    paths = sorted(glob.glob(str(RAW_DIR / "wmata_predictions_*.csv")))
    if not paths:
        raise FileNotFoundError(
            f"no wmata_predictions_*.csv in {RAW_DIR} - run src/collect_wmata.py first"
        )
    df = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    logger.info("loaded %d rows from %d file(s)", len(df), len(paths))
    return df


def resolve_destinations(df, logger):
    """Fill DestinationCode from DestinationName.

    The name -> code map is learned from the rows where WMATA did supply a code, then
    extended with the abbreviation table above. Learning it keeps this working if a new
    destination appears in a later collection.
    """
    name_key = normalize_name(df.destination_name)

    learned = (
        df[df.destination_code.notna()]
        .assign(key=name_key[df.destination_code.notna()])
        .groupby("key")
        .destination_code.agg(lambda s: s.mode().iat[0])
        .to_dict()
    )
    ambiguous = (
        df[df.destination_code.notna()]
        .assign(key=name_key[df.destination_code.notna()])
        .groupby("key")
        .destination_code.nunique()
    )
    if (ambiguous > 1).any():
        raise ValueError(
            f"destination names mapping to several codes: "
            f"{ambiguous[ambiguous > 1].index.tolist()}"
        )

    lookup = {**learned, **DESTINATION_ALIASES}

    resolved = df.destination_code.fillna(name_key.map(lookup))
    df["destination_code_imputed"] = df.destination_code.isna() & resolved.notna()
    df["destination_code"] = resolved
    df["is_last_train"] = name_key.isin(LAST_TRAIN_NAMES)

    # Non-revenue entries ("No Passenger", "Train") carry no destination by design.
    unresolved = df[
        df.destination_code.isna()
        & ~df.is_last_train
        & (df.service_class == "revenue")
    ]
    if not unresolved.empty:
        logger.warning(
            "%d rows have no destination code and no alias: %s",
            len(unresolved), sorted(unresolved.destination_name.unique())[:10],
        )
    return df


def clean(df, logger):
    before = len(df)
    df = df.drop_duplicates().copy()
    logger.info("dropped %d exact duplicate rows", before - len(df))

    df = df.rename(columns={
        "Car": "car_count",
        "DestinationCode": "destination_code",
        "DestinationName": "destination_name",
        "Group": "group",
        "Line": "line",
        "LocationCode": "location_code",
        "LocationName": "location_name",
    })

    df["snapshot_ts"] = pd.to_datetime(df.snapshot_ts, utc=True)

    minutes = pd.to_numeric(df.Min, errors="coerce")
    df["minutes"] = minutes
    # An empty Min carries the same meaning as the `---` token: no prediction on the
    # board. "unknown" is left for tokens we have not seen, so they surface in the log.
    df["status"] = (
        df.Min.map(MIN_STATUS)
        .where(minutes.isna(), "countdown")
        .mask(df.Min.isna(), "no_prediction")
        .fillna("unknown")
    )
    # ARR and BRD are the train at the platform, which is a zero-minute countdown.
    df.loc[df.status.isin(["arriving", "boarding"]), "minutes"] = 0

    unknown = df.loc[df.status == "unknown", "Min"]
    if not unknown.empty:
        logger.warning(
            "%d rows with unrecognised Min values: %s",
            len(unknown), unknown.value_counts().head().to_dict(),
        )

    df["service_class"] = df.line.map(NON_REVENUE_LINES).fillna("revenue")
    df.loc[df.service_class != "revenue", "line"] = pd.NA

    df = resolve_destinations(df, logger)

    out = df[[
        "snapshot_ts", "location_code", "location_name", "group", "line",
        "destination_code", "destination_name", "destination_code_imputed",
        "is_last_train", "car_count", "minutes", "status", "service_class",
    ]].sort_values(["snapshot_ts", "location_code", "group"]).reset_index(drop=True)

    summarize(out, logger)
    return out


def summarize(out, logger):
    logger.info(
        "clean rows: %d | snapshots: %d | stations: %d | %s to %s",
        len(out), out.snapshot_ts.nunique(), out.location_code.nunique(),
        out.snapshot_ts.min(), out.snapshot_ts.max(),
    )
    logger.info("status: %s", out.status.value_counts().to_dict())
    logger.info("service_class: %s", out.service_class.value_counts().to_dict())
    logger.info(
        "destination codes recovered from name: %d (%.1f%%) | still missing: %d | last-train markers: %d",
        int(out.destination_code_imputed.sum()),
        100 * out.destination_code_imputed.mean(),
        int(out.destination_code.isna().sum()),
        int(out.is_last_train.sum()),
    )


def main():
    logger = setup_logging("clean_predictions")

    out = clean(load_raw(logger), logger)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)
    logger.info("wrote %d rows to %s", len(out), OUT_PATH.relative_to(ROOT))


if __name__ == "__main__":
    main()
