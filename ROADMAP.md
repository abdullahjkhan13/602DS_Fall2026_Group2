# Project Roadmap — WMATA Metrorail and Weather Conditions

MSML602 / DATA602, Group 2 — Duckwoo Kwon, Junhyung Han, Abdullah Khan.

This is the master plan: what is finished, and every step between here and the final
deliverable. See [README.md](README.md) for setup and raw data schemas, and the project
proposal for the original framing.

**End goal.** A single analytical dataset where each row is one train arrival event at a
WMATA station (station, line, direction, arrival time, observed headway, scheduled
headway), joined to the weather and rail incidents in effect at that moment — plus an
analysis of how weather affects service, broken out by line, time of day, and station.

**Status legend:** `[x]` done · `[ ]` not started · `[~]` in progress

---

## Where we are right now

*Last updated 2026-10-28.*

**The key arrived and a 12-hour pilot ran on 23–24 October.** The processing pipeline now
runs end to end against that pilot: schedule parsing, prediction cleaning and arrival
reconstruction all produce output, and reconstruction recovers 98% of the trips GTFS says
were scheduled. **The blocker is now extended collection**, not code — the pilot recorded
zero precipitation, so it cannot answer the research question whatever we do with it.

| Phase | State |
|---|---|
| 0 — Collection code | Done, six collectors |
| 1 — Reliability, scheduling, storage | Ran for the 12h pilot; cloud host and the duplicate-snapshot bug still open |
| 2 — Arrival reconstruction | Built and validated (`src/reconstruct_arrivals.py`); headways not yet computed |
| 3 — GTFS schedule parsing | Done — `src/build_schedule.py` |
| 4 — Crosswalk | Rebuilt from the live feed; direction mapping still unverified |
| 5 — Weather | Archive API confirmed; no processing or join written |
| 6–8 — Incidents, dataset, QA | Not started |
| 9 — EDA | Weather climatology audit done; nothing else |
| 10–11 — Analysis, deliverables | Not started |

**Findings that changed the plan:**

1. **WMATA publishes GTFS-Realtime rail feeds** (Phase 1.3). The hope was that
   `TripUpdates` carries real arrival times keyed by `trip_id`, collapsing most of
   Phase 2. **Still undecided:** 3,693 files were collected during the pilot but the
   protobuf has never been decoded. It now matters less — reconstruction from
   predictions alone already recovers 98% of scheduled trips — so this is a possible
   cross-check rather than a dependency.
2. **The crosswalk had a silent-failure trap** (Phase 4). Joining at GTFS *station* level
   would have dropped Metro Center, Gallery Place, L'Enfant Plaza and Fort Totten without
   error. Joining at platform level avoids it. Solved and validated.
3. **The collection window almost certainly contains no testable snow** (Phase 9). Seven
   years of history give a median of 4 snow hours in this calendar window. Rain, wind and
   freezing temperatures are all well-powered; snow is not. **This affects the research
   question as written** and should be discussed as a group.
4. **The collector fires twice per cycle** (Phase 1.1). Half of all pilot snapshots are
   byte-identical boards captured 2–3 seconds apart: 1,406 snapshots are really 710
   collection cycles, and 49.5% of the 752,791 rows are redundant. It also doubles the
   API calls counted against the rate budget. **Fix before extended collection.**
5. **`DestinationCode` is recoverable, not lost** (Phase 2). It is missing on 49% of
   prediction rows, but only because WMATA abbreviates the destination name on exactly
   those rows (`Shady Grv` for `Shady Grove`) and omits the code. `DestinationName` is
   never missing, so the code is recovered from it in `src/clean_predictions.py`. Every
   remaining gap is a `LAST TRAIN` marker or a non-revenue train.
6. **Countdown matching was the wrong approach** (Phase 2). Linking trains by how `Min`
   decrements breaks whenever WMATA revises a prediction. Tracking *predicted arrival
   time* instead — `snapshot_ts + Min`, which holds steady as the countdown ticks down —
   is far more stable, and is what the implemented version does.

---

## Phase 0 — Raw data collection (DONE)

- [x] Real-time rail prediction collector (`src/collect_wmata.py`), appending with a
      `snapshot_ts` we add ourselves, since the API does not timestamp responses
