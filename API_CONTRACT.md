# FaceByYou API contract

**Audience:** CTO, mobile/web clients, QA, and DevOps  
**Base URL:** `{environment-base-url}/api/v1`  
**Format:** JSON request and response bodies; UTF-8; ISO-8601 timestamps.

This document describes the contract implemented by the current backend. The
interactive equivalent is `{base-url}/docs` in a running non-production API.

## Authentication and conventions

Protected endpoints require a backend bearer token:

```http
Authorization: Bearer <backend-access-token>
```

The app exchanges a Firebase ID token for that backend token through the login
endpoints. `POST /auth/dev-login` and `POST /admin/dev-login` are development
helpers and return `404` when `ENVIRONMENT` is production.

Unless noted, expected failures are returned as:

```json
{"detail": "Human-readable explanation"}
```

Common statuses are `401` (missing/invalid bearer token), `403` (not owner or
insufficient role), `404` (not found), `413` (image exceeds 50 MB), `415`
(unsupported media type), and `422` (invalid request shape or value).

All scan images must be JPEG with `Content-Type: image/jpeg`. Both `.jpg` and
`.jpeg` local filenames are fine; the API assigns the S3 objects canonical
names: `front.jpg`, `left.jpg`, and `right.jpg`.

## Account and authentication

| Endpoint | Authentication | Behavior |
|---|---|---|
| `POST /auth/register` | No | Creates Firebase credential and a DynamoDB profile. |
| `POST /auth/login` | No | Verifies Firebase ID token, reactivates a pending-deletion account, and returns backend bearer token. |
| `POST /auth/google` | No | Verifies Firebase Google token; creates a minimal profile when absent; reactivates a pending-deletion account. |
| `POST /auth/apple` | No | Same behavior as Google for Apple token. |
| `POST /auth/reset-password` | No | Starts Firebase password-reset email flow. |
| `POST /auth/dev-login` | No, non-production | Creates/uses a development profile and returns backend bearer token. |

### `POST /auth/register`

```json
{
  "firstName": "Ada",
  "lastName": "Lovelace",
  "dateOfBirth": "2000-01-02",
  "email": "ada@example.com",
  "password": "client-chosen-password"
}
```

Success (`200`):

```json
{"success": true, "userId": "firebase-uid", "message": "Account created successfully"}
```

Firebase conflicts or registration failures return `409`.

### `POST /auth/login`

```json
{"id_token": "firebase-id-token"}
```

Success (`200`):

```json
{"success": true, "access_token": "backend-jwt", "token_type": "bearer", "user_id": "firebase-uid"}
```

### `POST /auth/google` and `POST /auth/apple`

```json
{"token": "firebase-provider-id-token"}
```

Success (`200`) uses `userId` (camel case):

```json
{"success": true, "access_token": "backend-jwt", "token_type": "bearer", "userId": "firebase-uid"}
```

### `POST /auth/reset-password`

```json
{"email": "ada@example.com"}
```

Success (`200`): `{"success": true, "message": "Password reset email sent"}`.

## User profile and deletion lifecycle

| Endpoint | Behavior |
|---|---|
| `GET /users/me` | Returns the authenticated user profile and aggregate scan metrics. |
| `PUT /users/me` | Updates only `display_name` and/or `skin_type`. |
| `DELETE /users/me` | Marks account `PENDING_DELETION` and sets a deletion time 30 days ahead. |

`GET /users/me` success (`200`) includes fields such as:

```json
{
  "user_id": "firebase-uid",
  "email": "ada@example.com",
  "first_name": "Ada",
  "last_name": "Lovelace",
  "date_of_birth": "2000-01-02",
  "status": "ACTIVE",
  "display_name": "Ada Lovelace",
  "skin_type": "Combination",
  "total_scans": 4,
  "latest_score": 88.2,
  "previous_score": 85.5,
  "best_score": 90.1,
  "average_score": 86.7,
  "delta": 2.7,
  "deletion_scheduled_at": null
}
```

`PUT /users/me` request example:

```json
{"display_name": "Ada", "skin_type": "Combination"}
```

`DELETE /users/me` success (`200`):

```json
{
  "success": true,
  "message": "Account scheduled for permanent deletion",
  "deletion_scheduled_at": "2026-08-28T12:00:00+00:00"
}
```

Logging in through email, Google, or Apple before that timestamp restores the
profile to `ACTIVE` and removes the deletion timestamp. The scheduled cleanup
job permanently removes the Firebase account plus that user's S3 uploads,
analyses, sessions, image metadata, analytics events, audit records, and user
record once the window elapses. An administrator's delete action is immediate.

## Scan session and direct S3 uploads

The backend, not the client, creates the scan session ID. The client retains it
through upload and analysis. A session begins `OPEN`, has a 24-hour DynamoDB
TTL, and becomes `LOCKED` after successful analysis.

