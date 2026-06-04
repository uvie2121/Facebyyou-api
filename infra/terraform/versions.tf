terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # For team use, configure a remote backend (S3 + DynamoDB lock). Left local
  # for the initial MVP; uncomment and fill in once a state bucket exists.
  # backend "s3" {
  #   bucket         = "facebyyou-tfstate"
  #   key            = "facebyyou-api/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "facebyyou-tflock"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "FaceByYou"
      Component   = "backend-api"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}
