"""Separate planning and aggregate activity tables in the existing SQLite database."""
import json
import sqlite3
from contextlib import contextmanager

from .planning import utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendation_runs (
    id TEXT PRIMARY KEY, generated_at TEXT NOT NULL, snapshot TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS authority_reviews (
    id INTEGER PRIMARY KEY, candidate_id TEXT NOT NULL, run_id TEXT NOT NULL,
    action TEXT NOT NULL, reason TEXT NOT NULL, actor TEXT NOT NULL, reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS passenger_activity (
    id INTEGER PRIMARY KEY, location_id TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
    source_ref TEXT NOT NULL, record TEXT NOT NULL, recorded_at TEXT NOT NULL,
    UNIQUE(location_id, period_start, period_end, source_ref)
);
"""


class PlanningStore:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def reviews(self, public=False):
        with self.connect() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM authority_reviews ORDER BY id")]
        # Review reasons and operator labels may contain private notes. Public export only exposes state/time.
        return [{k: v for k, v in r.items() if k not in ("actor", "reason")} for r in rows] if public else rows

    def save_run(self, snapshot):
        with self.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO recommendation_runs VALUES (?,?,?)",
                         (snapshot["run_id"], snapshot["generated_at"], json.dumps(snapshot, ensure_ascii=False)))

    def review(self, candidate_id, run_id, action, reason):
        with self.connect() as conn:
            conn.execute("INSERT INTO authority_reviews(candidate_id,run_id,action,reason,actor,reviewed_at) "
                         "VALUES (?,?,?,?,?,?)", (candidate_id, run_id, action, reason, "authenticated-admin-token", utc_now()))
        return self.reviews()[-1]

    def activity(self, public=True):
        with self.connect() as conn:
            rows = [json.loads(r["record"]) | {"id": r["id"]} for r in conn.execute("SELECT * FROM passenger_activity")]
        if public:
            rows = [r for r in rows if r["publication_permitted"]]
        # Rows remain individual source/period observations: never silently sum overlapping populations.
        return sorted(rows, key=lambda r: (-r["passengers_per_hour"], r["location_id"], r["period_start"]))

    def import_activity(self, records):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for record in records:
                # Replacements of exact source-period records are idempotent; overlapping windows are ambiguous.
                overlap = conn.execute(
                    "SELECT 1 FROM passenger_activity WHERE location_id=? AND source_ref=? "
                    "AND period_start < ? AND period_end > ? AND NOT (period_start=? AND period_end=?)",
                    (record["location_id"], record["source_ref"], record["period_end"], record["period_start"],
                     record["period_start"], record["period_end"])).fetchone()
                if overlap:
                    raise ValueError("Overlapping periods for the same location and source; import distinct windows")
                conn.execute("INSERT INTO passenger_activity(location_id,period_start,period_end,source_ref,record,recorded_at) "
                             "VALUES (?,?,?,?,?,?) ON CONFLICT(location_id,period_start,period_end,source_ref) "
                             "DO UPDATE SET record=excluded.record,recorded_at=excluded.recorded_at",
                             (record["location_id"], record["period_start"], record["period_end"], record["source_ref"],
                              json.dumps(record, ensure_ascii=False), utc_now()))
        return len(records)
