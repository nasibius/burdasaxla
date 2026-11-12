import type {
  Context, CuratedFeature, Impact, LngLat, Meta, RecResponse, RuleCatalog, SearchItem, Segment, SegFeature,
  SourcesReport, VehicleClass,
} from "./types";

const env = (import.meta as any).env ?? {};
const BASE = env.VITE_API_BASE ?? "";
/** Static mode: no backend; data comes from precomputed JSON (GitHub Pages build). */
export const STATIC_MODE = env.VITE_STATIC === "1";
const DATA = `${env.BASE_URL ?? "/"}static-data/`;

async function req<T>(path: string, init?: RequestInit & { token?: string }): Promise<T> {
  const headers: Record<string, string> = {};
  if (!(init?.body instanceof FormData)) headers["content-type"] = "application/json";
  if (init?.token) headers["x-admin-token"] = init.token;
  let r: Response;
  try {
    r = await fetch(BASE + path, { ...init, headers: { ...headers, ...(init?.headers as any) } });
  } catch {
    throw new Error("network");
  }
  if (!r.ok) {
    let msg: unknown = `${r.status}`;
    try { msg = (await r.json()).detail ?? msg; } catch { /* not JSON */ }
    if (Array.isArray(msg)) msg = msg.map((d: any) => `${(d.loc ?? []).slice(-1)[0] ?? ""}: ${d.msg}`).join("; ");
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

// ---------------------------------------------------------------- static mode
const cache = new Map<string, Promise<any>>();
function data<T>(name: string): Promise<T> {
  if (!cache.has(name)) {
    cache.set(name, fetch(DATA + name).then((r) => {
      if (!r.ok) throw new Error(`${name}: ${r.status}`);
      return r.json();
    }).catch((e) => { cache.delete(name); throw e; }));
  }
  return cache.get(name)!;
}

let enginePromise: Promise<import("./static/engine").StaticEngine> | null = null;
function engine() {
  if (!enginePromise) {
    enginePromise = Promise.all([import("./static/engine"), data<any>("engine.json"), data<Meta>("meta.json")])
      .then(([mod, d, meta]) => new mod.StaticEngine(d, meta.center))
      .catch((e) => { enginePromise = null; throw e; });
  }
  return enginePromise;
}

function inArea(meta: Meta, [lon, lat]: LngLat) {
  const [s, w, n, e] = meta.bbox, m = 0.01;
  return lat >= s - m && lat <= n + m && lon >= w - m && lon <= e + m;
}

const staticApi = {
  meta: async (vehicle: VehicleClass) => {
    const m = await data<Meta>("meta.json");
    return { ...m, vehicle, stats: m.stats_by_vehicle?.[vehicle] ?? m.stats };
  },
  segments: async (vehicle: VehicleClass) => {
    const fc = await data<{ features: SegFeature[] }>("segments.json");
    return { features: fc.features.map((f) => ({ ...f, properties: { ...f.properties, status: f.properties.by_vehicle[vehicle] } })) };
  },
  context: () => data<Context>("context.json"),
  rules: () => data<RuleCatalog>("rules.json"),
  segment: async (id: string) => {
    const all = await data<Record<string, Segment>>("segment-details.json");
    if (!all[id]) throw new Error("segment not found");
    return all[id];
  },
  search: async (q: string) => {
    const [{ searchItems }, items] = await Promise.all([import("./static/engine"), data<any[]>("search.json")]);
    return searchItems(items, q) as SearchItem[];
  },
  features: () => data<CuratedFeature[]>("features.json"),
  recommend: async (destination: LngLat, origin: LngLat | null, _mode: "dropoff" | "pickup", maxWalk: number, vehicle: VehicleClass) => {
    const meta = await data<Meta>("meta.json");
    if (!inArea(meta, destination)) return { results: [], unverified_candidates: [], message: "outside_area", curb_at_door: null } as RecResponse;
    const o = origin && inArea(meta, origin) ? origin : null;
    const res = (await engine()).recommend(destination, o, maxWalk, vehicle);
    if (origin && !o) res.warnings = [...(res.warnings ?? []), "origin_outside_area"];
    return res;
  },
  driverNearest: async (origin: LngLat, vehicle: VehicleClass) => {
    const meta = await data<Meta>("meta.json");
    if (!inArea(meta, origin)) return { results: [], unverified_candidates: [], message: "outside_area" } as RecResponse;
    return (await engine()).nearestStops(origin, 1200, vehicle);
  },
};

// ------------------------------------------------------------------ live API
const liveApi = {
  meta: (vehicle: VehicleClass) => req<Meta>(`/api/meta?vehicle=${vehicle}`),
  segments: (vehicle: VehicleClass) => req<{ features: SegFeature[] }>(`/api/map/segments?vehicle=${vehicle}`),
  context: () => req<Context>("/api/map/context"),
  rules: () => req<RuleCatalog>("/api/rules"),
  segment: (id: string) => req<Segment>(`/api/segments/${encodeURIComponent(id)}`),
  search: (q: string) => req<SearchItem[]>(`/api/search?q=${encodeURIComponent(q)}`),
  features: () => req<CuratedFeature[]>("/api/features"),
  recommend: (destination: LngLat, origin: LngLat | null, mode: "dropoff" | "pickup", max_walk_m: number, vehicle: VehicleClass) =>
    req<RecResponse>("/api/dropoff/recommendations", {
      method: "POST", body: JSON.stringify({ destination, origin, mode, max_walk_m, vehicle }),
    }),
  driverNearest: (origin: LngLat, vehicle: VehicleClass) =>
    req<RecResponse>("/api/driver/nearest-stops", { method: "POST", body: JSON.stringify({ origin, vehicle }) }),
};

export type NewFeature = Omit<CuratedFeature, "id" | "status" | "evidence" | "impact" | "problems"> & {
  status?: "pending" | "verified";
};

export const api = {
  ...(STATIC_MODE ? staticApi : liveApi),
  evidenceUrl: (id: number, token?: string) => `${BASE}/api/evidence/${id}${token ? `?token=${encodeURIComponent(token)}` : ""}`,
  admin: {
    tasks: (token: string) => req<CuratedFeature[]>("/api/validation/tasks", { token }),
    list: (token: string) => req<CuratedFeature[]>("/api/admin/features", { token }),
    get: (token: string, id: number) => req<CuratedFeature>(`/api/admin/features/${id}`, { token }),
    add: (token: string, body: NewFeature) =>
      req<CuratedFeature>("/api/admin/features", { method: "POST", body: JSON.stringify(body), token }),
    edit: (token: string, id: number, body: Partial<NewFeature>) =>
      req<CuratedFeature>(`/api/admin/features/${id}`, { method: "PATCH", body: JSON.stringify(body), token }),
    preview: (token: string, body: Partial<NewFeature>) =>
      req<Impact>("/api/admin/preview", { method: "POST", body: JSON.stringify(body), token }),
    uploadEvidence: (token: string, id: number, file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return req<{ camera: { lon: number; lat: number; heading: number | null } | null; taken_at: string | null }>(
        `/api/admin/features/${id}/evidence`, { method: "POST", body: fd, token });
    },
    decide: (token: string, id: number, decision: "verified" | "rejected", review_note?: string, reviewer?: string) =>
      req("/api/validation/approve", { method: "POST", body: JSON.stringify({ id, decision, review_note, reviewer }), token }),
    remove: (token: string, id: number) => req(`/api/admin/features/${id}`, { method: "DELETE", token }),
    importOsm: (token: string, observer: string) =>
      req<{ found: number; created: number; skipped_duplicates: number }>("/api/admin/import/osm",
        { method: "POST", body: JSON.stringify({ observer }), token }),
    importMapillary: (token: string, observer: string) =>
      req<{ found: number; created: number; skipped_duplicates: number; map_features_in_area: number }>(
        "/api/admin/import/mapillary", { method: "POST", body: JSON.stringify({ observer }), token }),
    importGeojson: (token: string, observer: string, collection: unknown) =>
      req<{ found: number; created: number; skipped_duplicates: number; errors: string[] }>("/api/admin/import/geojson",
        { method: "POST", body: JSON.stringify({ observer, collection }), token }),
    sources: () => req<SourcesReport>("/api/sources"),
  },
};
