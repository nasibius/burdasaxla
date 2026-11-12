import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { STATIC_MODE, api } from "./api";
import AdminPanel, { TOOL_GEOM } from "./components/AdminPanel";
import { IInfo, ILayers, IMap, IMoon, IShield, ISun, IX, Logo } from "./components/Icons";
import Legend from "./components/Legend";
import MapView, { type MapResult } from "./components/MapView";
import Panel from "./components/Panel";
import RulesPanel from "./components/RulesPanel";
import SegmentDrawer from "./components/SegmentDrawer";
import { makeT, type Lang } from "./i18n";
import type {
  Context, CuratedFeature, FeatureKind, LngLat, Meta, Mode, RecResponse, RuleCatalog, RuleInfo, SearchItem, Segment, SegFeature, VehicleClass,
} from "./types";

const store = {
  get: (k: string, d: string) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set: (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
};

const DEMO_ORIGIN: LngLat = [49.8436, 40.3757];

export default function App() {
  const [theme, setTheme] = useState<"dark" | "light">(() => store.get("bs-theme", "dark") as any);
  const [lang, setLang] = useState<Lang>(() => store.get("bs-lang", "az") as Lang);
  const [view, setView] = useState<"map" | "admin">(() => (location.hash === "#admin" ? "admin" : "map"));
  const t = makeT(lang);

  const [meta, setMeta] = useState<Meta | null>(null);
  const [segments, setSegments] = useState<SegFeature[]>([]);
  const [context, setContext] = useState<Context | null>(null);
  const [features, setFeatures] = useState<CuratedFeature[]>([]);
  const [version, setVersion] = useState(0);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  const [mode, setMode] = useState<Mode>("dropoff");
  const [destination, setDestination] = useState<LngLat | null>(null);
  const [destLabel, setDestLabel] = useState("");
  const [origin, setOrigin] = useState<LngLat | null>(DEMO_ORIGIN);
  const [originLabel, setOriginLabel] = useState<string | null>(null); // null = demo start point
  const [picking, setPicking] = useState<"destination" | "origin" | null>(null);
  const [maxWalk, setMaxWalk] = useState(450);
  const [resp, setResp] = useState<RecResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [vehicle, setVehicle] = useState<VehicleClass>(() => (store.get("bs-vehicle", "taxi") === "private" ? "private" : "taxi"));
  const [catalog, setCatalog] = useState<RuleCatalog | null>(null);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [segDetail, setSegDetail] = useState<Segment | null>(null);
  const [layers, setLayers] = useState({ segments: true, stops: true, crossings: true, features: true });
  const [layersOpen, setLayersOpen] = useState(false);
  const [zoom, setZoom] = useState(16);
  const [fit, setFit] = useState<{ pts: LngLat[]; token: number; maxZoom?: number }>({ pts: [], token: 0 });

  // admin drawing
  const [token, setToken] = useState(() => store.get("bs-admin", ""));
  const [tool, setTool] = useState<FeatureKind | null>(null);
  const [draft, setDraft] = useState<LngLat[]>([]);
  const [draftDone, setDraftDone] = useState(false);
  const pointRequest = useRef<((c: LngLat) => void) | null>(null);
  const [cameraMarks, setCameraMarks] = useState<{ camera: LngLat; target: LngLat; heading?: number | null }[]>([]);
  const [highlight, setHighlight] = useState<number | null>(null);

  useEffect(() => { document.documentElement.dataset.theme = theme; store.set("bs-theme", theme); }, [theme]);
  useEffect(() => { document.documentElement.lang = lang; store.set("bs-lang", lang); }, [lang]);
  useEffect(() => { store.set("bs-admin", token); }, [token]);
  useEffect(() => { store.set("bs-vehicle", vehicle); }, [vehicle]);
  useEffect(() => { api.rules().then(setCatalog).catch(() => setCatalog(null)); }, []);
  useEffect(() => {
    const onHash = () => setView(location.hash === "#admin" ? "admin" : "map");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // data loading
  useEffect(() => {
    Promise.all([api.meta(vehicle), api.segments(vehicle), api.context()])
      .then(([m, s, c]) => { setMeta(m); setSegments(s.features); setContext(c); setLoadErr(null); })
      .catch((e) => setLoadErr(e.message));
  }, [version, vehicle]);
  useEffect(() => {
    const p = view === "admin" && token && !STATIC_MODE
      ? api.admin.list(token).then((l) => l.filter((f) => f.status !== "rejected")).catch(() => api.features())
      : api.features();
    p.then(setFeatures).catch(() => setFeatures([]));
  }, [version, view, token]);

  // recommendations
  const reqId = useRef(0);
  useEffect(() => {
    if (view !== "map") return;
    const ready = mode === "driver" ? !!origin : !!destination;
    if (!ready) { setResp(null); return; }
    const id = ++reqId.current;
    setLoading(true); setError(null);
    const h = window.setTimeout(() => {
      const call = mode === "driver" ? api.driverNearest(origin!, vehicle) : api.recommend(destination!, origin, mode, maxWalk, vehicle);
      call.then((r) => {
        if (id !== reqId.current) return;
        setResp(r);
        setSelectedKey(r.results[0] ? "c" + r.results[0].rank : r.unverified_candidates?.[0] ? "u" + r.unverified_candidates[0].rank : null);
        const pts: LngLat[] = [...r.results.map((x) => x.point), ...(r.unverified_candidates ?? []).map((x) => x.point)];
        if (destination && mode !== "driver") pts.push(destination);
        if (origin && (mode === "driver" || r.results.some((x) => x.drive_route))) pts.push(origin);
        setFit((f) => ({ pts, token: f.token + 1, maxZoom: pts.length > 1 ? 18 : 16 }));
        if (mode !== "driver" && destLabel.startsWith("📍") && r.curb_at_door?.name) setDestLabel("📍 " + r.curb_at_door.name);
      }).catch((e) => id === reqId.current && setError(e.message === "network" ? t("err_network") : e.message))
        .finally(() => id === reqId.current && setLoading(false));
    }, 120);
    return () => window.clearTimeout(h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, destination, origin, maxWalk, version, view, vehicle]);

  const openSegment = useCallback((id: string, _at?: LngLat) => {
    api.segment(id).then((sg) => { setSegDetail(sg); setRulesOpen(false); }).catch((e) => setError(e.message));
  }, []);

  const onMapClick = useCallback((c: LngLat) => {
    if (view === "admin") {
      if (pointRequest.current) { pointRequest.current(c); pointRequest.current = null; return; }
      if (!tool || draftDone) return;
      const next = [...draft, c];
      setDraft(next);
      const g = TOOL_GEOM[tool];
      if ((g === "point" && next.length === 1) || (g === "line" && next.length === 2)) setDraftDone(true);
      return;
    }
    if (picking === "origin") { setOrigin(c); setOriginLabel(`${c[1].toFixed(5)}, ${c[0].toFixed(5)}`); setPicking(null); return; }
    if (picking === "destination" || (mode !== "driver" && !destination)) {
      setDestination(c); setDestLabel(`📍 ${c[1].toFixed(5)}, ${c[0].toFixed(5)}`); setPicking(null); return;
    }
    setSegDetail(null);
  }, [view, tool, draft, draftDone, picking, mode, destination]);

  const onPickSearch = (it: SearchItem) => { setDestination([it.lon, it.lat]); setDestLabel(it.name); setPicking(null); };
  const onMyLocation = () => {
    if (!navigator.geolocation) { setError(t("geo_unavailable")); setPicking("origin"); return; }
    navigator.geolocation.getCurrentPosition((pos) => {
      const c: LngLat = [pos.coords.longitude, pos.coords.latitude];
      const b = meta?.bbox;
      if (b && (c[1] < b[0] || c[1] > b[2] || c[0] < b[1] || c[0] > b[3])) { setError(t("outside_area")); setPicking("origin"); return; }
      setOrigin(c); setOriginLabel(t("my_location"));
    }, (err) => { setError(t(err.code === 1 ? "geo_denied" : "geo_unavailable")); setPicking("origin"); },
    { enableHighAccuracy: true, timeout: 8000 });
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setPicking(null); setSegDetail(null); setLayersOpen(false);
      if (tool) { setDraft([]); setDraftDone(false); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tool]);

  const cancelDraft = () => { setDraft([]); setDraftDone(false); setTool(null); };
  const center = useMemo<LngLat>(() => meta?.center ?? [49.8497, 40.3797], [meta]);
  const results: MapResult[] = view === "map"
    ? [...(resp?.results ?? []).map((r) => ({ ...r, key: "c" + r.rank })),
       ...(resp?.unverified_candidates ?? []).map((r) => ({ ...r, key: "u" + r.rank, unverified: true }))]
    : [];
  const rulesById = useMemo<Record<string, RuleInfo>>(
    () => Object.fromEntries((catalog?.rules ?? []).map((r) => [r.id, r])), [catalog]);

  if (!meta && loadErr) {
    return (
      <div style={{ display: "grid", placeItems: "center", height: "100%", padding: 24, textAlign: "center" }}>
        <div><Logo size={56} /><h2>BurdaSaxla API</h2><p style={{ color: "var(--muted)" }}>{loadErr}<br />Start the backend: <code>uvicorn app.main:app --port 8000</code></p></div>
      </div>
    );
  }

  const toggleLayer = (k: keyof typeof layers) => setLayers((l) => ({ ...l, [k]: !l[k] }));

  return (
    <div className="app">
      <MapView
        center={center} theme={theme} lang={lang} segments={segments} context={context} features={features} layers={layers}
        destination={view === "map" && mode !== "driver" ? destination : null} origin={view === "map" ? origin : null}
        results={results} selectedKey={selectedKey} selectedSegment={segDetail?.id ?? null}
        cameraMarks={view === "admin" ? cameraMarks : []} highlightFeature={view === "admin" ? highlight : null}
        picking={!!picking || (view === "admin" && !!tool && !draftDone)}
        fitPoints={fit.pts} fitToken={fit.token} fitMaxZoom={fit.maxZoom}
        draft={view === "admin" && tool ? { kind: tool, coords: draft } : null}
        onMapClick={onMapClick} onSelectKey={setSelectedKey}
        onSelectSegment={(id, at) => {
          // While placing a point (destination/driver/admin drawing), a click on a curb is a placement, not "open details".
          if (picking || (view === "admin" && ((tool && !draftDone) || pointRequest.current))) onMapClick(at);
          else openSegment(id);
        }}
        onMoveDestination={(c) => { setDestination(c); setDestLabel(`📍 ${c[1].toFixed(5)}, ${c[0].toFixed(5)}`); }}
        onMoveOrigin={(c) => { setOrigin(c); setOriginLabel(`${c[1].toFixed(5)}, ${c[0].toFixed(5)}`); }}
        onZoom={setZoom} zoom={zoom}
      />

      {view === "map" ? (
        <Panel
          lang={lang} meta={meta} mode={mode} setMode={(m) => { setMode(m); setSegDetail(null); }}
          destLabel={destLabel} setDestLabel={setDestLabel} destination={destination}
          origin={origin} originLabel={originLabel ?? t("demo_origin")} picking={picking} setPicking={setPicking}
          onPickSearch={onPickSearch} onClearDestination={() => { setDestination(null); setDestLabel(""); setResp(null); }}
          onMyLocation={onMyLocation} maxWalk={maxWalk} setMaxWalk={setMaxWalk}
          resp={resp} loading={loading} error={error} selectedKey={selectedKey} onSelect={setSelectedKey}
          onOpenSegment={openSegment} vehicle={vehicle} setVehicle={setVehicle}
        />
      ) : (
        <AdminPanel
          lang={lang} token={token} setToken={setToken} tool={tool}
          setTool={(k) => { setTool(k); setDraft([]); setDraftDone(false); }}
          draft={draft} draftDone={draftDone} onFinishPolygon={() => setDraftDone(true)} onCancelDraft={cancelDraft}
          onChanged={() => setVersion((v) => v + 1)} version={version}
          requestPoint={(cb) => { pointRequest.current = cb; }}
          setCameraMarks={setCameraMarks} setHighlight={setHighlight}
          focusMap={(pts) => setFit((f) => ({ pts, token: f.token + 1, maxZoom: 19 }))}
        />
      )}

      <div className="toolbar">
        <div className="mob-brand glass"><Logo size={28} /><span>Burda<b>Saxla</b></span></div>
        <button className={`tb-btn ${layersOpen ? "active" : ""}`} onClick={() => setLayersOpen((o) => !o)} aria-label={t("layers")}>
          <ILayers size={17} /><span className="lbl">{t("layers")}</span>
        </button>
        <button className={`tb-btn ${rulesOpen ? "active" : ""}`} onClick={() => { setRulesOpen((o) => !o); setSegDetail(null); }} aria-label={t("rules_btn")}>
          <IInfo size={17} /><span className="lbl">{t("rules_btn")}</span>
        </button>
        <button className="tb-btn" onClick={() => setLang(lang === "az" ? "en" : "az")} aria-label="language">{lang === "az" ? "EN" : "AZ"}</button>
        <button className="tb-btn" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="theme">
          {theme === "dark" ? <ISun size={17} /> : <IMoon size={17} />}
        </button>
        <button className="tb-btn" onClick={() => { location.hash = view === "admin" ? "" : "#admin"; setSegDetail(null); }}>
          {view === "admin" ? <IMap size={17} /> : <IShield size={17} />}<span className="lbl">{view === "admin" ? t("map") : t("admin")}</span>
        </button>
      </div>

      {layersOpen && (
        <div className="popover glass">
          {([["segments", "layer_segments"], ["stops", "layer_stops"], ["crossings", "layer_crossings"], ["features", "layer_features"]] as const).map(([k, label]) => (
            <div key={k} className={`toggle-row ${layers[k] ? "on" : ""}`} onClick={() => toggleLayer(k)} role="switch" aria-checked={layers[k]}>
              <span>{t(label)}</span><span className="sw" />
            </div>
          ))}
        </div>
      )}

      {picking && (
        <div className="pick-toast glass">
          {picking === "destination" ? t("picking_dest") : t("picking_origin")}
          <button onClick={() => setPicking(null)}><IX size={12} /></button>
        </div>
      )}

      {!segDetail && !rulesOpen && <Legend meta={meta} lang={lang} theme={theme} showRoutes={results.length > 0} />}
      {segDetail && <SegmentDrawer seg={segDetail} lang={lang} onClose={() => setSegDetail(null)} rules={rulesById} law={catalog?.law} vehicle={vehicle} />}
      {rulesOpen && !segDetail && catalog && <RulesPanel catalog={catalog} lang={lang} onClose={() => setRulesOpen(false)} />}
    </div>
  );
}
