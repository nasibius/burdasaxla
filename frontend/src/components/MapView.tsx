import type React from "react";
import L from "leaflet";
import { useEffect, useMemo, useRef } from "react";
import { MapContainer, Marker, Polygon, Polyline, TileLayer, Tooltip, useMap, useMapEvents, CircleMarker } from "react-leaflet";
import type { Context, CuratedFeature, LngLat, Recommendation, SegFeature, Status } from "../types";
import { makeT, ruleTitle, type Lang } from "../i18n";

export const STATUS_COLORS: Record<"dark" | "light", Record<Status, string>> = {
  dark: { PROHIBITED: "#ff5468", ALLOWED: "#2fd581", UNVERIFIED: "#f5b82e" },
  light: { PROHIBITED: "#e5334a", ALLOWED: "#10a85c", UNVERIFIED: "#d99a00" },
};

const ENV = (import.meta as any).env ?? {};
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas";
// Basemaps: Esri Canvas by default (no key). Override with VITE_TILE_DARK / VITE_TILE_LIGHT
// (e.g. a CARTO or MapTiler URL with your key) — set VITE_TILE_LABELS_* to "" to drop label overlays.
const TILES = {
  dark: {
    base: ENV.VITE_TILE_DARK ?? `${ESRI}/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
    labels: ENV.VITE_TILE_LABELS_DARK ?? `${ESRI}/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
  },
  light: {
    base: ENV.VITE_TILE_LIGHT ?? `${ESRI}/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
    labels: ENV.VITE_TILE_LABELS_LIGHT ?? `${ESRI}/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
  },
};
const ATTR = 'Data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · Basemap &copy; Esri, HERE, Garmin';

const ll = (c: LngLat): [number, number] => [c[1], c[0]];

const destIcon = L.divIcon({
  className: "pin",
  iconSize: [34, 44],
  iconAnchor: [17, 42],
  html: `<svg class="pin-dest" viewBox="0 0 34 44"><path d="M17 1C8.2 1 1 7.9 1 16.5 1 28 17 43 17 43s16-15 16-26.5C33 7.9 25.8 1 17 1z" fill="#ffffff"/><path d="M17 4C9.8 4 4 9.6 4 16.5 4 25.6 17 38.6 17 38.6S30 25.6 30 16.5C30 9.6 24.2 4 17 4z" fill="#0f1528"/><path d="M12 11.5v11M12 11.5h9l-2 3 2 3h-9" stroke="#ffd166" stroke-width="2.2" fill="none" stroke-linejoin="round" stroke-linecap="round"/></svg>`,
});
const carIcon = L.divIcon({
  className: "pin",
  iconSize: [38, 38],
  iconAnchor: [19, 19],
  html: `<div class="pin-pulse"></div><div class="pin-car"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 17h14v-4.5l-1.8-4.6A2 2 0 0 0 15.3 6.5H8.7a2 2 0 0 0-1.9 1.4L5 12.5z"/><path d="M5 12.5h14"/></svg></div>`,
});
const rankIcon = (label: string, sel: boolean, unverified: boolean) =>
  L.divIcon({ className: "pin", iconSize: [30, 30], iconAnchor: [15, 15],
    html: `<div class="pin-rank ${sel ? "sel" : ""} ${unverified ? "unverified" : ""}">${label}</div>` });

export type MapResult = Recommendation & { key: string; unverified?: boolean };
const signIcon = (kind: string, pending: boolean) =>
  L.divIcon({
    className: "pin", iconSize: [26, 26], iconAnchor: [13, 13],
    html: kind === "sign_3_27"
      ? `<svg width="26" height="26" viewBox="0 0 26 26" style="filter:drop-shadow(0 2px 4px rgba(0,0,0,.45));opacity:${pending ? 0.6 : 1}"><circle cx="13" cy="13" r="12" fill="#e11d48" stroke="#fff" stroke-width="1.5"/><circle cx="13" cy="13" r="7.5" fill="#1d4ed8"/><path d="M7.7 7.7l10.6 10.6M18.3 7.7 7.7 18.3" stroke="#e11d48" stroke-width="2.4"/></svg>`
      : `<svg width="26" height="26" viewBox="0 0 26 26" style="filter:drop-shadow(0 2px 4px rgba(0,0,0,.45));opacity:${pending ? 0.6 : 1}"><circle cx="13" cy="13" r="12" fill="#e11d48" stroke="#fff" stroke-width="1.5"/><circle cx="13" cy="13" r="7.5" fill="#1d4ed8"/><path d="M7.7 18.3 18.3 7.7" stroke="#e11d48" stroke-width="2.4"/></svg>`,
  });

