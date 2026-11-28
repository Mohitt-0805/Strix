# Strix Backend API & Contract Specification

Base URL: `http://localhost:8000` (or configured via `VITE_API_BASE_URL`)

## Authentication & Authorization
- **Bearer Token**: Attach `Authorization: Bearer <token>` to all authenticated API calls.
- **Roles**:
  - `admin`: Full access including `/audit`, `/audit/verify`, `/audit/export.csv`, `/users`.
  - `investigator`: Operational access (upload clips, process runs, inspect frames, enhance, search, evidence PDF).
- **Signed Media URLs**: Media URLs returned as relative strings (e.g., `"/files?p=...&sig=..."`) must be prefixed with `API_BASE_URL` and used directly in `<img>` and `<video>` tags without `Authorization` headers.

---

## Endpoints

### 1. Public Configuration & Health
- `GET /health`: SQLite connectivity & media tool availability (`ffmpeg`, `ffprobe`).
- `GET /config/public`: Public limits, accepted video extensions, model labels, pipeline mode (`"real"` or `"fake"`), banner (`"FAKE PIPELINE, DEMO DATA"`), and human-verification notice.
- `GET /zones`: Available ATM standing zone configurations:
  ```json
  [
    {
      "id": "atm_01",
      "polygon": [[0.45, 0.35], [0.95, 0.35], [0.95, 0.95], [0.45, 0.95]],
      "note": "Default normalized ATM standing zone"
    }
  ]
  ```

### 2. Auth Endpoints
- `POST /auth/login`: `{ "username": "...", "password": "..." }`
  - Response: `{ "access_token": "<jwt>", "token_type": "bearer", "user": { "id": 1, "username": "...", "role": "admin"|"investigator", "full_name": "...", "active": true, "created_at": "..." } }`
  - Error: Uniform error `{ "detail": "...", "code": "..." }` (401, 403, 429).
- `GET /auth/me`: Current user profile.

### 3. Clip Ingest & Media
- `POST /clips`: `multipart/form-data` with:
  - `file`: Video file (MP4, AVI, MOV, MKV, WMV, FLV, MPEG, MPG)
  - `atm_id`: Optional terminal identifier
  - `clip_start_time`: Optional ISO-8601 string (e.g., `2026-11-26T15:30:00`)
  - `notes`: Optional case notes
  - Response: `ClipOut` with `id`, metadata, duration, fps, resolution, SHA-256 hash, and signed `video_url`.
- `GET /clips`: List all clips newest-first.
- `GET /clips/{id}`: Fetch single clip metadata.
- `PATCH /clips/{id}`: Update `clip_start_time`, `atm_id`, `zone_polygon_norm`, or `notes`.
- `GET /clips/{id}/video`: Stream video with HTTP Range support (`206`).

### 4. Pipeline Run Processing
- `POST /clips/{id}/process`: Initiate asynchronous forensic processing.
  - Body:
    ```json
    {
      "transaction_time": "2026-11-26T21:14:24",
      "window_sec": 10.0,
      "sample_fps": 2.0,
      "tracker": "iou",
      "atm_id": "ATM-JPR-014"
    }
    ```
  - Response (`202 Accepted`): `{ "run_id": "<uuid>", "status": "queued" }`
- `GET /runs/{run_id}`: Poll processing status every 2 seconds.
  - Fields: `run_id`, `clip_id`, `status` (`"queued"|"running"|"done"|"failed"`), `stage`, `progress` (0 to 100), `progress_message`, `error_code`, `error_advice`.
- `GET /runs/{run_id}/result`: Retrieve final forensic result:
  - `run_id`, `clip_id`, `transaction_time`, `person_track_id`.
  - `best_frames`: Array of ranked frames with `frame_id`, `timestamp_sec`, `quality_score`, `reliability` (`"High"|"Medium"|"Low"`), `flags`, `flag_scores` (`"model estimate"`), `metrics`, signed `crop_url`, and `frame_url`.
  - `link_confidence`, `link_reason`, `link_low_margin` (boolean warning flag), `selection_reason`.

### 5. Frame Selection & Enhancement
- `POST /runs/{run_id}/selection`: Update curated evidence frame set:
  - Body: `{ "frame_ids": ["f_1", "f_2"] }`
- `POST /runs/{run_id}/frames/{frame_id}/enhance`: Non-destructive super-resolution:
  - Body:
    ```json
    {
      "crop_box": [120, 80, 64, 64],
      "scale": 2,
      "method": "lanczos"
    }
    ```
  - Crops in NATURAL image pixels, resizes by 2x or 4x, burns permanent red `ENHANCED` tag into pixels, original untouched.

### 6. Cross-Clip Face Search
- `POST /search`:
  - Body:
    ```json
    {
      "run_id": "<uuid>",
      "frame_id": "f_1",
      "top_k": 10,
      "best_per_clip": true
    }
    ```
  - Response:
    ```json
    {
      "search_id": "<uuid>",
      "run_id": "<uuid>",
      "frame_id": "f_1",
      "matches": [
        {
          "clip_id": "clip_2",
          "filename": "atm_east.mp4",
          "run_id": "run_2",
          "frame_id": "f_5",
          "timestamp_sec": 8.2,
          "score": 0.79,
          "reliability": "Medium",
          "flags": ["low_light"],
          "source": "original",
          "track_id": 1,
          "short_track": false,
          "crop_url": "/files?p=...",
          "frame_url": "/files?p=..."
        }
      ],
      "notice": "Possible matches only. A human investigator must verify every result.",
      "score_note": "uncalibrated similarity, tune on sample data"
    }
    ```
  - Note: `short_track: true` matches must be displayed as Low Confidence.

### 7. Evidence PDF Dossier
- `GET /runs/{run_id}/evidence.pdf` (optional `?search_id=<uuid>`):
  - Fetched with `Authorization: Bearer <token>` as `blob`.
  - Generates signed court-ready ReportLab PDF dossier titled `Evidence Sheet` with evidence ID `EV-<run_id>`.

### 8. Audit Trail (Admin Only)
- `GET /audit`: Paginated hash-chained ledger.
- `GET /audit/verify`: Cryptographic verification of SHA-256 chain integrity.
- `GET /audit/export.csv`: Official CSV export.
