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
