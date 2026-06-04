#!/usr/bin/env bash
# EC2 bootstrap (cloud-init user_data) for the FaceByYou API.
# Installs Python, Nginx, the CloudWatch agent, pulls the repo, loads config from
# Secrets Manager, and starts the API under systemd. Idempotent-ish for re-runs.
set -euo pipefail

# These are templated by Terraform (see infra/terraform/ec2.tf).
ENVIRONMENT="${environment}"
AWS_REGION="${aws_region}"
SECRET_ARN="${secret_arn}"
REPO_URL="${repo_url}"
GIT_BRANCH="${git_branch}"

APP_DIR=/opt/facebyyou-api

dnf install -y python3.11 python3.11-pip git nginx amazon-cloudwatch-agent jq || \
  yum install -y python3 python3-pip git nginx amazon-cloudwatch-agent jq

id facebyyou &>/dev/null || useradd --system --create-home facebyyou

# --- Fetch application code ---
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --all && git -C "$APP_DIR" reset --hard "origin/$GIT_BRANCH"
else
  git clone --branch "$GIT_BRANCH" "$REPO_URL" "$APP_DIR"
fi

# --- Python environment ---
python3.11 -m venv "$APP_DIR/.venv" || python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# --- Configuration from Secrets Manager ---
# Secret is a JSON object of KEY=VALUE app settings; render it to .env.
aws secretsmanager get-secret-value --region "$AWS_REGION" --secret-id "$SECRET_ARN" \
  --query SecretString --output text \
  | jq -r 'to_entries[] | "\(.key)=\(.value)"' > "$APP_DIR/.env"
{
  echo "ENVIRONMENT=$ENVIRONMENT"
  echo "AWS_REGION=$AWS_REGION"
} >> "$APP_DIR/.env"
chown facebyyou:facebyyou "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"
chown -R facebyyou:facebyyou "$APP_DIR"

# --- Nginx reverse proxy ---
cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/conf.d/facebyyou-api.conf
rm -f /etc/nginx/conf.d/default.conf || true
systemctl enable --now nginx
systemctl reload nginx

# --- API service ---
cp "$APP_DIR/deploy/facebyyou-api.service" /etc/systemd/system/facebyyou-api.service
systemctl daemon-reload
systemctl enable --now facebyyou-api

# --- CloudWatch agent (ship journald + nginx logs) ---
systemctl enable --now amazon-cloudwatch-agent || true

echo "FaceByYou API bootstrap complete for environment=$ENVIRONMENT"
