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
│   |── check_train_positions.py    # one-off field inspection
│   └── pilot_12h.py
├── reference/                # hand-verified lookup tables (committed)
│   ├── station_crosswalk.csv # WMATA LocationCode <-> GTFS platform
│  └── gtfs_notes.md         # feed structure findings
├── notebooks/                # Jupyter Notbooks for data inspection and analysis
│   └── WMATA_Data_Integration_Feasibility.ipynb
├── data/
│   ├── raw/                  # append-only snapshots (contents git-ignored)
│   ├── processed/            # derived tables (contents git-ignored)
|   └── WMATA_12h_pilot.zip
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

### `data/raw/wmata_predictions_<date>.csv`

One row per predicted train arrival at a station, per snapshot.

| Field | Type | Description |
|---|---|---|
| `Car` | string | Number of cars |
| `Destination` | string | Short destination name |
| `DestinationCode` | string | Destination station code |
| `DestinationName` | string | Full destination name |
| `Group` | string | Platform / direction group |
| `Line` | string | Metrorail line code |
| `LocationCode` | string | Station code |
| `LocationName` | string | Station name |
| `Min` | string | Minutes to arrival or status (`ARR`, `BRD`, `---`) |
| `snapshot_ts` | datetime (UTC) | Time when the data was collected |

During our pilot, we found non-numeric values in the `Min` column, including `ARR`, `BRD`, and `---`. These values will need to be handled during preprocessing.

### `data/raw/train_positions_<date>.csv`

One row per reported train position, per snapshot.

| Field | Type | Description |
|---|---|---|
| `TrainId` | string | Train identifier |
| `TrainNumber` | string | Train number |
| `CarCount` | integer | Number of cars |
| `DirectionNum` | integer | Train direction |
| `CircuitId` | integer | Track circuit identifier |
| `DestinationStationCode` | string | Destination station code |
| `LineCode` | string | Metrorail line code |
| `ServiceType` | string | Type of train service |
| `snapshot_ts` | datetime (UTC) | Time when the data was collected |

This dataset will help us track train movements and reconstruct arrival events.

### `data/raw/wmata_incidents_<date>.csv`

One row per active rail incident, per snapshot.

| Field | Type | Description |
|---|---|---|
| `IncidentID` | string | Incident identifier |
| `Description` | string | Incident description |
| `IncidentType` | string | Incident category |
| `LinesAffected` | string | Affected Metrorail lines |
| `DateUpdated` | datetime | Last update reported by WMATA |
| `snapshot_ts` | datetime (UTC) | Time when the data was collected |

The same incident may appear in multiple snapshots if it remains active.

### `data/raw/weather_<date>.csv`

One row per weather collection snapshot.

| Field | Type | Description |
|---|---|---|
| `time` | datetime (UTC) | Weather observation time |
| `temperature_2m` | float | Temperature (°C) |
| `precipitation` | float | Total precipitation (mm) |
| `rain` | float | Rainfall (mm) |
| `snowfall` | float | Snowfall (cm) |
| `wind_speed_10m` | float | Wind speed (km/h) |
| `wind_gusts_10m` | float | Wind gust speed (km/h) |
| `weather_code` | integer | Weather condition code |
| `latitude` | float | Latitude |
| `longitude` | float | Longitude |
| `snapshot_ts` | datetime (UTC) | Time when the data was collected |

Weather observations may have repeated timestamps because our collection frequency is higher than the weather update frequency.

### Static GTFS

Static GTFS data contains station, route, trip, and schedule information.

| File | Description |
|---|---|
| `stops.txt` | Station and stop information |
| `routes.txt` | Metrorail routes |
| `trips.txt` | Scheduled trips |
| `stop_times.txt` | Scheduled arrival and departure times |
| `calendar.txt` | Service schedules |
| `calendar_dates.txt` | Service exceptions |

We use GTFS station information to match WMATA station codes and plan to use scheduled stop times to calculate scheduled headways.

### `data/raw/gtfs_rt/`

GTFS-Realtime data is stored as compressed Protocol Buffer files (`.pb.gz`).

These files contain real-time transit updates that may help us reconstruct train arrival events.

During our 12-hour pilot, we collected approximately 3,695 GTFS-Realtime files. Further processing is needed before integrating this data into our final dataset.

## Status

Full plan, phase by phase, in [ROADMAP.md](ROADMAP.md). Summary:

### Done — data collection and pilot validation

- [x] Real-time rail predictions collected with `snapshot_ts`
- [x] Train positions collected with `snapshot_ts`
- [x] Rail incidents collected with `snapshot_ts`
- [x] Weather data collected from Open-Meteo
- [x] Static GTFS feed downloaded
- [x] GTFS-Realtime data collected
- [x] Single entry point (`src/main.py`) for running all six collectors
- [x] Collection scripts include retries, logging, and daily-partitioned files
- [x] Station crosswalk created (`reference/station_crosswalk.csv`)
- [x] Completed a 12-hour pilot collection (October 23–24, 2026)
- [x] Checked missing values, duplicates, and timestamp consistency
- [x] Tested WMATA–GTFS station matching and WMATA–weather timestamp alignment

### Pilot results

Our 12-hour pilot collected:

- 752,791 WMATA prediction records
- 134,108 train position records
- 97 weather records
- 63 rail incident records
- Approximately 3,695 GTFS-Realtime files
- Static GTFS data containing 2,176 stops and 14,228 trips

We also tested data integration using a Jupyter Notebook.

- WMATA–GTFS station matching: 94 out of 102 station codes matched (92.16%).
- WMATA–weather timestamp matching: 752,791 out of 752,791 prediction records matched (100%) using a one-hour backward tolerance.

