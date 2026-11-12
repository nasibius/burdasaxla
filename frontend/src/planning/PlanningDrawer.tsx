import { useState } from "react";
import { STATIC_MODE, planningApi } from "../api";
import type { PlanningItem, PlanningResult, ReviewAction } from "../types";
import { makeT, ruleTitle, type Lang } from "../i18n";
import { IAlert, IX } from "../components/Icons";
import { REVIEW_ACTIONS, ReviewBadge } from "./PlanningPanel";
import { makePT, whyText } from "./strings";

export default function PlanningDrawer({ item, plan, lang, token, threshold, onClose, onChanged, onOpenSegment }: {
  item: PlanningItem; plan: PlanningResult; lang: Lang; token: string; threshold: number;
  onClose: () => void; onChanged: () => void; onOpenSegment: (id: string) => void;
}) {
  const p = makePT(lang);
  const t = makeT(lang);
  const [action, setAction] = useState<ReviewAction>("needs_survey");
  const [reason, setReason] = useState("");
  const [reviewer, setReviewer] = useState(() => { try { return localStorage.getItem("bs-observer") ?? ""; } catch { return ""; } });
  const [msg, setMsg] = useState<string | null>(null);
  const canWrite = !STATIC_MODE && !plan.read_only && !!token;
  const isTask = item.type === "survey_task";
  const weights = isTask ? plan.parameters.survey_weights : plan.parameters.candidate_weights;
  const score = isTask ? item.priority_score : item.score;

  const save = async () => {
    setMsg(null);
    try {
      try { localStorage.setItem("bs-observer", reviewer); } catch { /* ignore */ }
      const r = await planningApi.review(token, item.id, action, reviewer, reason || undefined, threshold);
      setMsg(r.note); setReason(""); onChanged();
    } catch (e: any) { setMsg(e.message); }
  };

  return (
    <aside className="drawer glass plan-drawer" aria-label="planning item">
      <div className="drawer-head plan-head">
        <button className="x-btn" onClick={onClose} aria-label={t("close")}><IX size={16} /></button>
        <span className="status-pill plan">{isTask ? p("cls_SURVEY_TASK") : p("cls_" + item.candidate_class)}</span>
        <h3>{isTask ? `${p("task")} ${item.id.replace("survey-", "")}` : item.street || "—"}</h3>
        <div className="not-approved"><IAlert size={13} />{p("not_approved")}</div>
        <div className="kv">
          <div><div className="k">{p("priority")}</div><div className="v">{score == null ? "—" : Math.round(score)}</div></div>
          <div><div className="k">Rank</div><div className="v">{item.rank ?? "—"}</div></div>
          <div><div className="k">{isTask ? p("destinations") : t("length")}</div><div className="v">{isTask ? item.access_nodes : `${Math.round(item.length_m)} m`}</div></div>
        </div>
      </div>
      <div className="drawer-body">
        <div className="sec-t">{p("why")}</div>
        <p className="body-p">{whyText(item, lang)}</p>
        {!isTask && (
          <dl className="dq">
            <dt>{t("side")}</dt><dd>{t("dir_" + item.compass)}</dd>
            <dt>{t("st_" + item.current_legal_status)}</dt><dd>{p("st_" + item.coverage_finding)}</dd>
            <dt>Walk</dt><dd>{item.walk_distance_to_gap_m} m (vs {item.current_avg_walk_to_verified_m} m)</dd>
          </dl>
        )}

        <div className="sec-t">{p("why_not")}</div>
        <p className="body-p">{p("why_not_body")}</p>

        <div className="sec-t">{p("factors")}</div>
        <table className="tbl">
          <tbody>
            {Object.entries(item.factors).map(([k, v]) => (
              <tr key={k} className={v == null ? "muted-row" : ""}>
                <td>{p("f_" + k)}</td>
                <td>{v == null ? <i>{p("factor_missing")}</i> : `${Math.round(v * 100)}%`}</td>
                <td className="muted">{p("weight")} {Math.round((weights[k] ?? 0) * 100)}%</td>
              </tr>
            ))}
          </tbody>
        </table>

        {isTask && <>
          <div className="sec-t">{p("coverage_states")}</div>
          <div className="chips">
            {Object.entries(item.coverage_states).filter(([, n]) => n).map(([st, n]) => (
              <span key={st} className={`chip cov ${st}`}>{p("st_" + st)}: {n}</span>
            ))}
          </div>
          <div className="sec-t">{p("access_kinds")}</div>
          <div className="chips">{Object.entries(item.access_kinds).map(([k, n]) => <span key={k} className="chip">{k} × {n}</span>)}</div>
          <div className="sec-t">{p("curb")}</div>
          <div className="kv-line">{item.curb_m.total} m · {t("st_PROHIBITED")} {item.curb_m.prohibited} m · {t("st_UNVERIFIED")} {item.curb_m.unverified} m · {t("st_ALLOWED")} {item.curb_m.allowed} m</div>
          {item.curb_segments_to_survey.length > 0 && <>
            <div className="sec-t">{p("curb_survey")}</div>
            {item.curb_segments_to_survey.map((c) => (
              <button key={c.segment_id} className="seg-link" onClick={() => onOpenSegment(c.segment_id)}>
                {c.street || "—"} · {t("dir_" + c.compass)} · {Math.round(c.length_m)} m
                <span className="muted"> — {c.cautions.map((r) => ruleTitle(r, lang)).join(", ")}</span>
              </button>
            ))}
          </>}
        </>}

        {!isTask && <>
          <div className="sec-t">{p("requires")}</div>
          <ul className="limits">{item.requires.map((r) => <li key={r}>{r}</li>)}</ul>
          {item.exclusions_in_cluster && Object.keys(item.exclusions_in_cluster).length > 0 && (
            <div className="kv-line">Excluded nearby: {Object.entries(item.exclusions_in_cluster).map(([k, n]) => `${k} × ${n}`).join(", ")}</div>
          )}
          <button className="seg-link" onClick={() => onOpenSegment(item.segment_id)}>{t("why")} → {item.segment_id}</button>
        </>}

        <div className="sec-t">{p("missing")}</div>
        <ul className="limits">{item.missing_evidence.map((m) => <li key={m}>{m}</li>)}</ul>

        <div className="sec-t">{p("review")} <ReviewBadge action={item.review?.action} lang={lang} /></div>
        {canWrite ? (
          <div className="form-grid" style={{ marginTop: 0 }}>
            <div className="seg-ctl small" style={{ gridTemplateColumns: "1fr 1fr", marginTop: 0 }}>
              {REVIEW_ACTIONS.map((a) => <button key={a} className={action === a ? "on" : ""} onClick={() => setAction(a)}>{p("rev_" + a)}</button>)}
            </div>
            <input placeholder={`${p("reviewer")} *`} value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
            <textarea placeholder={`${p("reason")}${action === "reject" ? " *" : ""}`} value={reason} onChange={(e) => setReason(e.target.value)} />
            <button className="btn-ghost good" disabled={reviewer.trim().length < 2 || (action === "reject" && !reason.trim())} onClick={save}>{p("save_review")}</button>
          </div>
        ) : (
          <div className="static-note">{p("read_only")}</div>
        )}
        {msg && <div className="warn-line" style={{ marginTop: 8 }}>{msg}</div>}
        {!!item.review_history?.length && <>
          <div className="sec-t">{p("review_history")}</div>
          {item.review_history.map((r, k) => (
            <div key={k} className="kv-line"><ReviewBadge action={r.action} lang={lang} /> {r.reviewer} · {r.reviewed_at?.slice(0, 16).replace("T", " ")}{r.reason ? ` — ${r.reason}` : ""}</div>
          ))}
        </>}
      </div>
    </aside>
  );
}
