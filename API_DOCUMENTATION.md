# FaceByYou API documentation

This is the client integration guide for the FaceByYou API. For the complete
CTO/QA/DevOps specification, data-retention rules, and staging handoff, see
[API_CONTRACT.md](API_CONTRACT.md).

## Base URL and authorization

All paths are relative to `https://{api-host}/api/v1`. Protected requests use:

```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

Typical error body: `{"detail": "Human-readable explanation"}`.

## Main mobile scan flow

1. Sign in and obtain a backend access token.
2. `POST /sessions` to create a server-owned scan session.
3. `POST /sessions/{session_id}/uploads` to get three S3 upload forms.
4. Multipart POST front, left, and right JPEGs directly to S3.
5. Refresh only a failed/expired view's form when necessary.
6. Optionally validate each uploaded view.
7. `POST /analysis/{session_id}` and wait synchronously for the result.
8. Use analysis history and trends for the user dashboard.

The client maps each captured photo to `front`, `left`, or `right`. It does not
choose the stored filename; the backend assigns canonical S3 object names.

## Authentication

### Register

`POST /auth/register`

```json
{
  "firstName": "Ada",
  "lastName": "Lovelace",
  "dateOfBirth": "2000-01-02",
  "email": "ada@example.com",
  "password": "user-password"
}
```

Returns `200`: `{"success":true,"userId":"firebase-uid","message":"Account created successfully"}`.

### Login

The Firebase client signs the user in, obtains a Firebase ID token, then sends:

`POST /auth/login`

```json
{"id_token": "firebase-id-token"}
```

Returns `200`:

```json
{
  "success": true,
  "access_token": "backend-jwt",
  "token_type": "bearer",
  "user_id": "firebase-uid"
}
```

`POST /auth/google` and `POST /auth/apple` accept
`{"token":"firebase-id-token"}` and return the same token fields, except the
user key is `userId`. `POST /auth/reset-password` accepts
`{"email":"user@example.com"}`.

## Profile and account deletion

| Endpoint | Request | Result |
|---|---|---|
| `GET /users/me` | None | Current profile and aggregate scores. |
| `PUT /users/me` | `{"display_name":"Ada","skin_type":"Combination"}` | Updated profile. |
| `DELETE /users/me` | None | Schedules deletion 30 days ahead. |

Deleting an account changes it to `PENDING_DELETION`. A successful email,
Google, or Apple login inside the 30-day window restores it to `ACTIVE`.

## Sessions and S3 uploads

### Create a session

`POST /sessions` returns:

```json
{"session_id":"session-id","status":"OPEN"}
```

### Request all three upload forms

`POST /sessions/{session_id}/uploads`

```json
{
  "content_type": "image/jpeg",
  "files": {
    "front": "local-front.jpeg",
    "left": "local-left.jpg",
    "right": "local-right.jpg"
  }
}
```

The `files` keys must be exactly `front`, `left`, and `right`. Local filenames
may use `.jpg` or `.jpeg`; the values do not determine S3 filenames.

Returns:

```json
{
  "session_id": "session-id",
  "status": "OPEN",
  "urls": {
    "front": {"url":"https://bucket.s3...","fields":{"key":"...","Content-Type":"image/jpeg"}},
    "left": {"url":"https://bucket.s3...","fields":{"key":"...","Content-Type":"image/jpeg"}},
    "right": {"url":"https://bucket.s3...","fields":{"key":"...","Content-Type":"image/jpeg"}}
  }
}
```

### Upload a returned form

For each view, send a multipart HTTP `POST` to `urls[view].url`:

```text
append every key/value in urls[view].fields to the multipart form
append the image as a field named "file" with MIME type image/jpeg
POST the multipart form to urls[view].url
```

All returned fields are mandatory and must be sent unchanged. The S3 policy
rejects non-JPEG requests and objects above 50 MB before storage. A successful
S3 upload normally returns `204`.

### Refresh only one upload

`POST /sessions/{session_id}/uploads/{view}`, where `view` is `front`, `left`,
or `right`. It needs no body and returns:

```json
{
  "session_id":"session-id",
  "view":"right",
  "upload_url":"https://bucket.s3...",
  "upload_fields":{"key":"...","Content-Type":"image/jpeg"},
  "expires_in":900
}
```

Use the same multipart procedure with `upload_url` and `upload_fields`.

### Validate an uploaded view

`POST /sessions/{session_id}/validate`

```json
{"view":"front"}
```

The response includes `success`, `valid`, `errors`, and image metrics. Ask the
user to recapture when `valid` is false.

## Analysis and history

`POST /analysis/{session_id}` runs synchronously. Its body may be empty;
`analysis_types` is accepted but currently does not change processing:

```json
{"analysis_types":["skin","makeup"]}
```

It verifies all uploads, runs vision scoring and NIM feedback, saves the
analysis, updates aggregate score statistics, locks the session, and returns
`201` with an `AnalysisResult`. If NIM is unavailable, a validated fallback
feedback object is returned.

| Endpoint | Result |
|---|---|
| `GET /analysis?limit=25` | Up to `limit` owned analyses. Chronological ordering is not guaranteed until the planned created-time index is deployed. |
| `GET /analysis/{analysis_id}` | One owned analysis. |
| `GET /analysis/session/{session_id}` | Analyses for one owned session. |
| `GET /history/trends` | Overall and category score deltas. |

## Analytics and administration

`POST /analytics/event` accepts:

```json
{"eventName":"scan_started","metadata":{"source":"camera"}}
```

Administration routes are under `/admin`:

- `ANALYST`: platform metrics, user list/detail, and image metadata.
- `ADMIN`: analyst access plus immediate user/image deletion.
- `SUPER_ADMIN`: admin access plus team listing, invitations, and revocation.

See [API_CONTRACT.md](API_CONTRACT.md#administration-and-rbac) for the full
admin endpoint list and payloads.

## Client error handling

| Status | Meaning | Client action |
|---|---|---|
| `401` | Missing, expired, or invalid token | Refresh/sign in again. |
| `403` | Session/resource ownership failure or locked session | Do not retry blindly; begin a new session if needed. |
| `404` | Session, object, or analysis missing | Restart the affected flow. |
| `413` | Image exceeds 50 MB | Ask for a smaller image. |
| `415` | Not a JPEG request/object | Require a JPEG image. |
| `422` | Invalid body or view/files map | Correct client request construction. |
| `502` | Temporary S3/NIM preparation failure | Retry with normal backoff. |