These results suggest that the datasets can be connected for further analysis. However, timestamp matching does not confirm actual train arrivals.

### Next — extended collection and analysis

- [ ] **Extended data collection.** Run the collectors for approximately seven days to capture more variation in weather and train service.
- [ ] **Arrival event reconstruction.** Use consecutive prediction snapshots to estimate actual train arrivals based on `Min`, `ARR`, `BRD`, and train movements.
- [ ] **Observed headway.** Calculate the time between consecutive reconstructed arrivals at the same station, line, and direction.
- [ ] **Scheduled headway.** Use GTFS schedules to calculate expected arrival intervals.
- [ ] **Station identifier matching.** Investigate the eight WMATA station codes that did not match GTFS station IDs.
- [ ] **Data cleaning.** Handle missing values, duplicate records, and non-numeric arrival predictions.
- [ ] **Data integration.** Join train arrival events with weather observations and rail incidents.
- [ ] **Time handling.** Convert UTC timestamps to `America/New_York` for time-of-day analysis.
- [ ] **Analysis.** Compare observed and scheduled headways under different weather conditions.

### Known gaps in the current code

- **Missing values.** Some prediction records are missing `DestinationCode`, and some train position records are missing `DestinationStationCode` or `LineCode`.
- **Non-numeric arrival predictions.** The `Min` column includes values such as `ARR`, `BRD`, and `---`, which require special handling.
- **Duplicate observations.** Repeated collection can produce duplicate or near-duplicate records, especially when the source updates less frequently than our scripts.
- **Station matching.** Eight WMATA station codes did not match GTFS station IDs during our initial test.
- **Weather coverage.** Weather is currently collected for one location near Metro Center rather than individual stations.
- **Limited weather variation.** No rainfall was recorded during the 12-hour pilot, so a longer collection period is needed.
- **Arrival reconstruction.** We have not yet converted prediction snapshots into confirmed train arrival events.
- **Testing.** Additional automated tests are needed for data cleaning and integration.

## Scheduling

The collection scripts are designed to run automatically at regular intervals. This allows us to collect continuous snapshots instead of relying on manual runs.

### Collection frequency

| Data Source | Frequency |
|---|---|
| WMATA Rail Predictions | Every 1 minute |
| WMATA Train Positions | Every 1 minute |
| WMATA GTFS-Realtime | Every 1 minute |
| WMATA Rail Incidents | Every 5 minutes |
| Open-Meteo Weather | Every 15 minutes |
| Static GTFS | Weekly |

These are our planned collection intervals. Actual intervals may vary depending on API response times, network conditions, and system availability.

### Windows — Task Scheduler

The repository includes `setup_scheduler.ps1` to configure automated collection using Windows Task Scheduler.

Run the following command in PowerShell:

```powershell
.\setup_scheduler.ps1
```

The scheduled task runs `src/main.py`, which manages the data collection scripts.

### macOS / Linux — cron

On macOS or Linux, collection can be scheduled using `cron`.

Open the crontab editor:

```bash
crontab -e
```

Example schedule:

```cron
* * * * * cd /path/to/602DS_Fall2026_Group2 && /path/to/python src/main.py >> logs/collector.log 2>&1
```

Replace `/path/to/602DS_Fall2026_Group2` with the actual project directory and `/path/to/python` with the Python executable from your environment.

This example runs `src/main.py` every minute. Individual collection frequencies should be controlled by the collection scripts or separate scheduler entries.

### Extended data collection

After completing our 12-hour pilot on October 23–24, 2026, our next step is to collect data for approximately seven days.

We plan to use a cloud-based environment for this collection to avoid interruptions caused by shutting down or disconnecting a local computer.

During the extended collection, we will check:

- Whether the collection scripts continue running without major interruptions
- Whether timestamps and collection intervals remain consistent
- Whether missing values and duplicate records increase over time
- Whether the dataset captures different weather conditions
- Whether the collected data is sufficient for train arrival reconstruction

The extended dataset will be used for further cleaning, integration, and analysis.


## Risks

- **API rate limits and connection failures.** Frequent requests to WMATA APIs may cause rate limits or temporary failures. Our collection scripts include retries and logging, but interruptions may still occur.

- **Missing snapshots.** Network issues, API downtime, or computer shutdowns may create gaps in the collected data. We plan to use a cloud-based environment for the seven-day collection to reduce interruptions.

- **Arrival event reconstruction.** WMATA provides predicted arrival times rather than a complete history of actual arrivals. We need to reconstruct arrival events from consecutive snapshots, which may introduce estimation errors.

- **Missing and duplicate data.** Our pilot identified missing station information, non-numeric arrival predictions, and duplicate observations. These issues must be addressed during preprocessing.

- **Station identifier matching.** WMATA and GTFS use different station identifiers. Our initial test matched 94 out of 102 WMATA station codes (92.16%), leaving eight codes that require further investigation.

- **Weather data limitations.** Weather observations currently represent a single location near Metro Center. Conditions may differ across stations, and our 12-hour pilot did not capture rainfall.

- **Timestamp alignment.** Although all WMATA prediction records were matched with weather timestamps during our pilot, this does not guarantee that the observations represent exactly the same moment.

- **Confounding factors.** Train delays may also be affected by incidents, maintenance, passenger demand, and time of day. We will consider these factors when analyzing the relationship between weather and Metrorail performance.

- **Limited collection period.** Seven days of data may not capture enough severe weather events or unusual service disruptions. Our findings will depend on the weather and operating conditions observed during collection.
