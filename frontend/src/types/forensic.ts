/**
 * Core forensic types strictly aligned with:
 * - docs/api-contract.md
 * - docs/sample_result.json
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
}

export interface Frame {
  frame_id: number | string;
  frame_path: string;
  timestamp_sec: number;
  quality_score: number;
  reliability: 'High' | 'Medium' | 'Low';
  flags: string[];
  enhanced: boolean;
  enhancement: Enhancement | null;
  metrics: Metrics;
  embedding_path: string;
  match_ready?: boolean | null;
  rank_reason?: string | null;
  crop_path?: string | null;
  image_url?: string;
  crop_url?: string;
}

export interface PipelineResult {
  clip_id: string;
  transaction_time: string;
  person_track_id: number | null;
  best_frames: Frame[];
  link_confidence?: string | null;
  link_reason?: string | null;
  selection_reason?: string | null;
  timings_ms?: Record<string, number> | null;
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

export interface PublicConfig {
  pipeline_mode: 'fake' | 'real';
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

export type CaseStatus = 'In Progress' | 'Pending Review' | 'Verified' | 'Flagged' | 'Archived' | 'Closed' | 'Under Review';

export interface CaseRecord {
  caseId: string;
  txnId: string;
  title: string;
  atmId: string;
  camera: string;
  location: string;
  dateCreated: string;
  timestamp: string;
  clipsCount: number;
  reviewer: string;
  status: CaseStatus;
  lastUpdated: string;
  amount: string;
  cardLast4: string;
  matchConfidence: number;
  quality: number;
  conditions: string[];
  sha256: string;
  bestFrames: Frame[];
  notes?: string;
  videoUrl?: string;
  clipId?: string;
}

export interface FrameExtractRequest {
  start_sec: number;
  end_sec: number;
  fps: number;
}

export interface FrameEnhanceRequest {
  crop_box: [number, number, number, number];
  scale: 2 | 4;
  method: 'Baseline' | 'Fast' | 'Detailed';
}

export interface FaceSearchMatch {
  match_id: string;
  clip_id: string;
  timestamp_sec: number;
  original_similarity: number;
  enhanced_similarity?: number;
  thumbnail_url: string;
  location?: string;
  atm_id?: string;
  flag_warning?: string;
}
