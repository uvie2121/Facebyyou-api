# FaceByYou API

AI-powered skin analysis and virtual-makeup backend for the **FaceByYou** MVP.
This repo contains the **backend** (FastAPI) and the **infrastructure/DevOps
foundation** to deploy it to AWS on an **EC2** instance.

> Scope: backend + infra only. Mobile app (`mobile-app`) lives in a separate repo.

---

## Architecture (MVP)

```
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
- **Storage**: S3 for face images/videos. Clients upload via **presigned POST**
  so large media never transits the API server; size + content-type are enforced
  by the presigned policy and S3 lifecycle rules control cost.
- **Database**: DynamoDB (`users`, `analyses`) — serverless, cheap, scales with
  no ops. Repository functions isolate it so we can move to RDS later.
- **Auth**: JWT bearer tokens (AWS Cognito in prod; local `dev-login` for engineers).
- **Secrets**: AWS Secrets Manager — no keys in code. boto3 uses the EC2 IAM role.
- **Logging**: structured JSON to stdout → CloudWatch.
- **CI/CD**: GitHub Actions (lint + test on PR, deploy on push to env branches).

## Project layout

```
app/
  main.py              FastAPI app, middleware, error handling
  core/                config, JSON logging, JWT security
  models/schemas.py    Pydantic request/response models
  services/            aws clients, S3 storage, DynamoDB, face analysis
  api/routes/          health, auth, users, uploads, analysis
deploy/                Dockerfile assets, nginx, systemd unit, EC2 user_data
infra/terraform/       S3, DynamoDB, IAM, Secrets Manager, EC2, CloudWatch
.github/workflows/     ci.yml, deploy.yml
tests/                 offline smoke tests
```

## API surface (`/api/v1`)

| Method | Path                     | Purpose                                |
|--------|--------------------------|----------------------------------------|
| GET    | `/health`                | Liveness probe                         |
| POST   | `/auth/dev-login`        | Issue a dev JWT (non-prod only)        |
| GET    | `/users/me`              | Current user profile                   |
| PUT    | `/users/me`              | Create/update profile                  |
| POST   | `/uploads/presign`       | Presigned S3 POST for image/video      |
| POST   | `/analysis`              | Run face analysis on an uploaded object|
| GET    | `/analysis`              | List analysis history                  |
| GET    | `/analysis/{id}`         | Fetch one analysis result              |

Interactive docs at `/docs` (disabled in production).

---

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload
# open http://localhost:8000/docs
```

Get a dev token, then call protected routes:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/dev-login \
  -H 'content-type: application/json' \
  -d '{"email":"me@facebyyou.ai"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl localhost:8000/api/v1/users/me -H "Authorization: Bearer $TOKEN"
```

> Upload/analysis routes touch S3/DynamoDB; run against AWS (or local DynamoDB +
> moto) or rely on the offline test suite which mocks those calls.

## Run with Docker

```bash
docker compose up --build
```

## Tests & lint

```bash
pytest
ruff check .
```

---

## Infrastructure (Terraform)

The `infra/terraform` stack provisions one **environment** (dev/staging/prod) at a
time, covering the MVP DevOps checklist: S3 buckets (with size/lifecycle rules),
DynamoDB tables, an IAM instance role (least privilege), a Secrets Manager secret,
an EC2 instance bootstrapped to run the API, and CloudWatch log groups.

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # set environment, region, key_name, etc.
terraform init
terraform plan
terraform apply
```

See [`infra/terraform/README.md`](infra/terraform/README.md) and
[`deploy/README.md`](deploy/README.md) for details and the deployment runbook.

## Environments & branching

| Branch     | Environment | Notes                          |
|------------|-------------|--------------------------------|
| `dev`      | Dev         | active development             |
| `staging`  | Staging     | pre-production testing         |
| `main`     | Production  | real users; protected branch   |

## Security & privacy notes

Because users upload **face data**, the infra defaults to private S3 buckets
(public access blocked), server-side encryption, least-privilege IAM, and short
lived presigned URLs. A privacy policy, terms, and image-usage disclosure are
required before launch (tracked outside this repo).
