# Deployment runbook

Two supported paths to run the API on AWS EC2.

## A. Terraform-managed EC2 (recommended for MVP)

`terraform apply` (see `infra/terraform/`) launches an EC2 instance whose
`user_data` runs [`user_data.sh`](user_data.sh). That script:

1. Installs Python 3.11, Nginx, the CloudWatch agent.
2. Clones the repo at the environment branch.
3. Pulls app settings from **Secrets Manager** into `/opt/facebyyou-api/.env`.
4. Starts Uvicorn via the [`systemd` unit](facebyyou-api.service) behind
   [Nginx](nginx.conf).

To ship new code on an existing box, GitHub Actions (`deploy.yml`) SSHes in and
runs `git pull && pip install -r requirements.txt && systemctl restart
facebyyou-api`.

## B. Docker on EC2

If you prefer containers, install Docker on the instance and run the published
image (or `docker compose up -d`). The IAM instance role still supplies AWS
credentials to the container automatically.

## Files

| File                      | Purpose                                  |
|---------------------------|------------------------------------------|
| `user_data.sh`            | EC2 cloud-init bootstrap (templated by TF)|
| `facebyyou-api.service`   | systemd unit running Uvicorn             |
| `nginx.conf`              | reverse proxy + body-size cap            |

## Health check

`GET /api/v1/health` → `200 {"status":"ok",...}`. Used by Nginx, the EC2/ELB
health check, and CI smoke tests.
