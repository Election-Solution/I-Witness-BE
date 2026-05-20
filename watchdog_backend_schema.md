# WatchDog Alert — Backend Schema & API Specification

> Reference document for the Python (FastAPI) backend powering the **WatchDog Alert** real-time election incident triage platform.
> Stack assumption: **FastAPI + SQLAlchemy 2.x + PostgreSQL + Alembic + Pydantic v2**. Async endpoints. JWT auth for admins.

---

## 1. High-Level Architecture

```
[ Mobile/Web Client ]
        │  HTTPS / JSON
        ▼
[  FastAPI App  ] ── [ Redis (cache + pub/sub for live map) ]
        │
        ├── [ PostgreSQL + PostGIS ]  ← incidents, users, audit
        ├── [ S3 / Cloud Storage ]    ← evidence (photos/videos)
        └── [ AI Service (LLM) ]      ← summarization + severity scoring
```

Suggested project layout:

```
app/
├── main.py
├── core/            # config, security, settings
├── api/
│   └── v1/
│       ├── routes_incidents.py
│       ├── routes_admin.py
│       ├── routes_auth.py
│       ├── routes_meta.py
│       └── routes_uploads.py
├── models/          # SQLAlchemy ORM models
├── schemas/         # Pydantic request/response models
├── services/        # business logic (ai_summary, geocoding, notifier)
├── db/              # session, base, migrations
└── tests/
```

---

## 2. Database Schema (PostgreSQL)

All tables use `id UUID PRIMARY KEY DEFAULT gen_random_uuid()` and `created_at`, `updated_at` timestamps (`TIMESTAMPTZ`).

### 2.1 `users` — Admin & staff accounts
| Column          | Type             | Notes                                       |
| --------------- | ---------------- | ------------------------------------------- |
| id              | UUID PK          |                                             |
| email           | CITEXT UNIQUE    | login                                       |
| password_hash   | TEXT             | bcrypt / argon2                             |
| full_name       | TEXT             |                                             |
| phone           | TEXT NULL        |                                             |
| is_active       | BOOLEAN          | default true                                |
| created_at      | TIMESTAMPTZ      |                                             |
| updated_at      | TIMESTAMPTZ      |                                             |

> **Roles are stored separately** (see `user_roles`) — never on `users`.

### 2.2 `user_roles`
| Column   | Type                                      | Notes |
| -------- | ----------------------------------------- | ----- |
| id       | UUID PK                                   |       |
| user_id  | UUID FK → users(id) ON DELETE CASCADE     |       |
| role     | ENUM `app_role` (`admin`,`triager`,`viewer`) |    |
| UNIQUE (user_id, role) |                                |       |

### 2.3 `states` / `lgas` / `wards` / `polling_units` — Location hierarchy
Normalized so reports can be aggregated cleanly.

```sql
states          (id, name UNIQUE, code)
lgas            (id, state_id FK, name, UNIQUE(state_id, name))
wards           (id, lga_id FK, name, UNIQUE(lga_id, name))
polling_units   (id, ward_id FK, code, name, lat NUMERIC(9,6), lng NUMERIC(9,6))
```

### 2.4 `incidents` — Core table
| Column            | Type                                  | Notes                                       |
| ----------------- | ------------------------------------- | ------------------------------------------- |
| id                | UUID PK                               |                                             |
| public_ref        | TEXT UNIQUE                           | e.g. `WDA-1042`, generated on insert        |
| state_id          | UUID FK → states                      |                                             |
| lga_id            | UUID FK → lgas NULL                   |                                             |
| ward_id           | UUID FK → wards NULL                  |                                             |
| polling_unit_id   | UUID FK → polling_units NULL          |                                             |
| polling_unit_text | TEXT NULL                             | freeform fallback if PU not in DB           |
| issue_type        | ENUM `issue_type`                     | `missing_items`,`staff_late`,`security`,`other` |
| raw_details       | TEXT                                  | reporter's words, max 1000 chars            |
| ai_summary        | TEXT NULL                             | 2-sentence LLM summary                      |
| severity          | ENUM `severity` (`low`,`medium`,`high`) | initially set by AI, editable by admin    |
| status            | ENUM `incident_status` (`new`,`checking`,`resolved`) | default `new`              |
| lat               | NUMERIC(9,6) NULL                     |                                             |
| lng               | NUMERIC(9,6) NULL                     |                                             |
| geom              | GEOGRAPHY(Point, 4326) NULL           | PostGIS, generated from lat/lng             |
| reporter_phone    | TEXT NULL                             | optional, hashed if stored                  |
| reporter_ip       | INET NULL                             | abuse mitigation                            |
| assigned_to       | UUID FK → users NULL                  | triager handling it                         |
| resolved_at       | TIMESTAMPTZ NULL                      |                                             |
| created_at        | TIMESTAMPTZ                           |                                             |
| updated_at        | TIMESTAMPTZ                           |                                             |

**Indexes**
- `idx_incidents_status` on (status)
- `idx_incidents_state_status` on (state_id, status)
- `idx_incidents_created_at` on (created_at DESC)
- `gix_incidents_geom` GIST on (geom)

