output "api_public_ip" {
  description = "Public IP of the API EC2 instance."
  value       = aws_instance.api.public_ip
}

output "api_public_dns" {
  description = "Public DNS of the API EC2 instance."
  value       = aws_instance.api.public_dns
}

output "uploads_bucket" {
  description = "S3 bucket for user uploads."
  value       = aws_s3_bucket.uploads.bucket
}

output "users_table" {
  value = aws_dynamodb_table.users.name
}

output "analyses_table" {
  value = aws_dynamodb_table.analyses.name
}

output "app_secret_arn" {
  description = "Secrets Manager ARN holding app config / API keys."
  value       = aws_secretsmanager_secret.app.arn
}

output "log_group" {
  value = aws_cloudwatch_log_group.api.name
}