- [x] Rail incident collector (`src/collect_incidents.py`), appending with `snapshot_ts`
- [x] Current weather collector (`src/collect_weather.py`), Open-Meteo, Metro Center
      coordinates, appending with `snapshot_ts`
- [x] Static GTFS rail feed download (`src/collect_gtfs.py`), dated per download
- [x] GTFS-Realtime collector (`src/collect_gtfs_rt.py`) — trip updates, vehicle
      positions and alerts, stored as gzipped raw protobuf
- [x] Train position collector (`src/collect_train_positions.py`)
- [x] Single entry point running all six (`src/main.py`), with per-collector failure
      isolation
- [x] API key handling via git-ignored `.env`, with a committed `.env.example`
- [x] Repo hygiene: `requirements.txt`, tracked `data/raw/` and `data/processed/`
      directories, documented schemas in the README

**What this means:** acquisition is written and tested for every source we might use.
Every remaining phase is either *keeping it running* or *turning snapshots into the unit
of analysis.*

---

## Decisions needed before anything else

These block or shape the work downstream. Resolve them as a group, then record the
answers in this file.

**Still open:**

- [ ] **Collection end date** — when does data collection stop so analysis can start?
      Everything downstream is sized by this.
- [ ] **24/7 or service hours only?** Metrorail runs roughly 05:00–00:00. Overnight
      collection produces almost no arrivals but keeps the pipeline simple.
- [ ] **Which machine hosts collection?** A laptop on a scheduler stops when it sleeps;
      an always-on machine is far safer. This gates starting collection.
- [ ] **Does the research question still lead with snow?** The climatology says it
      cannot be answered in this window (see *Where we are right now*). Reframing around
      rain, wind and freezing temperatures is the realistic option.
- [ ] **Owner for each phase below.**

**Resolved:**

- [x] **Snapshot cadence** — 60s for the three real-time sources, 5 min incidents,
      15 min weather, weekly GTFS. Encoded in `setup_scheduler.ps1`.
- [x] **Collect `TrainPositions` and GTFS-RT?** Yes, both, from day one. Neither can be
      backfilled, and Phase 1.3 cannot be settled without real data.
- [x] **Storage format** — daily-partitioned CSV for tabular sources, gzipped raw
      protobuf for GTFS-RT, Parquet for the processed layer.

---

## Phase 1 — Make collection continuous and reliable (URGENT)

Nothing else matters until this is done. Real-time prediction data cannot be recovered
after the fact: every hour the scheduler is not running is an hour permanently missing
from the dataset. This is the single highest-priority item in the project.

### 1.1 Scheduling
- [x] Mechanism chosen and scripted — `setup_scheduler.ps1` registers every collector as
      a Windows scheduled task, and refuses to run without a `.venv` and `.env`
- [x] Collectors written for all candidate sources, so collection can start the moment a
      key exists: predictions, GTFS-RT, train positions, incidents, weather, GTFS static
- [x] `src/verify_access.py` — probes every endpoint and reports which the key can reach
- [x] **Run it.** 12-hour pilot collected 23–24 Oct 2026 (`data/pilot/WMATA_12h_pilot.zip`)
- [ ] **Fix the duplicate firing.** Every cycle is collected twice, 2–3 seconds apart
      (see finding 4). Check for a double-registered task in `setup_scheduler.ps1`
- [x] Cadence per source, encoded in `setup_scheduler.ps1`:
      - predictions, GTFS-RT, train positions: every 60s
      - incidents: every 5 min
      - weather: every 15 min (Open-Meteo refreshes roughly this often; faster is waste)
      - GTFS static: weekly
- [ ] Confirm it survives sleep/reboot on whichever machine hosts it
- [ ] Verify the WMATA rate budget: the free tier is limited (commonly 10 calls/sec and
      50,000/day). At 60s cadence, predictions cost ~1,440 calls/day — comfortably
      inside the cap, but confirm against your key's actual tier before raising cadence.

> **Trade-off worth discussing:** a laptop on cron is simplest but dies when the laptop
> does. GitHub Actions runs unattended but its scheduled jobs are best-effort and can be
> delayed under load, which adds jitter to `snapshot_ts`. A always-on machine is the
> safest if anyone has one.

