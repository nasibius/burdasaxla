import L from "leaflet";
import { CircleMarker, Marker, Polygon, Tooltip } from "react-leaflet";
import type { ActivityRow, LngLat, PlanningItem, PlanningResult } from "../types";
import type { Lang } from "../i18n";
import { makePT } from "./strings";

const ll = (c: LngLat): [number, number] => [c[1], c[0]];
export const COV_COLORS = { SERVED: "#2fd581", POTENTIAL_COVERAGE_GAP: "#ff7a45", INVENTORY_UNKNOWN: "#94a3b8", NETWORK_UNRELIABLE: "#64748b" };

const candIcon = (label: string, sel: boolean) => L.divIcon({
  className: "pin", iconSize: [30, 30], iconAnchor: [15, 15],
  html: `<div class="pin-cand ${sel ? "sel" : ""}">${label}</div>`,
});
const supplyIcon = L.divIcon({ className: "pin", iconSize: [24, 24], iconAnchor: [12, 12], html: `<div class="pin-supply">P</div>` });

/** Planning layers. Deliberately NOT using the legal red/green/yellow palette. */
export default function PlanningLayers({ plan, items, activity, selectedId, onSelect, lang, zoom }: {
  plan: PlanningResult; items: PlanningItem[]; activity: ActivityRow[]; selectedId: string | null;
  onSelect: (id: string) => void; lang: Lang; zoom: number;
}) {
  const p = makePT(lang);
  const maxRate = Math.max(1, ...activity.map((a) => a.per_hour ?? 0));
  return (
    <>
      {items.filter((i) => i.type === "survey_task").map((i) => (
        <Polygon key={i.id} positions={(i.geometry.coordinates[0] as LngLat[]).map(ll)} eventHandlers={{ click: () => onSelect(i.id) }}
          pathOptions={{ color: selectedId === i.id ? "#ffffff" : "#a78bfa", weight: selectedId === i.id ? 3 : 1, dashArray: "3 5",
            opacity: selectedId === i.id ? 1 : 0.45, fillColor: "#a78bfa",
            fillOpacity: selectedId === i.id ? 0.3 : Math.min(0.14, 0.01 + ((i as any).priority_score ?? 0) / 700) }}>
          <Tooltip className="seg-tip" sticky>{p("task")} #{i.rank} · {p("priority")} {Math.round((i as any).priority_score ?? 0)}</Tooltip>
        </Polygon>
      ))}
      {zoom >= 16 && plan.coverage.map((n) => (
        <CircleMarker key={n.id} center={[n.lat, n.lon]} radius={zoom >= 17 ? 3.5 : 2.5} interactive={zoom >= 17}
          pathOptions={{ color: COV_COLORS[n.state], weight: 1, fillColor: COV_COLORS[n.state], fillOpacity: 0.9 }}>
          <Tooltip className="seg-tip" direction="top">{n.name || n.kind} · {p("st_" + n.state)}{n.distance_m != null ? ` · ${n.distance_m} m` : ""} <i>(proxy)</i></Tooltip>
        </CircleMarker>
      ))}
      {plan.supply.map((s) => (
        <Marker key={s.segment_id} position={ll(s.point)} icon={supplyIcon}><Tooltip className="seg-tip">{p("lg_supply")} · {s.street}</Tooltip></Marker>
      ))}
      {plan.observed_suitable?.map((s) => (
        <CircleMarker key={s.segment_id} center={ll(s.point)} radius={4} pathOptions={{ color: "#fff", weight: 1, fillColor: "#2fd581", fillOpacity: 1 }}>
          <Tooltip className="seg-tip">{p("lg_observed")} · {s.street}</Tooltip>
        </CircleMarker>
      ))}
      {activity.map((a) => (
        <CircleMarker key={"a" + a.id} center={ll(a.geometry.coordinates)} radius={6 + 16 * Math.sqrt((a.per_hour ?? 0) / maxRate)}
          pathOptions={{ color: "#38bdf8", weight: 2, fillColor: "#38bdf8", fillOpacity: 0.25 }}>
          <Tooltip className="seg-tip">{a.place_name} · ↑{a.pickups} ↓{a.dropoffs}{a.per_hour != null ? ` · ${a.per_hour}/h` : ""}</Tooltip>
        </CircleMarker>
      ))}
      {items.filter((i) => i.type === "candidate").map((i) => (
        <Marker key={i.id} position={ll((i as any).point)} icon={candIcon(String(i.rank ?? "?"), selectedId === i.id)}
          eventHandlers={{ click: () => onSelect(i.id) }} zIndexOffset={800}>
          <Tooltip className="seg-tip" direction="top">{p("lg_candidate")}</Tooltip>
        </Marker>
      ))}
    </>
  );
}

export function PlanningLegend({ lang }: { lang: Lang }) {
  const p = makePT(lang);
  return (
    <div className="legend glass planning-legend">
      <h5>{p("legend_plan")}</h5>
      <div className="lg-row"><span className="lg-swatch" style={{ background: "#a78bfa", height: 10, opacity: .6 }} /><span>{p("lg_task")}</span></div>
      <div className="lg-row"><span className="lg-dot cand" /><span>{p("lg_candidate")}</span></div>
      <div className="lg-row"><span className="lg-dot supply">P</span><span>{p("lg_supply")}</span></div>
      <div className="lg-row"><span className="lg-dot" style={{ background: "#38bdf8" }} /><span>{p("lg_activity")}</span></div>
      {(["SERVED", "INVENTORY_UNKNOWN", "POTENTIAL_COVERAGE_GAP", "NETWORK_UNRELIABLE"] as const).map((s) => (
        <div className="lg-row" key={s}><span className="lg-dot" style={{ background: COV_COLORS[s], width: 8, height: 8 }} /><span>{p("st_" + s)}</span></div>
      ))}
      <h5 style={{ marginTop: 8 }}>{p("legend_today")}</h5>
      <div className="kv-line" style={{ marginTop: 0 }}>{p("legend_today_note")}</div>
    </div>
  );
}
