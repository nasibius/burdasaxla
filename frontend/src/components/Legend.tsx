import type { Meta } from "../types";
import { makeT, type Lang } from "../i18n";
import { STATUS_COLORS } from "./MapView";

export default function Legend({ meta, lang, theme, showRoutes }: { meta: Meta | null; lang: Lang; theme: "dark" | "light"; showRoutes: boolean }) {
  const t = makeT(lang);
  const c = STATUS_COLORS[theme];
  const km = (s: "PROHIBITED" | "ALLOWED" | "UNVERIFIED") => meta ? (meta.stats.by_status[s].length_m / 1000).toFixed(1) + " km" : "";
  return (
    <div className="legend glass">
      <h5>{t("legend")}</h5>
      {(["ALLOWED", "PROHIBITED", "UNVERIFIED"] as const).map((s) => (
        <div className="lg-row" key={s} title={t("st_" + s + "_long")}>
          <span className="lg-swatch" style={{ background: c[s] }} />
          <span>{t("st_" + s + (s === "ALLOWED" && meta?.demo_survey ? "_sim" : ""))}{s === "ALLOWED" && meta?.demo_survey && <> <span className="sim-badge">{t("sim_badge")}</span></>}</span>
          <span className="km">{km(s)}</span>
        </div>
      ))}
      {showRoutes && (
        <div className="lg-routes">
          <div className="lg-row"><span className="lg-swatch" style={{ background: "var(--brand)" }} /><span>{t("drive")}</span></div>
          <div className="lg-row"><span className="lg-swatch" style={{ background: "repeating-linear-gradient(90deg, var(--walk) 0 4px, transparent 4px 8px)" }} /><span>{t("walk")}</span></div>
        </div>
      )}
    </div>
  );
}
