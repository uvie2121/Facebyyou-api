# CI/CD: GitHub Actions deploys to EC2 via SSM Run Command using short-lived
# OIDC credentials (no long-lived AWS keys stored in GitHub).

variable "github_repo" {
  description = "GitHub owner/repo allowed to assume the deploy role."
  type        = string
  default     = "uvie2121/Facebyyou-api"
}

# One OIDC provider per account. If you deploy multiple environments into the
# same account, set this to false in all but the first to avoid a duplicate.
variable "create_github_oidc_provider" {
  description = "Whether to create the account-wide GitHub OIDC provider."
  type        = bool
  default     = true
}

data "tls_certificate" "github" {
  count = var.create_github_oidc_provider ? 1 : 0
  url   = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github" {
  count           = var.create_github_oidc_provider ? 1 : 0
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github[0].certificates[0].sha1_fingerprint]
}

locals {
  github_oidc_provider_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only workflows from this repo may assume the role.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "${local.name}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
  depends_on         = [aws_iam_openid_connect_provider.github]
}

data "aws_iam_policy_document" "github_deploy" {
  # Run the deploy script on exactly this instance via the managed shell document.
  statement {
    sid     = "SsmSendCommand"
    actions = ["ssm:SendCommand"]
    resources = [
      aws_instance.api.arn,
      "arn:aws:ssm:${var.aws_region}::document/AWS-RunShellScript",
    ]
  }

  # Read back command status/output so the workflow can succeed/fail correctly.
  statement {
    sid = "SsmReadResults"
    actions = [
      "ssm:GetCommandInvocation",
      "ssm:ListCommandInvocations",
      "ssm:ListCommands",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "DescribeInstances"
    actions   = ["ec2:DescribeInstances"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "${local.name}-github-deploy-policy"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}
