import type { Segment } from "../types";
import { fmtDist, makeT, ruleText, ruleTitle, type Lang } from "../i18n";
import { IBan, ICheck, IExternal, IHelp, IX } from "./Icons";

const osmUrl = (ref: string) => (ref.startsWith("node/") || ref.startsWith("way/") ? `https://www.openstreetmap.org/${ref}` : null);

export default function SegmentDrawer({ seg, lang, onClose }: { seg: Segment; lang: Lang; onClose: () => void }) {
  const t = makeT(lang);
  const Icon = seg.status === "PROHIBITED" ? IBan : seg.status === "VERIFIED" ? ICheck : IHelp;
  const fmtDate = (d?: string | null) => {
    if (!d) return t("never");
    const x = new Date(d);
    return `${String(x.getDate()).padStart(2, "0")}.${String(x.getMonth() + 1).padStart(2, "0")}.${x.getFullYear()}`;
  };
  return (
    <aside className="drawer glass" aria-label="segment details">
      <div className={`drawer-head ${seg.status}`}>
        <button className="x-btn" onClick={onClose} aria-label={t("close")}><IX size={16} /></button>
        <span className={`status-pill ${seg.status}`}><Icon size={14} />{t("st_" + seg.status)}</span>
        <h3>{seg.name || "—"}</h3>
        <div className="dsub">{t("st_" + seg.status + "_long")}</div>
        <div className="kv">
          <div><div className="k">{t("side")}</div><div className="v">{t("dir_" + seg.compass)}</div></div>
          <div><div className="k">{t("length")}</div><div className="v">{fmtDist(seg.length_m, lang)}</div></div>
          <div><div className="k">{t("confidence")}</div><div className="v">{t("conf_" + seg.confidence)}</div></div>
        </div>
      </div>
      <div className="drawer-body">
        {seg.reasons.length > 0 && <>
          <div className="sec-t">{t("reasons")}</div>
          {seg.reasons.map((r) => {
            const url = osmUrl(r.source_ref);
            return (
              <div className="reason" key={r.rule + r.source_ref}>
                <div className="r-t">{ruleTitle(r.rule, lang)} {r.approximation && <span className="mini">{t("approx")}</span>}</div>
                <div className="r-d">{ruleText(r.rule, lang)}</div>
                <div className="r-m">
                  <span>§ {r.legal_ref}</span>
                  <span>{t("source")}: {t("src_" + r.source)}{url ? <> · <a href={url} target="_blank" rel="noreferrer">{r.source_ref} <IExternal size={11} /></a></> : <> · {r.source_ref}</>}</span>
                  <span>{r.rule}@v{r.rule_version}</span>
                </div>
              </div>
            );
          })}
        </>}
        {seg.notes.length > 0 && <>
          <div className="sec-t">{t("notes")}</div>
          {seg.notes.map((r) => (
            <div className="reason info" key={r.rule + r.source_ref}>
              <div className="r-t">{ruleTitle(r.rule, lang)}</div>
              <div className="r-d">{ruleText(r.rule, lang)}</div>
            </div>
          ))}
        </>}
        {seg.status === "UNKNOWN" && (
          <div className="reason info" style={{ borderLeftColor: "var(--unk)" }}>
            <div className="r-t">{t("st_UNKNOWN")}</div>
            <div className="r-d">{lang === "az"
              ? "Məlum qadağa tapılmadı, amma bu hissə sahədə yoxlanılmayıb (nişanlar, sarı xətlər). Qadağanın olmaması avtomatik icazə demək deyil."
              : "No known prohibition, but this curb has not been surveyed (signs, yellow lines). Absence of a prohibition is not an automatic permission."}</div>
          </div>
        )}
        <div className="sec-t">{t("data_quality")}</div>
        <dl className="dq">
          <dt>{t("sources")}</dt><dd>{seg.sources.map((s) => t("src_" + s)).join(", ")}</dd>
          <dt>{t("last_verified")}</dt><dd>{fmtDate(seg.last_verified)}</dd>
          <dt>{t("osm_snapshot")}</dt><dd>{fmtDate(seg.osm_timestamp)}</dd>
          <dt>{t("traffic")}</dt><dd>{seg.oneway ? "↑ oneway" : "⇅"} · {t(seg.travel === "fwd" ? "with_way" : "against_way")}</dd>
          <dt>{t("ruleset")}</dt><dd>{seg.ruleset_version}</dd>
          <dt>OSM</dt><dd><a href={`https://www.openstreetmap.org/${seg.osm_ref}`} target="_blank" rel="noreferrer">{seg.osm_ref} <IExternal size={11} /></a></dd>
        </dl>
        {seg.coverage.length > 0 && <div className="foot-note">✓ {seg.coverage.map((c) => `${t("kind_" + c.kind)} #${c.feature_id}${c.source === "demo_seed" ? " (demo)" : ""}`).join(", ")}</div>}
        <div className="foot-note">{t("curb_geom_note")}</div>
      </div>
    </aside>
  );
}