### 1.2 Robustness (DONE)
- [x] Per-collector failure isolation in `main.py` — one source failing no longer stops
      the rest
- [x] Retry with backoff on transient HTTP failures, skipping retries on 401/403/404
      where retrying is pointless
- [x] Rotating file logging to `logs/` — stdout is lost under a scheduler
- [x] Failures logged with tracebacks, so gaps in the series are explainable later

### 1.3 Evaluate richer real-time sources — time-sensitive, high value
`GetPrediction` returns no train identifier, which is what makes arrival reconstruction
(Phase 2) hard and approximate. There are two better options, and **both must be
evaluated before collection starts**, because neither can be backfilled.

**a. GTFS-Realtime rail feeds.** The Mobility Database catalog lists three rail GTFS-RT
feeds alongside the static one:

| Feed | URL |
|---|---|
| Trip updates | `https://api.wmata.com/gtfs/rail-gtfsrt-tripupdates.pb` |
| Vehicle positions | `https://api.wmata.com/gtfs/rail-gtfsrt-vehiclepositions.pb` |
| Alerts | `https://api.wmata.com/gtfs/rail-gtfsrt-alerts.pb` |

This could **collapse most of Phase 2**. GTFS-RT `TripUpdates` are keyed by `trip_id`,
which joins directly to `stop_times.txt` — meaning observed and scheduled arrival come
from the same identifier and scheduled headway needs no inference at all. Supporting
evidence: `trips.txt` already carries `train_id` and `scheduled_trip_id` columns, so WMATA
is clearly tracking individual trains through the schedule.

- [ ] Fetch each feed and inspect it (needs `gtfs-realtime-bindings` + `protobuf`)
- [ ] Check whether `TripUpdates` carries actual arrival times or only predictions
- [ ] Confirm `trip_id` values match the static feed's
- [ ] **If this works, prefer it over countdown reconstruction** and rewrite Phase 2
      around it — reserve the prediction board as a fallback and cross-check

**b. The `TrainPositions` REST endpoint** — documented as including a train ID, track
circuit ID, line, direction, destination, and seconds-at-location.

- [x] Run `python src/check_train_positions.py` once the key arrives
- [x] If it carries a stable train ID, add a collector — useful for identity even if
      GTFS-RT covers arrivals. `src/collect_train_positions.py` ran through the pilot:
      134,108 rows carrying `TrainId`, `CircuitId` and `SecondsAtLocation`, with
      `LineCode`/`DestinationStationCode` missing on 5.55%
- [ ] **Decide whether train positions improve reconstruction.** Arrival reconstruction
      currently uses predictions only and already matches 98% of scheduled trips. Train
      IDs could confirm identity across snapshots, but the gain is now marginal

Collect whatever proves useful from day one, even before the processing code exists.
Reconstruction can be written later; the data to feed it only exists in real time.

### 1.4 Storage
- [x] Daily partitioning — every CSV collector writes `<name>_<YYYY-MM-DD>.csv`, and the
      GTFS-RT collector writes under `gtfs_rt/<feed>/<date>/`
- [x] GTFS-RT stored as gzipped raw protobuf: decoding is a schema assumption, and a
      wrong one loses data permanently, while raw bytes can be re-parsed any number of
      times
- [x] Raw data stays out of git
- [x] **Measure actual growth after day one.** Measured on the pilot: 752,791 prediction
      rows (~64 MB CSV) and 3,693 GTFS-RT files in 12 hours, so roughly 1.5M rows/day at
      current cadence — but half of that is the duplicate firing in finding 4, so a fixed
      collector should produce ~750k rows/day. ~100 MB/day uncompressed in total
- [ ] Exclude `data/` from OneDrive sync — per-minute appends in a synced folder cause
      sync churn and can lock files mid-write

> This directory is inside OneDrive. Continuous appends to large files in a synced folder
> can cause sync churn or file locking. Check whether `data/` should be excluded from
> OneDrive sync.

---

## Phase 2 — Arrival event reconstruction (CORE TECHNICAL WORK)

