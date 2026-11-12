import { useEffect, useMemo, useState } from "react";
import { ADMIN_URL, STATIC_MODE, api, type NewFeature } from "../api";
import type { CuratedFeature, FeatureKind, FeatureSource, Impact, LngLat, SourcesReport } from "../types";
import { makeT, type Lang } from "../i18n";
import { IAlert, ICheck, IExternal, IMap, IShield, ITrash, IX, Logo } from "./Icons";

export const TOOL_GEOM: Record<FeatureKind, "point" | "line" | "polygon"> = {
  sign_3_27: "point", sign_3_28: "point", marking_1_4: "line", marking_1_10: "line", bus_lane: "line",
  taxi_stand: "line", observed_prohibition: "line", official_zone: "line", survey_area: "polygon",
};

const TOOL_BADGE: Record<FeatureKind, { bg: string; fg: string; txt: string }> = {
  sign_3_27: { bg: "#e11d48", fg: "#fff", txt: "3.27" },
  sign_3_28: { bg: "#1d4ed8", fg: "#fff", txt: "3.28" },
  marking_1_4: { bg: "#facc15", fg: "#111", txt: "1.4" },
  marking_1_10: { bg: "#fde68a", fg: "#111", txt: "1.10" },
  bus_lane: { bg: "#f97316", fg: "#fff", txt: "BUS" },
  taxi_stand: { bg: "#fde047", fg: "#111", txt: "5.14" },
  observed_prohibition: { bg: "#ff5468", fg: "#fff", txt: "52.IV" },
  official_zone: { bg: "#22d3ee", fg: "#06212a", txt: "AYNA" },
  survey_area: { bg: "#818cf8", fg: "#fff", txt: "✓" },
};
const CLAUSES = ["52.IV.1", "52.IV.3", "52.IV.5", "52.IV.8", "52.IV.9", "52.IV.11"];
const MANUAL_SOURCES: FeatureSource[] = ["field_survey", "street_photo", "ayna_official", "other_official", "mapillary", "ai_vision"];

const store = {
  get: (k: string, d = "") => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set: (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
};
const today = () => new Date().toISOString().slice(0, 10);

interface FormState {
  id?: number;
  kind: FeatureKind;
  side: "auto" | "left" | "right";
  zone_mode: "to_next_intersection" | "length" | "to_point";
  zone_length_m: string;
  zone_end: LngLat | null;
  plate: string;
  line_type: "unknown" | "solid" | "dashed";
  clause: string;
  source: FeatureSource;
  source_url: string;
  source_ref: string;
  observer: string;
  observed_at: string;
  note: string;
  status: "pending" | "verified";
  files: File[];
}

const emptyForm = (kind: FeatureKind): FormState => ({
  kind, side: "auto", zone_mode: "to_next_intersection", zone_length_m: "", zone_end: null, plate: "",
  line_type: "unknown", clause: "", source: "field_survey", source_url: "", source_ref: "",
  observer: store.get("bs-observer"), observed_at: today(), note: "", status: "pending", files: [],
});

function formFromFeature(f: CuratedFeature): FormState {
  const p = f.props ?? {};
  return {
    id: f.id, kind: f.kind, side: p.side ?? "auto", zone_mode: p.zone_mode ?? "to_next_intersection",
    zone_length_m: p.zone_length_m ? String(p.zone_length_m) : "", zone_end: p.zone_end ?? null, plate: p.plate ?? "",
    line_type: p.line_type ?? "unknown", clause: p.clause ?? "", source: (f.source as FeatureSource) ?? "field_survey",
    source_url: f.source_url ?? "", source_ref: f.source_ref ?? "", observer: f.observer ?? store.get("bs-observer"),
    observed_at: f.observed_at ?? today(), note: f.note ?? "", status: "pending", files: [],
  };
}

function propsOf(f: FormState): Record<string, unknown> {
  const p: Record<string, unknown> = {};
  if (f.side !== "auto") p.side = f.side;
  if (f.kind === "sign_3_27" || f.kind === "sign_3_28") {
    p.zone_mode = f.zone_mode;
    if (f.zone_mode === "length") p.zone_length_m = Number(f.zone_length_m);
    if (f.zone_mode === "to_point" && f.zone_end) p.zone_end = f.zone_end;
    if (f.plate) p.plate = f.plate;
  }
  if (f.kind === "bus_lane") p.line_type = f.line_type;
  if (f.kind === "observed_prohibition") p.clause = f.clause || null;
  return p;
}

function geometryFor(kind: FeatureKind, coords: LngLat[]) {
  const g = TOOL_GEOM[kind];
  if (g === "point") return { type: "Point" as const, coordinates: coords[0] };
  if (g === "line") return { type: "LineString" as const, coordinates: coords };
  return { type: "Polygon" as const, coordinates: [[...coords, coords[0]]] };
}

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
  requestPoint: (cb: (c: LngLat) => void) => void;
  setCameraMarks: (m: { camera: LngLat; target: LngLat; heading?: number | null }[]) => void;
  setHighlight: (id: number | null) => void;
  focusMap: (pts: LngLat[]) => void;
}

