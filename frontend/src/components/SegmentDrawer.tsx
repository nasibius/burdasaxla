import { useState } from "react";
import type { LawInfo, Reason, RuleInfo, Segment, VehicleClass } from "../types";
import { fmtDist, makeT, ruleText, ruleTitle, type Lang } from "../i18n";
import { IAlert, IBan, ICheck, IExternal, IHelp, IInfo, IX } from "./Icons";

const osmUrl = (ref?: string) => (ref && (ref.startsWith("node/") || ref.startsWith("way/")) ? `https://www.openstreetmap.org/${ref}` : null);

export function VerificationBadge({ level, lang }: { level?: string; lang: Lang }) {
  if (!level) return null;
  const t = makeT(lang);
  return <span className={`vbadge ${level}`}>{t("ver_" + level)}</span>;
}

function ReasonCard({ r, kind, lang, rule, vehicle }: { r: Reason; kind: "prohibit" | "caution" | "info"; lang: Lang; rule?: RuleInfo; vehicle: VehicleClass }) {
  const t = makeT(lang);
  const [open, setOpen] = useState(false);
  const url = osmUrl(r.source_ref);
  const exempt = rule?.exempt ?? r.exempt ?? [];
  return (
    <div className={`reason ${kind}`}>
      <div className="r-t">
        {ruleTitle(r.rule, lang)}
        <VerificationBadge level={rule?.verification ?? r.verification} lang={lang} />
      </div>
      <div className="r-d">{ruleText(r.rule, lang)}</div>
      {exempt.length > 0 && (
        <div className={`r-exempt ${exempt.includes(vehicle) ? "on" : ""}`}>
          {t("exempt_for")}: {exempt.map((v) => t("vehicle_" + v)).join(", ")}
        </div>
      )}
      <div className="r-m">
        {rule?.article && <span>§ {rule.legal_ref}</span>}
        {r.source && r.source !== "engine" && (
          <span>{t("source")}: {t("src_" + r.source)}
            {url ? <> · <a href={url} target="_blank" rel="noreferrer">{r.source_ref} <IExternal size={11} /></a></>
              : r.source_ref && r.source_ref !== "coverage" && r.source_ref !== "conflict" ? <> · {r.source_ref}</> : null}
          </span>
        )}
        {rule && <span>{r.rule}@v{rule.version}</span>}
        {rule && (rule.quote || rule.note) && (
          <button className="linkish" onClick={() => setOpen((o) => !o)}>{open ? "−" : "+"} {t("legal_basis")}</button>
        )}
      </div>
      {open && rule && (
        <div className="r-quote">
          {rule.quote && <><div className="q-l">{t("quote")}</div><blockquote>“{rule.quote}”</blockquote></>}
          {rule.note && <><div className="q-l">{t("impl_note")}</div><p>{rule.note}</p></>}
        </div>
      )}
    </div>
  );
}

export default function SegmentDrawer({ seg, lang, onClose, rules, law, vehicle }: {
  seg: Segment; lang: Lang; onClose: () => void; rules: Record<string, RuleInfo>; law?: LawInfo; vehicle: VehicleClass;
}) {
  const t = makeT(lang);
  const status = seg.status_by_vehicle?.[vehicle] ?? seg.status;
  const Icon = status === "PROHIBITED" ? IBan : status === "ALLOWED" ? ICheck : IHelp;
  const fmtDate = (d?: string | null) => {
    if (!d) return t("never");
    const x = new Date(d);
    if (Number.isNaN(+x)) return d;
    return `${String(x.getDate()).padStart(2, "0")}.${String(x.getMonth() + 1).padStart(2, "0")}.${x.getFullYear()}`;
  };
  const differs = seg.status_by_vehicle && seg.status_by_vehicle.taxi !== seg.status_by_vehicle.private;
  return (
    <aside className="drawer glass" aria-label="segment details">
      <div className={`drawer-head ${status}`}>
        <button className="x-btn" onClick={onClose} aria-label={t("close")}><IX size={16} /></button>
        <span className={`status-pill ${status}`}><Icon size={14} />{t("st_" + status)}</span>
        <h3>{seg.name || "—"}</h3>
        <div className="dsub">{t("st_" + status + "_long")}</div>
        <div className="kv">
          <div><div className="k">{t("side")}</div><div className="v">{t("dir_" + seg.compass)}</div></div>
          <div><div className="k">{t("length")}</div><div className="v">{fmtDist(seg.length_m, lang)}</div></div>
          <div><div className="k">{t("confidence")}</div><div className="v">{t("conf_" + seg.confidence)}</div></div>
        </div>
        {differs && (
          <div className="per-vehicle">
            {t("per_vehicle")}:{" "}
            {(["taxi", "private"] as VehicleClass[]).map((v) => (
              <span key={v} className={`mini-pill ${seg.status_by_vehicle[v]}`}>{t("vehicle_" + v)}: {t("st_" + seg.status_by_vehicle[v])}</span>
            ))}
          </div>
        )}
      </div>
      <div className="drawer-body">
        {seg.reasons.length > 0 && <>
          <div className="sec-t">{t("reasons")}</div>
          {seg.reasons.map((r) => <ReasonCard key={r.rule + r.source_ref} r={r} kind="prohibit" lang={lang} rule={rules[r.rule]} vehicle={vehicle} />)}
        </>}
        {seg.cautions?.length > 0 && <>
          <div className="sec-t">{t("cautions")}</div>
          {seg.cautions.map((r) => <ReasonCard key={r.rule + r.source_ref} r={r} kind="caution" lang={lang} rule={rules[r.rule]} vehicle={vehicle} />)}
        </>}
        {seg.notes.length > 0 && <>
          <div className="sec-t">{t("notes")}</div>
          {seg.notes.map((r) => <ReasonCard key={r.rule + r.source_ref} r={r} kind="info" lang={lang} rule={rules[r.rule]} vehicle={vehicle} />)}
        </>}
        <div className="sec-t">{t("data_quality")}</div>
        <dl className="dq">
          <dt>{t("sources")}</dt><dd>{seg.sources.map((s) => t("src_" + s)).join(", ")}</dd>
          <dt>{t("last_verified")}</dt><dd>{fmtDate(seg.last_verified)}</dd>
          <dt>{t("osm_snapshot")}</dt><dd>{fmtDate(seg.osm_timestamp)}</dd>
          <dt>{t("traffic")}</dt><dd>{seg.oneway ? `↑ ${t("oneway")}` : `⇅ ${t("twoway")}`}</dd>
          <dt>{t("ruleset")}</dt><dd>{seg.ruleset_version}</dd>
          <dt>OSM</dt><dd><a href={`https://www.openstreetmap.org/${seg.osm_ref}`} target="_blank" rel="noreferrer">{seg.osm_ref} <IExternal size={11} /></a></dd>
        </dl>
        {seg.coverage.length > 0 && (
          <div className="foot-note"><ICheck size={12} /> {seg.coverage.map((c) => `${t("kind_" + c.kind)} #${c.feature_id} · ${t("src_" + c.source)}`).join(", ")}</div>
        )}
        {law && (
          <div className="law-box">
            <IInfo size={14} />
            <div>
              <div>{law.title}</div>
              <a href={law.url} target="_blank" rel="noreferrer">{t("law_link")} <IExternal size={11} /></a>
              <span className="muted"> · {law.retrieved}</span>
            </div>
          </div>
        )}
        <div className="foot-note"><IAlert size={12} /> {t("curb_geom_note")}</div>
      </div>
    </aside>
  );
}
