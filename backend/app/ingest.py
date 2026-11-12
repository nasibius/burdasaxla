"""Import real traffic-sign / road-marking observations into the validation queue.

Sources, in the order the project investigates them:
  1. Official datasets (AYNA): no machine-readable dataset was found on ayna.gov.az
     (checked 2026-11-12); official zones are entered manually with their source URL.
  2. OpenStreetMap: traffic_sign=* nodes and parking:*:restriction tags.
  3. Mapillary: map features (signs) whose position Mapillary computed from several images.
  4. Geotagged photographs / field observations (GeoJSON bulk import or the admin panel).

Rules that every importer follows:
  * Nothing is invented: if a source has no data, the importer creates nothing.
  * Everything enters as `pending` with a traceable source (source + source_ref and/or URL).
  * A camera's GPS position is never used as the sign position (see photo_metadata()).
"""
from __future__ import annotations

import io
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .citymodel import SIDES, to_ll_coords, to_m_point
from .store import FEATURE_KINDS, Store

# OSM traffic_sign values: "AZ:3.27", "RU:3.27" (same Vienna-convention numbering), "3.27", several separated by ; or ,
_SIGN_RE = re.compile(r"(?:^|[;,]\s*)(?:[A-Z]{2}:)?(3\.2[78])(?=$|[\[;,\s])")
SIGN_KIND = {"3.27": "sign_3_27", "3.28": "sign_3_28"}


def _today():
    return datetime.now(timezone.utc).date().isoformat()


# ---------------------------------------------------------------- OSM
def osm_candidates(model) -> list[dict]:
    """Sign nodes and restriction tags present in the OSM snapshot (may legitimately be empty)."""
    out = []
    for nid, el in model.nodes.items():
        t = el.get("tags", {})
        val = t.get("traffic_sign") or ""
        for code in _SIGN_RE.findall(val):
            props = {"osm_tags": t}
            direction = t.get("traffic_sign:direction") or t.get("direction")
            ways = [w for w in (model.ways.get(i) for i in model.node_ways.get(nid, ())) if w]
            if ways and direction in ("forward", "backward"):
                # sign mapped on the road: it faces traffic going `direction` along that way
                w = ways[0]
                want = "fwd" if direction == "forward" else "bwd"
                props["side"] = next((s for s in SIDES if w.travel(s) == want), None)
            out.append({"kind": SIGN_KIND[code], "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
                        "source": "osm", "source_ref": f"node/{nid}",
                        "source_url": f"https://www.openstreetmap.org/node/{nid}",
                        "note": f"OSM traffic_sign={val}", "props": props})
    for w in model.ways.values():
        t = w.tags
        for side in SIDES:
            vals = {t.get(f"parking:{side}:restriction"), t.get("parking:both:restriction"),
                    t.get(f"parking:lane:{side}"), t.get("parking:lane:both")}
            if "no_stopping" not in vals:
                continue
            a, b = w.curb_point(0.5, side), w.curb_point(w.length - 0.5, side)
            out.append({"kind": "observed_prohibition",
                        "geometry": {"type": "LineString", "coordinates": to_ll_coords([(a.x, a.y), (b.x, b.y)])},
                        "source": "osm", "source_ref": f"way/{w.id}:{side}",
                        "source_url": f"https://www.openstreetmap.org/way/{w.id}",
                        "note": "OSM parking restriction no_stopping — confirm the sign/marking and the legal clause",
                        "props": {"side": side, "clause": None}})
    return out


# ------------------------------------------------------------ Mapillary
MAPILLARY_API = "https://graph.mapillary.com/map_features"
MAPILLARY_CLASSES = {
    # Mapillary traffic-sign classes -> candidate Azerbaijani sign. Equivalence must be confirmed by a reviewer.
    "regulatory--no-stopping": "sign_3_27",
    "regulatory--no-parking": "sign_3_28",
}


def mapillary_class_to_kind(object_value: str):
    for prefix, kind in MAPILLARY_CLASSES.items():
        if object_value.startswith(prefix + "--") or object_value == prefix:
            return kind
    return None


def fetch_mapillary(token: str, bbox, opener=urllib.request.urlopen) -> list[dict]:
    """Traffic-sign map features in bbox (S, W, N, E). Their geometry is Mapillary's triangulated
    sign position (computed from several images), not a camera location."""
    s, w, n, e = bbox
    q = urllib.parse.urlencode({
        "access_token": token, "bbox": f"{w},{s},{e},{n}", "limit": 2000,
        "fields": "id,object_value,object_type,geometry,aligned_direction,first_seen_at,last_seen_at,images",
    })
    with opener(f"{MAPILLARY_API}?{q}", timeout=60) as r:
        payload = json.load(r)
    return payload.get("data", [])


