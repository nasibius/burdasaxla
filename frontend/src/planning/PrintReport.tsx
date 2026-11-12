import type { PlanningItem, PlanningResult } from "../types";
import type { Lang } from "../i18n";
import { makePT, whyText } from "./strings";

/** One-page printable report (browser print / save as PDF). Rendered only while printing. */
export default function PrintReport({ plan, items, lang }: { plan: PlanningResult; items: PlanningItem[]; lang: Lang }) {
  const p = makePT(lang);
  const s = plan.summary;
  return (
    <div className="print-report">
      <h1>{p("report_title")}</h1>
      <p><b>{p("area")}:</b> {plan.area.name} · <b>{p("report_generated")}:</b> {new Date().toISOString().slice(0, 16).replace("T", " ")} UTC ·
        <b> {p("data_as_of")}:</b> {plan.generated_at} · <b>{p("osm")}:</b> {plan.source_versions.osm_snapshot} · {plan.algorithm_version} · {plan.source_versions.ruleset}</p>
      <p className="warn">{p("purpose")}</p>
      {!plan.inventory_complete && <p className="warn"><b>{p("inventory_unknown_title")}.</b> {p("inventory_unknown_body")}</p>}
      <table>
        <tbody>
          <tr><td>{p("sum_supply")}</td><td>{s.verified_supply_by_type.official_designated} (+{s.verified_supply_by_type.field_verified_suitable} {p("sum_observed")})</td></tr>
          <tr><td>{p("sum_tasks")}</td><td>{s.survey_tasks}</td></tr>
          <tr><td>{p("sum_candidates")}</td><td>{s.candidates.SCREENED_FOR_FURTHER_STUDY + s.candidates.DATA_COLLECTION_NEEDED}</td></tr>
          <tr><td>{p("sum_coverage")}</td><td>{s.served_share == null ? p("sum_coverage_na") : `${Math.round(s.served_share * 100)}%`}</td></tr>
          <tr><td>{p("sum_demand")}</td><td>{plan.demand_measured ? s.measured_activity_rows : p("not_measured")}</td></tr>
          <tr><td>{p("threshold")}</td><td>{plan.parameters.threshold_m} m — {p("threshold_note")}</td></tr>
        </tbody>
      </table>
      <h2>{p("report_items")} ({items.length})</h2>
      <table className="items">
        <thead><tr><th>#</th><th>ID</th><th>Class</th><th>{p("priority")}</th><th>{p("why")}</th><th>{p("missing")}</th><th>{p("review")}</th></tr></thead>
        <tbody>{items.slice(0, 10).map((i) => (
          <tr key={i.id}><td>{i.rank ?? "—"}</td><td>{i.id}</td><td>{i.type === "candidate" ? p("cls_" + i.candidate_class) : p("cls_SURVEY_TASK")}</td>
            <td>{(i.type === "candidate" ? i.score : i.priority_score) == null ? "—" : Math.round((i.type === "candidate" ? i.score : i.priority_score) as number)}</td>
            <td>{whyText(i, lang)}</td><td>{i.missing_evidence.slice(0, 1).join("; ")}</td><td>{i.review ? p("rev_" + i.review.action) : "—"}</td></tr>
        ))}</tbody>
      </table>
      {items.length > 10 && <p>… +{items.length - 10} (CSV / GeoJSON export)</p>}
      <h2>{p("method_title")}</h2>
      <ul>{plan.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
    </div>
  );
}
