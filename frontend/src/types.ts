export type Status = "PROHIBITED" | "ALLOWED" | "UNVERIFIED";  // RED | GREEN | YELLOW
export type VehicleClass = "taxi" | "private";
export type LngLat = [number, number];
export type Mode = "dropoff" | "pickup" | "driver";

export type Verification = "verified_text" | "interpretation" | "heuristic";

export interface Reason {
  rule: string;
  rule_version?: number;
  effect?: "prohibit" | "caution" | "info";
  legal_ref?: string;
  article?: string;
  verification?: Verification;
  applies_to?: "dayanma" | "durma";
  exempt?: string[];
  params?: Record<string, unknown>;
  source?: string;
  source_ref?: string;
  detail?: Record<string, unknown>;
}

export interface RuleInfo {
  id: string;
  version: number;
  effect: "prohibit" | "caution" | "info";
  article: string;
  verification: Verification;
  quote: string;
  applies_to: string;
  params: Record<string, unknown>;
  exempt: string[];
  note: string;
  legal_ref: string;
  source_url: string | null;
}

export interface LawInfo { title: string; url: string; retrieved: string; version_note: string }
export interface RuleCatalog { version: string; law: LawInfo; rules: RuleInfo[] }

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
  status_by_vehicle: Record<VehicleClass, Status>;
  reasons: Reason[];
  cautions: Reason[];
  notes: Reason[];
  coverage: { feature_id: number; kind: string; source: string; note?: string; verified_at?: string }[];
  official: boolean;
  sources: string[];
  osm_ref: string;
  osm_timestamp?: string;
  last_verified?: string | null;
  confidence: string;
  geometry_quality: string;
  ruleset_version: string;
  coords: LngLat[];
}

export interface SegFeature {
  type: "Feature";
  id: string;
  geometry: { type: "LineString"; coordinates: LngLat[] };
  properties: {
    id: string; status: Status; by_vehicle: Record<VehicleClass, Status>; name: string; side: string; compass?: string;
    length_m: number; rules: string[]; cautions: string[]; official: boolean; highway: string;
  };
}

export interface Meta {
  area: string;
  bbox: [number, number, number, number];
  center: LngLat;
  osm_timestamp: string;
  built_at: string;
  build_ms: number;
  ruleset: string;
  law?: LawInfo;
  mode?: "api" | "static";
  vehicle?: VehicleClass;
  stats_by_vehicle?: Record<VehicleClass, Meta["stats"]>;
  stats: {
    by_status: Record<Status, { count: number; length_m: number }>;
    prohibited_length_by_rule: Record<string, number>;
    unverified_length_by_reason?: Record<string, number>;
    observations?: { verified: number; pending: number; verified_by_kind: Record<string, number> };
    ways: number; crossings: number; bus_stops: number; intersections: number; signals: number;
  };
}

export interface SearchItem { name: string; kind: string; lat: number; lon: number; alt: string[] }

export interface Evidence {
  status: Status;
  legally_confirmed: boolean;
  reasons: Reason[];
  cautions: Reason[];
  notes: string[];
  sources: string[];
  confidence: string;
  coverage?: { feature_id: number; kind: string; source: string; verified_at?: string }[];
  last_verified?: string | null;
}

export interface Recommendation extends Evidence {
  rank: number;
  point: LngLat;
  segment_id: string;
  street: string;
  side: "left" | "right";
  compass: string;
  official: boolean;
  walk_m?: number;
  walk_min?: number;
  walk_route?: LngLat[];
  drive_route?: LngLat[];
  drive_m?: number;
  drive_min?: number;
  length_m?: number;
  crossing?: { must_cross: boolean; safe_crossing?: boolean; crossing_distance_m?: number };
  score?: number;
}

export interface DoorInfo extends Evidence {
  segment_id: string;
  name: string;
  side: string;
  compass?: string;
  distance_m: number;
}

export interface RecResponse {
  results: Recommendation[];
  unverified_candidates?: Recommendation[];
  curb_at_door?: DoorInfo | null;
  diagnostics?: { candidates_in_radius: number; unreachable_by_car: number; ranked: number; max_walk_m: number };
  message: string | null;
  warnings?: string[];
}

export interface Context {
  crossings: { ref: string; coord: LngLat }[];
  bus_stops: { ref: string; coord: LngLat; name: string }[];
  signals: { ref: string; coord: LngLat }[];
}

export type FeatureKind =
  | "sign_3_27" | "sign_3_28" | "marking_1_4" | "marking_1_10" | "bus_lane" | "taxi_stand"
  | "observed_prohibition" | "official_zone" | "survey_area";

export type FeatureSource =
  | "field_survey" | "street_photo" | "mapillary" | "ai_vision" | "osm" | "ayna_official" | "other_official";

export interface EvidenceFile {
  id: number;
  feature_id: number;
  filename: string;
  original_name?: string;
  content_type: string;
  sha256: string;
  size: number;
  uploaded_at: string;
  camera_lon?: number | null;
  camera_lat?: number | null;
  camera_heading?: number | null;
  taken_at?: string | null;
}

export interface Impact {
  matched: { way_id: number; side: string; start_m: number; end_m: number; street: string; compass?: string; travel?: string }[];
  affected_segments: { id: string; status: Status; name: string; side: string }[];
  conflicts: { segment_id: string | null; type: string; rules?: string[] }[];
}

