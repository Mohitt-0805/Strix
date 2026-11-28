import axios, { AxiosError } from 'axios';
import {
  User,
  LoginResponse,
  PublicConfig,
  AuditListResponse,
  AuditVerifyResponse,
  ClipOut,
  ClipPatchRequest,
  ATMZone,
  ProcessClipRequest,
  ProcessClipResponse,
  RunStatus,
  RunResult,
  EnhanceFrameRequest,
  Enhancement,
  SearchRequest,
  SearchResult,
  SelectionRequest,
} from '@/types/forensic';
import { DEMO_CLIPS, DEMO_RUNS, DEMO_RUN_RESULTS, DEMO_ZONES, DEMO_AUDIT_LOGS } from './mockData';

export const DEMO_MODE: boolean =
  (import.meta as any).env?.VITE_DEMO_MODE === '1' ||
  (import.meta as any).env?.VITE_DEMO_MODE === 'true';

// Backward compatibility alias
export const MOCK_MODE = DEMO_MODE;
export const isMockMode = DEMO_MODE;

export const API_BASE_URL: string =
  (import.meta as any).env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

/**
 * Prefix relative media URLs from the backend with the API base URL.
 * Signed media URLs are relative (e.g. "/files?p=...&sig=...") and can be used directly in <img>/<video>.
 */
export function getMediaUrl(url: string | null | undefined): string {
  if (!url) return '';
  if (url.startsWith('http://') || url.startsWith('https://')) {
    return url;
  }
  const cleanPath = url.startsWith('/') ? url : `/${url}`;
  return `${API_BASE_URL}${cleanPath}`;
}

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Attach Bearer token to all outgoing requests
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('strix_token');
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor to catch 401 Unauthenticated
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('strix_token');
      localStorage.removeItem('strix_user');
      sessionStorage.removeItem('strix_token');
      sessionStorage.removeItem('strix_user');
      window.dispatchEvent(new CustomEvent('strix:auth_expired'));
    }
    return Promise.reject(error);
  }
);

/* =========================================================================
   Real Backend API Client (Strictly Matching BACKEND_API.md)
   ========================================================================= */

