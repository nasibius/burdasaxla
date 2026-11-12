import { useState } from "react";
import type { RuleCatalog } from "../types";
import { makeT, ruleText, ruleTitle, type Lang } from "../i18n";
import { IExternal, IX } from "./Icons";
import { VerificationBadge } from "./SegmentDrawer";

const ORDER = { prohibit: 0, caution: 1, info: 2 } as const;

/** Every rule the engine applies, with its article, the official quote and how certain we are about it. */
export default function RulesPanel({ catalog, lang, onClose }: { catalog: RuleCatalog; lang: Lang; onClose: () => void }) {
  const t = makeT(lang);
  const [filter, setFilter] = useState<"all" | "prohibit" | "caution" | "info">("all");
  const rules = [...catalog.rules]
    .filter((r) => filter === "all" || r.effect === filter)
    .sort((a, b) => ORDER[a.effect] - ORDER[b.effect] || a.id.localeCompare(b.id));
  return (
    <aside className="drawer glass rules-panel" aria-label={t("rules_title")}>
      <div className="drawer-head">
        <button className="x-btn" onClick={onClose} aria-label={t("close")}><IX size={16} /></button>
        <h3 style={{ marginTop: 0 }}>{t("rules_title")}</h3>
        <div className="dsub">{t("rules_sub")}</div>
        <div className="law-box" style={{ marginTop: 12 }}>
          <div>
            <div>{catalog.law.title}</div>
            <a href={catalog.law.url} target="_blank" rel="noreferrer">{t("law_link")} <IExternal size={11} /></a>
            <div className="muted" style={{ fontSize: 11.5 }}>{catalog.law.version_note} · {catalog.version}</div>
          </div>
        </div>
        <div className="seg-ctl small">
          {(["all", "prohibit", "caution", "info"] as const).map((f) => (
            <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
              {f === "all" ? "∗" : t("eff_" + f)}
            </button>
          ))}
        </div>
      </div>
      <div className="drawer-body">
        {rules.map((r) => (
          <div key={r.id} className={`reason ${r.effect}`}>
            <div className="r-t">{ruleTitle(r.id, lang)} <VerificationBadge level={r.verification} lang={lang} /></div>
            <div className="r-d">{ruleText(r.id, lang)}</div>
            <div className="r-m">
              <span className={`eff ${r.effect}`}>{t("eff_" + r.effect)}</span>
              {r.article && <span>§ m.{r.article}</span>}
              {r.applies_to === "durma" && <span>{t("applies_durma")}</span>}
              {r.exempt.length > 0 && <span>{t("exempt_for")}: {r.exempt.map((v) => t("vehicle_" + v)).join(", ")}</span>}
              <span>{r.id}@v{r.version}</span>
            </div>
            {(r.quote || r.note) && (
              <div className="r-quote">
                {r.quote && <blockquote>“{r.quote}”</blockquote>}
                {r.note && <p>{r.note}</p>}
              </div>
            )}
          </div>
        ))}
      </div>
    </aside>
  );
}