### 2.5 `incident_evidence`
| Column        | Type                                 | Notes                              |
| ------------- | ------------------------------------ | ---------------------------------- |
| id            | UUID PK                              |                                    |
| incident_id   | UUID FK → incidents ON DELETE CASCADE|                                    |
| storage_key   | TEXT                                 | S3/object-store key                |
| mime_type     | TEXT                                 | `image/jpeg`, `video/mp4`, ...     |
| size_bytes    | BIGINT                               |                                    |
| width / height| INTEGER NULL                         |                                    |
| created_at    | TIMESTAMPTZ                          |                                    |

### 2.6 `incident_status_history` — Audit trail
| Column        | Type                                | Notes                       |
| ------------- | ----------------------------------- | --------------------------- |
| id            | UUID PK                             |                             |
| incident_id   | UUID FK → incidents                 |                             |
| from_status   | ENUM `incident_status` NULL         |                             |
| to_status     | ENUM `incident_status`              |                             |
| changed_by    | UUID FK → users NULL                | NULL if system / AI         |
| note          | TEXT NULL                           |                             |
| created_at    | TIMESTAMPTZ                         |                             |

### 2.7 `incident_notes` — Internal triage comments
| Column        | Type                       | Notes |
| ------------- | -------------------------- | ----- |
| id            | UUID PK                    |       |
| incident_id   | UUID FK → incidents        |       |
| author_id     | UUID FK → users            |       |
| body          | TEXT                       |       |
| created_at    | TIMESTAMPTZ                |       |

### 2.8 `rate_limits` (optional, can live in Redis)
Track submissions per IP / phone per minute to prevent spam.

---

## 3. Enums

```sql
CREATE TYPE app_role          AS ENUM ('admin','triager','viewer');
CREATE TYPE issue_type        AS ENUM ('missing_items','staff_late','security','other');
CREATE TYPE severity          AS ENUM ('low','medium','high');
CREATE TYPE incident_status   AS ENUM ('new','checking','resolved');
```

---

## 4. REST API — `/api/v1`

Conventions:
- Plural resource nouns. `kebab-case` only where multi-word.
- JSON in/out. `snake_case` field names.
- Auth: `Authorization: Bearer <jwt>` for protected routes.
- Errors: RFC 7807 `application/problem+json`.
- Pagination: `?limit=50&cursor=<opaque>` → response `{ data, next_cursor }`.

### 4.1 Public — Reporter endpoints

| Method | Path                              | Auth | Purpose                                  |
| ------ | --------------------------------- | ---- | ---------------------------------------- |
| POST   | `/api/v1/incidents`               | none | Submit a new report                      |
| GET    | `/api/v1/incidents/public`        | none | Live map feed (limited fields)           |
| GET    | `/api/v1/incidents/public/{ref}`  | none | Public view of a single incident         |
| POST   | `/api/v1/uploads/evidence`        | none | Multipart upload, returns `storage_key`  |
| GET    | `/api/v1/meta/states`             | none | List states                              |
| GET    | `/api/v1/meta/states/{id}/lgas`   | none | LGAs in a state                          |
| GET    | `/api/v1/meta/lgas/{id}/wards`    | none | Wards in an LGA                          |
| GET    | `/api/v1/meta/issue-types`        | none | Enum values for the form                 |

**`POST /api/v1/incidents` — request**
```json
{
  "state_id": "uuid",
  "lga_id": "uuid|null",
  "ward_id": "uuid|null",
  "polling_unit_id": "uuid|null",
  "polling_unit_text": "PU 014",
  "issue_type": "staff_late",
  "details": "INEC officials still not here at 9am...",
  "evidence_keys": ["uploads/2026/04/abc.jpg"],
  "reporter_phone": "+2348012345678"
}
```

**Response `201`**
```json
{
  "id": "uuid",
  "public_ref": "WDA-1042",
  "status": "new",
  "severity": "medium",
  "ai_summary": "INEC officials have not arrived...",
  "created_at": "2026-04-30T08:02:11Z"
}
```

### 4.2 Admin — Triage endpoints (require role `admin` or `triager`)

| Method | Path                                         | Purpose                                  |
| ------ | -------------------------------------------- | ---------------------------------------- |
| GET    | `/api/v1/admin/incidents`                    | List with filters: `status`, `severity`, `state_id`, `from`, `to`, `q` |
| GET    | `/api/v1/admin/incidents/{id}`               | Full detail incl. evidence + history     |
| PATCH  | `/api/v1/admin/incidents/{id}`               | Update severity / assignment / notes     |
| POST   | `/api/v1/admin/incidents/{id}/status`        | Advance status (`new`→`checking`→`resolved`) |
| POST   | `/api/v1/admin/incidents/{id}/notes`         | Add internal note                        |
| POST   | `/api/v1/admin/incidents/{id}/regenerate-summary` | Re-run AI summary                   |
| GET    | `/api/v1/admin/stats/overview`               | Counts per status/severity/state         |
| GET    | `/api/v1/admin/stats/timeseries`             | Reports over time (for charts)           |

