# FaceByYou API

AI-powered skin analysis and virtual-makeup backend for **FaceByYou**.
This repository contains the **FastAPI backend** and the **infrastructure/DevOps foundation** to deploy it to AWS on an **EC2** instance.

> **Scope:** Backend + Infra. The mobile application (`mobile-app`) lives in a separate repository.  
> **API Specification:** See [API_CONTRACT.md](API_CONTRACT.md) for the full API contract, and [API_DOCUMENTATION.md](API_DOCUMENTATION.md) for the non-interactive API documentation.

---

## Architecture (MVP)

```text
 React Native app
        │  HTTPS (JWT bearer)
        ▼
 ┌──────────────────────┐        presigned POST
 │  EC2 (Nginx + Uvicorn│◀──────────────────────────┐
 │  FastAPI via systemd)│                            │
 └─────────┬────────────┘                            │
           │ boto3 (IAM instance role)               │
   ┌───────┼──────────────┬───────────────┐          │
   ▼       ▼              ▼               ▼          ▼
DynamoDB  S3 uploads   Secrets Mgr   CloudWatch   Mobile uploads
(users,   bucket       (API keys)    (logs)       go straight to S3
 analyses)
```

- **Compute**: EC2 running Uvicorn behind Nginx, managed by `systemd`.
- **Storage**: Private S3 bucket for face scan uploads. Clients upload directly via **presigned POST** so large images never transit the API server; size (max 50 MB) and content type (`image/jpeg`) are enforced by presigned policies.
- **Database**: Serverless DynamoDB tables (`users`, `analyses`, `sessions`, `admin_users`, `uploaded_images`, `analytics_events`, `audit_logs`).
- **Auth**: Firebase Auth & JWT Bearer tokens (with local `dev-login` for non-production environments).
- **Secrets**: AWS Secrets Manager & runtime configuration.
- **AI / Computer Vision**: MediaPipe face landmarker & NVIDIA NIM AI feedback.
- **Logging**: structured JSON to stdout → CloudWatch.
- **CI/CD**: GitHub Actions (lint + test on PR, deploy on push to env branches).

---

## Core Scan Workflow

```text
Authenticate (Bearer JWT)
  │
  ├──> POST /api/v1/sessions (Creates OPEN session)
  ├──> POST /api/v1/sessions/{session_id}/uploads (Returns presigned S3 POST forms for front, left, right)
  ├──> Multipart POST to S3 (Upload front.jpg, left.jpg, right.jpg directly to S3)
  ├──> POST /api/v1/sessions/{session_id}/uploads/{view} (Optional: refresh presigned URL for a single failed view)
  ├──> POST /api/v1/sessions/{session_id}/validate (Optional: early quality & landmark validation check)
  ├──> POST /api/v1/analysis/{session_id} (Triggers tri-angle analysis, computes scores & NIM feedback, locks session)
  └──> GET  /api/v1/history/trends (Retrieve lifetime trends & category improvement deltas)
```

Canonical S3 object key structure:
```text
uploads/{user_id}/{YYYY/MM/DD}/{session_id}/front.jpg
uploads/{user_id}/{YYYY/MM/DD}/{session_id}/left.jpg
uploads/{user_id}/{YYYY/MM/DD}/{session_id}/right.jpg
```

---

## Project Layout

```text
app/
  main.py, FastAPI app, middleware, lifecycle, error handling
  core/ Config, security (JWT/RBAC), logging
  models/ Schemas, Pydantic request & response models
  services/ AWS clients (S3, DynamoDB), face analysis, image validation, cleanup worker
  api/routes/ API route handlers: health, auth, users, sessions, uploads, analysis, history, analytics, admin
deploy/ Dockerfile, Nginx configs, systemd service, EC2 user_data
infra/terraform/ S3, DynamoDB, IAM, Secrets Manager, EC2, CloudWatch
docs/ Developer onboarding & infrastructure documentation
tests/ Offline test suite (Pytest with full service mocks)
API_CONTRACT.md Authoritative API contract specification
API_SPECIFICATION.md Non-interactive API documentation
```

---

## API Routes Overview (`/api/v1`)

### System & Health
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/health` | No | Liveness probe & health status |

### Authentication (`/auth`)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/auth/register` | No | Create user account (Firebase + DynamoDB profile) |
| POST | `/api/v1/auth/login` | No | Exchange Firebase ID token for backend JWT (reactivates pending deletion) |
| POST | `/api/v1/auth/google` | No | Firebase Google sign-in/up |
| POST | `/api/v1/auth/apple` | No | Firebase Apple sign-in/up |
| POST | `/api/v1/auth/reset-password` | No | Request password reset email |
| POST | `/api/v1/auth/dev-login` | Non-prod | Issue a dev access token |

