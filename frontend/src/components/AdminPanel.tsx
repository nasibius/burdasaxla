import { useEffect, useState } from "react";
import { api } from "../api";
import type { CuratedFeature, FeatureKind, LngLat } from "../types";
import { makeT, type Lang } from "../i18n";
import { IAlert, ICheck, IShield, ITrash, IX, Logo } from "./Icons";

export const TOOL_GEOM: Record<FeatureKind, "point" | "line" | "polygon"> = {
  sign_3_27: "point", sign_3_28: "point", marking_1_4: "line", marking_1_10: "line",
  bus_lane: "line", official_zone: "line", survey_area: "polygon",
};

const TOOL_BADGE: Record<FeatureKind, { bg: string; fg: string; txt: string }> = {
  sign_3_27: { bg: "#e11d48", fg: "#fff", txt: "3.27" },
  sign_3_28: { bg: "#1d4ed8", fg: "#fff", txt: "3.28" },
  marking_1_4: { bg: "#facc15", fg: "#111", txt: "1.4" },
  marking_1_10: { bg: "#fde68a", fg: "#111", txt: "1.10" },
  bus_lane: { bg: "#f97316", fg: "#fff", txt: "BUS" },
  official_zone: { bg: "#22d3ee", fg: "#06212a", txt: "AYNA" },
  survey_area: { bg: "#818cf8", fg: "#fff", txt: "✓" },
};

interface Props {
  lang: Lang;
  token: string;
  setToken: (t: string) => void;
  tool: FeatureKind | null;
  setTool: (k: FeatureKind | null) => void;
  draft: LngLat[];
  draftDone: boolean;
  onFinishPolygon: () => void;
  onCancelDraft: () => void;
  onChanged: () => void;
  version: number;
}

function geometryFor(kind: FeatureKind, coords: LngLat[]) {
  const g = TOOL_GEOM[kind];
  if (g === "point") return { type: "Point" as const, coordinates: coords[0] };
  if (g === "line") return { type: "LineString" as const, coordinates: coords };
  return { type: "Polygon" as const, coordinates: [[...coords, coords[0]]] };
}