**`POST /admin/incidents/{id}/status` — request**
```json
{ "to_status": "checking", "note": "Contacted ward agent." }
```

### 4.3 Auth

| Method | Path                          | Purpose                            |
| ------ | ----------------------------- | ---------------------------------- |
| POST   | `/api/v1/auth/login`          | email + password → JWT pair        |
| POST   | `/api/v1/auth/refresh`        | refresh token → new access token   |
| POST   | `/api/v1/auth/logout`         | revoke refresh token               |
| GET    | `/api/v1/auth/me`             | current user + roles               |

### 4.4 Realtime

- `GET /api/v1/realtime/incidents` — **Server-Sent Events** stream of new/updated incidents (drives the live map and admin desk without polling).
- Event payload mirrors the public incident shape with an `event` field: `incident.created`, `incident.updated`, `incident.status_changed`.

---

## 5. Pydantic Schemas (sketch)

```python
class IncidentBase(BaseModel):
    state_id: UUID
    lga_id: UUID | None = None
    ward_id: UUID | None = None
    polling_unit_id: UUID | None = None
    polling_unit_text: str | None = Field(None, max_length=80)
    issue_type: IssueType
    details: str = Field(..., min_length=5, max_length=1000)

class IncidentCreate(IncidentBase):
    evidence_keys: list[str] = []
    reporter_phone: str | None = None

class IncidentPublic(BaseModel):
    public_ref: str
    state: str
    lga: str | None
    ward: str | None
    polling_unit: str | None
    issue_type: IssueType
    severity: Severity
    status: IncidentStatus
    ai_summary: str | None
    lat: float | None
    lng: float | None
    created_at: datetime

class IncidentAdmin(IncidentPublic):
    id: UUID
    raw_details: str
    assigned_to: UUID | None
    evidence: list[EvidenceOut]
    history: list[StatusHistoryOut]
    notes: list[NoteOut]
```

---

## 6. Background Jobs (Celery / RQ / FastAPI BackgroundTasks)

| Job                          | Trigger                       | Action                                      |
| ---------------------------- | ----------------------------- | ------------------------------------------- |
| `summarize_incident`         | after `POST /incidents`       | call LLM → write `ai_summary` + `severity`  |
| `geocode_incident`           | after create if no lat/lng    | resolve via PU → fallback to ward centroid  |
| `notify_admins`              | on `severity = high`          | push / SMS / email to on-call triagers      |
| `cleanup_orphan_evidence`    | hourly                        | drop uploads not attached to any incident   |

---

## 7. Security Notes

- Hash `reporter_phone` (HMAC with server pepper) if stored — used only for rate-limit / dedupe.
- Strict file validation on uploads: MIME sniff + max size (e.g. 10 MB image, 50 MB video).
- Per-IP and per-phone rate limits on `POST /incidents` (e.g. 5/min, 30/hour).
- All admin routes behind JWT + role check using a `require_role("admin","triager")` dependency.
- CORS: allow only the production web origin.
- Audit every status change in `incident_status_history`.

---

## 8. Example FastAPI Router Skeleton

```python
# app/api/v1/routes_incidents.py
from fastapi import APIRouter, Depends, status
from app.schemas.incident import IncidentCreate, IncidentPublic
from app.services.incidents import create_incident, list_public_incidents

router = APIRouter(prefix="/incidents", tags=["incidents"])

@router.post("", response_model=IncidentPublic, status_code=status.HTTP_201_CREATED)
async def submit_incident(payload: IncidentCreate, db=Depends(get_db)):
    return await create_incident(db, payload)

@router.get("/public", response_model=list[IncidentPublic])
async def public_feed(state_id: UUID | None = None, db=Depends(get_db)):
    return await list_public_incidents(db, state_id=state_id)
```

---

## 9. Environment Variables

```
DATABASE_URL=postgresql+asyncpg://user:pass@host/watchdog
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=...
JWT_ACCESS_TTL=900
JWT_REFRESH_TTL=2592000
S3_BUCKET=watchdog-evidence
S3_REGION=eu-west-1
AI_PROVIDER_API_KEY=...
PHONE_HASH_PEPPER=...
CORS_ORIGINS=https://watchdog.example
```

---

## 10. Mapping to Current Frontend Mock

| Frontend field (`Incident`)   | Backend source                                  |
| ----------------------------- | ----------------------------------------------- |
| `id`                          | `incidents.public_ref`                          |
| `state` / `lga` / `ward`      | joined from location tables                     |
| `pollingUnit`                 | `polling_units.code` or `polling_unit_text`     |
| `issueType`                   | `incidents.issue_type` (mapped to display label)|
| `summary`                     | `incidents.ai_summary`                          |
| `severity`                    | `incidents.severity`                            |
| `status`                      | `incidents.status`                              |
| `lat` / `lng`                 | `incidents.lat` / `incidents.lng`               |
| `reportedAt`                  | derived from `incidents.created_at`             |
