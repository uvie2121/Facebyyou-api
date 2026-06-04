# Secrets Manager secret holding app config / API keys.
# The EC2 bootstrap reads this and renders it to /opt/facebyyou-api/.env.
# Seed only non-sensitive defaults here; real keys are set out-of-band
# (console/CLI) so they never enter Terraform state in plaintext.

resource "aws_secretsmanager_secret" "app" {
  name        = "${local.name}-app-config"
  description = "FaceByYou API runtime configuration and third-party API keys."
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id

  secret_string = jsonencode({
    JWT_SECRET              = "CHANGE_ME_ROTATE_VIA_CONSOLE"
    S3_UPLOAD_BUCKET        = local.uploads_bucket
    DYNAMODB_USERS_TABLE    = local.users_table
    DYNAMODB_ANALYSES_TABLE = local.analyses_table
    LOG_LEVEL               = "INFO"
  })

  # Allow operators to rotate/add keys in the console without Terraform reverting.
  lifecycle {
    ignore_changes = [secret_string]
  }
}
