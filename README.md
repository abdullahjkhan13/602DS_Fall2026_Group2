# 602DS — WMATA Metrorail and Weather Conditions

MSML602 / DATA602 group project (Group 2: Duckwoo Kwon, Junhyung Han, Abdullah Khan).

**Research question:** How do weather conditions affect service on WMATA Metrorail, and
how does that effect differ by line, time of day, and station?

**Unit of analysis (final dataset):** one train arrival event at a WMATA station, for a
specific line and direction — with station, line, direction, arrival time, observed
headway, and scheduled headway, joined to the weather and rail incidents in effect at
that time.

Because WMATA's real-time API provides predictions rather than historical arrival records, we. eed to. econstruct actual train arrival events from repeated observations. To do this, we collect data at regular intervals and store the restuls for later analysis.
---

## Repository layout

```
602DS/
├── src/
│   ├── main.py                 # runs every collector once
│   ├── common.py               # shared config, logging, retry, CSV append
│   ├── verify_access.py        # probe all endpoints — run this first with a new key
│   ├── collect_wmata.py        # rail predictions      -> wmata_predictions_<date>.csv
│   ├── collect_train_positions.py  # train positions   -> train_positions_<date>.csv
│   ├── collect_gtfs_rt.py      # GTFS-RT feeds         -> gtfs_rt/<feed>/<date>/*.pb.gz
│   ├── collect_incidents.py    # rail incidents        -> wmata_incidents_<date>.csv
│   ├── collect_weather.py      # weather (Open-Meteo)  -> weather_<date>.csv
│   ├── collect_gtfs.py         # static GTFS feed      -> wmata_gtfs_<date>.zip
│   ├── build_crosswalk.py      # GTFS -> reference/station_crosswalk.csv
│   └── check_train_positions.py    # one-off field inspection
├── reference/                # hand-verified lookup tables (committed)
│   ├── station_crosswalk.csv # WMATA LocationCode <-> GTFS platform
│  └── gtfs_notes.md         # feed structure findings
├── notebooks/                # Jupyter Notbooks for data inspection and analysis
├── data/
│   ├── raw/                  # append-only snapshots (contents git-ignored)
│   └── processed/            # derived tables (contents git-ignored)
├── logs/                     # collector logs (git-ignored, created on first run)
├── setup_scheduler.ps1       # register/remove the Windows scheduled tasks
└── requirements.txt
```

The *contents* of `data/` are git-ignored — the directories themselves are kept in the
repo via `.gitkeep` so the collectors have somewhere to write on a fresh clone. Raw data
is not committed; collaborators regenerate it by running the collectors.

## Data Collection Setup

We completed our initial 12-hour pilot data collection on October 23–24, 2026. The collection scripts are now available for additional data collection.

To set up the collection environment, follow these steps:

1. Install the required Python packages.
2. Configure the WMATA API key.
3. Verify access to the required endpoints.
4. Run the collection scripts.

Since WMATA provides real-time data, repeated collection is necessary to build a dataset for our analysis.

## Setup

