import { STATIC_MODE } from './api';
import type { LngLat } from './types';
export type ReviewStatus = 'needs_survey' | 'shortlist' | 'reject' | 'more_data_needed';
export interface Candidate {
  candidate_id: string; name: string; road_side: string; length_m: number;
  geometry: { type: 'LineString'; coordinates: LngLat[] };
  officially_approved: boolean; current_legal_status: string; measured_taxi_demand_available: boolean;
  candidate_class: string; review_status: ReviewStatus; coverage_finding: string;
  display_order: number; score: number | null; rank: number | null; evidence_strength: string;
  reasons: string[]; missing_evidence: string[]; constraints: string[]; source_url: string;
  source_snapshot: Record<string, string | null>; last_verified: string | null;
  run_id: string; algorithm_version: string; limitations: string[]; methodology: string;
  is_synthetic_example: boolean; walk_distance_to_verified_zone_m: number | null;
  review_history: { action: ReviewStatus; reviewed_at: string; reason?: string }[];
}
export interface Activity {
  id: number; location_id: string; name: string; pickups: number; dropoffs: number;
  period_start: string; period_end: string; source_ref: string; source_url: string;
  license: string; collection_method: string; passengers_per_hour: number;
  longitude: number; latitude: number;
}
/** One analysed access point. Always a geographic proxy (OSM place), never measured demand. */
export interface CoverageNode {
  id: string; name: string; geometry: { type: 'Point'; coordinates: LngLat }; is_proxy: true;
  source_url: string; state: 'SERVED' | 'POTENTIAL_COVERAGE_GAP' | 'INVENTORY_UNKNOWN' | 'NETWORK_UNRELIABLE';
  distance_m: number | null; reason: string;
}
export interface PlanningSnapshot {
  area: { id: string; name: string; geometry: { type: 'Polygon'; coordinates: LngLat[][] } };
  run_id: string; generated_at: string; algorithm_version: string;
  source_versions: Record<string, string | null>; inventory_state: string;
  parameters: { threshold_m: number }; limitations: string[]; methodology: string;
  summary: { verified_official_locations: number; observed_usable_curb_segments: number;
    survey_tasks: number; analyzed_nodes: number; excluded_segments: number; coverage_share: number | null };
  candidates: Candidate[]; passenger_activity: Activity[]; coverage: CoverageNode[];
  verified_locations: { id: number; geometry: any; source_url: string | null; verified_at: string | null }[];
  exclusions: { segment_id: string; reason: string }[];
  empty_reason: string | null;
}
const env = (import.meta as any).env;
async function request<T>(path: string, token?: string, body?: unknown): Promise<T> {
  const response = await fetch(`${env.VITE_API_BASE ?? ''}/api/authority/${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { 'X-Admin-Token': token } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail ?? response.status));
  }
  return response.json();
}
export const planningApi = {
  snapshot: async (threshold = 450): Promise<PlanningSnapshot> => {
    if (!STATIC_MODE) return request(`overview?threshold_m=${threshold}`);
    const response = await fetch(`${env.BASE_URL}static-data/planning.json`);
    if (!response.ok) throw new Error(`Planning snapshot unavailable (${response.status})`);
    return response.json();
  },
  review: (candidate: Candidate, action: ReviewStatus, reason: string, token: string, threshold: number) =>
    request(`candidates/${encodeURIComponent(candidate.candidate_id)}/review?threshold_m=${threshold}`, token,
      { action, reason, run_id: candidate.run_id }),
  importActivity: (body: unknown, token: string) => request('passenger-activity', token, body),
};
export const exportColumns = ['candidate_id', 'name', 'road_side', 'candidate_class', 'review_status', 'coverage_finding',
  'score', 'rank', 'officially_approved', 'current_legal_status', 'length_m', 'evidence_strength', 'last_verified',
  'walk_distance_to_verified_zone_m', 'measured_taxi_demand_available', 'geometry', 'source_snapshot', 'source_url', 'missing_evidence', 'constraints', 'limitations',
  'methodology', 'is_synthetic_example', 'run_id'] as const;
export function csvCell(value: unknown): string {
  let text = value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
  if (/^[\s]*[=+@-]/.test(text)) text = "'" + text;
  return '"' + text.replace(/"/g, '""') + '"';
}
export function download(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function exportPlanning(rows: Candidate[], snapshot: PlanningSnapshot, format: 'csv' | 'geojson') {
  const content = format === 'csv' ? [exportColumns.join(','), ...rows.map(c => exportColumns.map(k => csvCell(c[k])).join(','))].join('\r\n')
    : JSON.stringify({ type: 'FeatureCollection', run_id: snapshot.run_id, limitations: snapshot.limitations,
      methodology: snapshot.methodology, features: rows.map(({ geometry, ...properties }) => ({ type: 'Feature', geometry, properties })) }, null, 2);
  download(`burdasaxla-planning.${format}`, content, format === 'csv' ? 'text/csv;charset=utf-8' : 'application/geo+json');
}