This is the heart of the project and its biggest technical risk. The API gives a rolling
board of *predictions*; the unit of analysis is an *arrival*. Nobody hands you arrivals —
they have to be inferred from how predictions change across consecutive snapshots.

**The problem:** at each snapshot, for every station and platform group, you see the next
few trains with a `Min` value. There is no train ID (unless Phase 1.3 provides one). To
say "a train arrived at 14:32," you must recognize the *same* train across snapshots as
its `Min` counts down, and detect the moment it arrives.

**Implemented in `src/clean_predictions.py` and `src/reconstruct_arrivals.py`.**

- [x] **Load and normalize raw predictions.** `src/clean_predictions.py` splits `Min`
      into `minutes` + `status` (`ARR`/`BRD` → 0 with the status kept, `---` and empty →
      `no_prediction`), drops the 252 exact duplicates, classifies the `No` and `--`
      placeholder lines as non-revenue, and recovers the missing destination codes
      (finding 5)
- [x] **Define the tracking key.** `(location_code, group, line, destination_code)`.
      Only viable because the destination code is now populated on all 742,584 revenue
      rows — at 49% missing it would have been unusable
- [x] **Link observations across snapshots.** Not by `Min` decrement, which finding 6
      rules out. Observations are linked where `snapshot_ts + minutes` stays stable
      within a 3-minute tolerance; greedy nearest-ETA matching, one observation per
      track per cycle. Duplicate snapshots are collapsed into cycles first
- [x] **Detect the arrival.** All three candidate rules implemented and the one that
      fired is recorded per row, so they can be compared rather than assumed: last `BRD`
      (20,543), last `ARR` (1,536), countdown expiring off the board (1,590)
- [x] **Assign an arrival timestamp** and record its uncertainty. `arrival_uncertainty_s`
      carries the gap to the previous observed cycle (~60s), rather than implying
      precision we do not have
- [~] **Handle the edge cases**, each of which silently corrupts headways if ignored:
      - [x] `Min` jumping upward when WMATA revises a prediction — absorbed by ETA
            tracking; the size of the revision is kept in `max_eta_jump_s`
      - [x] trains held at a platform (`BRD` persisting across many snapshots) — the
            *last* boarding cycle is the arrival, not the first
      - [x] trains vanishing without arriving — 2,887 tracks, kept with a null
            `arrival_ts` and `detection_rule="vanished"` rather than dropped
      - [x] gaps in collection producing false "disappearances" — `gap_affected` flags
            tracks a gap falls inside, ends, or starts (1,113 tracks)
      - [~] two trains to the same destination queued at the same platform — a track
            takes at most one observation per cycle, but this has not been tested
            against a known real case
      - [ ] end-of-line terminals, where arrival and departure behave differently —
            not yet examined
- [~] **Validate.** Do not proceed to headways until reconstruction is trusted — every
      downstream number inherits its errors
      - [x] **Volume vs. the schedule:** 23,669 reconstructed arrivals against 24,153
            GTFS scheduled trips in the same window = **98.0%**, and 95.7–98.6% on every
            line individually. The schedule is independent of the reconstruction, which
            makes this the strongest check available
      - [x] **Headway plausibility:** median 9.2 min, IQR 6.1–13.3, 97.9% inside the
            1–30 min band
      - [~] **By hand against raw snapshots:** one station-hour checked in full
            (A02 / group 1 / RD → B11) and both fully-observed trains matched exactly on
            timestamp and rule. Worth repeating on a terminal and a transfer station
- [x] **Output** `data/processed/arrival_events.parquet`: one row per reconstructed
      arrival, with a confidence or method flag — 26,556 tracks, 23,669 of them arrivals

### 2.1 Observed headway
- [ ] Sort arrivals by station / line / direction / time
- [ ] Observed headway = gap between consecutive arrivals
- [ ] Flag headways spanning a collection gap as unreliable rather than real
- [ ] Decide handling for the first arrival of each service day (no predecessor)

---

## Phase 3 — GTFS schedule processing

Produces the scheduled baseline that observed service is measured against.

