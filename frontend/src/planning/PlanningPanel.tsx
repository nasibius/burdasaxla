import { useEffect, useState } from "react";
import { STATIC_MODE, planningApi } from "../api";
import type { ActivityRow, LngLat, PlanningItem, PlanningResult, ReviewAction } from "../types";
import type { Lang } from "../i18n";
import { IAlert, IExternal, IInfo, IMap, IShield, Logo } from "../components/Icons";
import { exportCsv, exportGeojson } from "./export";
import { makePT, whyText } from "./strings";

export type PlanTab = "tasks" | "candidates" | "activity" | "method";
export type ReviewFilter = "all" | "unreviewed" | ReviewAction;

interface Props {
  lang: Lang;
  plan: PlanningResult | null;
  loading: boolean;
  error: string | null;
  threshold: number;
  setThreshold: (n: number) => void;
  tab: PlanTab;
  setTab: (t: PlanTab) => void;
  filter: ReviewFilter;
  setFilter: (f: ReviewFilter) => void;
  visible: PlanningItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  activity: ActivityRow[];
  token: string;
  onChanged: () => void;
  requestPoint: (cb: (c: LngLat) => void) => void;
  onPrint: () => void;
}

export const REVIEW_ACTIONS: ReviewAction[] = ["needs_survey", "shortlist", "more_data", "reject"];

function fmtDate(d?: string | null) {
  if (!d) return "—";
  const x = new Date(d);
  return Number.isNaN(+x) ? d : `${String(x.getDate()).padStart(2, "0")}.${String(x.getMonth() + 1).padStart(2, "0")}.${x.getFullYear()} ${String(x.getHours()).padStart(2, "0")}:${String(x.getMinutes()).padStart(2, "0")}`;
}

export function ReviewBadge({ action, lang }: { action?: ReviewAction | null; lang: Lang }) {
  const p = makePT(lang);
  if (!action) return null;
  return <span className={`rev-badge ${action}`}>{p("rev_" + action)}</span>;
}

