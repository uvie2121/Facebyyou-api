# Shared locals and lookups. Resource definitions are split by concern into
# s3.tf, dynamodb.tf, iam.tf, secrets.tf, and ec2.tf for maintainability.

locals {
  name           = "${var.name_prefix}-${var.environment}"
  uploads_bucket = "${var.name_prefix}-uploads-${var.environment}"
  users_table    = "${var.name_prefix}-users-${var.environment}"
  analyses_table = "${var.name_prefix}-analyses-${var.environment}"
}

data "aws_caller_identity" "current" {}

# Latest Amazon Linux 2023 AMI for the API host.
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}
