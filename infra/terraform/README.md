# FaceByYou infrastructure (Terraform)

Provisions the AWS DevOps foundation for one environment at a time.

## What it creates

| Resource                | File           | Purpose                                  |
|-------------------------|----------------|------------------------------------------|
| S3 bucket               | `s3.tf`        | Private, encrypted, versioned, lifecycle |
| DynamoDB tables         | `dynamodb.tf`  | `users`, `analyses` (on-demand)          |
| Secrets Manager secret  | `secrets.tf`   | App config + API keys                    |
| IAM role + profile      | `iam.tf`       | Least-privilege EC2 instance role        |
| EC2 + SG + log group    | `ec2.tf`       | API host, firewall, CloudWatch logs      |

## Usage

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # edit environment/region/key_name
terraform init
terraform plan
terraform apply
```

Per-environment state: use separate workspaces or `-var-file` per env, e.g.

```bash
terraform workspace new dev && terraform apply -var environment=dev
```

For team use, enable the S3 remote backend block in `versions.tf`.

## After apply

1. Set real secrets:
   ```bash
   aws secretsmanager put-secret-value \
     --secret-id "$(terraform output -raw app_secret_arn)" \
     --secret-string '{"JWT_SECRET":"<random>","OPENAI_API_KEY":"...","S3_UPLOAD_BUCKET":"<bucket>"}'
   ```
2. Hit the API: `curl http://$(terraform output -raw api_public_ip)/api/v1/health`

## Security defaults

- S3 public access fully blocked; SSE-AES256; lifecycle expiration on raw uploads.
- IMDSv2 required on EC2; encrypted root volume.
- IAM scoped to the specific buckets/tables/secret (no wildcards on data).
- Restrict `ssh_ingress_cidr` to your IP/VPN before production.