export interface CuratedFeature {
  id: number;
  kind: FeatureKind;
  status: "pending" | "verified" | "rejected";
  geometry: { type: "Point" | "LineString" | "Polygon"; coordinates: any };
  props: Record<string, any>;
  source: string;
  source_url?: string | null;
  source_ref?: string | null;
  observer?: string | null;
  observed_at?: string | null;
  confidence?: number | null;
  note?: string | null;
  review_note?: string | null;
  created_at?: string;
  verified_at?: string | null;
  verified_by?: string | null;
  evidence?: EvidenceFile[];
  impact?: Impact;
  problems?: string[];
  audit?: { ts: string; action: string; detail?: string | null }[];
}

export interface SourcesReport {
  osm: { snapshot: string; ways: number; crossings: number; bus_stops: number; signals: number; traffic_sign_candidates: number };
  observations: { source: string; kind: string; status: string; count: number }[];
  survey_coverage: { curb_m_verified: number; curb_m_total: number; share: number };
  official_ayna_dataset: string;
  mapillary: { configured: boolean };
}

// ------------------------------------------------------------------ B2G planning
export type CoverageState = "SERVED" | "POTENTIAL_COVERAGE_GAP" | "INVENTORY_UNKNOWN" | "NETWORK_UNRELIABLE";
export type ReviewAction = "needs_survey" | "shortlist" | "reject" | "more_data";

export interface PlanningReview { id?: number; target_id: string; action: ReviewAction; reason?: string | null; reviewer: string; reviewed_at: string }

export interface CoverageNode {
  id: string; lon: number; lat: number; kind: string; name: string; transit_hub: boolean; is_proxy: true;
  state: CoverageState; distance_m: number | null; threshold_m: number; reason: string; nearest_supply?: string | null;
}

interface PlanningItemBase {
  id: string;
  rank: number | null;
  geometry: { type: "Polygon" | "LineString"; coordinates: any };
  why: string;
  missing_evidence: string[];
  factors: Record<string, number | null>;
  factors_missing: string[];
  officially_approved: false;
  review?: PlanningReview | null;
  review_history?: PlanningReview[];
}

export interface SurveyTask extends PlanningItemBase {
  type: "survey_task";
  cell: [number, number];
  centroid: LngLat;
  priority_score: number | null;
  access_nodes: number;
  access_nodes_are_proxy: true;
  access_kinds: Record<string, number>;
  transit_hubs: string[];
  coverage_states: Partial<Record<CoverageState, number>>;
  measured_activity: "not_measured" | { rows: number; per_hour: number };
  curb_m: { total: number; unverified: number; prohibited: number; allowed: number };
  curb_segments_to_survey: { segment_id: string; street: string; compass: string; length_m: number; cautions: string[] }[];
  no_defensible_candidate?: boolean;
}

export interface Candidate extends PlanningItemBase {
  type: "candidate";
  segment_id: string;
  candidate_class: "SCREENED_FOR_FURTHER_STUDY" | "DATA_COLLECTION_NEEDED";
  point: LngLat;
  street: string;
  road_side: string;
  compass: string;
  length_m: number;
  current_legal_status: Status;
  coverage_finding: CoverageState;
  measured_taxi_demand_available: boolean;
  walk_distance_to_gap_m: number;
  current_avg_walk_to_verified_m: number;
  score: number | null;
  cluster: string;
  requires: string[];
  exclusions_in_cluster: Record<string, number> | null;
}

export type PlanningItem = SurveyTask | Candidate;

export interface SupplyPoint { segment_id: string; type: "official_designated" | "field_verified_suitable"; point: LngLat; street: string; side: string; verified_at?: string | null }

export interface PlanningResult {
  algorithm_version: string;
  generated_at: string;
  parameters: { threshold_m: number; cell_m: number; survey_weights: Record<string, number>; candidate_weights: Record<string, number> };
  area: { id: string; name?: string; inventory_status: "unknown" | "complete"; inventory_source_url?: string | null;
    inventory_declared_by?: string | null; inventory_declared_at?: string | null; polygon?: any };
  source_versions: { osm_snapshot: string; model_built_at: string; ruleset: string; verified_observations: number; measured_activity_rows: number };
  inventory_complete: boolean;
  demand_measured: boolean;
  summary: {
    verified_supply_locations: number;
    verified_supply_by_type: { official_designated: number; field_verified_suitable: number };
    access_nodes: number;
    coverage_states: Record<CoverageState, number>;
    survey_tasks: number;
    candidates: { SCREENED_FOR_FURTHER_STUDY: number; DATA_COLLECTION_NEEDED: number };
    measured_activity_rows: number;
    served_share: number | null;
  };
  supply: SupplyPoint[];
  observed_suitable: SupplyPoint[];
  coverage: CoverageNode[];
  survey_tasks: SurveyTask[];
  candidates: Candidate[];
  limitations: string[];
  read_only?: boolean;
  run_id?: number;
}

export interface ActivityRow {
  id: number;
  place_name: string;
  geometry: { type: "Point"; coordinates: LngLat };
  period_start: string;
  period_end: string;
  pickups: number | string;
  dropoffs: number | string;
  per_hour: number | null;
  vehicle_scope: string;
  method: "field_count" | "operator_aggregate" | "official_statistic";
  source: string;
  source_url?: string | null;
  verified_at?: string | null;
  status?: string;
  observer?: string;
}
