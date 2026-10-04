import json
import argparse
import os
import random
import time
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

# User and track pools: ids are drawn at random (rather than derived from the record
# index) so users listen to several tracks and tracks have several listeners. The
# decreasing weights create popular tracks and users, which makes rankings and
# activity metrics informative.
USER_POOL = [f"usr_{100 + n}" for n in range(100)]
USER_WEIGHTS = [1 / (n + 5) for n in range(len(USER_POOL))]
TRACK_POOL = [f"trk_{50 + n}" for n in range(60)]
TRACK_WEIGHTS = [1 / (n + 2) for n in range(len(TRACK_POOL))]


def random_event_timestamp(now: datetime, days_back: int) -> datetime:
    """Event time: ``now`` when ``days_back`` is 0; otherwise a random instant within the last
    ``days_back + 1`` days (today included), never in the future. Used to backfill history
    in one go; events from earlier days reach Silver as ``LATE``."""
    if days_back <= 0:
        return now
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=random.randint(0, days_back))
    return min(day_start + timedelta(seconds=random.randint(0, 86399)), now)


def build_record(i: int, event_timestamp: datetime, batch_id: str) -> dict:
    """Build a single record of the batch, applying the data quality scenarios by index ``i``."""
    record = {
        "event_id": f"evt_{batch_id}_{i}",
        "batch_id": batch_id,
        "user_id": random.choices(USER_POOL, weights=USER_WEIGHTS)[0],
        "track_id": random.choices(TRACK_POOL, weights=TRACK_WEIGHTS)[0],
        "platform": "spotify_clone",
        "duration_played_sec": 180 + i,
        "timestamp": event_timestamp.strftime("%Y-%m-%dT%H:%M:%S%z")
    }

    # Simulates a required attribute that is null in part of the records.
    if i % 3 == 0:
        record["user_id"] = None

    # Simulates schema evolution with an additional attribute.
    if i % 4 == 0:
        record["device_type"] = random.choice(["mobile", "desktop", "smart_tv"])

    # Simulates a key that is missing entirely from the payload.
    if i % 7 == 0 and "user_id" in record:
        del record["user_id"]

    # Simulates a type inconsistency in one specific record.
    if i == 9:
        record["duration_played_sec"] = "INVALID_DURATION"

    # Simulates a duration value outside the expected domain.
    if i % 5 == 0 and i != 0:
        record["duration_played_sec"] = -10

    # Simulates late events and events with a future timestamp. The late divisor (13) is
    # coprime with the other scenarios so it does not always coincide with a null
    # user_id (i % 3) or a present device_type (i % 4).
    if i % 13 == 0 and i != 0:
        delayed_timestamp = event_timestamp - timedelta(days=2)
        record["timestamp"] = delayed_timestamp.strftime("%Y-%m-%dT%H:%M:%S%z")
    elif i % 11 == 0:
        future_timestamp = event_timestamp + timedelta(days=1)
        record["timestamp"] = future_timestamp.strftime("%Y-%m-%dT%H:%M:%S%z")

    # Simulates empty attributes instead of null or missing ones.
    if i % 10 == 0 and i != 0:
        record["track_id"] = ""
        record["platform"] = ""

    return record


def generate_simulated_data(
    output_dir: str = "/Volumes/databricks_course_ws_new/landing/events_volume",
    num_files: int = 5,
    min_records: int = 10,
    max_records: int = 25,
    interval_sec: int = 5,
    days_back: int = 0,
):
    """
    Generate JSON Lines files with controlled data quality variations.

    The generated data includes null values, missing attributes, schema evolution,
    inconsistent types, out-of-order events and conflicting duplicates to exercise
    the pipeline.

    ``days_back`` > 0 spreads the event timestamps over the last N days (history backfill).

    ``interval_sec`` must be >= 1: the file name has one-second resolution, so a
    smaller interval would overwrite the previous file.
    """
    if min_records > max_records:
        raise ValueError("min_records cannot be greater than max_records")
    if interval_sec < 1:
        raise ValueError("interval_sec must be >= 1 (the file name has one-second resolution)")
    if days_back < 0:
        raise ValueError("days_back cannot be negative")

    os.makedirs(output_dir, exist_ok=True)

    tz_local = ZoneInfo("America/Sao_Paulo")

    for file_nr in range(num_files):
        records = []
        batch_size = random.randint(min_records, max_records)
        batch_id = uuid4().hex

        for i in range(batch_size):
            event_timestamp = random_event_timestamp(datetime.now(tz_local), days_back)
            records.append(build_record(i, event_timestamp, batch_id))

        # Adds a conflicting duplicate to exercise the Silver tie-break rule.
        if len(records) > 0:
            duplicate_record = records[0].copy()
            duplicate_record["duration_played_sec"] = 999999
            duplicate_record["user_id"] = "usr_conflict"
            records.append(duplicate_record)

        # Identifies the batch with the São Paulo local time.
        timestamp_str = datetime.now(tz_local).strftime("%Y-%m-%dT%H%M%S%z")
        file_path = os.path.join(output_dir, f"eventos_com_caos_{timestamp_str}.json")

        # Writes one JSON record per line to make incremental ingestion easier.
        with open(file_path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        print(f"File {file_nr + 1}/{num_files} saved successfully to: {file_path}")

        # Waits between batches to simulate an incremental source.
        if file_nr < num_files - 1:
            time.sleep(interval_sec)

    print("Simulation finished successfully!")

# Allows running the generator directly in the local environment or in the Databricks job.
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate JSON Lines events for the landing zone.")
    parser.add_argument("--output-dir", default="/Volumes/databricks_course_ws_new/landing/events_volume")
    parser.add_argument("--num-files", type=int, default=5)
    parser.add_argument("--min-records", type=int, default=10, help="Minimum records per file")
    parser.add_argument("--max-records", type=int, default=25, help="Maximum records per file")
    parser.add_argument("--interval-sec", type=int, default=5, help="Pause between files in seconds (>= 1)")
    parser.add_argument("--days-back", type=int, default=0, help="Spread events over the last N days (0 = only now)")
    args = parser.parse_args()
    generate_simulated_data(
        output_dir=args.output_dir,
        num_files=args.num_files,
        min_records=args.min_records,
        max_records=args.max_records,
        interval_sec=args.interval_sec,
        days_back=args.days_back,
    )