def mapillary_candidates(features: list[dict]) -> list[dict]:
    out = []
    for f in features:
        kind = mapillary_class_to_kind(f.get("object_value", ""))
        if not kind or (f.get("geometry") or {}).get("type") != "Point":
            continue
        images = [i.get("id") for i in ((f.get("images") or {}).get("data") or []) if i.get("id")]
        out.append({"kind": kind, "geometry": f["geometry"], "source": "mapillary", "source_ref": str(f["id"]),
                    "source_url": f"https://www.mapillary.com/app/?focus=map&mapFeatureKey={f['id']}",
                    "note": f"Mapillary detection {f.get('object_value')} — confirm it is an Azerbaijani "
                            f"{'3.27' if kind == 'sign_3_27' else '3.28'} sign and check its side/plates",
                    "props": {"mapillary_class": f.get("object_value"), "aligned_direction": f.get("aligned_direction"),
                              "first_seen_at": f.get("first_seen_at"), "last_seen_at": f.get("last_seen_at"),
                              "image_ids": images[:10], "position_method": "mapillary_triangulated"}})
    return out


# -------------------------------------------------------------- GeoJSON
def geojson_candidates(fc: dict, default_source="field_survey") -> list[dict]:
    """FeatureCollection from a field-survey tool. Each feature needs properties.kind and a source reference
    (source_ref, source_url or photo_url); observer and observed_at are recorded."""
    out, errors = [], []
    for i, f in enumerate(fc.get("features", [])):
        p = dict(f.get("properties") or {})
        kind = p.pop("kind", None)
        if kind not in FEATURE_KINDS:
            errors.append(f"feature {i}: unknown kind {kind!r}")
            continue
        ref = p.pop("source_ref", None) or p.get("photo_url")
        url = p.pop("source_url", None)
        if not (ref or url):
            errors.append(f"feature {i}: needs source_ref, source_url or photo_url")
            continue
        out.append({"kind": kind, "geometry": f.get("geometry"), "source": p.pop("source", default_source),
                    "source_ref": ref, "source_url": url, "note": p.pop("note", None),
                    "observer": p.pop("observer", None), "observed_at": p.pop("observed_at", None), "props": p})
    return out, errors


# ---------------------------------------------------------------- photos
def _ratio(x):
    try:
        return float(x)
    except TypeError:
        return x[0] / x[1] if x[1] else 0.0


def photo_metadata(data: bytes) -> dict:
    """Camera position, heading and time from EXIF. This is where the photo was TAKEN — the sign itself
    stands somewhere in the view, so the reviewer places the sign on the map separately."""
    from PIL import ExifTags, Image
    meta = {"camera": None, "taken_at": None, "exif": {}}
    try:
        img = Image.open(io.BytesIO(data))
        exif = img.getexif()
    except Exception:  # noqa: BLE001 - not an image / no EXIF
        return meta
    base = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
    sub = exif.get_ifd(0x8769) if hasattr(exif, "get_ifd") else {}
    taken = {ExifTags.TAGS.get(k, k): v for k, v in sub.items()}.get("DateTimeOriginal") or base.get("DateTime")
    if taken:
        meta["taken_at"] = str(taken).replace(":", "-", 2)
    gps = {ExifTags.GPSTAGS.get(k, k): v for k, v in exif.get_ifd(0x8825).items()} if hasattr(exif, "get_ifd") else {}
    try:
        def deg(v, ref):
            d = _ratio(v[0]) + _ratio(v[1]) / 60 + _ratio(v[2]) / 3600
            return -d if ref in ("S", "W") else d
        lat = deg(gps["GPSLatitude"], gps.get("GPSLatitudeRef", "N"))
        lon = deg(gps["GPSLongitude"], gps.get("GPSLongitudeRef", "E"))
        heading = _ratio(gps["GPSImgDirection"]) if "GPSImgDirection" in gps else None
        meta["camera"] = {"lon": round(lon, 7), "lat": round(lat, 7),
                          "heading": round(heading, 1) if heading is not None else None}
    except (KeyError, TypeError, IndexError, ZeroDivisionError):
        pass
    meta["exif"] = {k: str(v)[:80] for k, v in base.items() if k in ("Make", "Model", "DateTime", "Software")}
    return meta


def sign_at_camera_position(feature: dict, evidence: list[dict], tolerance_m=1.0) -> bool:
    """True if a point sign sits exactly where a photo was taken — i.e. the camera GPS was used as the sign position."""
    if feature["geometry"]["type"] != "Point":
        return False
    sp = to_m_point(*feature["geometry"]["coordinates"])
    for ev in evidence:
        has_camera = ev.get("camera_lon") is not None and ev.get("camera_lat") is not None
        if has_camera and sp.distance(to_m_point(ev["camera_lon"], ev["camera_lat"])) < tolerance_m:
            return True
    return False


# ----------------------------------------------------------------- write
def enqueue(store: Store, candidates: list[dict], observer: str) -> dict:
    """Insert candidates as pending observations, skipping ones already imported (same source + source_ref)."""
    created, skipped = [], 0
    for c in candidates:
        if c.get("source_ref") and store.find_by_source_ref(c["source"], c["source_ref"]):
            skipped += 1
            continue
        row = store.add(c["kind"], c["geometry"], c["source"], c.get("props") or {}, "pending", c.get("source_url"),
                        c.get("note"), source_ref=c.get("source_ref"), observer=c.get("observer") or observer,
                        observed_at=c.get("observed_at") or _today())
        created.append(row["id"])
    return {"created": len(created), "skipped_duplicates": skipped, "ids": created}


__all__ = ["osm_candidates", "fetch_mapillary", "mapillary_candidates", "geojson_candidates", "photo_metadata",
           "sign_at_camera_position", "enqueue"]