const LINE_STYLE: Record<string, L.PathOptions> = {
  marking_1_4: { color: "#facc15", weight: 4, opacity: 0.95 },
  marking_1_10: { color: "#facc15", weight: 4, opacity: 0.95, dashArray: "8 7" },
  bus_lane: { color: "#f97316", weight: 5, opacity: 0.85 },
  taxi_stand: { color: "#fde047", weight: 6, opacity: 0.9, dashArray: "2 6" },
  observed_prohibition: { color: "#ff5468", weight: 5, opacity: 0.85, dashArray: "10 5" },
  official_zone: { color: "#22d3ee", weight: 7, opacity: 0.9 },
};

const cameraIcon = L.divIcon({
  className: "pin", iconSize: [22, 22], iconAnchor: [11, 11],
  html: `<div style="width:22px;height:22px;border-radius:50%;background:#0f1528;border:2px solid #fff;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 6px rgba(0,0,0,.4)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.2"/></svg></div>`,
});

function segWeight(z: number) {
  return z >= 18 ? 6 : z >= 17 ? 4.5 : z >= 16 ? 3.4 : 2.4;
}

function SegmentsLayer({ data, theme, onSelect, lang, selectedId }: {
  data: SegFeature[]; theme: "dark" | "light"; onSelect: (id: string, at: LngLat) => void; lang: Lang; selectedId?: string | null;
}) {
  const map = useMap();
  // Keep the latest handler in a ref: the Leaflet layer is built once per data/theme change,
  // so a captured callback would go stale (e.g. ignore picking/drawing mode).
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const layerRef = useRef<L.GeoJSON | null>(null);
  const t = makeT(lang);
  const renderer = useMemo(() => L.canvas({ padding: 0.4, tolerance: 6 }), []);

  useEffect(() => {
    const colors = STATUS_COLORS[theme];
    const style = (f?: GeoJSON.Feature): L.PathOptions => {
      const st = (f?.properties as any)?.status as Status;
      return {
        color: colors[st], weight: segWeight(map.getZoom()), opacity: st === "UNVERIFIED" ? 0.8 : 0.95,
        lineCap: "butt", renderer,
      };
    };
    const layer = L.geoJSON({ type: "FeatureCollection", features: data } as any, {
      style,
      onEachFeature: (f, lyr) => {
        const p = f.properties as SegFeature["properties"];
        const shown = p.rules.length ? p.rules : (p.cautions ?? []);
        const rules = shown.slice(0, 3).map((r) => ruleTitle(r, lang)).join(" · ");
        lyr.bindTooltip(
          `<div class="tip-st" style="color:${colors[p.status]}">${t("st_" + p.status)}</div><b>${p.name || "—"}</b>` +
          `<div style="color:var(--muted)">${t("dir_" + (p as any).compass)} · ${Math.round(p.length_m)} m</div>` +
          (rules ? `<div style="margin-top:3px">${rules}</div>` : ""),
          { className: "seg-tip", sticky: true, direction: "top", offset: [0, -8] },
        );
        lyr.on("mouseover", (e: any) => e.target.setStyle({ weight: segWeight(map.getZoom()) + 3 }));
        lyr.on("mouseout", (e: any) => layer.resetStyle(e.target));
        lyr.on("click", (e: L.LeafletMouseEvent) => {
          L.DomEvent.stopPropagation(e);
          onSelectRef.current(p.id, [e.latlng.lng, e.latlng.lat]);
        });
      },
    });
    layer.addTo(map);
    layerRef.current = layer;
    const onZoom = () => layer.setStyle(style as any);
    map.on("zoomend", onZoom);
    return () => {
      map.off("zoomend", onZoom);
      layer.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, theme, lang, map, renderer]);

  const sel = selectedId ? data.find((f) => f.id === selectedId) : null;
  return sel ? (
    <>
      <Polyline positions={sel.geometry.coordinates.map(ll)} pathOptions={{ color: "#ffffff", weight: 11, opacity: 0.9, lineCap: "round" }} interactive={false} />
      <Polyline positions={sel.geometry.coordinates.map(ll)} pathOptions={{ color: STATUS_COLORS[theme][sel.properties.status], weight: 6, opacity: 1, lineCap: "round" }} interactive={false} />
    </>
  ) : null;
}

function ClickHandler({ onClick }: { onClick: (c: LngLat) => void }) {
  useMapEvents({ click: (e) => onClick([e.latlng.lng, e.latlng.lat]) });
  return null;
}

function ZoomWatcher({ onZoom }: { onZoom: (z: number) => void }) {
  const map = useMapEvents({ zoomend: () => onZoom(map.getZoom()) });
  useEffect(() => onZoom(map.getZoom()), [map, onZoom]);
  return null;
}

function FitTo({ points, token, maxZoom = 18 }: { points: LngLat[]; token: number; maxZoom?: number }) {
  const map = useMap();
  useEffect(() => {
    if (!points.length) return;
    const b = L.latLngBounds(points.map(ll));
    const mobile = window.innerWidth <= 760;
    map.flyToBounds(b, {
      paddingTopLeft: mobile ? [30, 80] : [440, 60],
      paddingBottomRight: mobile ? [30, window.innerHeight * 0.62] : [60, 60],
      maxZoom, duration: 0.8,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);
  return null;
}

export interface MapProps {
  center: LngLat;
  theme: "dark" | "light";
  lang: Lang;
  segments: SegFeature[];
  context: Context | null;
  features: CuratedFeature[];
  layers: { segments: boolean; stops: boolean; crossings: boolean; features: boolean };
  destination: LngLat | null;
  origin: LngLat | null;
  results: MapResult[];
  selectedKey: string | null;
  selectedSegment: string | null;
  picking: boolean;
  fitPoints: LngLat[];
  fitToken: number;
  fitMaxZoom?: number;
  draft?: { kind: string; coords: LngLat[] } | null;
  /** Photo evidence: where the camera was vs. where the sign is (never the same thing). */
  cameraMarks?: { camera: LngLat; target: LngLat; heading?: number | null }[];
  children?: React.ReactNode;
  highlightFeature?: number | null;
  onMapClick: (c: LngLat) => void;
  onSelectSegment: (id: string, at: LngLat) => void;
  onSelectKey: (key: string) => void;
  onMoveDestination: (c: LngLat) => void;
  onMoveOrigin: (c: LngLat) => void;
  onZoom: (z: number) => void;
  zoom: number;
}

export default function MapView(p: MapProps) {
  const sel = p.results.find((r) => r.key === p.selectedKey) ?? null;
  const brand = p.theme === "dark" ? "#5b8cff" : "#2f6bff";
  const walk = p.theme === "dark" ? "#c4a7ff" : "#7c3aed";  // not yellow: yellow means "unverified"

  return (
    <div className={`map ${p.picking ? "picking" : ""}`}>
      <MapContainer center={ll(p.center)} zoom={16} minZoom={13} maxZoom={19} zoomControl={false} preferCanvas style={{ height: "100%", width: "100%" }}>
        <TileLayer key={p.theme + "b"} url={TILES[p.theme].base} maxNativeZoom={16} maxZoom={20} attribution={ATTR} />
        {TILES[p.theme].labels && (
          <TileLayer key={p.theme + "l"} url={TILES[p.theme].labels} maxNativeZoom={16} pane="shadowPane" opacity={0.85} maxZoom={16.5} />
        )}
        <ClickHandler onClick={p.onMapClick} />
        <ZoomWatcher onZoom={p.onZoom} />
        <FitTo points={p.fitPoints} token={p.fitToken} maxZoom={p.fitMaxZoom} />

        {p.layers.features && p.features.filter((f) => f.kind === "survey_area").map((f) => (
          <Polygon key={f.id} positions={(f.geometry.coordinates[0] as LngLat[]).map(ll)} interactive={false}
            pathOptions={{ color: p.theme === "dark" ? "#a5b4fc" : "#6366f1", weight: 1.5, dashArray: "4 6", fillOpacity: 0.035, opacity: 0.55 }} />
        ))}

        {p.layers.segments && (
          <SegmentsLayer data={p.segments} theme={p.theme} onSelect={p.onSelectSegment} lang={p.lang} selectedId={p.selectedSegment} />
        )}

        {p.layers.features && p.features.filter((f) => f.geometry.type === "LineString").map((f) => (
          <Polyline key={f.id} positions={(f.geometry.coordinates as LngLat[]).map(ll)}
            pathOptions={{ ...(LINE_STYLE[f.kind] ?? {}), opacity: f.status === "pending" ? 0.55 : 0.95,
              ...(f.status === "pending" ? { dashArray: "4 6" } : {}), ...(p.highlightFeature === f.id ? { weight: 9 } : {}) }}>
            <Tooltip className="seg-tip" sticky>{makeT(p.lang)("kind_" + f.kind)}{f.status === "pending" ? " · pending" : ""}</Tooltip>
          </Polyline>
        ))}
        {p.layers.features && p.features.filter((f) => f.geometry.type === "Point").map((f) => (
          <Marker key={f.id} position={ll(f.geometry.coordinates as LngLat)} icon={signIcon(f.kind, f.status === "pending")}>
            <Tooltip className="seg-tip" direction="top" offset={[0, -12]}>{makeT(p.lang)("kind_" + f.kind)}</Tooltip>
          </Marker>
        ))}

        {p.layers.stops && p.context?.bus_stops.map((b) => (
          <CircleMarker key={b.ref} center={ll(b.coord)} radius={p.zoom >= 17 ? 6 : 4.5}
            pathOptions={{ color: "#ffffff", weight: 1.5, fillColor: "#f97316", fillOpacity: 1 }}>
            <Tooltip className="seg-tip" direction="top">🚌 {b.name || "Bus stop"}</Tooltip>
          </CircleMarker>
        ))}
        {p.layers.crossings && p.zoom >= 16 && p.context?.crossings.map((c) => (
          <CircleMarker key={c.ref} center={ll(c.coord)} radius={p.zoom >= 18 ? 4 : 2.6} interactive={false}
            pathOptions={{ color: p.theme === "dark" ? "#e2e8f0" : "#334155", weight: 1, fillColor: p.theme === "dark" ? "#e2e8f0" : "#334155", fillOpacity: 0.9 }} />
        ))}

        {/* routes: non-selected faint, selected bold */}
        {p.results.filter((r) => r.key !== p.selectedKey).map((r) => (
          r.drive_route ? <Polyline key={"d" + r.key} positions={r.drive_route.map(ll)} interactive={false}
            pathOptions={{ color: brand, weight: 3, opacity: 0.25 }} /> : null
        ))}
        {sel?.drive_route && <>
          <Polyline positions={sel.drive_route.map(ll)} interactive={false} pathOptions={{ color: p.theme === "dark" ? "#0b1020" : "#ffffff", weight: 10, opacity: 0.9, lineJoin: "round" }} />
          <Polyline positions={sel.drive_route.map(ll)} interactive={false} pathOptions={{ color: brand, weight: 6, opacity: 1, lineJoin: "round" }} />
        </>}
        {sel?.walk_route && <>
          <Polyline positions={sel.walk_route.map(ll)} interactive={false} pathOptions={{ color: p.theme === "dark" ? "#0b1020" : "#ffffff", weight: 7, opacity: 0.8, lineJoin: "round" }} />
          <Polyline positions={sel.walk_route.map(ll)} interactive={false} pathOptions={{ color: walk, weight: 4, dashArray: "1 8", lineCap: "round", opacity: 1 }} />
        </>}

        {p.results.map((r) => (
          <Marker key={r.key} position={ll(r.point)} icon={rankIcon(r.unverified ? "?" : String(r.rank), r.key === p.selectedKey, !!r.unverified)}
            zIndexOffset={r.key === p.selectedKey ? 900 : r.unverified ? 400 : 500} eventHandlers={{ click: () => p.onSelectKey(r.key) }} />
        ))}

        {p.destination && (
          <Marker position={ll(p.destination)} icon={destIcon} draggable zIndexOffset={1000}
            eventHandlers={{ dragend: (e) => { const c = (e.target as L.Marker).getLatLng(); p.onMoveDestination([c.lng, c.lat]); } }} />
        )}
        {p.origin && (
          <Marker position={ll(p.origin)} icon={carIcon} draggable zIndexOffset={1100}
            eventHandlers={{ dragend: (e) => { const c = (e.target as L.Marker).getLatLng(); p.onMoveOrigin([c.lng, c.lat]); } }} />
        )}

        {p.cameraMarks?.map((c, i) => (
          <span key={"cam" + i}>
            <Polyline positions={[ll(c.camera), ll(c.target)]} pathOptions={{ color: "#ffffff", weight: 1.5, dashArray: "3 5", opacity: 0.9 }} interactive={false} />
            <Marker position={ll(c.camera)} icon={cameraIcon}>
              <Tooltip className="seg-tip" direction="top">📷 {c.heading != null ? `${Math.round(c.heading)}°` : ""}</Tooltip>
            </Marker>
          </span>
        ))}
        {p.draft && p.draft.coords.length > 0 && (
          p.draft.kind === "survey_area"
            ? <Polygon positions={p.draft.coords.map(ll)} pathOptions={{ color: brand, weight: 2, dashArray: "5 5", fillOpacity: 0.08 }} />
            : <Polyline positions={p.draft.coords.map(ll)} pathOptions={{ ...(LINE_STYLE[p.draft.kind] ?? { color: brand }), weight: 5 }} />
        )}
        {p.draft && p.draft.kind.startsWith("sign_") && p.draft.coords[0] && (
          <Marker position={ll(p.draft.coords[0])} icon={signIcon(p.draft.kind, false)} />
        )}
        {p.draft && !p.draft.kind.startsWith("sign_") && p.draft.coords.map((c, i) => (
          <CircleMarker key={"dp" + i} center={ll(c)} radius={5} pathOptions={{ color: "#fff", weight: 2, fillColor: brand, fillOpacity: 1 }} />
        ))}
        {p.children}
      </MapContainer>
    </div>
  );
}
