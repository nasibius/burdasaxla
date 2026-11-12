"""SQLite persistence for curated features and their validation workflow.

OSM data is re-importable and read-only; everything a human adds or verifies
(signs, markings, bus lanes, official AYNA zones, survey areas) lives here with
its source, status and timestamps. Only `verified` rows reach the rule engine.
"""
import json
import sqlite3
import threading
from datetime import datetime, timezone

from .config import DB_PATH

FEATURE_KINDS = {
    # kind: (geometry type, description)
    "sign_3_27": "point",
    "sign_3_28": "point",
    "marking_1_4": "line",
    "marking_1_10": "line",
    "bus_lane": "line",
    "official_zone": "line",
    "survey_area": "polygon",
}
STATUSES = {"pending", "verified", "rejected"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    geometry TEXT NOT NULL,          -- GeoJSON geometry, WGS84
    props TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL,            -- e.g. 'field_survey', 'ayna_official', 'ai_vision', 'demo_seed'
    source_url TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    verified_at TEXT,
    verified_by TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    feature_id INTEGER,
    detail TEXT
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path=DB_PATH):
        self.path = str(path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _row(r):
        d = dict(r)
        d["geometry"] = json.loads(d["geometry"])
        d["props"] = json.loads(d["props"] or "{}")
        return d

    def _audit(self, action, feature_id=None, detail=None):
        self._conn.execute(
            "INSERT INTO audit_log(ts, action, feature_id, detail) VALUES (?,?,?,?)",
            (_now(), action, feature_id, json.dumps(detail, ensure_ascii=False) if detail else None),
        )

    # -- CRUD ------------------------------------------------------------
    def add(self, kind, geometry, source, props=None, status="pending", source_url=None, note=None):
        if kind not in FEATURE_KINDS:
            raise ValueError(f"unknown kind {kind}")
        if status not in STATUSES:
            raise ValueError(f"unknown status {status}")
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO features(kind,status,geometry,props,source,source_url,note,created_at,verified_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (kind, status, json.dumps(geometry), json.dumps(props or {}, ensure_ascii=False), source,
                 source_url, note, _now(), _now() if status == "verified" else None),
            )
            self._audit("create", cur.lastrowid, {"kind": kind, "status": status, "source": source})
            self._conn.commit()
            return self.get(cur.lastrowid)

    def get(self, fid):
        r = self._conn.execute("SELECT * FROM features WHERE id=?", (fid,)).fetchone()
        return self._row(r) if r else None

    def list(self, status=None, kind=None):
        q, args = "SELECT * FROM features WHERE 1=1", []
        if status:
            q += " AND status=?"
            args.append(status)
        if kind:
            q += " AND kind=?"
            args.append(kind)
        q += " ORDER BY id DESC"
        return [self._row(r) for r in self._conn.execute(q, args).fetchall()]

    def set_status(self, fid, status, by="admin"):
        if status not in STATUSES:
            raise ValueError(f"unknown status {status}")
        with self._lock:
            self._conn.execute(
                "UPDATE features SET status=?, verified_at=?, verified_by=? WHERE id=?",
                (status, _now(), by, fid),
            )
            self._audit(f"set_status:{status}", fid, {"by": by})
            self._conn.commit()
        return self.get(fid)

    def update_geometry(self, fid, geometry):
        with self._lock:
            self._conn.execute("UPDATE features SET geometry=? WHERE id=?", (json.dumps(geometry), fid))
            self._audit("move", fid)
            self._conn.commit()
        return self.get(fid)

    def delete(self, fid):
        with self._lock:
            self._conn.execute("DELETE FROM features WHERE id=?", (fid,))
            self._audit("delete", fid)
            self._conn.commit()

    def audit(self, limit=50):
        rows = self._conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