### User Profile & Account (`/users`)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/users/me` | Bearer | Get current user profile and scan statistics |
| PUT | `/api/v1/users/me` | Bearer | Update `display_name` and/or `skin_type` |
| DELETE | `/api/v1/users/me` | Bearer | Schedule account deletion (30-day retention window) |

### Sessions & Uploads (`/sessions`)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/sessions` | Bearer | Create an `OPEN` scan session |
| POST | `/api/v1/sessions/{session_id}/uploads` | Bearer | Get 3 presigned S3 POST forms (`front`, `left`, `right`) |
| POST | `/api/v1/sessions/{session_id}/uploads/{view}` | Bearer | Refresh upload URL for single failed/expired view |
| POST | `/api/v1/sessions/{session_id}/validate` | Bearer | Validate single view upload before analysis |

### Analysis & History (`/analysis`, `/history`)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/analysis/{session_id}` | Bearer | Run tri-angle analysis, compute scores/NIM feedback, lock session |
| GET | `/api/v1/analysis` | Bearer | List user's analysis history |
| GET | `/api/v1/analysis/{analysis_id}` | Bearer | Fetch specific analysis result |
| GET | `/api/v1/analysis/session/{session_id}` | Bearer | Fetch analyses for a specific session |
| GET | `/api/v1/history/trends` | Bearer | Get aggregate stats & category improvement deltas |

### Analytics (`/analytics`)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/analytics/event` | Bearer | Track telemetry/event in background worker |

### Admin & RBAC (`/admin`)
| Method | Path | Min Role | Purpose |
|---|---|---|---|
| POST | `/api/v1/admin/admin-login` | Admin | Firebase-backed admin login |
| POST | `/api/v1/admin/dev-login` | Admin | Dev-only admin login |
| GET | `/api/v1/admin/metrics` | Analyst | Platform metrics overview |
| GET | `/api/v1/admin/users` | Analyst | List registered users |
| GET | `/api/v1/admin/users/{user_id}` | Analyst | Fetch user scan summary |
| GET | `/api/v1/admin/images` | Analyst | Image moderation queue |
| DELETE | `/api/v1/admin/user/{user_id}` | Admin | Immediately purge user account & data |
| DELETE | `/api/v1/admin/image/{image_id}` | Admin | Delete moderated image from S3 & DB |
| GET | `/api/v1/admin/team` | SuperAdmin | List admin team members |
| POST | `/api/v1/admin/invite` | SuperAdmin | Invite new admin/analyst |
| DELETE | `/api/v1/admin/access/{admin_id}` | SuperAdmin | Revoke admin privileges |

Interactive documentation is available locally at `/docs` (disabled in production).

---

## Local Development

```bash
# 1. Setup virtual environment
python -m venv .venv
# On Windows:
.\.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements-dev.txt

# 3. Environment configuration
cp .env.example .env

# 4. Start local server
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs` in your browser for Swagger UI.

### Dev Token Usage Example

```bash
# Obtain dev JWT token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/dev-login \
  -H "Content-Type: application/json" \
  -d '{"email":"me@facebyyou.ai"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# Use token to call protected endpoint
curl http://localhost:8000/api/v1/users/me -H "Authorization: Bearer $TOKEN"
```

---

## Testing with Docker 

```bash
docker compose up --build

# Run pytest test suite
pytest -q

# Code formatting & linting
ruff check .
```

---

## Infrastructure & Deployment (Terraform)

The `infra/terraform` directory provisions AWS infrastructure across environments (`dev`, `staging`, `prod`): S3 buckets with CORS and lifecycle policies, DynamoDB tables, IAM roles, Secrets Manager, EC2 instance with bootstrapped to run the API, and CloudWatch log groups.

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # set environment, region, key_name, etc.
terraform init
terraform plan
terraform apply
```

See [`infra/terraform/README.md`](infra/terraform/README.md) and [`deploy/README.md`](deploy/README.md) for detailed deployment runbooks.

---

## Environments & Branching

| Branch | Environment | Description |
|---|---|---|
| `dev` | Development | Active development & feature branches |
| `staging` | Staging | Pre-production validation |
| `main` | Production | Live production deployment |

---

## Security & Privacy Notes

Because users upload **face data**, the infrastructure enforces:
- Private S3 buckets with blocked public access and AES-256 server-side encryption.
- Direct-to-S3 presigned POST upload forms with short-lived expiration and key scope constraints.
- Least-privilege IAM roles and JWT bearer authentication.
- Scheduled 30-day retention cleanup for pending account deletions.
A privacy policy, terms, and image-usage disclosure are
required before launch (tracked outside this repo).
