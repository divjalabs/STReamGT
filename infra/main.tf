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

  # Env shared by both the API and head tasks.
  common_env = [
    { name = "ENVIRONMENT", value = "production" },
    { name = "S3_BUCKET", value = var.data_bucket },
    { name = "S3_REGION", value = var.region },
    { name = "AWS_REGION", value = var.region },
    { name = "DB_HOST", value = var.db_endpoint },
    { name = "DB_USER", value = var.db_user },
    { name = "DB_NAME", value = var.db_name },
    { name = "EMAIL_FROM", value = var.email_from },
    { name = "SMTP_HOST", value = "email-smtp.${var.region}.amazonaws.com" },
    { name = "SMTP_PORT", value = "587" },
    { name = "SMTP_USE_TLS", value = "true" },
    { name = "FRONTEND_BASE_URL", value = "https://${aws_cloudfront_distribution.app.domain_name}" },
  ]

  common_secrets = [
    { name = "SECRET_KEY", valueFrom = data.aws_secretsmanager_secret.app_secret.arn },
    { name = "DB_PASSWORD", valueFrom = data.aws_secretsmanager_secret.db_password.arn },
  ]
}

# ---------- data: existing resources ----------
data "aws_iam_role" "exec" { name = var.exec_role_name }
data "aws_iam_role" "api" { name = var.api_role_name }
data "aws_iam_role" "head" { name = var.head_role_name }
data "aws_secretsmanager_secret" "app_secret" { name = "${var.project}/app-secret-key" }
data "aws_secretsmanager_secret" "db_password" { name = "${var.project}/db-password" }
data "aws_s3_bucket" "site" { bucket = var.site_bucket }

# ---------- logs ----------
resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project}-api"
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

# ---------- task definition: API (always-on service) ----------
resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = data.aws_iam_role.exec.arn
  task_role_arn            = data.aws_iam_role.api.arn

  container_definitions = jsonencode([{
    name         = "api"
    image        = var.backend_image
    essential    = true
    command      = ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
    portMappings = [{ containerPort = 8000 }]
    environment = concat(local.common_env, [
      { name = "RUN_MODE", value = "ecs" },
      { name = "ECS_CLUSTER", value = aws_ecs_cluster.main.name },
      { name = "HEAD_TASK_DEF", value = local.head_task_family },
      { name = "ECS_SUBNETS", value = join(",", var.subnets) },
      { name = "ECS_SECURITY_GROUP", value = var.api_sg },
    ])
    secrets = local.common_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "api"
      }
    }
  }])
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
    environment = concat(local.common_env, [
      { name = "NEXTFLOW_PROFILE", value = "awsbatch" },
      { name = "NXF_BATCH_QUEUE", value = var.batch_queue },
      { name = "OBITOOLS_IMAGE", value = var.obitools_image },
      { name = "NXF_WORK", value = local.nxf_work },
      { name = "PIPELINE_DIR", value = "/app/pipeline" },
      { name = "JOB_SCRATCH_ROOT", value = "/scratch" },
    ])
    secrets = local.common_secrets
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

# ---------- ALB (HTTP origin behind CloudFront) ----------
resource "aws_lb" "api" {
  name               = "${var.project}-alb"
  load_balancer_type = "application"
  subnets            = var.subnets
  security_groups    = [var.alb_sg]
}

resource "aws_lb_target_group" "api" {
  name        = "${var.project}-api"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"
  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# ---------- ECS service (API) ----------
resource "aws_ecs_service" "api" {
  name            = "${var.project}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.subnets
    security_groups  = [var.api_sg]
    assign_public_ip = true
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
  depends_on = [aws_lb_listener.http]
}

# ---------- CloudFront (SPA + /api/* -> ALB), no custom domain ----------
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
    origin_id   = "alb-api"
    domain_name = aws_lb.api.dns_name
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
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
    target_origin_id         = "alb-api"
    viewer_protocol_policy    = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # Managed-CachingDisabled
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # Managed-AllViewerExceptHostHeader
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
