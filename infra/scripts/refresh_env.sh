#!/usr/bin/env bash
# Re-render /opt/facebyyou-api/.env from Secrets Manager and restart the API.
# Run on the EC2 host (via SSM). Mirrors the logic in deploy/user_data.sh so a
# secret change can be applied without re-bootstrapping the instance.
set -euo pipefail

SECRET_ARN="arn:aws:secretsmanager:us-east-1:708761843741:secret:facebyyou-dev-app-config-6GWtQ1"
APP_DIR=/opt/facebyyou-api

cd "$APP_DIR"
aws secretsmanager get-secret-value --region us-east-1 --secret-id "$SECRET_ARN" \
  --query SecretString --output text \
  | jq -r 'to_entries[] | "\(.key)=\(.value)"' > "$APP_DIR/.env"
{
  echo "ENVIRONMENT=dev"
  echo "AWS_REGION=us-east-1"
} >> "$APP_DIR/.env"
chown facebyyou:facebyyou "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"

systemctl restart facebyyou-api
sleep 4
curl -fsS http://127.0.0.1:8000/api/v1/health
echo
echo "ENV_KEYS=$(cut -d= -f1 "$APP_DIR/.env" | tr '\n' ',')"