| Endpoint | Behavior |
|---|---|
| `POST /sessions` | Creates an owned `OPEN` session. |
| `POST /sessions/{session_id}/uploads` | Returns all three S3 presigned **POST** forms. |
| `POST /sessions/{session_id}/uploads/{view}` | Returns a replacement POST form for one failed/expired view. |
| `POST /sessions/{session_id}/validate` | Checks one uploaded view and runs image-quality validation. |

### `POST /sessions`

Success (`200`):

```json
{"session_id": "opaque-session-id", "status": "OPEN"}
```

### `POST /sessions/{session_id}/uploads`

```json
{
  "content_type": "image/jpeg",
  "files": {
    "front": "camera-file-name.jpg",
    "left": "camera-file-name.jpeg",
    "right": "camera-file-name.jpg"
  }
}
```

The `files` map must contain exactly `front`, `left`, and `right`; local
filenames are not used as S3 names. Success (`200`):

```json
{
  "session_id": "opaque-session-id",
  "status": "OPEN",
  "urls": {
    "front": {"url": "https://...", "fields": {"key": "...", "Content-Type": "image/jpeg"}},
    "left": {"url": "https://...", "fields": {"key": "...", "Content-Type": "image/jpeg"}},
    "right": {"url": "https://...", "fields": {"key": "...", "Content-Type": "image/jpeg"}}
  }
}
```

Each view contains a URL and form fields. Upload the image with a multipart HTTP
`POST`: append every returned field, then append the file as `file` with content
type `image/jpeg`. The maximum size is 50 MB per image. S3 enforces the signed
content type and size policy before storing the object; backend validation then
verifies the resulting object before analysis.

### `POST /sessions/{session_id}/uploads/{view}`

`view` is one of `front`, `left`, `right`. No request body. Use this after only
one network failure or URL expiry; the other URLs remain valid.

Success (`200`):

```json
{
  "session_id": "opaque-session-id",
  "view": "right",
  "upload_url": "https://...",
  "upload_fields": {"key": "...", "Content-Type": "image/jpeg"},
  "expires_in": 900
}
```

### `POST /sessions/{session_id}/validate`

```json
{"view": "front"}
```

This can be called after the specific S3 upload to give the client early
quality feedback. It rejects missing (`404`), non-JPEG (`415`), and oversized
(`413`) objects before image-quality validation. A normal success response is
the image validator result, for example:

```json
{"success": true, "valid": true, "errors": []}
```

If the image validator cannot process the image, the API returns `200` with
`{"success": false, "valid": false, "errors": ["Image validation failed"]}`.

## Analysis and history

| Endpoint | Behavior |
|---|---|
| `POST /analysis/{session_id}` | Validates all three uploads, runs vision scoring and synchronous NIM feedback, saves result, locks session. |
| `GET /analysis?limit=25` | Returns up to 25 analyses for the caller. Chronological ordering is not guaranteed until the time index is added. |
| `GET /analysis/{analysis_id}` | Returns one owned analysis. |
| `GET /analysis/session/{session_id}` | Returns all caller-owned analyses for a session. |
| `GET /history/trends` | Returns lifetime score aggregates and deltas between the latest two scans. |

### `POST /analysis/{session_id}`

Request body is currently optional:

```json
{"analysis_types": ["skin", "makeup"]}
```

`analysis_types` is accepted for forward compatibility but is not currently
used to vary processing; clients should not rely on it to select partial
analysis. The request is synchronous: it returns after vision scoring, NIM
feedback/fallback, persistence, and session locking.

Success (`201`) returns an `AnalysisResult`:

```json
{
  "analysis_id": "analysis-id",
  "user_id": "firebase-uid",
  "session_id": "opaque-session-id",
  "status": "completed",
  "skin_metrics": [{"name": "metric", "score": 88.0, "note": "optional"}],
  "category_scores": {
    "foundation_score": 88.0,
    "blend_score": 88.0,
    "contour_score": 88.0,
    "eyes_score": 88.0,
    "lips_score": 88.0,
    "symmetry_score": 88.0,
    "base_finish_score": 88.0,
    "color_balance_score": 88.0,
    "overall_score": 88.0
  },
  "ai_feedback": {
    "glam_type": "soft_glam",
    "strengths": ["..."],
    "improvements": ["..."],
    "recommendations": ["..."]
  },
  "confidence_score": 95.0,
  "makeup_suggestions": [],
  "early_detection_flags": [],
  "skin_age_estimate": null,
  "disclaimer": null,
  "created_at": "2026-07-29T12:00:00+00:00"
}
```

NIM receives score data and short-lived, read-only image URLs. If NIM is
unavailable or returns invalid JSON, the API returns a validated fallback
feedback object instead of failing the analysis.

`GET /analysis` supports `limit` only. It returns a JSON array of the same
`AnalysisResult` shape. Cursor/time-index pagination is **not implemented**
yet; the current random `analysis_id` sort key cannot guarantee chronological
history. A `user_id + created_at` index and cursor contract require CTO/DevOps
agreement before implementation.

`GET /history/trends` success (`200`):

