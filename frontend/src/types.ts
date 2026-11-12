export type Status = "PROHIBITED" | "VERIFIED" | "UNKNOWN";
export type LngLat = [number, number];
export type Mode = "dropoff" | "pickup" | "driver";

export interface Reason {
  rule: string;
  rule_version: number;
  effect: "prohibit" | "info";
  legal_ref: string;
  params: Record<string, unknown>;
  approximation: boolean;
  source: string;
  source_ref: string;
  detail: Record<string, unknown>;
}

export interface Segment {
  id: string;
  way_id: number;
  side: "left" | "right";
  travel: "fwd" | "bwd";
  compass: string;
  name: string;
  highway: string;
  oneway: boolean;
  start_m: number;
  end_m: number;
  length_m: number;
  status: Status;
  reasons: Reason[];
  notes: Reason[];
  coverage: { feature_id: number; kind: string; source: string; note?: string; verified_at?: string }[];
  official: boolean;
  sources: string[];
  osm_ref: string;
  osm_timestamp?: string;
  last_verified?: string | null;
  confidence: "verified" | "estimated" | "rule_derived" | "insufficient_data";
  geometry_quality: string;
  ruleset_version: string;
  coords: LngLat[];
}

export interface SegFeature {
  type: "Feature";
  id: string;
  geometry: { type: "LineString"; coordinates: LngLat[] };
  properties: { id: string; status: Status; name: string; side: string; length_m: number; rules: string[]; official: boolean; highway: string };
}

export interface Meta {
  area: string;
  bbox: [number, number, number, number];
  center: LngLat;
  osm_timestamp: string;
  built_at: string;
  build_ms: number;
  ruleset: string;
  stats: {
    by_status: Record<Status, { count: number; length_m: number }>;
    prohibited_length_by_rule: Record<string, number>;
    ways: number; crossings: number; bus_stops: number; intersections: number; signals: number;
  };
}

export interface SearchItem { name: string; kind: string; lat: number; lon: number; alt: string[] }

export interface Recommendation {
  rank: number;
  point: LngLat;
  segment_id: string;
  street: string;
  side: "left" | "right";
  compass: string;
  status: Status;
  official: boolean;
  confidence: string;
  walk_m?: number;
  walk_min?: number;
  walk_route?: LngLat[];
  drive_route?: LngLat[];
  drive_m?: number;
  drive_min?: number;
  length_m?: number;
  crossing?: { must_cross: boolean; safe_crossing?: boolean; crossing_distance_m?: number };
  notes: string[];
  score?: number;
}

export interface DoorInfo {
  segment_id: string;
  status: Status;
  name: string;
  side: string;
  distance_m: number;
  reasons: { rule: string; legal_ref: string; source_ref: string; detail: Record<string, unknown> }[];
}

export interface RecResponse {
  results: Recommendation[];
  curb_at_door?: DoorInfo | null;
  diagnostics?: { candidates_in_radius: number; unreachable_by_car: number; ranked: number; max_walk_m: number };
  message: string | null;
}

export interface Context {
  crossings: { ref: string; coord: LngLat }[];
  bus_stops: { ref: string; coord: LngLat; name: string }[];
  signals: { ref: string; coord: LngLat }[];
}

export type FeatureKind = "sign_3_27" | "sign_3_28" | "marking_1_4" | "marking_1_10" | "bus_lane" | "official_zone" | "survey_area";

export interface CuratedFeature {
  id: number;
  kind: FeatureKind;
  status: "pending" | "verified" | "rejected";
  geometry: { type: "Point" | "LineString" | "Polygon"; coordinates: any };
  props: Record<string, any>;
  source: string;
  source_url?: string | null;
  note?: string | null;
  created_at: string;
  verified_at?: string | null;
  verified_by?: string | null;
  impact?: {
    matched: { way_id: number; side: string; start_m: number; end_m: number; street: string }[];
    affected_segments: { id: string; status: Status; name: string; side: string }[];
    conflicts: { segment_id: string; type: string; rules?: string[] }[];
  };
}