export default function AdminPanel(p: Props) {
  const t = makeT(p.lang);
  const [authed, setAuthed] = useState(false);
  const [tokenInput, setTokenInput] = useState(p.token);
  const [tasks, setTasks] = useState<CuratedFeature[]>([]);
  const [all, setAll] = useState<CuratedFeature[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ source: "field_survey", source_url: "", note: "", status: "pending" as "pending" | "verified" });
  const [impact, setImpact] = useState<CuratedFeature["impact"] | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async (tok = p.token) => {
    try {
      const [tk, ls] = await Promise.all([api.admin.tasks(tok), api.admin.list(tok)]);
      setTasks(tk); setAll(ls.filter((f) => f.status === "verified")); setAuthed(true); setErr(null);
    } catch (e: any) { setAuthed(false); setErr(e.message); }
  };
  useEffect(() => { if (p.token) load(); /* eslint-disable-next-line */ }, [p.token, p.version]);

  useEffect(() => {
    setImpact(null);
    if (!p.tool || !p.draftDone) return;
    api.admin.preview(p.token, { kind: p.tool, geometry: geometryFor(p.tool, p.draft), source: form.source, props: {} } as any)
      .then(setImpact).catch((e) => setErr(e.message));
    // eslint-disable-next-line
  }, [p.draftDone, p.draft, p.tool]);

  const save = async () => {
    if (!p.tool) return;
    setBusy(true);
    try {
      await api.admin.add(p.token, {
        kind: p.tool, geometry: geometryFor(p.tool, p.draft), source: form.source,
        source_url: form.source_url || undefined, note: form.note || undefined, status: form.status, props: {},
      } as any);
      p.onCancelDraft();
      p.onChanged();
      await load();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  const decide = async (id: number, d: "verified" | "rejected") => {
    setBusy(true);
    try { await api.admin.decide(p.token, id, d); p.onChanged(); await load(); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const remove = async (id: number) => {
    setBusy(true);
    try { await api.admin.remove(p.token, id); p.onChanged(); await load(); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  const hint = p.tool ? (TOOL_GEOM[p.tool] === "point" ? t("admin_draw_point") : TOOL_GEOM[p.tool] === "line" ? t("admin_draw_line") : t("admin_draw_poly")) : "";

  return (
    <section className="panel glass">
      <div className="panel-head">
        <div className="brand">
          <Logo />
          <div>
            <div className="brand-name">Burda<b>Saxla</b></div>
            <div className="brand-sub"><IShield size={13} />{t("admin_title")}</div>
          </div>
        </div>
      </div>
      <div className="panel-body">
        {!authed ? (
          <form onSubmit={(e) => { e.preventDefault(); p.setToken(tokenInput); load(tokenInput); }}>
            <div className="field-label"><span>{t("admin_token")}</span></div>
            <div className="form-grid" style={{ marginTop: 0 }}>
              <input type="password" value={tokenInput} onChange={(e) => setTokenInput(e.target.value)} placeholder="burdasaxla-admin" autoFocus />
            </div>
            <button className="btn-primary" type="submit">{t("admin_login")}</button>
            {err && <div className="err">{err}</div>}
          </form>
        ) : (
          <>
            <div className="field-label"><span>{t("admin_add")}</span></div>
            <div className="admin-tools">
              {(Object.keys(TOOL_GEOM) as FeatureKind[]).map((k) => (
                <button key={k} className={`tool ${p.tool === k ? "on" : ""}`} onClick={() => p.setTool(p.tool === k ? null : k)}>
                  <span className="t-ic" style={{ background: TOOL_BADGE[k].bg, color: TOOL_BADGE[k].fg }}>{TOOL_BADGE[k].txt}</span>
                  <span>{t("kind_" + k)}</span>
                </button>
              ))}
            </div>

            {p.tool && (
              <div className="drawing-box">
                <div>{hint}</div>
                {!p.draftDone && (
                  <div className="row">
                    {TOOL_GEOM[p.tool] === "polygon" && p.draft.length >= 3 && <button className="btn-ghost good" onClick={p.onFinishPolygon}><ICheck size={13} />{t("admin_finish")}</button>}
                    <button className="btn-ghost" onClick={p.onCancelDraft}><IX size={13} />{t("admin_cancel")}</button>
                  </div>
                )}
                {p.draftDone && (
                  <>
                    {impact && (
                      <div style={{ marginTop: 8 }}>
                        <b>{t("admin_affects")}:</b> {impact.affected_segments.length} {t("admin_segments")}
                        {impact.matched[0] && <> · {impact.matched[0].street || "—"} ({impact.matched[0].side})</>}
                        {impact.conflicts.length > 0 && (
                          <div className="conflict"><IAlert size={13} />{t("admin_conflict")}: {t("conflict_" + impact.conflicts[0].type)} ({impact.conflicts.length})</div>
                        )}
                      </div>
                    )}
                    <div className="form-grid">
                      <select value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} aria-label={t("admin_source")}>
                        {["field_survey", "ayna_official", "street_imagery", "ai_vision"].map((s) => <option key={s} value={s}>{t("src_" + s)}</option>)}
                      </select>
                      <input placeholder={t("admin_source_url")} value={form.source_url} onChange={(e) => setForm({ ...form, source_url: e.target.value })} />
                      <textarea placeholder={t("admin_note")} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
                      <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as any })}>
                        <option value="pending">{t("admin_status_pending")}</option>
                        <option value="verified">{t("admin_status_verified")}</option>
                      </select>
                    </div>
                    <div className="row">
                      <button className="btn-ghost good" disabled={busy} onClick={save}><ICheck size={13} />{t("admin_save")}</button>
                      <button className="btn-ghost" onClick={p.onCancelDraft}><IX size={13} />{t("admin_cancel")}</button>
                    </div>
                  </>
                )}
              </div>
            )}

            {err && <div className="err">{err}</div>}

            <div className="results-head"><h4>{t("admin_queue")}</h4><small>{tasks.length}</small></div>
            {tasks.length === 0 && <div className="mode-hint" style={{ margin: "0 2px" }}>{t("admin_empty_queue")}</div>}
            {tasks.map((f) => (
              <div className="task" key={f.id}>
                <div className="t-h">
                  <span className="t-ic tool" style={{ padding: 0, border: 0, background: "none" }}>
                    <span className="t-ic" style={{ background: TOOL_BADGE[f.kind].bg, color: TOOL_BADGE[f.kind].fg, width: 26, height: 26, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 800 }}>{TOOL_BADGE[f.kind].txt}</span>
                  </span>
                  {t("kind_" + f.kind)} <span style={{ color: "var(--muted)", fontWeight: 500 }}>#{f.id}</span>
                </div>
                <div className="t-m">
                  {t("src_" + f.source)} · {new Date(f.created_at).toLocaleString()}
                  {f.impact?.matched[0] && <> · {f.impact.matched[0].street || "—"} ({f.impact.matched[0].side})</>}
                  {f.note && <div>“{f.note}”</div>}
                  {f.impact && <div>{t("admin_affects")}: {f.impact.affected_segments.length} {t("admin_segments")}</div>}
                </div>
                {f.impact?.conflicts.length ? <div className="conflict"><IAlert size={13} />{t("conflict_" + f.impact.conflicts[0].type)}</div> : null}
                <div className="t-a">
                  <button className="btn-ghost good" disabled={busy} onClick={() => decide(f.id, "verified")}><ICheck size={13} />{t("admin_approve")}</button>
                  <button className="btn-ghost danger" disabled={busy} onClick={() => decide(f.id, "rejected")}><IX size={13} />{t("admin_reject")}</button>
                </div>
              </div>
            ))}

            <div className="results-head"><h4>{t("admin_verified")}</h4><small>{all.length}</small></div>
            {all.map((f) => (
              <div className="task" key={f.id}>
                <div className="t-h">
                  <span style={{ background: TOOL_BADGE[f.kind].bg, color: TOOL_BADGE[f.kind].fg, width: 26, height: 26, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 800 }}>{TOOL_BADGE[f.kind].txt}</span>
                  {t("kind_" + f.kind)} <span style={{ color: "var(--muted)", fontWeight: 500 }}>#{f.id}</span>
                  <button className="btn-ghost danger" style={{ marginLeft: "auto", padding: "5px 8px" }} disabled={busy} onClick={() => remove(f.id)} title={t("admin_delete")}><ITrash size={13} /></button>
                </div>
                <div className="t-m">{t("src_" + f.source)} · {f.verified_at ? new Date(f.verified_at).toLocaleDateString() : ""}{f.note && <div>“{f.note}”</div>}</div>
              </div>
            ))}
          </>
        )}
      </div>
    </section>
  );
}
