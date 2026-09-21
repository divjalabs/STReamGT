# All defaults are the resources already provisioned by hand (docs/aws-setup.md phases 0-8).
# Override in terraform.tfvars if any differ.

variable "region" { default = "eu-central-1" }
variable "account_id" { default = "236726878099" }
variable "project" { default = "streamgt" }

variable "data_bucket" { default = "streamgt-data-236726878099" }
variable "site_bucket" { default = "streamgt-site-236726878099" }

variable "vpc_id" { default = "vpc-0e9d86429fe9e16ef" }
variable "subnets" {
  type    = list(string)
  default = ["subnet-00ce16d02d55fab80", "subnet-0979fb2e7f3916aea", "subnet-028380a3442c47845"]
}

# Security group of the per-job head task (public subnet, egress only).
variable "head_sg" { default = "sg-0a952b15762b85860" }
variable "batch_sg" { default = "sg-0558e28375c4f2748" }

variable "exec_role_name" { default = "streamgt-exec" }
variable "head_role_name" { default = "streamgt-head" }

variable "backend_image" { default = "236726878099.dkr.ecr.eu-central-1.amazonaws.com/streamgt-backend:latest" }
# Lambda API image (deploy/Dockerfile.lambda, arm64). Only used when the function is created.
variable "api_lambda_image" { default = "236726878099.dkr.ecr.eu-central-1.amazonaws.com/streamgt-backend:api-lambda" }
variable "obitools_image" { default = "236726878099.dkr.ecr.eu-central-1.amazonaws.com/streamgt-obitools:latest" }


variable "batch_queue" { default = "streamgt-queue" }
variable "email_from" { default = "elena.pazhenkova@divjalabs.com" }

# API Lambda memory (MB; CPU scales with it) and head task size (per-job, ephemeral).
variable "api_lambda_memory" { default = 1024 }
# The head task runs the WHOLE pipeline in one Fargate task (local_fargate profile), so it's large.
variable "head_cpu" { default = "8192" }
variable "head_memory" { default = "32768" }   # obiuniq per-locus dereplication is memory-heavy
variable "head_ephemeral_gb" { default = 200 } # Nextflow work dir + obiuniq /tmp dereplication chunks

# The app's public URL (links in emails, CORS). Fixed: it's the existing CloudFront domain.
variable "frontend_base_url" { default = "https://d2qy3qqpz2ebmu.cloudfront.net" }
