/**
 * Strix Forensic Types strictly matching the real FastAPI backend contract:
 * - backend/API.md
 * - backend/app/schemas.py
 * - pipeline/contract.py
 *
 * Keeps legacy/mock fields optional so demo mode and mock packs compile smoothly.
 */

export interface User {
  id: number;
  username: string;
  role: 'admin' | 'investigator';
  full_name: string;
  active: boolean;
  created_at: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface Metrics {
  sharpness: number;
  face_size: number;
  pose_yaw: number;
  illumination: number;
  occlusion: number;
}

export interface Enhancement {
  enhanced_path?: string;
  method: string;
  scale: number;
  model_version: string;
  crop_box: [number, number, number, number];
  search_embedding_source: string;
  enhanced_url?: string;
  original_url?: string;
  signed_enhanced_url?: string;
  run_id?: number | string;
  frame_id?: number | string;
  face_box?: [number, number, number, number] | null;
  cached?: boolean;
  warning?: string;
  score_diff?: number;
  secondary_warning?: string;
}

export interface Frame {
  frame_id: number | string;
  frame_path?: string;
  timestamp_sec: number;
  quality_score: number;
  reliability: 'High' | 'Medium' | 'Low';
  flags: string[];
  flag_scores?: Record<string, number> | null;
  enhanced: boolean;
  enhancement: Enhancement | null;
  metrics: Metrics;
  embedding_path?: string;
  selected?: boolean;
  crop_url?: string;
  frame_url?: string;
  image_url?: string;
  enhanced_url?: string | null;
  signed_crop_url?: string;
  signed_frame_url?: string;
  match_ready?: boolean | null;
  rank_reason?: string | null;
  crop_path?: string | null;
  face_box?: [number, number, number, number] | null;
}

export interface RunResult {
  run_id: number | string;
  clip_id: string;
  transaction_time: string;
  person_track_id: number | null;
  best_frames: Frame[];
  link_confidence?: 'High' | 'Medium' | 'Low' | null;
  link_reason?: string | null;
  link_low_margin?: boolean;
  selection_reason?: string | null;
  show_selection_reason?: boolean;
  video_url?: string;
  pipeline_mode?: string;
  banner?: string | null;
  notice?: string | null;
  timings_ms?: Record<string, number> | null;
  served_from_demo_pack?: boolean;
  selected_frame_ids?: (string | number)[];
  warnings?: string[];
  requested_sample_fps?: number | null;
  effective_sample_fps?: number | null;
  coverage_start_sec?: number | null;
  coverage_end_sec?: number | null;
}

// Alias for backwards compatibility with pipeline results
export type PipelineResult = RunResult;

export interface ClipOut {
  id: string;
  original_filename: string;
  stored_path: string;
  sha256: string;
  size_bytes: number;
  duration_sec: number;
  fps: number | null;
  width: number;
  height: number;
  codec: string | null;
  container: string | null;
  rotation: number;
  clip_start_time: string | null;
  clip_start_source: 'ffprobe_converted' | 'user' | 'unknown';
  atm_id: string | null;
  zone_polygon_norm: [number, number][] | null;
  notes: string | null;
  uploaded_by: number;
  created_at: string;
  video_url: string;
}

export interface ClipPatchRequest {
  clip_start_time?: string | null;
  atm_id?: string | null;
  zone_polygon_norm?: [number, number][] | null;
  notes?: string | null;
}

export interface ATMZone {
  id: string;
  polygon: [number, number][];
  note?: string;
}

export interface ProcessClipRequest {
  transaction_time: string;
  window_sec: number;
  sample_fps: number;
  tracker?: string;
  atm_id?: string;
}

export interface ProcessClipResponse {
  run_id: number | string;
  status: 'queued' | 'running' | 'done' | 'failed';
}

export interface RunStatus {
  run_id: number | string;
  clip_id: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  stage?: string;
  progress?: number | null; // 0.0 to 1.0 (or null)
  progress_message?: string;
  error_code?: string | null;
  error_message?: string | null;
  error_advice?: string | null;
  transaction_time?: string;
  tx_offset_sec?: number | null;
  window_sec?: number;
  sample_fps?: number;
  tracker?: string;
  atm_id?: string | null;
  pipeline_mode?: string;
  served_from_demo_pack?: boolean;
  link_low_margin?: boolean;
  requested_sample_fps?: number | null;
  effective_sample_fps?: number | null;
  warnings?: string[];
  coverage_start_sec?: number | null;
  coverage_end_sec?: number | null;
  created_by?: number;
  created_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
  selected_frame_ids?: (string | number)[];
  result?: RunResult | null;
}

export interface SelectionRequest {
  frame_ids: (string | number)[];
}

export interface SelectionResponse {
  run_id: number | string;
  selected_frame_ids: (string | number)[];
}

export interface EnhanceFrameRequest {
  crop_box: [number, number, number, number]; // [naturalX, naturalY, naturalW, naturalH] in full-frame pixels
  scale: 2 | 4;
  method?: 'lanczos' | string;
}

export interface SearchRequest {
  run_id: number | string;
  frame_id: string | number;
  top_k?: number;
  best_per_clip?: boolean;
  include_short_tracks?: boolean;
}

export interface SearchMatch {
  source?: 'run' | 'index' | 'original' | 'enhanced';
  track_id?: number | null;
  short_track?: boolean;
  clip_id: string;
  filename: string;
  run_id?: number | string | null;
  index_id?: number | string | null;
  frame_id: string | number;
  t?: number | null;
  timestamp_sec: number;
  score: number;
  reliability: 'High' | 'Medium' | 'Low';
  flags: string[];
  flag_scores?: Record<string, number> | null;
  crop_url?: string | null;
  frame_url?: string | null;
  thumbnail_url?: string;
  signed_crop_url?: string;
  signed_frame_url?: string;
}

export interface SearchResult {
  search_id: number | string;
  run_id: number | string;
  frame_id: string | number;
  top_k?: number;
  matches: SearchMatch[];
  notice: string;
  score_note: string;
  scope?: string;
  created_at?: string;
}

export interface IndexClipRequest {
  start_sec?: number;
  end_sec?: number | null;
  sample_fps?: number;
  tracker?: string;
  faces_per_track?: number;
  atm_id?: string;
}

export interface IndexClipResponse {
  index_id: number | string;
  status: 'queued' | 'running' | 'done' | 'failed';
}

export interface IndexFace {
  id: number | string;
  track_id: number;
  t: number;
  quality_score: number;
  reliability: 'High' | 'Medium' | 'Low';
  match_ready?: boolean | null;
  flags: string[];
  flag_scores?: Record<string, number> | null;
  face_box?: [number, number, number, number] | null;
  short_track?: boolean;
  crop_url?: string | null;
  frame_url?: string | null;
}

export interface IndexTrack {
  track_id: number;
  first_t: number;
  last_t: number;
  n_observations: number;
  short_track: boolean;
  confidence_note?: string | null;
  dwell_sec_in_zone: number;
  reason?: string | null;
  face_count: number;
  faces: IndexFace[];
}

export interface IndexStatus {
  index_id: number | string;
  clip_id: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  stage?: string;
  progress?: number | null;
  progress_message?: string;
  error_code?: string | null;
  error_message?: string | null;
  error_advice?: string | null;
  start_sec?: number;
  end_sec?: number | null;
  sample_fps?: number;
  tracker?: string;
  faces_per_track?: number;
  atm_id?: string | null;
  total_embeddings?: number;
  tracks?: IndexTrack[];
  timings_ms?: Record<string, number> | null;
  pipeline_mode?: string;
  served_from_demo_pack?: boolean;
  warnings?: string[];
  requested_sample_fps?: number | null;
  effective_sample_fps?: number | null;
  coverage_start_sec?: number | null;
  coverage_end_sec?: number | null;
  created_by?: number;
  created_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface AuditEntry {
  id: number;
  ts_utc: string;
  user_id: number | null;
  username: string | null;
  role: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  details: Record<string, any>;
  ip: string | null;
  prev_hash: string;
  entry_hash: string;
}

export interface AuditListResponse {
  items: AuditEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditVerifyResponse {
  ok: boolean;
  checked_count: number;
  first_bad_id: number | null;
  reason: string | null;
}

export interface PublicConfig {
  pipeline_mode: 'fake' | 'real';
  pipeline_ready?: boolean;
  warmup_state?: string;
  warmup?: Record<string, any>;
  demo_pack_enabled?: boolean;
  banner: string | null;
  notice: string;
  limits: {
    max_upload_mb: number;
    window_sec_min: number;
    window_sec_max: number;
    sample_fps_min: number;
    sample_fps_max: number;
    max_sampled_frames: number;
    embed_dim: number;
    signed_url_ttl_sec: number;
  };
  accepted_extensions: string[];
  model_labels: string[];
  display_tz: string;
}