function ActivityAdmin({ lang, token, onChanged, requestPoint }: { lang: Lang; token: string; onChanged: () => void; requestPoint: Props["requestPoint"] }) {
  const p = makePT(lang);
  const [pending, setPending] = useState<ActivityRow[] | null>(null);
  const [f, setF] = useState({ place_name: "", point: null as LngLat | null, period_start: "", period_end: "", pickups: "", dropoffs: "",
    method: "field_count", source: "", source_url: "", source_ref: "", observer: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const load = () => planningApi.adminActivity(token).then((r) => setPending(r.filter((a) => a.status === "pending"))).catch((e) => setMsg(e.message));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [token]);
  const submit = async () => {
    setMsg(null);
    try {
      await planningApi.addActivity(token, {
        place_name: f.place_name, point: f.point, period_start: f.period_start, period_end: f.period_end,
        pickups: Number(f.pickups), dropoffs: Number(f.dropoffs), method: f.method, source: f.source,
        source_url: f.source_url || undefined, source_ref: f.source_ref || undefined, observer: f.observer,
      });
      setF({ ...f, place_name: "", point: null, pickups: "", dropoffs: "" });
      await load(); onChanged();
    } catch (e: any) { setMsg(e.message); }
  };
  const decide = async (a: ActivityRow, d: "verified" | "rejected") => {
    const note = d === "rejected" ? window.prompt(p("reason")) ?? "" : undefined;
    if (d === "rejected" && !note) return;
    try { await planningApi.reviewActivity(token, a.id, d, f.observer || "planner", note); await load(); onChanged(); }
    catch (e: any) { setMsg(e.message); }
  };
  return (
    <div className="drawing-box" style={{ marginTop: 14 }}>
      <b>{p("activity_add")}</b>
      <div className="form-grid">
        <input placeholder={p("activity_place")} value={f.place_name} onChange={(e) => setF({ ...f, place_name: e.target.value })} />
        <button type="button" className="btn-ghost" onClick={() => requestPoint((c) => setF((x) => ({ ...x, point: c })))}>
          <IMap size={13} />{f.point ? `${f.point[1].toFixed(5)}, ${f.point[0].toFixed(5)}` : p("activity_pick")}
        </button>
        <div className="field-row">
          <input type="datetime-local" value={f.period_start} onChange={(e) => setF({ ...f, period_start: e.target.value })} />
          <input type="datetime-local" value={f.period_end} onChange={(e) => setF({ ...f, period_end: e.target.value })} />
        </div>
        <div className="field-row">
          <input type="number" min={0} placeholder={p("activity_in")} value={f.pickups} onChange={(e) => setF({ ...f, pickups: e.target.value })} />
          <input type="number" min={0} placeholder={p("activity_out")} value={f.dropoffs} onChange={(e) => setF({ ...f, dropoffs: e.target.value })} />
        </div>
        <select value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}>
          {["field_count", "operator_aggregate", "official_statistic"].map((m) => <option key={m} value={m}>{p("method_" + m)}</option>)}
        </select>
        <input placeholder="Source *" value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} />
        <input placeholder="Source URL" value={f.source_url} onChange={(e) => setF({ ...f, source_url: e.target.value })} />
        <input placeholder="Source ref (count sheet / dataset id)" value={f.source_ref} onChange={(e) => setF({ ...f, source_ref: e.target.value })} />
        <input placeholder={`${p("reviewer")} *`} value={f.observer} onChange={(e) => setF({ ...f, observer: e.target.value })} />
      </div>
      <div className="row"><button className="btn-ghost good" disabled={!f.point || !f.place_name || !f.observer || !f.source} onClick={submit}>{p("activity_add")}</button></div>
      <label className="btn-ghost file-btn" style={{ marginTop: 8 }}>{p("activity_csv")}
        <input type="file" accept=".csv,text/csv" onChange={async (e) => {
          const file = e.target.files?.[0];
          if (!file || !f.observer) { setMsg(`${p("reviewer")}?`); return; }
          try { const r = await planningApi.importActivity(token, await file.text(), f.observer); setMsg(`+${r.created} · ${r.errors.join("; ")}`); await load(); }
          catch (err: any) { setMsg(err.message); }
        }} />
      </label>
      {msg && <div className="warn-line" style={{ marginTop: 8 }}>{msg}</div>}
      {!!pending?.length && <>
        <div className="sec-t">{p("activity_pending")}</div>
        {pending.map((a) => (
          <div key={a.id} className="task">
            <div className="t-h">{a.place_name} <span className="muted">#{a.id}</span></div>
            <div className="kv-line">{a.pickups} ↑ · {a.dropoffs} ↓ · {fmtDate(a.period_start)} → {fmtDate(a.period_end)} · {a.source}</div>
            <div className="t-a">
              <button className="btn-ghost good" onClick={() => decide(a, "verified")}>✓</button>
              <button className="btn-ghost danger" onClick={() => decide(a, "rejected")}>✕</button>
            </div>
          </div>
        ))}
      </>}
    </div>
  );
}

