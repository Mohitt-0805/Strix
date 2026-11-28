/**
 * Strix Forensic Types strictly matching the real FastAPI backend contract:
 * - frontend/BACKEND_API.md
 * - backend/app/schemas.py
 * - pipeline/contract.py
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
  enhanced_path: string;
  method: string;
  scale: number;
  model_version: string;
  crop_box: [number, number, number, number];
  search_embedding_source: string;
  enhanced_url?: string;
  signed_enhanced_url?: string;
}

export interface Frame {
  frame_id: number | string;
  frame_path: string;
  timestamp_sec: number;
  quality_score: number;
  reliability: 'High' | 'Medium' | 'Low';
  flags: string[];
  flag_scores?: Record<string, number> | null;
  enhanced: boolean;
  enhancement: Enhancement | null;
  metrics: Metrics;
  embedding_path?: string;
  signed_crop_url?: string;
  signed_frame_url?: string;
  crop_url?: string;
  frame_url?: string;
  image_url?: string;
  match_ready?: boolean | null;
  rank_reason?: string | null;
  crop_path?: string | null;
  face_box?: [number, number, number, number] | null;
}

export interface RunResult {
  run_id: string;
  clip_id: string;
  transaction_time: string;
  person_track_id: number | null;
  best_frames: Frame[];
  link_confidence?: 'High' | 'Medium' | 'Low' | null;
  link_reason?: string | null;
  link_low_margin?: boolean;
  selection_reason?: string | null;
  timings_ms?: Record<string, number> | null;
  served_from_demo_pack?: boolean;
  selected_frame_ids?: (string | number)[];
  warnings?: string[];
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
  run_id: string;
  status: 'queued' | 'running' | 'done' | 'failed';
}

export interface RunStatus {
  run_id: string;
  clip_id: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  stage?: string;
  progress?: number; // 0 to 100
  progress_message?: string;
  error_code?: string;
  error_message?: string;
  error_advice?: string;
  transaction_time?: string;
  window_sec?: number;
  sample_fps?: number;
  created_at?: string;
  finished_at?: string;
  selected_frame_ids?: (string | number)[];
}

export interface SelectionRequest {
  frame_ids: (string | number)[];
}

export interface EnhanceFrameRequest {
  crop_box: [number, number, number, number]; // [naturalX, naturalY, naturalW, naturalH]
  scale: 2 | 4;
  method?: 'lanczos' | 'espcn' | string;
}

export interface SearchRequest {
  run_id: string;
  frame_id: string | number;
  top_k?: number;
  best_per_clip?: boolean;
}

export interface SearchMatch {
  clip_id: string;
  filename: string;
  run_id: string;
  frame_id: string | number;
  timestamp_sec: number;
  score: number;
  reliability: 'High' | 'Medium' | 'Low';
  flags: string[];
  source: 'original' | 'enhanced';
  track_id: number;
  short_track?: boolean;
  crop_url?: string;
  frame_url?: string;
  thumbnail_url?: string;
  signed_crop_url?: string;
  signed_frame_url?: string;
}

export interface SearchResult {
  search_id: string;
  run_id: string;
  frame_id: string | number;
  matches: SearchMatch[];
  notice: string;
  score_note: string;
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
