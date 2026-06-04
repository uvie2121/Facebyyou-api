variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment: dev | staging | production."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "environment must be one of: dev, staging, production."
  }
}

variable "name_prefix" {
  description = "Prefix for all resource names."
  type        = string
  default     = "facebyyou"
}

variable "repo_url" {
  description = "Git URL the EC2 instance clones the app from."
  type        = string
  default     = "https://github.com/uvie2121/Facebyyou-api.git"
}

variable "git_branch" {
  description = "Branch the EC2 instance deploys."
  type        = string
  default     = "main"
}

variable "instance_type" {
  description = "EC2 instance type for the API server."
  type        = string
  default     = "t3.small"
}

variable "key_name" {
  description = "Existing EC2 key pair name for SSH access (optional)."
  type        = string
  default     = null
}

variable "ssh_ingress_cidr" {
  description = "CIDR allowed to SSH (lock down to your IP/VPN)."
  type        = string
  default     = "0.0.0.0/0"
}

variable "upload_expiration_days" {
  description = "Days after which uploaded media is expired by S3 lifecycle."
  type        = number
  default     = 30
}