> **Feed structure confirmed** against a mirrored copy of the rail feed
> (`reference/gtfs_notes.md`). Three things differ from the standard assumptions:
> there is **no `calendar.txt`** — only `calendar_dates.txt`, listing every service date
> explicitly; `departure_time` values **exceed 24:00:00** (observed up to `26:12:00`);
> and `route_id` is `RED`/`BLUE`/… while the prediction API uses `RD`/`BL`/….

**Implemented in `src/build_schedule.py`.**

- [x] Unzip and load `stops.txt`, `routes.txt`, `trips.txt`, `stop_times.txt`,
      `calendar_dates.txt`
- [x] Resolve the service calendar. Simpler than expected: with no `calendar.txt`, there
      are no weekly patterns to expand — map `service_id` to date directly from
      `calendar_dates.txt`. The live feed has 12 service ids over 73 dates, all
      `exception_type` 1
- [x] Handle GTFS times past midnight — parsed as offsets from the service date, not
      clock times. The live feed reaches `27:15:00` (the 2024 snapshot only went to
      `26:12:00`), and 87,670 arrivals roll into the following calendar day
- [x] Build scheduled arrivals per stop / route / direction / service date — 2,897,925
      rows, verified against an independently computed row count
- [x] **Convert to UTC across the DST change.** The feed spans 2026-11-01, so this is
      not hypothetical: verified +4h (EDT) before and +5h (EST) after. Both
      `scheduled_arrival_local` and `scheduled_arrival_utc` are stored
- [ ] **Scheduled headway** = gap between consecutive scheduled arrivals at the same
      stop / route / direction, resolved for the time window containing each observed
      arrival. A groupby over the table above, best written alongside observed headway
      (Phase 2.1) so both are computed the same way
- [ ] Note the feed version and collection date — WMATA revises schedules, and an
      arrival must be compared against the schedule in force *that day*, not the latest
      one. If the feed changes mid-collection, keep both. The pilot feed is valid
      20261022–20261030, which does cover the pilot dates, but the output does not yet
      record which feed produced it
- [x] Output `data/processed/scheduled_arrivals.parquet` (arrivals; headways still to
      come, hence the name change from `scheduled_headways.parquet`)

---

## Phase 4 — Identifier crosswalk

The four sources do not share identifiers. Nothing joins until this exists.

**Mostly solved** — `src/build_crosswalk.py` generates
`reference/station_crosswalk.csv` (125 rows) with validation that fails loudly rather
than dropping stops. Rebuild it whenever the GTFS feed is refreshed.

- [x] **Station.** `stop_times.txt` references *platform* ids, not station ids, and
      platforms encode the code cleanly as `PF_<LocationCode>_<1|2|C>`. Platforms are
      therefore the join target. This matters: station-level ids **combine** codes at the
      four transfer stations (`STN_A01_C01`, `STN_B01_F01`, `STN_D03_F03`, `STN_B06_E06`),
      so joining at station level would silently drop Metro Center, Gallery Place,
      L'Enfant Plaza and Fort Totten — four of the busiest in the system
- [x] **Line.** `RD`→`RED`, `BL`→`BLUE`, `GR`→`GREEN`, `YL`→`YELLOW`, `OR`→`ORANGE`,
      `SV`→`SILVER`, with the lines serving each platform derived from the schedule
      rather than assumed
- [x] **Shared platforms** handled — `lines_wmata` is multi-valued where several lines
      serve one platform (e.g. `PF_C01_C` → `BL;OR;SV`)
- [x] **Coverage validated** — every stop referenced by `stop_times.txt` resolves, no
      duplicate platform ids, no missing coordinates. 125 platforms / 102 location
      codes / 98 stations, matching WMATA's published counts
- [ ] **Direction — STILL OPEN, needs live data.** Platform suffix `1`/`2` is named
      "TRACK 1/2 PLATFORM" and very likely equals WMATA's `Group`, but this is a
      hypothesis, not a verified fact. **Validate against real predictions before
      trusting any headway** — a silent mismatch reverses direction for a whole line.
      Note that 79 of 102 codes have only a *center* platform serving both directions,
      so for those, direction must come from `direction_id`/destination, not the platform