export default function PlanningPanel(props: Props) {
  const { lang, plan } = props;
  const p = makePT(lang);
  const [limit, setLimit] = useState(15);
  const s = plan?.summary;
  const canWrite = !STATIC_MODE && !plan?.read_only && !!props.token;

  const card = (i: PlanningItem) => {
    const isTask = i.type === "survey_task";
    const score = isTask ? i.priority_score : i.score;
    return (
      <div key={i.id} className={`card plan-card ${props.selectedId === i.id ? "sel" : ""} ${isTask ? "task-card" : "cand-card"}`}
        onClick={() => props.onSelect(i.id)} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && props.onSelect(i.id)}>
        <div className="card-top">
          <div className={`rank ${isTask ? "rank-task" : "rank-cand"}`}>{i.rank ?? "–"}</div>
          <div style={{ minWidth: 0 }}>
            <div className="street">{isTask ? `${p("task")} ${i.id.replace("survey-", "")}` : `${i.street || "—"}`}</div>
            <div className="sub">{isTask ? `${i.access_nodes} ${p("destinations")}${i.transit_hubs.length ? ` · ${p("transit")}: ${i.transit_hubs.slice(0, 2).join(", ")}` : ""}`
              : p("cls_" + i.candidate_class)}</div>
          </div>
          <span className="score-pill" title={p("priority")}>{score == null ? "—" : Math.round(score)}</span>
        </div>
        <div className="chips">
          <span className="chip plan">{isTask ? p("cls_SURVEY_TASK") : p("cls_" + i.candidate_class)}</span>
          <ReviewBadge action={i.review?.action} lang={lang} />
          {isTask && i.measured_activity === "not_measured" && <span className="chip">{p("sum_demand")}: {p("not_measured")}</span>}
          {isTask && i.no_defensible_candidate && <span className="chip unk">No defensible candidate</span>}
        </div>
        <div className="kv-line" style={{ marginTop: 6 }}>{whyText(i, lang)}</div>
      </div>
    );
  };

  return (
    <section className="panel glass planning-panel">
      <div className="panel-head">
        <div className="brand">
          <Logo />
          <div>
            <div className="brand-name">Burda<b>Saxla</b></div>
            <div className="brand-sub"><IShield size={13} />{p("title")}</div>
          </div>
        </div>
        <div className="seg-ctl small four" role="tablist">
          {(["tasks", "candidates", "activity", "method"] as PlanTab[]).map((t) => (
            <button key={t} role="tab" aria-selected={props.tab === t} className={props.tab === t ? "on" : ""} onClick={() => props.setTab(t)}>{p("tab_" + t)}</button>
          ))}
        </div>
      </div>
      <div className="panel-body">
        <div className="plan-purpose"><IInfo size={14} /><span>{p("purpose")}</span></div>
        {props.error && <div className="err">{props.error}</div>}
        {!plan && props.loading && <div className="mode-hint">…</div>}
        {plan && <>
          <div className="kv-line" style={{ marginTop: 10 }}>
            <span><b>{p("area")}:</b> {plan.area.name}</span>
            <span><b>{p("data_as_of")}:</b> {fmtDate(plan.generated_at)}</span>
            <span><b>{p("osm")}:</b> {fmtDate(plan.source_versions.osm_snapshot)}</span>
            <span><b>{p("ruleset")}:</b> {plan.source_versions.ruleset}</span>
            <span><b>{p("algo")}:</b> {plan.algorithm_version}</span>
          </div>

          {!plan.inventory_complete ? (
            <div className="inv-banner"><IAlert size={15} /><div><b>{p("inventory_unknown_title")}</b><div>{p("inventory_unknown_body")}</div></div></div>
          ) : (
            <div className="inv-banner ok"><IInfo size={15} /><div><b>{p("inventory_complete_title")}</b>
              <div>{plan.area.inventory_declared_by} · {fmtDate(plan.area.inventory_declared_at)} {plan.area.inventory_source_url &&
                <a href={plan.area.inventory_source_url} target="_blank" rel="noreferrer">source <IExternal size={11} /></a>}</div></div></div>
          )}

          {s && (
            <div className="stat-grid plan-stats">
              <div className="stat"><div className="v">{s.verified_supply_by_type.official_designated}</div><div className="l">{p("sum_supply")}</div><div className="l2">+{s.verified_supply_by_type.field_verified_suitable} {p("sum_observed")}</div></div>
              <div className="stat"><div className="v">{s.survey_tasks}</div><div className="l">{p("sum_tasks")}</div></div>
              <div className="stat"><div className="v">{s.candidates.SCREENED_FOR_FURTHER_STUDY + s.candidates.DATA_COLLECTION_NEEDED}</div><div className="l">{p("sum_candidates")}</div></div>
              <div className="stat"><div className="v small">{s.served_share == null ? "—" : `${Math.round(s.served_share * 100)}%`}</div><div className="l">{p("sum_coverage")}</div>
                <div className="l2">{s.served_share == null ? (plan.inventory_complete ? p("sum_coverage_na") : p("sum_unknown")) : `${plan.parameters.threshold_m} m`}</div></div>
              <div className="stat"><div className="v small">{plan.demand_measured ? s.measured_activity_rows : "—"}</div><div className="l">{p("sum_demand")}</div><div className="l2">{plan.demand_measured ? "rows" : p("not_measured")}</div></div>
              <div className="stat"><div className="v small">{s.coverage_states.INVENTORY_UNKNOWN + s.coverage_states.NETWORK_UNRELIABLE}</div><div className="l">{p("st_INVENTORY_UNKNOWN")} / {p("st_NETWORK_UNRELIABLE")}</div></div>
            </div>
          )}

          <div className="field-label"><span>{p("threshold")}</span><span>{props.threshold} m</span></div>
          {STATIC_MODE || plan.read_only
            ? <div className="kv-line">{p("threshold_static")}</div>
            : <input className="range" type="range" min={100} max={800} step={50} value={props.threshold} onChange={(e) => props.setThreshold(+e.target.value)} />}
          <div className="kv-line">{p("threshold_note")}</div>

          {(props.tab === "tasks" || props.tab === "candidates") && <>
            <div className="seg-ctl small" style={{ gridTemplateColumns: "repeat(3,1fr)" }}>
              {(["all", "unreviewed", "needs_survey", "shortlist", "more_data", "reject"] as ReviewFilter[]).map((f) => (
                <button key={f} className={props.filter === f ? "on" : ""} onClick={() => props.setFilter(f)}>
                  {f === "all" ? p("filter_all") : f === "unreviewed" ? p("filter_unreviewed") : p("rev_" + f)}
                </button>
              ))}
            </div>
            <div className="import-row" style={{ marginTop: 10 }}>
              <button className="btn-ghost" onClick={() => exportCsv(props.visible, plan)}>{p("export_csv")}</button>
              <button className="btn-ghost" onClick={() => exportGeojson(props.visible, plan)}>{p("export_geojson")}</button>
              <button className="btn-ghost" onClick={props.onPrint}>{p("export_print")}</button>
              {canWrite && <button className="btn-ghost" onClick={() => planningApi.run(props.token, props.threshold).then(props.onChanged)}>{p("run")}</button>}
            </div>
            <div className="kv-line">{p("export_note")} · {props.visible.length}</div>
          </>}

          {props.tab === "tasks" && <div style={{ marginTop: 12 }}>
            {props.visible.slice(0, limit).map(card)}
            {props.visible.length > limit && <button className="btn-ghost" onClick={() => setLimit(limit + 25)}>{p("show_more")} ({props.visible.length - limit})</button>}
          </div>}

          {props.tab === "candidates" && <div style={{ marginTop: 12 }}>
            {props.visible.length === 0 && (
              <div className="empty soft"><div className="e-ic"><IInfo size={22} /></div><h4>{p("no_candidates_title")}</h4><p>{p("no_candidates_body")}</p></div>
            )}
            {props.visible.map(card)}
          </div>}

          {props.tab === "activity" && <div style={{ marginTop: 12 }}>
            <h4 className="sec-h">{p("activity_title")}</h4>
            {props.activity.length === 0 ? (
              <div className="empty soft"><div className="e-ic"><IInfo size={22} /></div><h4>{p("activity_none")}</h4><p>{p("activity_none_body")}</p></div>
            ) : (
              <div className="tbl-wrap">
                <table className="tbl">
                  <thead><tr><th>{p("activity_place")}</th><th>{p("activity_in")}</th><th>{p("activity_out")}</th><th>{p("activity_rate")}</th><th>{p("activity_method")}</th></tr></thead>
                  <tbody>{props.activity.map((a) => (
                    <tr key={a.id} title={`${fmtDate(a.period_start)} → ${fmtDate(a.period_end)} · ${a.source}`}>
                      <td>{a.place_name}</td><td>{a.pickups}</td><td>{a.dropoffs}</td><td>{a.per_hour ?? "—"}</td><td>{p("method_" + a.method)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
            <div className="kv-line">{p("activity_suppressed")}</div>
            {canWrite && <ActivityAdmin lang={lang} token={props.token} onChanged={props.onChanged} requestPoint={props.requestPoint} />}
            {!canWrite && <div className="kv-line" style={{ marginTop: 8 }}>{p("read_only")}</div>}
          </div>}

          {props.tab === "method" && <div style={{ marginTop: 12 }}>
            <h4 className="sec-h">{p("method_states")}</h4>
            {(["SERVED", "POTENTIAL_COVERAGE_GAP", "INVENTORY_UNKNOWN", "NETWORK_UNRELIABLE"] as const).map((st) => (
              <div key={st} className="reason info" style={{ borderLeftColor: `var(--cov-${st})` }}>
                <div className="r-t">{p("st_" + st)} <span className="muted">· {s?.coverage_states[st] ?? 0}</span></div>
                <div className="r-d">{p("st_" + st + "_d")}</div>
              </div>
            ))}
            <h4 className="sec-h">{p("factors")}</h4>
            <table className="tbl">
              <tbody>
                {Object.entries(plan.parameters.survey_weights).map(([k, w]) => <tr key={k}><td>{p("f_" + k)}</td><td>{Math.round(w * 100)}%</td></tr>)}
              </tbody>
            </table>
            <h4 className="sec-h">{p("method_title")}</h4>
            <ul className="limits">{plan.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
          </div>}
        </>}
      </div>
      <div className="panel-foot">
        <span>{p("build")}: {__BUILD_INFO__.commit} · {fmtDate(__BUILD_INFO__.time)}</span>
        <span>{STATIC_MODE ? "static · read-only" : "API"}</span>
      </div>
    </section>
  );
}
