# EC2 API host: security group, CloudWatch log group, and the instance itself.

resource "aws_cloudwatch_log_group" "api" {
  name              = "/facebyyou/${var.environment}/api"
  retention_in_days = var.environment == "production" ? 90 : 14
}

resource "aws_security_group" "api" {
  name        = "${local.name}-api-sg"
  description = "FaceByYou API ingress/egress"

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_ingress_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "api" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  iam_instance_profile   = aws_iam_instance_profile.api.name
  vpc_security_group_ids = [aws_security_group.api.id]

  user_data = templatefile("${path.module}/../../deploy/user_data.sh", {
    environment = var.environment
    aws_region  = var.aws_region
    secret_arn  = aws_secretsmanager_secret.app.arn
    repo_url    = var.repo_url
    git_branch  = var.git_branch
  })

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  root_block_device {
    volume_size = 20
    encrypted   = true
  }

  tags = {
    Name = "${local.name}-api"
  }
}
