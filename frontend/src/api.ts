import type { Context, CuratedFeature, LngLat, Meta, RecResponse, SearchItem, Segment, SegFeature } from "./types";

const BASE = (import.meta as any).env?.VITE_API_BASE ?? "";

async function req<T>(path: string, init?: RequestInit & { token?: string }): Promise<T> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (init?.token) headers["x-admin-token"] = init.token;
  const r = await fetch(BASE + path, { ...init, headers: { ...headers, ...(init?.headers as any) } });
  if (!r.ok) {
    let msg = `${r.status}`;
    try { msg = (await r.json()).detail ?? msg; } catch { /* ignore */ }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export const api = {
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