- [x] Re-run against the live feed once the API key arrives — done against
      `wmata_gtfs_2026-10-23.zip`. Structure held exactly (125 platforms / 102 codes /
      98 stations, no additions or removals), but **12 platforms had the wrong lines**:
      E02–E10 are `GR;YL`, not `GR` (the Yellow Line now runs to Greenbelt — 1,607 trips
      in the live feed), and D11 is `OR;SV`. The stale crosswalk would have
      misattributed Yellow Line service at 11 stations

### 4.1 Station attributes (enables the "differs by station/line" analysis)
- [x] Station coordinates — in the crosswalk as `stop_lat`/`stop_lon`
- [ ] **Flag above-ground vs. underground segments.** This is likely the strongest
      predictor of weather sensitivity in the entire project: underground platforms are
      insulated from rain, snow, and heat, while above-ground track and rolling stock are
      not. Derive from WMATA station data or code manually — there are only 98 stations
- [x] Transfer stations flagged (`is_transfer_station`)
- [ ] Note terminals and single-track-prone segments

### Known limitation of the current crosswalk — CLOSED
It was previously built from a mirrored GTFS snapshot dated 2024-10-01. It is now built
from the live feed collected during the pilot, and the diff is recorded above. Rebuild
it whenever a newer GTFS zip is collected, since the Yellow Line change shows the line
assignments do go stale.

---

## Phase 5 — Weather processing and join

- [ ] Deduplicate — at 15-minute collection against an endpoint that updates at a similar
      rate, consecutive rows will repeat; key on the Open-Meteo `time` field, not
      `snapshot_ts`
- [ ] **Decide spatial granularity.** Currently one point (Metro Center) stands in for
      the whole system. Options: keep the single proxy and state the limitation; sample
      several points across the service area (e.g. one per line, or per outlying
      terminal); or interpolate per station. More points cost nothing in API terms but
      add pipeline complexity
- [x] **Open-Meteo archive API confirmed working** (`archive-api.open-meteo.com/v1/archive`,
      free, no key). Hourly history for arbitrary coordinates and dates.
      **Weather is therefore a solved problem and off the risk list:** gaps in
      `collect_weather.py` do not matter, and per-station weather costs nothing but
      pipeline code. The live collector is kept as ground truth and because the archive
      lags by a few days
- [ ] Decide whether to use archive data as the primary weather source and demote the
      live collector to a cross-check
- [ ] **Join to arrival events** by nearest timestamp — a backward as-of join with an
      explicit tolerance (e.g. 30 min), so an arrival never silently inherits weather
      from hours away
- [ ] **Derive features** for analysis:
      - binary conditions: raining, snowing, freezing, high wind
      - intensity bins rather than raw mm, since effects are unlikely to be linear
      - **lagged/cumulative measures** — precipitation over the prior 1h/3h, snow
        accumulation. Service impact follows accumulated conditions, not the instant
        reading; an inch of snow that fell two hours ago matters more than whether it
        happens to be falling right now. This is likely where the real signal lives
      - heat: temperature above thresholds relevant to heat restrictions
- [ ] Output `data/processed/weather_clean.parquet`

---

## Phase 6 — Incident processing and join

Incidents are the main confounder: a delay during a storm may have been caused by a
broken rail, and attributing it to weather would be wrong.

- [ ] **Collapse snapshots into incident intervals.** An open incident reappears in every
      snapshot; reduce to one row per `IncidentID` with `first_seen` / `last_seen`
- [ ] Parse `LinesAffected` — semicolon-delimited, often with stray whitespace — into
      one row per incident × line
- [ ] Classify `IncidentType` / `Description` into useful categories (mechanical, track,
      police/medical, weather-related, scheduled work)
- [ ] **Join to arrival events:** flag each arrival with any incident active on its line
      at that time
- [ ] Decide the analytical role: control variable in the model, exclusion filter, or
      both as a robustness check. **Note the subtlety:** some incidents are *caused* by
      weather, so controlling for all incidents would absorb part of the very effect
      being measured. Separate weather-caused incidents from independent ones
- [ ] Output `data/processed/incidents_clean.parquet`

---

## Phase 7 — Build the analytical dataset

- [ ] Assemble one row per arrival event joining Phases 2–6
- [ ] **Derived service metrics:**
      - headway deviation = observed − scheduled
      - excess wait time (the passenger-weighted standard, more defensible than raw
        headway difference)
      - a bunching / gapping indicator
