import axios, { AxiosError } from 'axios';
import {
  User,
  LoginResponse,
  PublicConfig,
  AuditListResponse,
  AuditVerifyResponse,
  ClipOut,
  FrameExtractRequest,
  FrameEnhanceRequest,
  FaceSearchMatch,
} from '@/types/forensic';
import { INITIAL_CASES, INITIAL_AUDIT_LOGS } from './mockData';

export const MOCK_MODE: boolean = (import.meta as any).env?.VITE_MOCK_MODE === 'true';
export const isMockMode = MOCK_MODE;
export const API_BASE_URL = (import.meta as any).env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

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
      window.dispatchEvent(new CustomEvent('strix:auth_expired'));
    }
    return Promise.reject(error);
  }
);

/* =========================================================================
   API Endpoints & Services (Strict Mock-Mode Gating)
   ========================================================================= */

export const api = {
  // Public Configuration & Health
  async getHealth() {
    try {
      const res = await apiClient.get('/health');
      return res.data;
    } catch (err: any) {
      if (isMockMode) {
        return { status: 'mock', db: 'mock', pipeline_mode: 'fake', ffmpeg: true, ffprobe: true };
      }
      throw new Error(`Backend not reachable at ${API_BASE_URL}`);
    }
  },

  async getPublicConfig(): Promise<PublicConfig> {
    try {
      const res = await apiClient.get<PublicConfig>('/config/public');
      return res.data;
    } catch (err: any) {
      if (isMockMode) {
        return {
          pipeline_mode: 'fake',
          banner: 'MOCK DATA, NOT A REAL RESULT',
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
          model_labels: ['MOCK'],
          display_tz: 'Asia/Kolkata',
        };
      }
      throw new Error(`Backend not reachable at ${API_BASE_URL}`);
    }
  },

  // Authentication
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
      // Only allow a demo user fallback if MOCK_MODE === true and fetch() throws a network error (no HTTP response at all)
      if (MOCK_MODE) {
        const mockUser: User = {
          id: 2,
          username: 'r.sharma',
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

      // If MOCK_MODE === false and the backend is unreachable, throw "Backend not reachable"
      localStorage.removeItem('strix_token');
      localStorage.removeItem('strix_user');
      sessionStorage.removeItem('strix_token');
      sessionStorage.removeItem('strix_user');
      throw new Error('Backend not reachable');
    }

    // Never return a fake user when the server responds with an HTTP error (401, 403, 429, 422, 500, etc.)
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
            // FastAPI 422 validation errors
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
        } catch {}
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
      if (isMockMode) {
        const stored = localStorage.getItem('strix_user');
        if (stored) return JSON.parse(stored);
      }
      throw err;
    }
  },

  logout() {
    localStorage.removeItem('strix_token');
    localStorage.removeItem('strix_user');
  },

  // Audit Logs
  async getAuditLogs(params?: { limit?: number; offset?: number; action?: string }): Promise<AuditListResponse> {
    try {
      const res = await apiClient.get<AuditListResponse>('/audit', { params });
      return res.data;
    } catch (err: any) {
      if (isMockMode) {
        const items = INITIAL_AUDIT_LOGS.map((a, idx) => ({
          id: idx + 1,
          ts_utc: a.timestamp,
          user_id: 1,
          username: a.investigator.split(' ')[0],
          role: 'investigator',
          action: a.action.toLowerCase().replace(/\s+/g, '_'),
          target_type: 'case',
          target_id: a.refId,
          details: { note: a.details },
          ip: '127.0.0.1',
          prev_hash: '0000000000000000000000000000000000000000000000000000000000000000',
          entry_hash: a.hash,
        }));
        return {
          items,
          total: items.length,
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
      if (isMockMode) {
        return {
          ok: true,
          checked_count: INITIAL_AUDIT_LOGS.length,
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
      if (isMockMode) {
        let csv = 'timestamp,investigator,action,refId,details,hash\n';
        INITIAL_AUDIT_LOGS.forEach((a) => {
          csv += `"${a.timestamp}","${a.investigator}","${a.action}","${a.refId}","${a.details}","${a.hash}"\n`;
        });
        return csv;
      }
      throw err;
    }
  },

  // Clips Management
  async listClips(): Promise<ClipOut[]> {
    try {
      const res = await apiClient.get<ClipOut[]>('/clips');
      return res.data;
    } catch (err: any) {
      if (isMockMode) {
        return [];
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
      if (isMockMode) {
        return {
          id: `clip_${Date.now()}`,
          original_filename: (formData.get('file') as File)?.name || 'atm_cctv_vestibule.mp4',
          stored_path: 'uploads/demo/atm_cctv_vestibule.mp4',
          sha256: '8f4a2c91d7e0b34f56a12c89e4b7d103a2c4f8e9102b3d4a5c6e7f8091a2b3c4',
          size_bytes: 4829104,
          duration_sec: 42.5,
          fps: 25.0,
          width: 1280,
          height: 720,
          codec: 'h264',
          container: 'mov,mp4,m4a,3gp,3g2,mj2',
          rotation: 0,
          clip_start_time: new Date().toISOString(),
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
      }
      throw err;
    }
  },

  // Frame Extraction
  async extractFrames(clipId: string, req: FrameExtractRequest) {
    try {
      const res = await apiClient.post(`/clips/${clipId}/frames/extract`, req);
      return res.data;
    } catch (err: any) {
      if (isMockMode) {
        return Array.from({ length: Math.min(req.fps * (req.end_sec - req.start_sec), 16) }).map(
          (_, i) => ({
            frame_id: `f_${i + 1}`,
            timestamp_sec: req.start_sec + i * (1 / req.fps),
            quality_score: Math.round((0.65 + Math.random() * 0.3) * 100) / 100,
            flags: i % 3 === 0 ? ['low_light'] : [],
            flag_scores: i % 3 === 0 ? { low_light: 0.78 } : null,
            reliability: i % 3 === 0 ? 'Medium' : 'High',
          })
        );
      }
      throw err;
    }
  },

  // Crop & Non-destructive Super-Resolution Enhancement
  async enhanceFrame(frameId: string | number, req: FrameEnhanceRequest) {
    try {
      const res = await apiClient.post(`/frames/${frameId}/enhance`, req);
      return res.data;
    } catch (err: any) {
      if (isMockMode) {
        return {
          success: true,
          method: req.method,
          scale: req.scale,
          model_version: `${req.method.toLowerCase()}_x${req.scale}_v1`,
          enhanced_label: 'ENHANCED',
          crop_box: req.crop_box,
          notice: 'Non-destructive super-resolution applied. Original pixels untouched.',
        };
      }
      throw err;
    }
  },

  // Cross-Clip Face Search
  async searchFace(frameId: string | number, onlyEnhanced: boolean = false): Promise<FaceSearchMatch[]> {
    try {
      const res = await apiClient.post(`/frames/${frameId}/search`, { only_enhanced: onlyEnhanced });
      return res.data;
    } catch (err: any) {
      if (isMockMode) {
        return [
          {
            match_id: 'MATCH-9021',
            clip_id: 'atm_clip_02_north',
            timestamp_sec: 14.8,
            original_similarity: 0.89,
            enhanced_similarity: 0.91,
            similarity_secondary: 0.91,
            delta: 0.02,
            reliability: 'High',
            thumbnail_url: '',
            location: 'MI Road Branch, Jaipur',
            atm_id: 'ATM-JPR-014',
          },
          {
            match_id: 'MATCH-8419',
            clip_id: 'atm_clip_05_east',
            timestamp_sec: 8.2,
            original_similarity: 0.62,
            enhanced_similarity: 0.79,
            similarity_secondary: 0.79,
            delta: 0.17,
            reliability: 'Medium',
            warning: 'Enhancement changed the result (>0.15 delta). Treat with caution.',
            thumbnail_url: '',
            location: 'Malviya Nagar Sector-4, Jaipur',
            atm_id: 'ATM-JPR-003',
            flag_warning: 'Enhancement changed the result (>0.15 delta). Treat with caution.',
          },
        ];
      }
      throw err;
    }
  },

  // Evidence Sheet & Export
  async addFramesToEvidence(caseId: string, frameIds: (string | number)[]) {
    try {
      const res = await apiClient.post(`/evidence/${caseId}/frames`, { frame_ids: frameIds });
      return res.data;
    } catch (err: any) {
      if (isMockMode) {
        return { success: true, count: frameIds.length };
      }
      throw err;
    }
  },

  async downloadEvidencePdf(caseId: string): Promise<Blob> {
    try {
      const res = await apiClient.get(`/evidence/${caseId}/pdf`, { responseType: 'blob' });
      return res.data;
    } catch (err: any) {
      if (isMockMode) {
        return new Blob(
          [
            `%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Contents 4 0 R>>endobj 4 0 obj<</Length 85>>stream\nBT /F1 12 Tf 50 700 Td (STRIX FORENSIC EVIDENCE DOSSIER: ${caseId}) Tj ET\nendstream\nendobj xref\n0 5\n0000000000 65535 f\ntrailer<</Size 5/Root 1 0 R>>startxref\n280\n%%EOF`,
          ],
          { type: 'application/pdf' }
        );
      }
      throw err;
    }
  },
};