export const api = {
  getMediaUrl,
  // 1. Public Configuration, Health & ATM Zones
  async getHealth() {
    try {
      const res = await apiClient.get('/health');
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        return { status: 'ok', db: 'ok', pipeline_mode: 'fake', ffmpeg: true, ffprobe: true };
      }
      throw new Error(`Backend not reachable at ${API_BASE_URL}`);
    }
  },

  async getPublicConfig(): Promise<PublicConfig> {
    try {
      const res = await apiClient.get<PublicConfig>('/config/public');
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        return {
          pipeline_mode: 'fake',
          banner: 'FAKE PIPELINE, DEMO DATA',
          notice: 'Possible matches only. A human investigator must verify every result.',
          limits: {
            max_upload_mb: 500,
            window_sec_min: 1,
            window_sec_max: 100,
            sample_fps_min: 0.5,
            sample_fps_max: 5.0,
            max_sampled_frames: 200,
            embed_dim: 512,
            signed_url_ttl_sec: 900,
          },
          accepted_extensions: ['mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'mpeg', 'mpg'],
          model_labels: ['MobileNetV3 Faster R-CNN', 'ByteTrack', 'InsightFace ArcFace'],
          display_tz: 'Asia/Kolkata',
        };
      }
      throw new Error(`Backend not reachable at ${API_BASE_URL}`);
    }
  },

  async getZones(): Promise<ATMZone[]> {
    try {
      const res = await apiClient.get('/zones');
      if (Array.isArray(res.data)) return res.data;
      if (res.data && typeof res.data === 'object') {
        return Object.entries(res.data).map(([id, val]: [string, any]) => ({
          id,
          polygon: val.polygon || [],
          note: val.note || '',
        }));
      }
      return [];
    } catch (err: any) {
      if (DEMO_MODE) {
        return DEMO_ZONES;
      }
      throw err;
    }
  },

  // 2. Authentication
  async login(username: string, password: string): Promise<LoginResponse> {
    let res: Response;
    try {
      res = await fetch(`${API_BASE_URL}/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username, password }),
      });
    } catch (networkError) {
      // Only allow a demo user fallback if DEMO_MODE === true and fetch() throws a network error
      if (DEMO_MODE) {
        const mockUser: User = {
          id: 2,
          username: username.split('@')[0] || 'r.sharma',
          role: 'investigator',
          full_name: 'Insp. R. Sharma',
          active: true,
          created_at: new Date().toISOString(),
        };
        const mockToken = `demo_mock_jwt_${Math.random().toString(36).substring(2)}`;
        localStorage.setItem('strix_token', mockToken);
        localStorage.setItem('strix_user', JSON.stringify(mockUser));
        return {
          access_token: mockToken,
          token_type: 'bearer',
          user: mockUser,
        };
      }

      // If DEMO_MODE === false and backend is unreachable, throw "Backend not reachable"
      localStorage.removeItem('strix_token');
      localStorage.removeItem('strix_user');
      sessionStorage.removeItem('strix_token');
      sessionStorage.removeItem('strix_user');
      throw new Error('Backend not reachable');
    }

    // Never return a fake user when the server responds with an HTTP error
    if (!res.ok) {
      localStorage.removeItem('strix_token');
      localStorage.removeItem('strix_user');
      sessionStorage.removeItem('strix_token');
      sessionStorage.removeItem('strix_user');

      let errorMessage = `HTTP error ${res.status}`;
      try {
        const errorData = await res.json();
        if (errorData) {
          if (typeof errorData.detail === 'string') {
            errorMessage = errorData.detail;
          } else if (Array.isArray(errorData.detail)) {
            errorMessage = errorData.detail.map((item: any) => item.msg || JSON.stringify(item)).join('; ');
          } else if (errorData.code) {
            errorMessage = errorData.code;
          } else if (errorData.message) {
            errorMessage = errorData.message;
          } else if (typeof errorData.detail === 'object') {
            errorMessage = JSON.stringify(errorData.detail);
          }
        }
      } catch {
        try {
          const text = await res.text();
          if (text) errorMessage = text;
        } catch { }
      }

      const error: any = new Error(errorMessage);
      error.status = res.status;
      throw error;
    }

    const data = await res.json();
    if (!data || !data.access_token || !data.user) {
      localStorage.removeItem('strix_token');
      localStorage.removeItem('strix_user');
      sessionStorage.removeItem('strix_token');
      sessionStorage.removeItem('strix_user');
      throw new Error('Invalid response structure from authentication server');
    }

    // Role comes strictly from the server response (user.role)
    const authenticatedUser: User = {
      id: data.user.id,
      username: data.user.username,
      role: data.user.role,
      full_name: data.user.full_name || data.user.username,
      active: data.user.active ?? true,
      created_at: data.user.created_at || new Date().toISOString(),
    };

    localStorage.setItem('strix_token', data.access_token);
    localStorage.setItem('strix_user', JSON.stringify(authenticatedUser));

    return {
      access_token: data.access_token,
      token_type: data.token_type || 'bearer',
      user: authenticatedUser,
    };
  },

  async getMe(): Promise<User> {
    try {
      const res = await apiClient.get<User>('/auth/me');
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        const stored = localStorage.getItem('strix_user');
        if (stored) return JSON.parse(stored);
      }
      throw err;
    }
  },

  logout() {
    localStorage.removeItem('strix_token');
    localStorage.removeItem('strix_user');
    sessionStorage.removeItem('strix_token');
    sessionStorage.removeItem('strix_user');
  },

  // 3. Clip Management
  async listClips(): Promise<ClipOut[]> {
    try {
      const res = await apiClient.get<ClipOut[]>('/clips');
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        return DEMO_CLIPS;
      }
      throw err;
    }
  },

  async getClip(clipId: string): Promise<ClipOut> {
    try {
      const res = await apiClient.get<ClipOut>(`/clips/${clipId}`);
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        const found = DEMO_CLIPS.find((c) => c.id === clipId);
        if (found) return found;
      }
      throw err;
    }
  },

  async uploadClip(
    formData: FormData,
    onUploadProgress?: (progressEvent: any) => void
  ): Promise<ClipOut> {
    try {
      const res = await apiClient.post<ClipOut>('/clips', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress,
      });
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        const fileObj = formData.get('file') as File | null;
        const newClip: ClipOut = {
          id: `clip_${Date.now()}`,
          original_filename: fileObj?.name || 'atm_cctv_vestibule.mp4',
          stored_path: 'uploads/demo/atm_cctv_vestibule.mp4',
          sha256: '8f4a2c91d7e0b34f56a12c89e4b7d103a2c4f8e9102b3d4a5c6e7f8091a2b3c4',
          size_bytes: fileObj?.size || 4829104,
          duration_sec: 42.5,
          fps: 25.0,
          width: 1280,
          height: 720,
          codec: 'h264',
          container: 'mov,mp4,m4a,3gp,3g2,mj2',
          rotation: 0,
          clip_start_time: (formData.get('clip_start_time') as string) || new Date().toISOString(),
          clip_start_source: 'user',
          atm_id: (formData.get('atm_id') as string) || 'ATM-JPR-014',
          zone_polygon_norm: [
            [0.45, 0.35],
            [0.95, 0.35],
            [0.95, 0.95],
            [0.45, 0.95],
          ],
          notes: (formData.get('notes') as string) || 'Footage ingested for transaction investigation',
          uploaded_by: 1,
          created_at: new Date().toISOString(),
          video_url: '/files?p=demo.mp4',
        };
        DEMO_CLIPS.unshift(newClip);
        return newClip;
      }
      throw err;
    }
  },

  async patchClip(clipId: string, payload: ClipPatchRequest): Promise<ClipOut> {
    try {
      const res = await apiClient.patch<ClipOut>(`/clips/${clipId}`, payload);
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        const clip = DEMO_CLIPS.find((c) => c.id === clipId);
        if (clip) {
          if (payload.clip_start_time !== undefined) clip.clip_start_time = payload.clip_start_time;
          if (payload.atm_id !== undefined) clip.atm_id = payload.atm_id;
          if (payload.zone_polygon_norm !== undefined) clip.zone_polygon_norm = payload.zone_polygon_norm;
          if (payload.notes !== undefined) clip.notes = payload.notes;
          return clip;
        }
      }
      throw err;
    }
  },

  // 4. Processing Runs
  async processClip(clipId: string, req: ProcessClipRequest): Promise<ProcessClipResponse> {
    try {
      const res = await apiClient.post<ProcessClipResponse>(`/clips/${clipId}/process`, req);
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        const runId = `run_${Date.now()}`;
        const newRun: RunStatus = {
          run_id: runId,
          clip_id: clipId,
          status: 'queued',
          stage: 'queued',
          progress: 0,
          progress_message: 'Job submitted to pipeline queue',
          transaction_time: req.transaction_time,
          window_sec: req.window_sec,
          sample_fps: req.sample_fps,
          created_at: new Date().toISOString(),
        };
        DEMO_RUNS.unshift(newRun);
        return { run_id: runId, status: 'queued' };
      }
      throw err;
    }
  },

  async getRun(runId: string): Promise<RunStatus> {
    try {
      const res = await apiClient.get<RunStatus>(`/runs/${runId}`);
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        const run = DEMO_RUNS.find((r) => r.run_id === runId) || DEMO_RUNS[0];
        // Simulate progressive pipeline stages in demo mode
        if (run && (run.status === 'queued' || run.status === 'running')) {
          const currentProg = run.progress || 0;
          if (currentProg < 30) {
            run.status = 'running';
            run.stage = 'detecting_faces';
            run.progress = 45;
            run.progress_message = 'Extracting candidate frames in transaction window';
          } else if (currentProg < 75) {
            run.stage = 'assessing_quality';
            run.progress = 85;
            run.progress_message = 'Computing 5-metric deterministic face clarity';
          } else {
            run.status = 'done';
            run.stage = 'completed';
            run.progress = 100;
            run.progress_message = 'Forensic candidate extraction complete';
          }
        }
        return run;
      }
      throw err;
    }
  },

  async getRunResult(runId: string): Promise<RunResult> {
    try {
      const res = await apiClient.get<RunResult>(`/runs/${runId}/result`);
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        return DEMO_RUN_RESULTS[runId] || DEMO_RUN_RESULTS['run_default'];
      }
      throw err;
    }
  },

  // 5. Frame Selection & Enhancement
  async updateSelection(runId: string, frameIds: (string | number)[]): Promise<{ success: boolean; frame_ids: (string | number)[] }> {
    try {
      const res = await apiClient.post(`/runs/${runId}/selection`, { frame_ids: frameIds });
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        const run = DEMO_RUNS.find((r) => r.run_id === runId);
        if (run) run.selected_frame_ids = frameIds;
        return { success: true, frame_ids: frameIds };
      }
      throw err;
    }
  },

  async enhanceFrame(runId: string, frameId: string | number, req: EnhanceFrameRequest): Promise<Enhancement> {
    try {
      const res = await apiClient.post<Enhancement>(`/runs/${runId}/frames/${frameId}/enhance`, req);
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        return {
          enhanced_path: `outputs/${runId}/f_${frameId}_enh_x${req.scale}.jpg`,
          method: req.method || 'lanczos',
          scale: req.scale,
          model_version: `${req.method || 'lanczos'}_x${req.scale}_v1`,
          crop_box: req.crop_box,
          search_embedding_source: 'original',
          enhanced_url: `/files?p=outputs%2F${runId}%2Ff_${frameId}_enh_x${req.scale}.jpg`,
        };
      }
      throw err;
    }
  },

  // 6. Cross-Clip Face Search
  async searchFace(req: SearchRequest): Promise<SearchResult> {
    try {
      const res = await apiClient.post<SearchResult>('/search', req);
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        return {
          search_id: `srch_${Date.now()}`,
          run_id: req.run_id,
          frame_id: req.frame_id,
          matches: [
            {
              clip_id: 'clip_02_north',
              filename: 'atm_cctv_vestibule_north.mp4',
              run_id: 'run_north_01',
              frame_id: 'f_18',
              timestamp_sec: 14.8,
              score: 0.91,
              reliability: 'High',
              flags: ['low_light'],
              source: 'original',
              track_id: 1,
              short_track: false,
              crop_url: '/files?p=demo_crop_1.jpg',
              frame_url: '/files?p=demo_frame_1.jpg',
              thumbnail_url: '',
            },
            {
              clip_id: 'clip_05_east',
              filename: 'atm_cctv_fascia_east.mp4',
              run_id: 'run_east_04',
              frame_id: 'f_42',
              timestamp_sec: 8.2,
              score: 0.79,
              reliability: 'Medium',
              flags: ['blur', 'low_light'],
              source: 'original',
              track_id: 2,
              short_track: true, // Shown as Low Confidence
              crop_url: '/files?p=demo_crop_2.jpg',
              frame_url: '/files?p=demo_frame_2.jpg',
              thumbnail_url: '',
            },
          ],
          notice: 'Possible matches only. A human investigator must verify every result.',
          score_note: 'uncalibrated similarity, tune on sample data',
        };
      }
      throw err;
    }
  },

  // 7. Evidence Dossier PDF
  async downloadEvidencePdf(runId: string, searchId?: string): Promise<Blob> {
    try {
      const params = searchId ? { search_id: searchId } : undefined;
      const res = await apiClient.get(`/runs/${runId}/evidence.pdf`, {
        params,
        responseType: 'blob',
      });
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        return new Blob(
          [
            `%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Contents 4 0 R>>endobj 4 0 obj<</Length 95>>stream\nBT /F1 12 Tf 50 700 Td (STRIX EVIDENCE DOSSIER: EV-${runId}) Tj ET\nendstream\nendobj xref\n0 5\n0000000000 65535 f\ntrailer<</Size 5/Root 1 0 R>>startxref\n290\n%%EOF`,
          ],
          { type: 'application/pdf' }
        );
      }
      throw err;
    }
  },

  // 8. Audit Trail (Admin Only)
  async getAuditLogs(params?: { limit?: number; offset?: number; action?: string; username?: string }): Promise<AuditListResponse> {
    try {
      const res = await apiClient.get<AuditListResponse>('/audit', { params });
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        return {
          items: DEMO_AUDIT_LOGS,
          total: DEMO_AUDIT_LOGS.length,
          limit: params?.limit || 50,
          offset: params?.offset || 0,
        };
      }
      throw err;
    }
  },

  async verifyAuditChain(): Promise<AuditVerifyResponse> {
    try {
      const res = await apiClient.get<AuditVerifyResponse>('/audit/verify');
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        return {
          ok: true,
          checked_count: DEMO_AUDIT_LOGS.length,
          first_bad_id: null,
          reason: null,
        };
      }
      throw err;
    }
  },

  async exportAuditCsv(): Promise<string> {
    try {
      const res = await apiClient.get('/audit/export.csv', { responseType: 'text' });
      return res.data;
    } catch (err: any) {
      if (DEMO_MODE) {
        let csv = 'id,ts_utc,user_id,username,role,action,target_type,target_id,details,ip,prev_hash,entry_hash\n';
        DEMO_AUDIT_LOGS.forEach((a) => {
          csv += `${a.id},"${a.ts_utc}",${a.user_id},"${a.username}","${a.role}","${a.action}","${a.target_type}","${a.target_id}","${JSON.stringify(a.details)}","${a.ip}","${a.prev_hash}","${a.entry_hash}"\n`;
        });
        return csv;
      }
      throw err;
    }
  },
};