Requires Python 3.9+ and a free WMATA developer API key
(https://developer.wmata.com/). Open-Meteo needs no key.

```bash
git clone https://github.com/abdullahjkhan13/602DS.git
cd 602DS

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

Create a `.env` file in the repository root:

```
WMATA_API_KEY=your_key_here
```

`.env` is git-ignored. Do not commit your key.

## Usage

Run every collector once:

```bash
python src/main.py
```

Or run one at a time — this is what the scheduler does, since the sources need
different cadences:

```bash
python src/collect_wmata.py
```

Each collector failure is isolated: one source going down does not stop the others.
Output goes to `logs/<collector>.log` as well as the console, since stdout is lost
under a scheduler.

The three CSV collectors **append to a per-day file** (`weather_2026-10-20.csv`),
writing a header only when the day's file is created, so no single file grows unbounded.
`collect_gtfs.py` writes a dated zip per download, because an arrival has to be compared
against the schedule in force on *that* day.

To build a usable dataset these must run on a schedule — see *Scheduling* below.

---

## Data sources

## Data sources

| Source | Endpoint | Auth | Cadence |
|---|---|---|---|
| WMATA Real-Time Rail Predictions | `StationPrediction.svc/json/GetPrediction/All` | API key header | every 1 min |
| WMATA Train Positions | `TrainPositions/TrainPositions` | API key header | every 1 min |
| WMATA Rail Incidents | `Incidents.svc/json/Incidents` | API key header | every 5 min |
| WMATA Rail GTFS (static) | `gtfs/rail-gtfs-static.zip` | API key header | weekly |
| WMATA GTFS-Realtime | GTFS-RT feeds | API key header | every 1 min |
| Open-Meteo Current Conditions | `api.open-meteo.com/v1/forecast` | none | every 15 min |

Weather data is currently collected from a single location, Metro Center
(38.8983, -77.0281), and used as a system-wide reference. Collecting weather
data from additional locations may improve station-level analysis.

During our 12-hour pilot on October 23–24, 2026, we collected data from all
six sources. The collected observations are stored with timestamps for
further processing and integration.

## Raw schemas

### `data/raw/wmata_predictions.csv`

One row per predicted train arrival, per snapshot.

| Field | Type | Description |
|---|---|---|
| `Car` | string | Number of cars in the train |
| `Destination` | string | Short destination name |
| `DestinationCode` | string | Destination station code |
| `DestinationName` | string | Full destination name |
| `Group` | string | Platform / direction group ("1" or "2") |
| `Line` | string | Metrorail line code (RD, BL, YL, OR, GR, SV) |
| `LocationCode` | string | Station code |
| `LocationName` | string | Station name |
| `Min` | string | Minutes to arrival, or a status (`ARR`, `BRD`, `---`) |
| `snapshot_ts` | datetime (UTC) | When the snapshot was collected — added by us, not from the API |

`Min` is a string, not a number: `ARR` (arriving), `BRD` (boarding), and `---`
(no prediction) all appear and must be handled during processing.

### `data/raw/wmata_incidents.csv`

One row per active incident, per snapshot. An incident that stays open appears in
multiple snapshots, distinguished by `snapshot_ts`.

| Field | Type | Description |
|---|---|---|
| `IncidentID` | string | WMATA incident identifier |
| `Description` | string | Free-text description |
| `IncidentType` | string | Incident category |
| `LinesAffected` | string | Semicolon-delimited line codes |
| `DateUpdated` | datetime | Last update time reported by WMATA |
| `snapshot_ts` | datetime (UTC) | When the snapshot was collected |

### `data/raw/weather.csv`

One row per snapshot.

| Field | Type | Description |
|---|---|---|
| `time` | datetime (UTC) | Observation time reported by Open-Meteo |
| `temperature_2m` | float | Air temperature at 2 m (°C) |
| `precipitation` | float | Total precipitation (mm) |
| `rain` | float | Rain (mm) |
| `snowfall` | float | Snowfall (cm) |
| `wind_speed_10m` | float | Wind speed at 10 m (km/h) |
| `wind_gusts_10m` | float | Wind gusts at 10 m (km/h) |
| `weather_code` | int | WMO weather interpretation code |
| `latitude` / `longitude` | float | Query location (Metro Center) |
| `snapshot_ts` | datetime (UTC) | When the snapshot was collected |

### `data/raw/wmata_gtfs.zip`

Standard GTFS static feed — `stops.txt`, `routes.txt`, `trips.txt`, `stop_times.txt`,
`calendar.txt`, and related files. `stop_times.txt` is the source of scheduled headways;
`stops.txt` maps GTFS stop IDs to WMATA station codes and provides station coordinates.

---

## Status

Full plan, phase by phase, in [ROADMAP.md](ROADMAP.md). Summary:

### Done — raw collection
- [x] Real-time rail predictions, appended with `snapshot_ts`
- [x] Rail incidents, appended with `snapshot_ts`
- [x] Current weather from Open-Meteo, appended with `snapshot_ts`
- [x] Static GTFS feed download
- [x] Single entry point (`src/main.py`) running all six, with failure isolation
- [x] Reliability: retries, rotating logs, daily-partitioned files, scheduler script
- [x] Crosswalk built and validated (`reference/station_crosswalk.csv`)

### Next — processing and analysis
- [ ] **Scheduling.** Automate `src/main.py` so snapshots accumulate; nothing useful can
      be derived from a handful of manual runs.
- [ ] **Arrival event reconstruction.** Collapse consecutive prediction snapshots into
      discrete arrival events (e.g. detect the `Min` countdown reaching `ARR`/`BRD`, or
      a train disappearing from the board) keyed by station, line, direction, and
      destination. This is the core transformation and the main technical risk.
- [ ] **Observed headway.** Difference between consecutive reconstructed arrivals at the
      same station / line / direction.
- [ ] **Scheduled headway.** Parse `stop_times.txt` + `calendar.txt` from the GTFS zip,
      resolve the service calendar for each date, and compute the scheduled gap for the
      matching time window.
- [ ] **Station identifier crosswalk.** Map WMATA `LocationCode` to GTFS `stop_id` —
      the two feeds do not use the same identifiers.
- [ ] **Joins.** Attach weather (nearest snapshot in time) and incidents (active on the
      line at the arrival time) to each arrival event.
- [ ] **Time handling.** Everything is stored in UTC; local time of day and peak/off-peak
      classification need `America/New_York` with DST handled correctly.
- [ ] **Analysis.** Delay/headway deviation vs. weather, broken out by line, station, and
      time of day.
- [ ] **Pilot validation.** Confirm the schema holds and the three sources actually join,
      per the pilot plan in the proposal.

### Known gaps in the current code
- No `.env.example`.
- No deduplication. Sampling faster than a source updates appends near-duplicate rows —
  weather especially, where the Open-Meteo `time` field repeats while `snapshot_ts`
  advances. Dedup is deferred to processing, and must key on the source's own timestamp
  rather than `snapshot_ts`.
- No tests.

## Scheduling

Each source is scheduled separately, because they need different cadences:

| Collector | Cadence | Why |
|---|---|---|
| `collect_wmata.py` | 1 min | Arrival reconstruction needs to see `Min` count down |
| `collect_gtfs_rt.py` | 1 min | Trip updates are the likely primary arrival source |
| `collect_train_positions.py` | 1 min | Train identity between snapshots |
| `collect_incidents.py` | 5 min | Incidents last minutes to hours |
| `collect_weather.py` | 15 min | Open-Meteo refreshes about this often |
| `collect_gtfs.py` | weekly | Static schedule changes rarely |

At these rates the WMATA calls total roughly 7,500/day, inside the free tier's
50,000/day with room to spare.

Three real-time sources run at once deliberately: it is not yet settled which gives the
most reliable arrival times (see [ROADMAP.md](ROADMAP.md) Phase 1.3), and that question
can only be answered with real data. Collecting all three costs little; choosing wrong
and finding out in December costs the project.

### Windows

```powershell
.\setup_scheduler.ps1            # register all tasks
.\setup_scheduler.ps1 -Remove    # unregister them
```

The script refuses to run without a `.venv` and a `.env`, so it cannot silently register
tasks that would fail every minute. It uses `.venv\Scripts\pythonw.exe` rather than a
Microsoft Store Python — the `WindowsApps` interpreter aliases are unreliable under Task
Scheduler — and `pythonw` avoids a console window popping up every minute.

Task Scheduler skips a run if the previous one is still going, so overlapping appends
cannot corrupt a file. It does **not** catch up on runs missed while the machine is
asleep — disable sleep on the collecting machine, or accept the gaps and flag them
during validation.

### macOS / Linux (cron)

```cron
* * * * *    cd /path/to/602DS && .venv/bin/python src/collect_wmata.py
*/5 * * * *  cd /path/to/602DS && .venv/bin/python src/collect_incidents.py
*/15 * * * * cd /path/to/602DS && .venv/bin/python src/collect_weather.py
0 4 * * 0    cd /path/to/602DS && .venv/bin/python src/collect_gtfs.py
```

### Verifying it runs

```bash
tail -f logs/wmata_predictions.log     # should gain a line each minute
ls -la data/raw/                       # files should be growing
```

## Risks

Carried over from the proposal, with current status:

- **Rate limits.** The free WMATA tier is capped (10 calls/sec, 50,000/day by default).
  High-cadence collection should stay well within this, but the budget should be checked
  before raising cadence.
- **Missing snapshots.** Arrivals between snapshots are invisible, so some events will
  be missed and headways will be over-estimated for those gaps.
- **Timestamp and identifier alignment.** The four sources use different identifiers and
  time conventions; the crosswalk and UTC/local handling above address this.
- **Weather granularity.** One grid point stands in for the whole system; a storm cell
  over one line will be misattributed system-wide.
- **Confounding events.** Delays from mechanical failure, staffing, or scheduled track
  work must be separated out using the incident feed before attributing anything to
  weather.