- [ ] **Time features, DST-safe.** Everything is stored UTC; convert to
      `America/New_York` for time-of-day and peak classification. The collection period
      spans the November DST change, so naive UTC offsets will shift an hour of data into
      the wrong peak bucket
- [ ] Peak / off-peak per WMATA's own definitions; day of week; weekday vs weekend
- [ ] Write a **data dictionary** for every column — required for the deliverable and
      genuinely useful for the group
- [ ] Output `data/processed/analysis_dataset.parquet` (plus CSV if the report needs it)

---

## Phase 8 — Validation and QA

Do this before analysis, not after. A plausible-looking regression on a broken join is
the worst outcome available.

- [ ] **Collection coverage:** find gaps in `snapshot_ts`; quantify uptime; document
      every outage
- [ ] **Plausibility bounds:** headways outside roughly 1–30 minutes are suspect;
      investigate rather than silently clip
- [ ] **Volume check:** reconstructed arrivals per station per day vs. GTFS scheduled
      trips. Large shortfalls mean reconstruction is dropping trains
- [ ] **Direction check:** confirm the `Group` ↔ `direction_id` mapping against known
      geography (a train to Shady Grove should be northbound on the Red Line)
- [ ] **Join integrity:** no arrival lacking weather; no unexplained nulls; row counts
      preserved through each merge
- [ ] **Pilot validation**, per the proposal: analyze 5–10% of the target dataset end to
      end and confirm the schema holds before committing to full-scale processing
- [ ] Record schema changes the pilot forces — the proposal explicitly anticipates this

---

## Phase 9 — Exploratory data analysis

- [ ] Missingness and outlier profile across all sources
- [ ] Distribution of headway deviation overall, by line, by station, by hour
- [ ] Baseline service patterns in *good* weather — the comparison point for everything
- [x] **Weather coverage audit — DONE, and it constrains the research question.**
      Open-Meteo archive data for Metro Center, 20 Oct – 15 Dec, 2019–2025:

      | Condition | median hours | range |
      |---|---|---|
      | Rain | 121 | 100–218 |
      | Heavy rain (≥2.5 mm/h) | 18 | 14–52 |
      | **Snow** | **4** | **2–19** |
      | Freezing (≤0 °C) | 84 | 53–189 |
      | Gusts ≥40 km/h | 147 | 92–214 |

      Out of 1,368 hours. **Snow is not testable in this window** — a median of 4 hours
      cannot support any claim, and the proposal names snow first among the conditions
      investigated. Rain, wind and freezing temperatures are all well-powered. Reframe
      the question around those three, and state the snow limitation explicitly in the
      report rather than reporting a null result as if it were a finding.
- [ ] Re-run the same audit against the *actual* collection window once it closes, since
      a single season can deviate from the climatology in either direction
- [ ] Incident frequency and overlap with weather events
- [ ] Visualizations for the report

---

## Phase 10 — Analysis

Answering the research question: *how do weather conditions affect WMATA service, and how
does that differ by line, time of day, and station?*

- [ ] **Descriptive:** mean headway deviation and excess wait by weather condition, with
      uncertainty intervals
- [ ] **Modeling:** regress headway deviation on weather features, controlling for line,
      station, hour of day, day of week, and incidents. Observations within a
      station-hour are correlated, so use clustered standard errors or a mixed model —
      naive OLS will understate uncertainty
- [ ] **Heterogeneity — this is the differentiating analysis:**
      - **above-ground vs. underground** (Phase 4.1): the cleanest natural comparison
        available, and close to a built-in control group
      - by line — lines differ in how much of their track is exposed
      - by time of day — peak service has less slack to absorb disruption
      - by station — terminals and transfers behave differently
- [ ] **Robustness:** with and without incident controls; alternative arrival-detection
      rules from Phase 2; excluding low-confidence arrivals
- [ ] **State the limitations honestly:** observational data, a short collection window,
      a single weather point, approximate arrival times, and no causal identification.
      Correlation is the defensible claim, and the proposal's stated goal

---

## Phase 11 — Deliverables