function Badge({ kind }: { kind: FeatureKind }) {
  const b = TOOL_BADGE[kind];
  return <span className="t-ic" style={{ background: b.bg, color: b.fg }}>{b.txt}</span>;
}

function anchorOf(f: CuratedFeature): LngLat {
  const g = f.geometry;
  if (g.type === "Point") return g.coordinates;
  if (g.type === "LineString") return g.coordinates[0];
  return g.coordinates[0][0];
}

export default function AdminPanel(p: Props) {
  const t = makeT(p.lang);
  const [authed, setAuthed] = useState(false);
  const [tokenInput, setTokenInput] = useState(p.token);
  const [tasks, setTasks] = useState<CuratedFeature[]>([]);
  const [all, setAll] = useState<CuratedFeature[]>([]);
  const [sources, setSources] = useState<SourcesReport | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [impact, setImpact] = useState<Impact | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"queue" | "verified" | "rejected">("queue");

  const load = async (tok = p.token) => {
    try {
      const [tk, ls, src] = await Promise.all([api.admin.tasks(tok), api.admin.list(tok), api.admin.sources()]);
      setTasks(tk); setAll(ls); setSources(src); setAuthed(true); setErr(null);
    } catch (e: any) { setAuthed(false); setErr(e.message); }
  };
  useEffect(() => { if (p.token && !STATIC_MODE) load(); /* eslint-disable-next-line */ }, [p.token, p.version]);

  // start a new form whenever a drawing tool is picked
  useEffect(() => {
    if (p.tool && (!form || form.kind !== p.tool || (form.id && !p.draft.length))) {
      if (!form?.id) setForm(emptyForm(p.tool));
    }
    // eslint-disable-next-line
  }, [p.tool]);

  const geometry = useMemo(() => (form && p.draftDone ? geometryFor(form.kind, p.draft) : null), [form?.kind, p.draftDone, p.draft]);

  // live impact preview (side, extent, conflicts)
  useEffect(() => {
    setImpact(null);
    if (!form) return;
    const existing = form.id ? all.find((f) => f.id === form.id) : null;
    const g = geometry ?? existing?.geometry;
    if (!g) return;
    const h = setTimeout(() => {
      api.admin.preview(p.token, { kind: form.kind, geometry: g, source: form.source, observer: form.observer || "preview", props: propsOf(form) } as any)
        .then(setImpact).catch((e) => setErr(e.message));
    }, 200);
    return () => clearTimeout(h);
    // eslint-disable-next-line
  }, [geometry, form?.kind, form?.side, form?.zone_mode, form?.zone_length_m, form?.zone_end, form?.line_type, form?.id]);

  const set = (patch: Partial<FormState>) => setForm((f) => (f ? { ...f, ...patch } : f));
  const closeForm = () => { setForm(null); setImpact(null); p.onCancelDraft(); p.setCameraMarks([]); p.setHighlight(null); };

  const save = async () => {
    if (!form) return;
    setBusy(true); setErr(null); setMsg(null);
    store.set("bs-observer", form.observer);
    try {
      const base = {
        source: form.source, source_url: form.source_url || undefined, source_ref: form.source_ref || undefined,
        observer: form.observer, observed_at: form.observed_at || undefined, note: form.note || undefined, props: propsOf(form),
      };
      let id = form.id;
      if (id) {
        await api.admin.edit(p.token, id, { ...base, ...(geometry ? { geometry } : {}) } as any);
      } else {
        if (!geometry) throw new Error(t("admin_draw_point"));
        id = (await api.admin.add(p.token, { kind: form.kind, geometry, status: "pending", ...base } as NewFeature)).id;
      }
      for (const file of form.files) await api.admin.uploadEvidence(p.token, id!, file);
      if (form.status === "verified") await api.admin.decide(p.token, id!, "verified", undefined, form.observer);
      closeForm();
      p.onChanged();
      await load();
    } catch (e: any) { setErr(e.message); p.onChanged(); await load(); } finally { setBusy(false); }
  };

  const decide = async (f: CuratedFeature, d: "verified" | "rejected") => {
    let note: string | undefined;
    if (d === "rejected") {
      note = window.prompt(t("admin_reject_note")) ?? undefined;
      if (!note) return;
    }
    setBusy(true); setErr(null);
    try { await api.admin.decide(p.token, f.id, d, note, store.get("bs-observer") || "admin"); p.onChanged(); await load(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const remove = async (f: CuratedFeature) => {
    if (!window.confirm(`${t("admin_delete")} #${f.id}?`)) return;
    setBusy(true);
    try { await api.admin.remove(p.token, f.id); p.onChanged(); await load(); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const edit = (f: CuratedFeature) => {
    p.onCancelDraft();
    setForm(formFromFeature(f));
    p.setHighlight(f.id);
    showCamera(f);
    document.querySelector(".panel .panel-body")?.scrollTo({ top: 0, behavior: "smooth" });
  };
  const showCamera = (f: CuratedFeature) => {
    const marks = (f.evidence ?? []).filter((e) => e.camera_lon != null && e.camera_lat != null)
      .map((e) => ({ camera: [e.camera_lon!, e.camera_lat!] as LngLat, target: anchorOf(f), heading: e.camera_heading }));
    p.setCameraMarks(marks);
    const g = f.geometry;
    const pts: LngLat[] = g.type === "Point" ? [g.coordinates] : g.type === "LineString" ? g.coordinates : g.coordinates[0];
    p.focusMap([...pts, ...marks.map((m) => m.camera)]);
  };
  const runImport = async (fn: () => Promise<any>) => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const r = await fn();
      setMsg(t("admin_import_result").replace("{found}", r.found).replace("{created}", r.created).replace("{dup}", r.skipped_duplicates)
        + (r.errors?.length ? ` · ${r.errors.join("; ")}` : ""));
      p.onChanged(); await load();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  const drawHint = form ? (TOOL_GEOM[form.kind] === "point" ? t("admin_draw_point") : TOOL_GEOM[form.kind] === "line" ? t("admin_draw_line") : t("admin_draw_poly")) : "";
  const editingFeature = form?.id ? all.find((f) => f.id === form.id) : null;
  const needsGeometry = !form?.id && !p.draftDone;
  const list = tab === "queue" ? tasks : all.filter((f) => f.status === tab);

  const FeatureCard = ({ f }: { f: CuratedFeature }) => (
    <div className="task" onMouseEnter={() => p.setHighlight(f.id)} onMouseLeave={() => p.setHighlight(null)}>
      <div className="t-h">
        <Badge kind={f.kind} /> {t("kind_" + f.kind)} <span className="muted" style={{ fontWeight: 500 }}>#{f.id}</span>
        <span className={`status-tag ${f.status}`}>{t("st_" + f.status)}</span>
      </div>
      <div className="kv-line">
        <span><b>{t("source")}:</b> {t("src_" + f.source)}{f.source_ref ? ` · ${f.source_ref}` : ""}</span>
        {f.observer && <span><b>{t("admin_observer")}:</b> {f.observer}</span>}
        {f.observed_at && <span><b>{t("admin_observed_at")}:</b> {f.observed_at}</span>}
        {f.confidence != null && <span><b>{t("admin_confidence")}:</b> {Math.round(f.confidence * 100)}%</span>}
        {f.impact?.matched[0] && <span><b>{f.impact.matched[0].street || "—"}</b> · {t("dir_" + (f.impact.matched[0].compass ?? "N"))}</span>}
        {f.impact && <span>{t("admin_affects")}: {f.impact.affected_segments.length} {t("admin_segments")}</span>}
      </div>
      {f.source_url && <div className="kv-line"><a href={f.source_url} target="_blank" rel="noreferrer">{f.source_url.slice(0, 60)} <IExternal size={11} /></a></div>}
      {f.note && <div className="kv-line">“{f.note}”</div>}
      {f.review_note && <div className="kv-line"><b>Review:</b> {f.review_note}</div>}
      {!!f.evidence?.length && (
        <div className="ev-grid">
          {f.evidence.map((e) => (
            <a key={e.id} href={api.evidenceUrl(e.id, p.token)} target="_blank" rel="noreferrer" title={e.camera_lon != null ? `${t("admin_camera")}: ${e.camera_lat}, ${e.camera_lon}` : e.original_name}>
              <img src={api.evidenceUrl(e.id, p.token)} alt={e.original_name ?? "evidence"} loading="lazy" />
            </a>
          ))}
        </div>
      )}
      {f.impact?.conflicts.map((c, i) => <div key={i} className="conflict"><IAlert size={13} />{t("admin_conflict")}: {t("conflict_" + c.type)}</div>)}
      {f.status === "pending" && !!f.problems?.length && (
        <div className="problems"><b>{t("admin_problems")}:</b><ul>{f.problems.map((x) => <li key={x}>{x}</li>)}</ul></div>
      )}
      <div className="t-a">
        {f.status === "pending" && <button className="btn-ghost good" disabled={busy || !!f.problems?.length} onClick={() => decide(f, "verified")}><ICheck size={13} />{t("admin_approve")}</button>}
        {f.status === "pending" && <button className="btn-ghost danger" disabled={busy} onClick={() => decide(f, "rejected")}><IX size={13} />{t("admin_reject")}</button>}
        <button className="btn-ghost" disabled={busy} onClick={() => edit(f)}>{t("admin_edit")}</button>
        {!!f.evidence?.some((e) => e.camera_lon != null) && <button className="btn-ghost" onClick={() => showCamera(f)}>📷</button>}
        <button className="btn-ghost danger" style={{ marginLeft: "auto", padding: "5px 8px" }} disabled={busy} onClick={() => remove(f)} title={t("admin_delete")}><ITrash size={13} /></button>
      </div>
    </div>
  );

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
        {STATIC_MODE ? (
          <div className="static-note">{t("static_admin")}
            {ADMIN_URL && <p><a className="btn-primary" href={ADMIN_URL}>{p.lang === "az" ? "Canlı admin panelini aç" : "Open live admin"}</a></p>}
          </div>
        ) : !authed ? (
          <form onSubmit={(e) => { e.preventDefault(); p.setToken(tokenInput); load(tokenInput); }}>
            <div className="field-label"><span>{t("admin_token")}</span></div>
            <div className="form-grid" style={{ marginTop: 0 }}>
              <input type="password" value={tokenInput} onChange={(e) => setTokenInput(e.target.value)} placeholder="BURDASAXLA_ADMIN_TOKEN" autoFocus />
            </div>
            <button className="btn-primary" type="submit">{t("admin_login")}</button>
            {err && <div className="err">{err}</div>}
          </form>
        ) : (
          <>
            {sources && (
              <div className="intro" style={{ marginTop: 0 }}>
                <div className="kv-line" style={{ marginTop: 0 }}><b>{t("admin_coverage")}:</b> {(sources.survey_coverage.share * 100).toFixed(1)}% · {(sources.survey_coverage.curb_m_verified / 1000).toFixed(2)} / {(sources.survey_coverage.curb_m_total / 1000).toFixed(1)} km</div>
                <div className="coverage-bar"><span style={{ width: `${Math.min(100, sources.survey_coverage.share * 100)}%` }} /></div>
                <div className="kv-line">OSM: {sources.osm.traffic_sign_candidates} sign tags · AYNA: {sources.official_ayna_dataset}</div>
              </div>
            )}

            {!form && <>
              <div className="field-label"><span>{t("admin_add")}</span></div>
              <div className="admin-tools">
                {(Object.keys(TOOL_GEOM) as FeatureKind[]).map((k) => (
                  <button key={k} className={`tool ${p.tool === k ? "on" : ""}`} onClick={() => p.setTool(p.tool === k ? null : k)}>
                    <Badge kind={k} /><span>{t("kind_" + k)}</span>
                  </button>
                ))}
              </div>
            </>}

            {form && (
              <div className="drawing-box">
                <div className="t-h" style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 650 }}>
                  <Badge kind={form.kind} /> {t("kind_" + form.kind)} {form.id ? <span className="muted">#{form.id} · {t("admin_edit")}</span> : null}
                </div>
                {editingFeature?.status === "verified" && <div className="kv-line"><IAlert size={12} /> {t("admin_reopen_note")}</div>}
                {needsGeometry && (
                  <div style={{ marginTop: 8 }}>
                    {drawHint}
                    <div className="row">
                      {TOOL_GEOM[form.kind] === "polygon" && p.draft.length >= 3 && <button className="btn-ghost good" onClick={p.onFinishPolygon}><ICheck size={13} />{t("admin_finish")}</button>}
                      <button className="btn-ghost" onClick={closeForm}><IX size={13} />{t("admin_cancel")}</button>
                    </div>
                  </div>
                )}
                {!needsGeometry && (
                  <>
                    {form.id && !(p.tool && !p.draftDone) && (
                      <div className="row"><button className="btn-ghost" onClick={() => { p.onCancelDraft(); p.setTool(form.kind); }}><IMap size={13} />{t("admin_move")}</button></div>
                    )}
                    {form.id && p.tool && !p.draftDone && <div style={{ marginTop: 8 }}>{drawHint}</div>}
                    {impact && (
                      <div style={{ marginTop: 8 }}>
                        <b>{t("admin_affects")}:</b> {impact.affected_segments.length} {t("admin_segments")}
                        {impact.matched[0] && <> · {impact.matched[0].street || "—"} · <b>{t("dir_" + (impact.matched[0].compass ?? "N"))}</b>
                          {" "}({t("admin_direction")}: {impact.matched[0].travel === "fwd" ? t("with_way") : t("against_way")})</>}
                        {impact.conflicts.map((c, i) => <div key={i} className="conflict"><IAlert size={13} />{t("admin_conflict")}: {t("conflict_" + c.type)}</div>)}
                      </div>
                    )}
                    <div className="form-grid">
                      {form.kind !== "survey_area" && (
                        <div>
                          <label>{t("admin_side")}</label>
                          <div className="seg-ctl small" style={{ gridTemplateColumns: "repeat(3,1fr)", marginTop: 0 }}>
                            {(["auto", "left", "right"] as const).map((s) => (
                              <button type="button" key={s} className={form.side === s ? "on" : ""} onClick={() => set({ side: s })}>{t("admin_side_" + s)}</button>
                            ))}
                          </div>
                        </div>
                      )}
                      {(form.kind === "sign_3_27" || form.kind === "sign_3_28") && <>
                        <div>
                          <label>{t("admin_zone")}</label>
                          <select value={form.zone_mode} onChange={(e) => set({ zone_mode: e.target.value as FormState["zone_mode"] })}>
                            <option value="to_next_intersection">{t("zone_to_next_intersection")}</option>
                            <option value="length">{t("zone_length")}</option>
                            <option value="to_point">{t("zone_to_point")}</option>
                          </select>
                        </div>
                        {form.zone_mode === "length" && <input type="number" min={1} max={1000} placeholder="m" value={form.zone_length_m} onChange={(e) => set({ zone_length_m: e.target.value })} />}
                        {form.zone_mode === "to_point" && (
                          <button type="button" className="btn-ghost" onClick={() => p.requestPoint((c) => set({ zone_end: c }))}>
                            <IMap size={13} />{form.zone_end ? `${form.zone_end[1].toFixed(5)}, ${form.zone_end[0].toFixed(5)}` : t("zone_pick_end")}
                          </button>
                        )}
                        <input placeholder={t("admin_plate")} value={form.plate} onChange={(e) => set({ plate: e.target.value })} />
                      </>}
                      {form.kind === "bus_lane" && (
                        <div>
                          <label>{t("admin_line_type")}</label>
                          <select value={form.line_type} onChange={(e) => set({ line_type: e.target.value as FormState["line_type"] })}>
                            <option value="unknown">{t("line_unknown")}</option>
                            <option value="solid">{t("line_solid")}</option>
                            <option value="dashed">{t("line_dashed")}</option>
                          </select>
                        </div>
                      )}
                      {form.kind === "observed_prohibition" && (
                        <div>
                          <label>{t("admin_clause")}</label>
                          <select value={form.clause} onChange={(e) => set({ clause: e.target.value })}>
                            <option value="">—</option>
                            {CLAUSES.map((c) => <option key={c} value={c}>m.{c}</option>)}
                          </select>
                        </div>
                      )}
                      <div className="field-row">
                        <div>
                          <label>{t("admin_source")}</label>
                          <select value={form.source} onChange={(e) => set({ source: e.target.value as FeatureSource })}>
                            {MANUAL_SOURCES.map((s) => <option key={s} value={s}>{t("src_" + s)}</option>)}
                          </select>
                        </div>
                        <div>
                          <label>{t("admin_observed_at")}</label>
                          <input type="date" value={form.observed_at} onChange={(e) => set({ observed_at: e.target.value })} />
                        </div>
                      </div>
                      <input placeholder={`${t("admin_observer")} *`} value={form.observer} onChange={(e) => set({ observer: e.target.value })} />
                      <input placeholder={t("admin_source_url")} value={form.source_url} onChange={(e) => set({ source_url: e.target.value })} />
                      <input placeholder={t("admin_source_ref")} value={form.source_ref} onChange={(e) => set({ source_ref: e.target.value })} />
                      <textarea placeholder={t("admin_note")} value={form.note} onChange={(e) => set({ note: e.target.value })} />
                      <div>
                        <label>{t("admin_photos")}</label>
                        <input type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={(e) => set({ files: Array.from(e.target.files ?? []) })} />
                        <div className="kv-line">{t("admin_photos_hint")}</div>
                        {!!editingFeature?.evidence?.length && (
                          <div className="ev-grid">{editingFeature.evidence.map((e) => (
                            <a key={e.id} href={api.evidenceUrl(e.id, p.token)} target="_blank" rel="noreferrer"><img src={api.evidenceUrl(e.id, p.token)} alt="" /></a>
                          ))}</div>
                        )}
                      </div>
                      <select value={form.status} onChange={(e) => set({ status: e.target.value as FormState["status"] })}>
                        <option value="pending">{t("admin_status_pending")}</option>
                        <option value="verified">{t("admin_status_verified")}</option>
                      </select>
                    </div>
                    <div className="row">
                      <button className="btn-ghost good" disabled={busy || form.observer.trim().length < 2} onClick={save}><ICheck size={13} />{t("admin_save")}</button>
                      <button className="btn-ghost" onClick={closeForm}><IX size={13} />{t("admin_cancel")}</button>
                    </div>
                  </>
                )}
              </div>
            )}

            {err && <div className="err">{err}</div>}
            {msg && <div className="warn-line" style={{ marginTop: 10 }}>{msg}</div>}

            <div className="admin-sec">
              <div className="seg-ctl small" style={{ gridTemplateColumns: "repeat(3,1fr)" }}>
                <button className={tab === "queue" ? "on" : ""} onClick={() => setTab("queue")}>{t("admin_queue")} · {tasks.length}</button>
                <button className={tab === "verified" ? "on" : ""} onClick={() => setTab("verified")}>{t("st_verified")} · {all.filter((f) => f.status === "verified").length}</button>
                <button className={tab === "rejected" ? "on" : ""} onClick={() => setTab("rejected")}>{t("st_rejected")} · {all.filter((f) => f.status === "rejected").length}</button>
              </div>
              <div style={{ height: 10 }} />
              {list.length === 0 && <div className="mode-hint" style={{ margin: "0 2px" }}>{t("admin_empty_queue")}</div>}
              {list.map((f) => <FeatureCard key={f.id} f={f} />)}
            </div>

            <div className="admin-sec">
              <div className="field-label"><span>{t("admin_import")}</span></div>
              <div className="import-row">
                <button className="btn-ghost" disabled={busy} onClick={() => runImport(() => api.admin.importOsm(p.token, store.get("bs-observer") || "osm-importer"))}>{t("admin_import_osm")}</button>
                <button className="btn-ghost" disabled={busy} title={sources?.mapillary.configured ? "" : "MAPILLARY_TOKEN"}
                  onClick={() => runImport(() => api.admin.importMapillary(p.token, store.get("bs-observer") || "mapillary-importer"))}>{t("admin_import_mapillary")}</button>
                <label className="btn-ghost file-btn">{t("admin_import_geojson")}
                  <input type="file" accept=".geojson,.json,application/geo+json,application/json" onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    try {
                      const fc = JSON.parse(await file.text());
                      runImport(() => api.admin.importGeojson(p.token, store.get("bs-observer") || "geojson-import", fc));
                    } catch { setErr("GeoJSON parse error"); }
                  }} />
                </label>
              </div>
              <div className="kv-line">{t("admin_all_pending")}</div>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
