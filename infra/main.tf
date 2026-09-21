terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
}

locals {
  head_task_family = "${var.project}-head"
  nxf_work         = "s3://${var.data_bucket}/work"

  # Secrets live in SSM Parameter Store (SecureString, free standard tier) under /<project>/,
  # created by hand (see README) so their values never enter Terraform state. The parameter name
  # is the env var name: /streamgt/SECRET_KEY -> SECRET_KEY.
  ssm_path           = "/${var.project}"
  ssm_arn_prefix     = "arn:aws:ssm:${var.region}:${var.account_id}:parameter${local.ssm_path}"
  secret_param_names = ["SECRET_KEY", "DATABASE_URL", "SMTP_USER", "SMTP_PASSWORD"]

  # Env shared by the API (Lambda) and the head task. DATABASE_URL (Neon) comes from SSM.
  common_env = {
    ENVIRONMENT       = "production"
    S3_BUCKET         = var.data_bucket
    S3_REGION         = var.region
    DB_NULL_POOL      = "true" # never hold idle connections: lets Neon scale to zero
    EMAIL_FROM        = var.email_from
    SMTP_HOST         = "email-smtp.${var.region}.amazonaws.com"
    SMTP_PORT         = "587"
    SMTP_USE_TLS      = "true"
    FRONTEND_BASE_URL = var.frontend_base_url # a var: CloudFront -> Lambda URL -> env would cycle
  }

  head_secrets = [for n in local.secret_param_names : { name = n, valueFrom = "${local.ssm_arn_prefix}/${n}" }]
}

# ---------- data: existing resources ----------
data "aws_iam_role" "exec" { name = var.exec_role_name }
data "aws_iam_role" "head" { name = var.head_role_name }
data "aws_s3_bucket" "site" { bucket = var.site_bucket }

# The (hand-made) ECS execution role injects the head task's secrets from SSM.
resource "aws_iam_role_policy" "exec_ssm" {
  name = "ssm-params"
  role = data.aws_iam_role.exec.name
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["ssm:GetParameters"], Resource = "${local.ssm_arn_prefix}/*" }]
  })
}

# ---------- logs ----------
resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${var.project}-api"
  retention_in_days = 30
}
resource "aws_cloudwatch_log_group" "head" {
  name              = "/ecs/${var.project}-head"
  retention_in_days = 30
}

# ---------- ECS cluster ----------
resource "aws_ecs_cluster" "main" {
  name = var.project
}

# ---------- task definition: head (one-off per job, launched by the API) ----------
resource "aws_ecs_task_definition" "head" {
  family                   = local.head_task_family
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.head_cpu
  memory                   = var.head_memory
  execution_role_arn       = data.aws_iam_role.exec.arn
  task_role_arn            = data.aws_iam_role.head.arn
  ephemeral_storage { size_in_gib = var.head_ephemeral_gb }

  container_definitions = jsonencode([{
    name      = "head" # matches dispatch.HEAD_CONTAINER_NAME
    image     = var.backend_image
    essential = true
    command   = ["python", "-m", "app.worker.run_job"] # JOB_ID appended by RunTask override
    # local_fargate: the head task runs the whole pipeline itself (Nextflow local executor,
    # OBITools baked into the image). The awsbatch-only vars (NXF_BATCH_QUEUE/OBITOOLS_IMAGE/
    # NXF_WORK) are intentionally absent — tasks.py only reads them when profile == awsbatch.
    environment = [for k, v in merge(local.common_env, {
      AWS_REGION       = var.region
      NEXTFLOW_PROFILE = "local_fargate"
      PIPELINE_DIR     = "/app/pipeline"
      JOB_SCRATCH_ROOT = "/scratch"
    }) : { name = k, value = v }]
    secrets = local.head_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.head.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "head"
      }
    }
  }])
}

# ---------- API: Lambda (container image + Lambda Web Adapter) behind a function URL ----------
# Pay-per-request: no always-on compute, no load balancer, no public IPv4. Runs outside the VPC,
# so it reaches Neon, ECS RunTask and SES SMTP over the internet with no NAT/endpoints.
resource "aws_iam_role" "lambda_api" {
  name = "${var.project}-lambda-api"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_api_logs" {
  role       = aws_iam_role.lambda_api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_api" {
  name = "api"
  role = aws_iam_role.lambda_api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { # presigned FASTQ uploads + result downloads
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"]
        Resource = "arn:aws:s3:::${var.data_bucket}/*"
      },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = "arn:aws:s3:::${var.data_bucket}" },
      { # launch the per-job head task
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [data.aws_iam_role.head.arn, data.aws_iam_role.exec.arn]
      },
      { # secrets, loaded at cold start (app.config._load_ssm_parameters)
        Effect   = "Allow"
        Action   = ["ssm:GetParametersByPath"]
        Resource = [local.ssm_arn_prefix, "${local.ssm_arn_prefix}/*"]
      },
    ]
  })
}

resource "aws_lambda_function" "api" {
  function_name = "${var.project}-api"
  role          = aws_iam_role.lambda_api.arn
  package_type  = "Image"
  image_uri     = var.api_lambda_image
  architectures = ["arm64"]
  memory_size   = var.api_lambda_memory
  timeout       = 60

  environment {
    variables = merge(local.common_env, {
      SSM_PARAMETER_PATH = "${local.ssm_path}/"
      RUN_MODE           = "ecs"
      ECS_CLUSTER        = aws_ecs_cluster.main.name
      HEAD_TASK_DEF      = local.head_task_family
      ECS_SUBNETS        = join(",", var.subnets)
      ECS_SECURITY_GROUP = var.head_sg
    })
  }

  depends_on = [aws_cloudwatch_log_group.api, aws_iam_role_policy_attachment.lambda_api_logs]

  # New images roll out with `aws lambda update-function-code` (see README), not Terraform.
  lifecycle { ignore_changes = [image_uri] }
}

# Public URL; CloudFront is the only intended caller (the app does its own JWT auth).
resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  authorization_type = "NONE"
}

# AWS also requires lambda:InvokeFunction (condition lambda:InvokedViaFunctionUrl=true) for public
# URLs. The pinned provider (5.x) can't express that condition, so it was added by hand (README):
#   aws lambda add-permission --function-name streamgt-api --statement-id \
#     FunctionURLInvokeAllowPublicAccess --action lambda:InvokeFunction --principal '*' \
#     --invoked-via-function-url
resource "aws_lambda_permission" "api_url" {
  statement_id           = "FunctionURLAllowPublicAccess"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.api.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

# ---------- CloudFront (SPA + /api/* -> Lambda function URL), no custom domain ----------
resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${var.project}-site-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "app" {
  enabled             = true
  default_root_object = "index.html"

  origin {
    origin_id                = "s3-site"
    domain_name              = data.aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }
  origin {
    origin_id   = "lambda-api"
    domain_name = split("/", aws_lambda_function_url.api.function_url)[2] # https://<id>.lambda-url...on.aws/
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id       = "s3-site"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
  }

  ordered_cache_behavior {
    path_pattern             = "/api/*"
    target_origin_id         = "lambda-api"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # Managed-CachingDisabled
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # Managed-AllViewerExceptHostHeader (function URLs need their own Host)
  }

  # SPA routing: send 403/404 to index.html
  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }
  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate {
    cloudfront_default_certificate = true # free *.cloudfront.net cert
  }
}

# Let CloudFront (via OAC) read the private site bucket.
resource "aws_s3_bucket_policy" "site" {
  bucket = data.aws_s3_bucket.site.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${data.aws_s3_bucket.site.arn}/*"
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.app.arn } }
    }]
  })
}