```json
{
  "averageScore": 86.7,
  "bestScore": 90.1,
  "previousScore": 85.5,
  "latestScore": 88.2,
  "improvement": 2.7,
  "categories": {
    "foundation": 2.0, "blend": 1.5, "contour": 0.0, "eyes": 0.0,
    "lips": 0.0, "symmetry": 0.0, "baseFinish": 0.0, "colorBalance": 0.0
  }
}
```

## Analytics

`POST /analytics/event` requires authentication and queues persistence in the
background. Request:

```json
{"eventName": "scan_started", "metadata": {"source": "camera"}}
```

The API appends the caller IP (from `X-Forwarded-For` when supplied) to the
stored metadata. Success (`200`): `{"success": true}`.

## Administration and RBAC

Roles are `SUPER_ADMIN`, `ADMIN`, and `ANALYST`. Analysts are read-only;
administrators and super-administrators may moderate/delete; super-admin is
required for team management.

| Endpoint | Minimum role | Behavior |
|---|---|---|
| `POST /admin/admin-login` | Firebase admin identity | Returns backend token after admin-table lookup. |
| `POST /admin/dev-login` | Non-production, registered admin | Returns development admin token. |
| `GET /admin/metrics` | Analyst | Platform aggregate metrics. |
| `GET /admin/users` | Analyst | Lightweight user list. |
| `GET /admin/users/{user_id}` | Analyst | User scan summary. |
| `GET /admin/images` | Analyst | Uploaded-image moderation metadata. |
| `DELETE /admin/user/{user_id}` | Admin | Immediately removes Firebase identity and user application data. |
| `DELETE /admin/image/{image_id}` | Admin | Deletes the S3 object and its image-metadata record. |
| `GET /admin/team` | Super-admin | Lists admins and analysts; logs audit event. |
| `POST /admin/invite` | Super-admin | Creates Firebase admin account and reset link. |
| `DELETE /admin/access/{admin_id}` | Super-admin | Removes admin-table access; cannot revoke self. |

`POST /admin/admin-login` request: `{"id_token": "firebase-id-token"}`.
`POST /admin/invite` request: `{"email": "person@example.com", "role": "ANALYST"}`.

## Current automated test coverage

`pytest` currently has 29 passing API-level tests. External services are
mocked deliberately, so these tests verify application behavior without cloud
credentials. Covered paths include:

- Authentication, registration date-of-birth handling, and reactivation during
  the deletion grace period.
- User profile access/update and user-scheduled versus admin-immediate deletion.
- Session creation; three-URL batch upload; one-view retry; session ownership;
  invalid image media type; validation missing-session behavior.
- Analysis missing-session, successful processing, and a simulated `413`
  oversized-upload rejection; history and trends.
- Presigned POST policy generation for the JPEG and 50 MB constraints, plus
  multi-page pending-deletion cleanup.
- NIM fallback, analytics event processing, RBAC login/read/moderation/team
  endpoints.

The suite does **not** upload a real 50 MB file to S3 or test real Firebase,
DynamoDB, S3, NIM, mobile networking, IAM, or browser/device CORS. Those are
appropriate QA/DevOps staging responsibilities.

## Staging handoff requirements

The remaining work to make a staging environment is deployment and verification,
not new ordinary backend feature work:

1. **Infrastructure (DevOps):** provision the seven DynamoDB tables referenced
   in `.env.example`, S3 bucket, lifecycle rules, IAM roles/policies, compute
   and load-balancer/API routing, logs/metrics, and a scheduled invocation for
   pending-deletion cleanup. The current worker paginates every DynamoDB scan
   page; a suitable status/timestamp query remains the scale optimization.
2. **DynamoDB design decision (CTO/DevOps):** agree and provision the
   chronological analysis-history GSI before cursor/time-index pagination is
   built. Existing `GET /analysis?limit=` works without this enhancement.
3. **Secrets (DevOps):** configure Firebase Admin credentials and
   `FIREBASE_WEB_API_KEY`, backend JWT secret, and NIM credentials/model
   endpoint in the approved secret store; grant runtime read access only.
   Materialize the company Firebase Admin JSON at a protected runtime path and
   set `FIREBASE_ADMIN_CREDENTIALS_PATH` to it; the API intentionally fails
   startup when that credential file is absent.
4. **Private media (DevOps):** keep the uploads bucket private; allow direct
   presigned POST/short-lived GET use only; configure S3 CORS for the actual
   staging mobile/web origins; avoid public object access.
5. **Environment configuration (DevOps):** set `ENVIRONMENT=staging`,
   `DEBUG=false`, explicit `BACKEND_CORS_ORIGINS` (not `*`), staging resource
   names, and a staging `JWT_SECRET`.
6. **QA acceptance (QA):** use real service credentials and devices to execute
   the scan happy path, upload interruption/single-view retry, 50 MB boundary,
   wrong MIME type, invalid/corrupt JPEG, session ownership, account deletion
   and reactivation, NIM fallback, and administrator RBAC scenarios.
7. **Release review (CTO):** decide whether to retain both upload URL endpoints
   and whether to remove or implement `analysis_types`; approve retention,
   deletion, and image-access policies.
