"""SQLite persistence for curated observations, evidence and the validation workflow.

OSM data is re-importable and read-only. Everything a human or an importer adds
(signs, markings, bus lanes, taxi stands, official AYNA zones, survey areas, other
observed prohibitions) lives here with its source, evidence and review state.
Only `verified` rows can change a curb to RED or GREEN; `pending` prohibiting rows
turn the affected curb YELLOW until reviewed.
"""
import json
import sqlite3
import threading
from datetime import datetime, timezone

from .config import DB_PATH

FEATURE_KINDS = {
    # kind: geometry type
    "sign_3_27": "point",
    "sign_3_28": "point",
    "marking_1_4": "line",
    "marking_1_10": "line",
    "bus_lane": "line",
    "taxi_stand": "line",
    "observed_prohibition": "line",
    "official_zone": "line",
    "survey_area": "polygon",
}
SOURCES = {"field_survey", "street_photo", "mapillary", "ai_vision", "osm", "ayna_official", "other_official",
           "demo_seed"}
AUTOMATED_SOURCES = {"mapillary", "ai_vision", "osm"}  # always enter as pending, need human review
STATUSES = {"pending", "verified", "rejected"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    geometry TEXT NOT NULL,          -- GeoJSON geometry, WGS84 (where the sign / marking actually is)
    props TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL,
    source_url TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    verified_at TEXT,
    verified_by TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_id INTEGER NOT NULL REFERENCES features(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    original_name TEXT,
    content_type TEXT,
    sha256 TEXT NOT NULL,
    size INTEGER,
    uploaded_at TEXT NOT NULL,
    camera_lon REAL,                 -- where the photo was TAKEN (EXIF), never used as the sign position
    camera_lat REAL,
    camera_heading REAL,
    taken_at TEXT,
    exif TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    feature_id INTEGER,
    detail TEXT
);
"""
# Columns added after v1 (migrated in place).
_NEW_COLUMNS = {
    "source_ref": "TEXT",       # e.g. node/123, mapillary map feature id, document number
    "observer": "TEXT",         # who observed / entered it
    "observed_at": "TEXT",      # when it was observed on the street (ISO date)
    "confidence": "REAL",       # detector confidence for automated sources
    "review_note": "TEXT",
    "updated_at": "TEXT",
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path=DB_PATH):
        self.path = str(path)
        # One shared connection is used from FastAPI worker threads: every read AND write takes the lock.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self):
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(features)")}
        for name, typ in _NEW_COLUMNS.items():
            if name not in cols:
                self._conn.execute(f"ALTER TABLE features ADD COLUMN {name} {typ}")
        # The v1 demo rectangle was never a real field survey: retire it so it can't make curbs GREEN.
        rows = self._conn.execute(
            "SELECT id FROM features WHERE source='demo_seed' AND status != 'rejected'").fetchall()
        for r in rows:
            self._conn.execute(
                "UPDATE features SET status='rejected', review_note=?, updated_at=? WHERE id=?",
                ("Demo placeholder, not a real field survey (retired in ruleset v2).", _now(), r["id"]))
            self._audit("retire_demo_seed", r["id"])

    # -- helpers ---------------------------------------------------------
    def _row(self, r, with_evidence=True):
        d = dict(r)
        d["geometry"] = json.loads(d["geometry"])
        d["props"] = json.loads(d["props"] or "{}")
        if with_evidence:
            d["evidence"] = self.evidence_for(d["id"])
        return d

    def _audit(self, action, feature_id=None, detail=None):
        self._conn.execute(
            "INSERT INTO audit_log(ts, action, feature_id, detail) VALUES (?,?,?,?)",
            (_now(), action, feature_id, json.dumps(detail, ensure_ascii=False) if detail else None),
        )

    # -- features --------------------------------------------------------
    def add(self, kind, geometry, source, props=None, status="pending", source_url=None, note=None, *,
            source_ref=None, observer=None, observed_at=None, confidence=None):
        if kind not in FEATURE_KINDS:
            raise ValueError(f"unknown kind {kind}")
        if status not in STATUSES:
            raise ValueError(f"unknown status {status}")
        with self._lock:
            now = _now()
            cur = self._conn.execute(
                "INSERT INTO features(kind,status,geometry,props,source,source_url,note,created_at,verified_at,"
                "source_ref,observer,observed_at,confidence,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (kind, status, json.dumps(geometry), json.dumps(props or {}, ensure_ascii=False), source,
                 source_url, note, now, now if status == "verified" else None,
                 source_ref, observer, observed_at, confidence, now),
            )
            self._audit("create", cur.lastrowid, {"kind": kind, "status": status, "source": source,
                                                  "source_ref": source_ref, "observer": observer})
            self._conn.commit()
            return self.get(cur.lastrowid)

    def get(self, fid):
        with self._lock:
            r = self._conn.execute("SELECT * FROM features WHERE id=?", (fid,)).fetchone()
            return self._row(r) if r else None

    def list(self, status=None, kind=None, with_evidence=True):
        q, args = "SELECT * FROM features WHERE 1=1", []
        if status:
            q += " AND status=?"
            args.append(status)
        if kind:
            q += " AND kind=?"
            args.append(kind)
        q += " ORDER BY id DESC"
        with self._lock:
            return [self._row(r, with_evidence) for r in self._conn.execute(q, args).fetchall()]

    def find_by_source_ref(self, source, source_ref):
        with self._lock:
            r = self._conn.execute("SELECT * FROM features WHERE source=? AND source_ref=?", (source, source_ref)).fetchone()
            return self._row(r) if r else None

    EDITABLE = {"geometry", "props", "source_url", "source_ref", "note", "observer", "observed_at", "kind"}

    def update(self, fid, by="admin", **fields):
        """Edit a feature. Any edit of a verified feature sends it back to review (status=pending)."""
        sets, args = [], []
        for k, v in fields.items():
            if k not in self.EDITABLE:
                raise ValueError(f"field {k} is not editable")
            sets.append(f"{k}=?")
            args.append(json.dumps(v, ensure_ascii=False) if k in ("geometry", "props") else v)
        if not sets:
            return self.get(fid)
        with self._lock:
            before = self.get(fid)
            sets += ["updated_at=?"]
            args += [_now()]
            if before and before["status"] == "verified":
                sets += ["status='pending'", "verified_at=NULL", "verified_by=NULL"]
            self._conn.execute(f"UPDATE features SET {', '.join(sets)} WHERE id=?", (*args, fid))
            self._audit("edit", fid, {"by": by, "fields": sorted(fields),
                                      "reopened": bool(before and before["status"] == "verified")})
            self._conn.commit()
        return self.get(fid)

    def set_status(self, fid, status, by="admin", review_note=None):
        if status not in STATUSES:
            raise ValueError(f"unknown status {status}")
        with self._lock:
            self._conn.execute(
                "UPDATE features SET status=?, verified_at=?, verified_by=?, review_note=?, updated_at=? WHERE id=?",
                (status, _now(), by, review_note, _now(), fid),
            )
            self._audit(f"set_status:{status}", fid, {"by": by, "review_note": review_note})
            self._conn.commit()
        return self.get(fid)

    def delete(self, fid):
        with self._lock:
            self._conn.execute("DELETE FROM evidence WHERE feature_id=?", (fid,))
            self._conn.execute("DELETE FROM features WHERE id=?", (fid,))
            self._audit("delete", fid)
            self._conn.commit()

    # -- evidence --------------------------------------------------------
    def add_evidence(self, feature_id, filename, original_name, content_type, sha256, size, camera=None, taken_at=None,
                     exif=None):
        camera = camera or {}
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO evidence(feature_id,filename,original_name,content_type,sha256,size,uploaded_at,"
                "camera_lon,camera_lat,camera_heading,taken_at,exif) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (feature_id, filename, original_name, content_type, sha256, size, _now(), camera.get("lon"),
                 camera.get("lat"), camera.get("heading"), taken_at, json.dumps(exif or {}, ensure_ascii=False)),
            )
            self._audit("evidence_add", feature_id, {"evidence_id": cur.lastrowid, "sha256": sha256})
            self._conn.commit()
            return self.get_evidence(cur.lastrowid)

    def get_evidence(self, eid):
        with self._lock:
            r = self._conn.execute("SELECT * FROM evidence WHERE id=?", (eid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["exif"] = json.loads(d["exif"] or "{}")
        return d

    def evidence_for(self, fid):
        with self._lock:
            rows = self._conn.execute("SELECT * FROM evidence WHERE feature_id=? ORDER BY id", (fid,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d.pop("exif", None)
            out.append(d)
        return out

    def audit(self, limit=50, feature_id=None):
        with self._lock:
            return self._audit_rows(limit, feature_id)

    def _audit_rows(self, limit, feature_id):
        if feature_id is not None:
            rows = self._conn.execute("SELECT * FROM audit_log WHERE feature_id=? ORDER BY id DESC LIMIT ?",
                                      (feature_id, limit)).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
