import type { PlanningItem, PlanningResult } from "../types";

/** Same columns as the API export (/api/authority/export), built from the visible, filtered items. */
export function exportRows(items: PlanningItem[], plan: PlanningResult) {
  return items.map((i) => {
    const [lon, lat] = i.type === "survey_task" ? i.centroid : i.point;
    return {
      id: i.id, type: i.type, rank: i.rank ?? "",
      class: i.type === "candidate" ? i.candidate_class : "SURVEY_TASK",
      score: i.type === "candidate" ? (i.score ?? "") : (i.priority_score ?? ""),
      street: i.type === "candidate" ? i.street : "", road_side: i.type === "candidate" ? i.road_side : "",
      lon: lon.toFixed(6), lat: lat.toFixed(6), why: i.why, missing_evidence: (i.missing_evidence ?? []).join(" | "),
      factors_missing: (i.factors_missing ?? []).join(" | "),
      coverage_states: i.type === "survey_task" ? JSON.stringify(i.coverage_states) : i.coverage_finding,
      access_nodes_are_proxy: i.type === "survey_task" ? "True" : "",
      demand_measured: plan.demand_measured ? "True" : "False", officially_approved: "False",
      current_legal_status: i.type === "candidate" ? i.current_legal_status : "",
      review_action: i.review?.action ?? "", review_reason: i.review?.reason ?? "", reviewer: i.review?.reviewer ?? "",
      threshold_m: plan.parameters.threshold_m, algorithm_version: plan.algorithm_version,
      osm_snapshot: plan.source_versions.osm_snapshot, generated_at: plan.generated_at, is_synthetic_example: "False",
      limitations: plan.limitations.join(" "),
    };
  });
}

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function exportCsv(items: PlanningItem[], plan: PlanningResult) {
  const rows = exportRows(items, plan);
  const cols = rows.length ? Object.keys(rows[0]) : ["id"];
  const esc = (v: unknown) => { const s = String(v ?? ""); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const text = [cols.join(","), ...rows.map((r) => cols.map((c) => esc((r as any)[c])).join(","))].join("\n");
  download("burdasaxla-planning.csv", "﻿" + text, "text/csv;charset=utf-8");
}

export function exportGeojson(items: PlanningItem[], plan: PlanningResult) {
  const rows = exportRows(items, plan);
  const fc = {
    type: "FeatureCollection",
    features: items.map((i, k) => ({ type: "Feature", geometry: i.geometry, properties: rows[k] })),
    metadata: { limitations: plan.limitations, area: plan.area.name, inventory_complete: plan.inventory_complete,
      source_versions: plan.source_versions, parameters: plan.parameters },
  };
  download("burdasaxla-planning.geojson", JSON.stringify(fc, null, 1), "application/geo+json");
}
