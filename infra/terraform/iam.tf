# Least-privilege IAM role for the EC2 instance. Grants only the specific S3,
# DynamoDB, Secrets Manager, and CloudWatch actions the API needs.

data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api" {
  name               = "${local.name}-api-role"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2.json
}

data "aws_iam_policy_document" "api" {
  statement {
    sid       = "S3Uploads"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.uploads.arn}/*"]
  }

  statement {
    sid       = "S3ListBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.uploads.arn]
  }

  statement {
    sid = "DynamoDBAccess"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Query",
      "dynamodb:BatchGetItem",
      "dynamodb:BatchWriteItem",
    ]
    resources = [
      aws_dynamodb_table.users.arn,
      aws_dynamodb_table.analyses.arn,
      "${aws_dynamodb_table.analyses.arn}/index/*",
    ]
  }

  statement {
    sid       = "ReadAppSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }

  statement {
    sid = "CloudWatchLogs"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/facebyyou/*"]
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "${local.name}-api-policy"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

# Allows the CloudWatch agent to ship metrics/logs.
resource "aws_iam_role_policy_attachment" "cw_agent" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

# Allows SSM Session Manager + Run Command (used by the CI/CD deploy pipeline,
# so we deploy without SSH keys or an open port 22).
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "api" {
  name = "${local.name}-api-profile"
  role = aws_iam_role.api.name
}
