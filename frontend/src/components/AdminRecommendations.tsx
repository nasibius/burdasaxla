import { useEffect, useState } from "react";
import { STATIC_MODE } from "../api";
import type { Lang } from "../i18n";
import type { LngLat } from "../types";
import { planningApi, type Candidate, type PlanningSnapshot, type ReviewStatus } from "../planning";

const STATUSES: ReviewStatus[] = ["needs_survey", "shortlist", "more_data_needed", "reject"];
const THRESHOLD = 450;

/** Admin "Recommendations" tab: AYNA planning survey targets with the review workflow, inside the admin panel. */
export default function AdminRecommendations({ lang, token, focusMap }: { lang: Lang; token: string; focusMap: (pts: LngLat[]) => void }) {
  const t = (en: string, az: string) => (lang === "az" ? az : en);
  const label = (s: ReviewStatus) => ({
    needs_survey: t("Needs survey", "Sahə yoxlaması"), shortlist: t("Shortlisted", "Qısa siyahıda"),
    reject: t("Rejected", "Rədd edilib"), more_data_needed: t("More data needed", "Əlavə məlumat lazımdır"),
  })[s];
  const [data, setData] = useState<PlanningSnapshot | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<ReviewStatus | "">("");
  const [open, setOpen] = useState("");
  const [action, setAction] = useState<ReviewStatus>("shortlist");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    planningApi.snapshot(THRESHOLD).then((d) => { setData(d); setError(""); }).catch((e) => setError(String(e.message ?? e)));
  }, [refresh]);

  if (error) return <div className="err">{error}</div>;
  if (!data) return <div className="mode-hint">{t("Loading recommendations…", "Tövsiyələr yüklənir…")}</div>;

  const rows = data.candidates.filter((c) => !filter || c.review_status === filter);
  const counts = Object.fromEntries(STATUSES.map((s) => [s, data.candidates.filter((c) => c.review_status === s).length]));
  const save = async (c: Candidate) => {
    setBusy(true); setMsg("");
    try {
      await planningApi.review(c, action, reason.trim(), token, THRESHOLD);
      setMsg(t("Review saved.", "Rəy yadda saxlanıldı.")); setReason(""); setOpen(""); setRefresh((n) => n + 1);
    } catch (e: any) { setMsg(String(e.message ?? e)); } finally { setBusy(false); }
  };

  return (
    <div className="admin-recs">
      <div className="mode-hint" style={{ margin: "0 2px 10px" }}>
        {t("AYNA planning recommendations: road sides worth a field survey for a future taxi pick-up/drop-off zone. They are survey targets, not legal approvals, and are not ranked.",
          "AYNA planlaşdırma tövsiyələri: gələcək taksi minmə/düşmə zonası üçün sahə yoxlamasına dəyər yol kənarları. Bunlar hüquqi təsdiq deyil, yoxlama hədəfləridir və sıralanmayıb.")}
      </div>
      <div className="recs-summary">
        <span><b>{data.candidates.length}</b> {t("targets", "hədəf")}</span>
        <span><b>{data.summary.verified_official_locations}</b> {t("official zones", "rəsmi zona")}</span>
        <span><b>{data.summary.observed_usable_curb_segments}</b> {t("observed curbs", "müşahidə olunan kənar")}</span>
      </div>
      <div className="recs-filter">
        <select aria-label="Recommendation status filter" value={filter} onChange={(e) => setFilter(e.target.value as ReviewStatus | "")}>
          <option value="">{t("All", "Hamısı")} · {data.candidates.length}</option>
          {STATUSES.map((s) => <option key={s} value={s}>{label(s)} · {counts[s]}</option>)}
        </select>
        <a className="btn-ghost" href="#authority">{t("Open AYNA dashboard", "AYNA panelini aç")}</a>
      </div>
      {msg && <div className="warn-line" style={{ marginTop: 8 }}>{msg}</div>}
      {rows.length === 0 && <div className="mode-hint">{data.empty_reason ?? t("No recommendations in this status.", "Bu statusda tövsiyə yoxdur.")}</div>}
      {rows.map((c) => (
        <div key={c.candidate_id} className={`task rec-card ${open === c.candidate_id ? "open" : ""}`}>
          <div className="rec-head" onClick={() => { setOpen(open === c.candidate_id ? "" : c.candidate_id); focusMap(c.geometry.coordinates); }}>
            <div>
              <b>{c.name || c.candidate_id}</b>
              <div className="rec-sub">{c.road_side} · {Math.round(c.length_m)} m{c.is_synthetic_example ? " · SIMULATED EXAMPLE" : ""}</div>
            </div>
            <span className={`rec-st ${c.review_status}`}>{label(c.review_status)}</span>
          </div>
          {open === c.candidate_id && (
            <div className="rec-body">
              {c.reasons.length > 0 && <div><b>{t("Why", "Niyə")}:</b> {c.reasons.join(" · ")}</div>}
              {c.missing_evidence.length > 0 && <div><b>{t("Missing evidence", "Çatışmayan sübut")}:</b> {c.missing_evidence.join(" · ")}</div>}
              {c.constraints.length > 0 && <div><b>{t("Constraints", "Məhdudiyyətlər")}:</b> {c.constraints.join(" · ")}</div>}
              {c.review_history.length > 0 && (
                <div><b>{t("History", "Tarixçə")}:</b> {c.review_history.map((h) => `${label(h.action)} (${h.reviewed_at.slice(0, 10)})${h.reason ? ": " + h.reason : ""}`).join(" · ")}</div>
              )}
              {STATIC_MODE ? (
                <div className="mode-hint">{t("Reviews are saved on the live backend (admin link above).", "Rəylər canlı serverdə saxlanılır (yuxarıdakı admin keçidi).")}</div>
              ) : (
                <div className="rec-review">
                  <select aria-label="Review action" value={action} onChange={(e) => setAction(e.target.value as ReviewStatus)}>
                    {STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
                  </select>
                  <input aria-label="Review reason" placeholder={t("Reason (min. 3 characters)", "Səbəb (min. 3 simvol)")} value={reason} onChange={(e) => setReason(e.target.value)} />
                  <button className="btn-primary" disabled={busy || !token || reason.trim().length < 3} onClick={() => save(c)}>{t("Save review", "Rəyi saxla")}</button>
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