- [ ] Final report / notebook: question, data, methods, results, limitations
- [ ] Reproducibility: anyone should be able to clone, install, collect, and rebuild
- [ ] Final README pass
- [ ] Data dictionary for the processed dataset
- [ ] Code cleanup and consistent structure
- [ ] Presentation materials, if required
- [ ] Confirm all course-specific submission requirements

---

## Suggested sequencing

Phase 1 is the only true emergency — it is the one task where delay destroys data that
cannot be recovered. Phases 3 and 4 depend only on the static GTFS feed, so they can be
built immediately and in parallel with collection; there is no reason to wait. Phase 2 is
the long pole and should start as soon as a few days of snapshots exist to test against.

| Order | Work | Depends on | Status |
|---|---|---|---|
| 1 | Phase 1 — **start collecting** | API key | **Done** — 12h pilot, 23–24 Oct |
| 2 | Phase 1.3 — settle the arrival source | 1 day of data | Predictions alone proved sufficient; GTFS-RT still undecoded |
| 3 | Phase 3 — GTFS parsing | GTFS zip only | **Done** — `src/build_schedule.py` |
| 4 | Phase 4.1 — above/underground | nothing | Not started; manual, start any time |
| 5 | Phase 2 — arrival reconstruction | Phase 1.3 outcome | **Done and validated** — the risk here has largely closed |
| 6 | **Extended collection** | cloud host | **Now the critical path** — nothing downstream is answerable without weather variation |
| 7 | Phase 2.1 + 3 — observed and scheduled headway | Phase 2 output | Next code to write; both are groupbys over existing tables |
| 8 | Phases 5 + 6 — weather and incidents | Phase 2 output | Parallelizable |
| 9 | Phase 7 — analytical dataset | Phases 2–6 | |
| 10 | Phase 8 — validation | Phase 7 | Gate before analysis |
| 11 | Phases 9 + 10 — EDA and analysis | Phase 8 | |
| 12 | Phase 11 — deliverables | All | |

**The sequencing has changed in one important way.** Phase 2 was the long pole and is now
done, so the critical path is no longer code — it is calendar time on the extended
collection. Everything from Phase 7 onward is blocked on having days with varied weather,
and that data only accrues in real time. Start the extended collection before writing
anything else.

Good parallel split across three people: one owns collection infrastructure (Phase 1),
one owns GTFS parsing and the crosswalk (Phases 3–4), one owns reconstruction (Phase 2).
The phases converge at Phase 7.

---

## Risk register

Carried from the proposal, updated with current status and mitigation.

| Risk | Status | Mitigation |
|---|---|---|
| Extended collection not yet running — data lost permanently | **Open, urgent** | The pilot proved the pipeline works. Every day not collecting is a day permanently missing, and the pilot caught no rain |
| Collector fires twice per cycle | **Open** | Doubles API calls and storage for no gain (finding 4). Fix `setup_scheduler.ps1` before extended collection |
| Arrival reconstruction proves unreliable | **Largely closed** | Built and validated at 98.0% of scheduled trips, 97.9% of headways plausible. Residual risk is terminals and queued trains (Phase 2 edge cases) |
| **No testable snow in the collection window** | **Confirmed** | Climatology measured (Phase 9): median 4 snow hours. Reframe around rain/wind/freezing and state the limitation |
| Rate limits / key expiry | Mitigated | ~7,500 of 50,000 daily calls; retries skip non-transient errors; failures logged |
| Missed snapshots between arrivals | Expected | 60s cadence; flag gap-spanning headways (Phase 2.1) |
| Timestamp / identifier misalignment | **Partly closed** | Crosswalk built and validated (Phase 4); `Group` ↔ direction still unverified; UTC throughout, DST-safe conversion still to do |
| Weather granularity — one point for the system | **Closed** | Archive API confirmed: any coordinates, any past date, free (Phase 5) |
| Confounding non-weather incidents | **Open** | Phase 6 controls, separating weather-caused incidents |
| Raw data volume | **Closed** | Measured on the pilot: ~100 MB/day, halving once the duplicate firing is fixed. Well within tolerance |
| Crosswalk built from a stale 2024 feed | **Closed** | Rebuilt from the live feed. It mattered: 12 platforms had the wrong lines (Phase 4) |
