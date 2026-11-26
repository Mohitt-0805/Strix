# Strix Backend API

Base URL (local): `http://127.0.0.1:8000`

## Error Format

Every error response uses the uniform JSON shape:

```json
{
  "detail": "Not Found",
  "code": "NOT_FOUND"
}
```

## Public Endpoints

### `GET /health`

Public health check verifying SQLite connectivity and `ffmpeg`/`ffprobe` availability.

**Request:**
```bash
curl -s http://127.0.0.1:8000/health
```

**Response (`200 OK`):**
```json
{
  "status": "ok",
  "db": "ok",
  "pipeline_mode": "fake",
  "ffmpeg": true,
  "ffprobe": true
}
```

---

### `GET /config/public`

Public non-secret configuration, limits, accepted video extensions, model labels, and the mandatory human-verification notice.

**Request:**
```bash
curl -s http://127.0.0.1:8000/config/public
```

**Response (`200 OK`):**
```json
{
  "pipeline_mode": "fake",
  "banner": "FAKE PIPELINE, DEMO DATA",
  "notice": "Possible matches only. A human investigator must verify every result.",
  "limits": {
    "max_upload_mb": 500,
    "window_sec_min": 1,
    "window_sec_max": 100,
    "sample_fps_min": 0.5,
    "sample_fps_max": 5.0,
    "max_sampled_frames": 200,
    "embed_dim": 512,
    "signed_url_ttl_sec": 900
  },
  "accepted_extensions": [
    "mp4",
    "avi",
    "mov",
    "mkv",
    "wmv",
    "flv",
    "mpeg",
    "mpg"
  ],
  "model_labels": [
    "FAKE PIPELINE"
  ],
  "display_tz": "Asia/Kolkata"
}
```

---

## Auth Endpoints

### `POST /auth/login`

Authenticate with username and password (throttled after 5 failed attempts in 5 minutes per `username + IP` -> `429`).

**Request:**
```bash
curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"..."}'
```

**Response (`200 OK`):**
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "admin",
    "role": "admin",
    "full_name": "System Admin",
    "active": true,
    "created_at": "2026-11-26T12:55:00.000000"
  }
}
```

---

### `GET /auth/me`

Return the authenticated user's profile (`Bearer` token required).

**Request:**
```bash
curl -s http://127.0.0.1:8000/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

**Response (`200 OK`):**
```json
{
  "id": 1,
  "username": "admin",
  "role": "admin",
  "full_name": "System Admin",
  "active": true,
  "created_at": "2026-11-26T12:55:00.000000"
}
```

---

## User Management Endpoints (Admin Only)

### `POST /users`

Create an `admin` or `investigator` user (`409 USERNAME_EXISTS` on duplicate).

**Request:**
```bash
curl -s -X POST http://127.0.0.1:8000/users \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username":"analyst1","password":"StrongPassword99","role":"investigator","full_name":"Analyst One"}'
```

**Response (`201 Created`):**
```json
{
  "id": 3,
  "username": "analyst1",
  "role": "investigator",
  "full_name": "Analyst One",
  "active": true,
  "created_at": "2026-11-26T12:56:00.000000"
}
```

---

### `GET /users`

List all users ordered by `id`.

**Request:**
```bash
curl -s http://127.0.0.1:8000/users \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Response (`200 OK`):**
```json
[
  {
    "id": 1,
    "username": "admin",
    "role": "admin",
    "full_name": "System Admin",
    "active": true,
    "created_at": "2026-11-26T12:55:00.000000"
  }
]
```

---

## Audit Endpoints (Admin Only)

### `GET /audit`

List append-only hash-chained audit entries (`limit`, `offset`, `action`, `username`).

**Request:**
```bash
curl -s "http://127.0.0.1:8000/audit?limit=10&offset=0" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Response (`200 OK`):**
```json
{
  "items": [
    {
      "id": 1,
      "ts_utc": "2026-11-26T12:55:00.123456Z",
      "user_id": 1,
      "username": "admin",
      "role": "admin",
      "action": "login_success",
      "target_type": "user",
      "target_id": "1",
      "details": {},
      "ip": "127.0.0.1",
      "prev_hash": "0000000000000000000000000000000000000000000000000000000000000000",
      "entry_hash": "<sha256>"
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0
}
```

---

### `GET /audit/export.csv`

Export the audit log as CSV and record an `audit_export` entry.

**Request:**
```bash
curl -s http://127.0.0.1:8000/audit/export.csv \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Response (`200 OK`, `text/csv`):**
```csv
id,ts_utc,user_id,username,role,action,target_type,target_id,details,ip,prev_hash,entry_hash
1,2026-11-26T12:55:00.123456Z,1,admin,admin,login_success,user,1,{},127.0.0.1,0000...,<sha256>
```

---

### `GET /audit/verify`

Recompute the SHA-256 hash chain across `audit_log` and report `ok` or the first corrupted `id`.

**Request:**
```bash
curl -s http://127.0.0.1:8000/audit/verify \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Response (`200 OK`):**
```json
{
  "ok": true,
  "checked_count": 2,
  "first_bad_id": null,
  "reason": null
}
```

---

## Clips & Signed Files Endpoints

### `POST /clips`

Stream-upload a video clip (`mp4, avi, mov, mkv, wmv, flv, mpeg, mpg`), compute SHA-256, probe metadata with `ffprobe`, and convert `creation_time` to `DISPLAY_TZ`.

**Request (`multipart/form-data`):**
```bash
curl -s -X POST http://127.0.0.1:8000/clips \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@sample.mp4" \
  -F "atm_id=ATM-001" \
  -F "notes=Test upload"
```

**Response (`201 Created`):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "original_filename": "sample.mp4",
  "stored_path": "uploads/550e8400-e29b-41d4-a716-446655440000/sample.mp4",
  "sha256": "<sha256>",
  "size_bytes": 123456,
  "duration_sec": 5.0,
  "fps": 10.0,
  "width": 320,
  "height": 240,
  "codec": "h264",
  "container": "mov,mp4,m4a,3gp,3g2,mj2",
  "rotation": 0,
  "clip_start_time": "2026-11-26T15:30:00",
  "clip_start_source": "ffprobe_converted",
  "atm_id": "ATM-001",
  "zone_polygon_norm": null,
  "notes": "Test upload",
  "uploaded_by": 1,
  "created_at": "2026-11-26T13:05:00.000000",
  "video_url": "/files?p=uploads%2F...&uid=1&exp=...&sig=..."
}
```

---

### `GET /clips` & `GET /clips/{id}`

List clips newest-first or fetch a single clip by UUID (`Bearer` token required).

---

### `PATCH /clips/{id}`

Update `clip_start_time` (sets `clip_start_source="user"`), `atm_id`, `zone_polygon_norm` (at least 3 `[x, y]` points in `0..1`), or `notes`.

---

### `GET /clips/{id}/video`

Stream the uploaded clip video with HTTP `Range` (`206 Partial Content`) support. Add `?download=1` for `Content-Disposition: attachment` and a `download_video` audit entry.

**Request:**
```bash
curl -i -r 0-99 -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/clips/$CLIP_ID/video
```

---

### `GET /files`

Serve files inside `DATA_DIR/uploads` or `DATA_DIR/outputs` using an HMAC-SHA256 signed URL (`p`, `uid`, `exp`, `sig`), with HTTP `Range` (`206`) and `?download=1` audit support. No `Authorization` header required.

**Request:**
```bash
curl -i -r 0-99 "http://127.0.0.1:8000$VIDEO_URL"
```

