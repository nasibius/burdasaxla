import type { Context, CuratedFeature, LngLat, Meta, RecResponse, SearchItem, Segment, SegFeature } from "./types";

const env = (import.meta as any).env ?? {};
const BASE = env.VITE_API_BASE ?? "";
/** Static mode: no backend; data comes from precomputed JSON (GitHub Pages build). */
export const STATIC_MODE = env.VITE_STATIC === "1";
const DATA = `${env.BASE_URL ?? "/"}static-data/`;

async function req<T>(path: string, init?: RequestInit & { token?: string }): Promise<T> {
  const headers: Record<string, string> = { "content-type": "application/json" };
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
    if (Array.isArray(msg)) msg = msg.map((d: any) => d.msg).join("; ");
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
  meta: () => data<Meta>("meta.json"),
  segments: () => data<{ features: SegFeature[] }>("segments.json"),
  context: () => data<Context>("context.json"),
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
  recommend: async (destination: LngLat, origin: LngLat | null, _mode: "dropoff" | "pickup", maxWalk: number) => {
    const meta = await data<Meta>("meta.json");
    if (!inArea(meta, destination)) return { results: [], message: "outside_area", curb_at_door: null } as RecResponse;
    const o = origin && inArea(meta, origin) ? origin : null;
    const res = (await engine()).recommend(destination, o, maxWalk);
    if (origin && !o) res.warnings = [...(res.warnings ?? []), "origin_outside_area"];
    return res;
  },
  driverNearest: async (origin: LngLat) => {
    const meta = await data<Meta>("meta.json");
    if (!inArea(meta, origin)) return { results: [], message: "outside_area" } as RecResponse;
    return (await engine()).nearestStops(origin);
  },
};

// ------------------------------------------------------------------ live API
const liveApi = {
  meta: () => req<Meta>("/api/meta"),
  segments: () => req<{ features: SegFeature[] }>("/api/map/segments"),
  context: () => req<Context>("/api/map/context"),
  segment: (id: string) => req<Segment>(`/api/segments/${encodeURIComponent(id)}`),
  search: (q: string) => req<SearchItem[]>(`/api/search?q=${encodeURIComponent(q)}`),
  features: () => req<CuratedFeature[]>("/api/features"),
  recommend: (destination: LngLat, origin: LngLat | null, mode: "dropoff" | "pickup", max_walk_m: number) =>
    req<RecResponse>("/api/dropoff/recommendations", {
      method: "POST", body: JSON.stringify({ destination, origin, mode, max_walk_m }),
    }),
  driverNearest: (origin: LngLat, radius_m = 1200) =>
    req<RecResponse>("/api/driver/nearest-stops", { method: "POST", body: JSON.stringify({ origin, radius_m }) }),
};

export const api = {
  ...(STATIC_MODE ? staticApi : liveApi),
  admin: {
    tasks: (token: string) => req<CuratedFeature[]>("/api/validation/tasks", { token }),
    list: (token: string) => req<CuratedFeature[]>("/api/admin/features", { token }),
    add: (token: string, body: Partial<CuratedFeature>) =>
      req<CuratedFeature>("/api/admin/features", { method: "POST", body: JSON.stringify(body), token }),
    preview: (token: string, body: Partial<CuratedFeature>) =>
      req<CuratedFeature["impact"]>("/api/admin/preview", { method: "POST", body: JSON.stringify(body), token }),
    decide: (token: string, id: number, decision: "verified" | "rejected") =>
      req("/api/validation/approve", { method: "POST", body: JSON.stringify({ id, decision }), token }),
    remove: (token: string, id: number) => req(`/api/admin/features/${id}`, { method: "DELETE", token }),
  },
};
