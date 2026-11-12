"""Download raw OpenStreetMap data for the demo area (28 May, Baku).

Tries the Overpass API first (filtered query), then falls back to the main OSM
API `/api/0.6/map` (everything in the bbox, split into tiles), converting the
XML into the same Overpass-style JSON the backend consumes.

Usage:  python scripts/fetch_osm.py [south west north east]
Writes: data/osm_raw.json
"""
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_BBOX = (40.3725, 49.8390, 40.3870, 49.8605)  # S, W, N, E around 28 May metro
UA = {"User-Agent": "BurdaSaxla-hackathon/0.1"}
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OSM_API = "https://api.openstreetmap.org/api/0.6/map"


def overpass_query(s, w, n, e):
    bb = f"({s},{w},{n},{e})"
    return f"""
[out:json][timeout:120];
(
  way["highway"]{bb};
  node["highway"~"crossing|bus_stop|traffic_signals|stop|give_way"]{bb};
  node["crossing"]{bb};
  node["public_transport"]{bb};
  way["public_transport"="platform"]{bb};
  node["traffic_sign"]{bb};
  node["railway"~"tram_stop|level_crossing"]{bb};
  nwr["amenity"]["name"]{bb};
  nwr["shop"]["name"]{bb};
  nwr["tourism"]["name"]{bb};
  nwr["office"]["name"]{bb};
  nwr["leisure"]["name"]{bb};
  nwr["building"]["name"]{bb};
  nwr["railway"="station"]{bb};
);
(._;>;);
out body;
"""


def via_overpass(bbox):
    data = urllib.parse.urlencode({"data": overpass_query(*bbox)}).encode()
    for url in OVERPASS_MIRRORS:
        try:
            req = urllib.request.Request(url, data=data, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                payload = json.load(r)
            print(f"Fetched from {url}")
            payload["source"] = url
            return payload
        except Exception as exc:  # noqa: BLE001 - try next source
            print(f"{url} failed: {exc}")
    return None


def _tile_xml(s, w, n, e, depth=0):
    url = f"{OSM_API}?bbox={w},{s},{e},{n}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
            return [r.read()]
    except urllib.error.HTTPError as exc:
        if exc.code == 400 and depth < 4:  # too many nodes -> split in 4
            mlat, mlon = (s + n) / 2, (w + e) / 2
            out = []
            for bb in ((s, w, mlat, mlon), (s, mlon, mlat, e), (mlat, w, n, mlon), (mlat, mlon, n, e)):
                out += _tile_xml(*bb, depth=depth + 1)
            return out
        raise


def via_osm_api(bbox):
    s, w, n, e = bbox
    # split into a 2x2 grid up front to stay well under the API's node limit
    mlat, mlon = (s + n) / 2, (w + e) / 2
    blobs = []
    for bb in ((s, w, mlat, mlon), (s, mlon, mlat, e), (mlat, w, n, mlon), (mlat, mlon, n, e)):
        blobs += _tile_xml(*bb)
    nodes, ways = {}, {}
    for blob in blobs:
        root = ET.fromstring(blob)
        for el in root:
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            if el.tag == "node":
                nodes[int(el.get("id"))] = {"type": "node", "id": int(el.get("id")), "lat": float(el.get("lat")),
                                            "lon": float(el.get("lon")), **({"tags": tags} if tags else {})}
            elif el.tag == "way":
                ways[int(el.get("id"))] = {"type": "way", "id": int(el.get("id")),
                                           "nodes": [int(nd.get("ref")) for nd in el.findall("nd")],
                                           **({"tags": tags} if tags else {})}
    # Keep it lean: drop untagged buildings etc. that the backend never reads.
    keep_ways = {i: w_ for i, w_ in ways.items() if w_.get("tags", {}).keys() & {
        "highway", "public_transport", "amenity", "shop", "tourism", "office", "leisure", "railway"}
        or ("name" in w_.get("tags", {}))}
    used = {n for w_ in keep_ways.values() for n in w_["nodes"]}
    keep_nodes = {i: nd for i, nd in nodes.items() if i in used or nd.get("tags")}
    print(f"OSM API: {len(nodes)} nodes / {len(ways)} ways -> kept {len(keep_nodes)} / {len(keep_ways)}")
    return {"version": 0.6, "source": OSM_API,
            "osm3s": {"timestamp_osm_base": datetime.now(timezone.utc).isoformat(timespec="seconds")},
            "elements": list(keep_nodes.values()) + list(keep_ways.values())}


def main():
    bbox = tuple(map(float, sys.argv[1:5])) if len(sys.argv) == 5 else DEFAULT_BBOX
    payload = via_overpass(bbox) or via_osm_api(bbox)
    payload["bbox"] = bbox
    out = Path(__file__).resolve().parents[1] / "data" / "osm_raw.json"
    out.write_text(json.dumps(payload, ensure_ascii=False))
    print(f"Saved {len(payload['elements'])} elements to {out}")


if __name__ == "__main__":
    main()
