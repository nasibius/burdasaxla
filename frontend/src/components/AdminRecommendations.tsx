import { useEffect, useState } from "react";
import { STATIC_MODE } from "../api";
import type { Lang } from "../i18n";
import type { LngLat } from "../types";
import { planningApi, type Candidate, type DemandReport, type PlanningSnapshot, type ReviewStatus } from "../planning";

const STATUSES: ReviewStatus[] = ["needs_survey", "shortlist", "more_data_needed", "reject"];
const THRESHOLD = 450;

type Props = { lang: Lang; token: string; focusMap: (pts: LngLat[]) => void };

/** Admin "Recommendations" tab: demand-based "build a new stopping place here" + AYNA survey targets. */
export default function AdminRecommendations(p: Props) {
  const [view, setView] = useState<"demand" | "survey">("demand");
  const az = p.lang === "az";
  return (
    <>
      <div className="seg-ctl small" style={{ gridTemplateColumns: "repeat(2,1fr)", marginBottom: 10 }}>
        <button className={view === "demand" ? "on" : ""} onClick={() => setView("demand")}>{az ? "Tələbat → yeni yer" : "Demand → new place"}</button>
        <button className={view === "survey" ? "on" : ""} onClick={() => setView("survey")}>{az ? "Sahə yoxlaması" : "Survey targets"}</button>
      </div>
      {view === "demand" ? <DemandRecommendations {...p} /> : <SurveyRecommendations {...p} />}
    </>
  );
}

function DemandRecommendations({ lang, focusMap }: Props) {
  const t = (en: string, az: string) => (lang === "az" ? az : en);
  const [data, setData] = useState<DemandReport | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState("");
  useEffect(() => { planningApi.demand().then(setData).catch((e) => setError(String(e.message ?? e))); }, []);
  if (error) return <div className="err">{error}</div>;
  if (!data) return <div className="mode-hint">{t("Loading…", "Yüklənir…")}</div>;
  const side = (s: string) => (s === "left" ? t("left side", "sol tərəf") : t("right side", "sağ tərəf"));
  const status = (s: string, sim: boolean) => s === "ALLOWED" ? (sim ? t("allowed · simulated", "olar · simulyasiya") : t("allowed", "olar"))
    : s === "UNVERIFIED" ? t("unverified", "yoxlanmayıb") : s;
  return (
    <div className="admin-recs">
      <div className="mode-hint" style={{ margin: "0 2px 10px" }}>
        {t(`Areas where drivers send many requests but there is no legal stopping place within ${data.legal_radius_m} m. The program recommends building a new stopping place here. A recommendation is a planning signal: the site still needs a field survey and an official decision.`,
          `Sürücülərin çoxlu sorğu göndərdiyi, amma ${data.legal_radius_m} m daxilində qanuni dayanma yeri olmayan ərazilər. Proqram burada yeni saxlama yeri yaratmağı tövsiyə edir. Tövsiyə planlaşdırma siqnalıdır: yer sahədə yoxlanmalı və rəsmi qərar verilməlidir.`)}
      </div>
      <div className="recs-summary">
        <span><b>{data.hotspots.length}</b> {t("hotspots", "ərazi")}</span>
        <span><b>{data.logged_requests}</b> {t("real requests logged", "real sorğu qeydə alınıb")}</span>
      </div>
      {data.demo && (
        <div className="banner sim" style={{ marginBottom: 10 }}>
          <span><span className="sim-badge">SİMULYASİYA</span> {t("Hotspots marked SIMULATED use invented request counts at real places, as a demo. Real hotspots appear as drivers use the live app.",
            "SİMULYASİYA ilə işarələnmiş ərazilərdə sorğu sayları uydurulmuş nümunədir (demo). Real ərazilər sürücülər canlı tətbiqdən istifadə etdikcə yaranır.")}</span>
        </div>
      )}
      {data.hotspots.length === 0 && <div className="mode-hint">{t(`No area has ${data.min_unmet}+ unmet requests yet.`, `Hələ ${data.min_unmet}+ cavabsız sorğusu olan ərazi yoxdur.`)}</div>}
      {data.hotspots.map((h) => {
        const s = h.suggested_site;
        return (
          <div key={h.id} className={`task rec-card ${open === h.id ? "open" : ""}`}>
            <div className="rec-head" onClick={() => { setOpen(open === h.id ? "" : h.id); focusMap(s ? [h.center, ...s.geometry] : [h.center]); }}>
              <div>
                <b>{h.place ?? (s?.name || t("Unnamed area", "Adsız ərazi"))}</b>{h.is_synthetic_example && <> <span className="sim-badge">SİMULYASİYA</span></>}
                <div className="rec-sub">{h.requests} {t("requests", "sorğu")} · {h.unmet} {t("without a legal spot", "qanuni yer tapılmadan")}</div>
              </div>
              <span className={`rec-st ${s ? "build" : "reject"}`}>{s ? t("Build new place", "Yeni yer tikmək") : t("No usable curb", "Uyğun kənar yoxdur")}</span>
            </div>
            {open === h.id && (
              <div className="rec-body">
                <div>
                  {t(`Drivers sent ${h.requests} requests to this area; ${h.unmet} times no legally confirmed stopping place was found. `,
                    `Bu əraziyə ${h.requests} sorğu göndərilib; ${h.unmet} dəfə təsdiqlənmiş qanuni dayanma yeri tapılmayıb. `)}
                  {h.nearest_legal_m == null
                    ? t("There is no confirmed legal stopping place in the analysed area.", "Analiz olunan ərazidə təsdiqlənmiş qanuni dayanma yeri yoxdur.")
                    : t(`The nearest confirmed one is ${h.nearest_legal_m} m away.`, `Ən yaxın təsdiqlənmiş yer ${h.nearest_legal_m} m uzaqdadır.`)}
                </div>
                {s ? (
                  <div className="rec-suggest">
                    <b>{t("Recommendation: a new stopping place can be built here", "Tövsiyə: bura yeni saxlanacaq yer tikmək olar")}</b>
                    <div>{s.name || "—"} · {side(s.side)} · {Math.round(s.length_m)} m · {s.distance_m} m {t("from the area centre", "ərazinin mərkəzindən")}</div>
                    <div>{t("Current curb status", "Cari status")}: {status(s.current_status, s.simulated_green)}{s.cautions.length ? ` · ${t("to check", "yoxlanmalı")}: ${s.cautions.join(", ")}` : ""}</div>
                  </div>
                ) : (
                  <div>{t(`No curb within ${data.site_radius_m} m is free of statutory prohibitions; a new place needs a road redesign.`,
                    `${data.site_radius_m} m daxilində qanuni qadağası olmayan kənar yoxdur; yeni yer üçün yolun yenidən planlaşdırılması lazımdır.`)}</div>
                )}
                <div className="rec-sub">{t("Not a legal approval: survey the site and get an official decision first.", "Hüquqi təsdiq deyil: əvvəlcə yer yoxlanmalı və rəsmi qərar alınmalıdır.")}</div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function SurveyRecommendations({ lang, token, focusMap }: Props) {
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
