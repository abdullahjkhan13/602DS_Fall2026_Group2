import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

DURATION = 12 * 60 * 60

TASKS = {
    "collect_wmata.py": 60,
    "collect_train_positions.py": 60,
    "collect_gtfs_rt.py": 60,
    "collect_incidents.py": 300,
    "collect_weather.py": 900,
}

start = time.monotonic()
end = start + DURATION

next_run = {task: start for task in TASKS}

print("Starting WMATA 12-hour pilot", flush=True)

# Collect static GTFS once
subprocess.run(
    [sys.executable, str(SRC / "collect_gtfs.py")],
    cwd=ROOT,
    check=False
)

while time.monotonic() < end:

    now = time.monotonic()

    for task, interval in TASKS.items():

        if now >= next_run[task]:

            print(f"Running {task}", flush=True)

            try:
                result = subprocess.run(
                    [sys.executable, str(SRC / task)],
                    cwd=ROOT,
                    timeout=120,
                    check=False
                )

                if result.returncode != 0:
                    print(f"Error: {task} exited with {result.returncode}", flush=True)

            except subprocess.TimeoutExpired:
                print(f"Timeout: {task}", flush=True)

            next_run[task] = time.monotonic() + interval

    time.sleep(1)

print("12-hour pilot completed.", flush=True)
