# ---------- weekly database backup ----------
# scripts/backup.sh has always worked; it was just never run unless somebody remembered. The
# September dumps had already expired from S3 before anyone went looking for them.
#
# This runs the same `python -m app.dbbackup` on a schedule. The local off-site copy stays manual
# — nothing in AWS can pull files onto a laptop — so scripts/backup.sh keeps its job.

# A family of its own, rather than a command override on streamgt-head. The override would be
# passed as free-form JSON that AWS accepts without checking against the ECS API, so a wrong key
# name would run the head image's DEFAULT command (a job runner with no job id), do nothing, and
# exit 0 — a backup that reports success while backing nothing up. Nothing to override here.
# It also means the schedule's permissions cannot start a genotyping run.
resource "aws_ecs_task_definition" "dbbackup" {
  family                   = "${var.project}-dbbackup"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024" # a pg_dump, not a pipeline: head's 8 vCPU / 32 GB is absurd here
  memory                   = "2048" # holds the dump in memory twice (capture, then gzip) — revisit as the DB grows
  execution_role_arn       = data.aws_iam_role.exec.arn
  task_role_arn            = data.aws_iam_role.head.arn # already allowed to write backups/db/

  container_definitions = jsonencode([{
    name      = "head" # same container name as the head family, so one log/event shape fits both
    image     = var.backend_image
    essential = true
    command   = ["python", "-m", "app.dbbackup"]
    environment = [for k, v in merge(local.common_env, {
      AWS_REGION = var.region
    }) : { name = k, value = v }]
    secrets = local.head_secrets # DATABASE_URL + the rest, from Parameter Store
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.head.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "dbbackup" # shares the pipeline's log group, own stream prefix
      }
    }
  }])
}

resource "aws_iam_role" "scheduler_backup" {
  name = "${var.project}-scheduler-backup"

  # No Condition keys, deliberately, and this matches AWS's own documented policy for a Scheduler
  # execution role. Adding aws:SourceAccount / aws:SourceArn — the usual confused-deputy guard —
  # makes CreateSchedule fail with "the execution role you provide must allow AWS EventBridge
  # Scheduler to assume the role", because that check runs before the schedule exists and without
  # those context keys. Tried both the exact schedule ARN and a wildcard; both are rejected.
  #
  # What limits the blast radius instead is the policy below: this role can start exactly one task
  # definition family in one cluster, and can pass exactly two roles, only to ECS.
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_backup" {
  name = "run-dbbackup-task"
  role = aws_iam_role.scheduler_backup.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "RunTheBackupTaskOnly"
        Effect = "Allow"
        Action = ["ecs:RunTask"]
        # Revision-less + ":*" so every future revision stays covered; pinning the revision here
        # would break the schedule the moment the task definition changed.
        Resource  = ["${aws_ecs_task_definition.dbbackup.arn_without_revision}:*"]
        Condition = { ArnEquals = { "ecs:cluster" = aws_ecs_cluster.main.arn } }
      },
      {
        Sid      = "PassTheTaskAndExecutionRoles"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = [data.aws_iam_role.exec.arn, data.aws_iam_role.head.arn]
        # Scoped to ECS: this role cannot hand those roles to Lambda or EC2.
        Condition = { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } }
      },
    ]
  })
}

resource "aws_scheduler_schedule" "db_backup" {
  name       = "${var.project}-db-backup"
  group_name = "default"
  state      = "ENABLED"

  # Sunday 03:15 local. Deliberately not 02:xx: on the two Sundays a year when the clocks change,
  # that hour either does not exist or happens twice.
  schedule_expression          = "cron(15 3 ? * SUN *)"
  schedule_expression_timezone = "Europe/Ljubljana"

  flexible_time_window {
    mode                      = "FLEXIBLE"
    maximum_window_in_minutes = 30 # jitter costs nothing and avoids the top-of-hour crowd
  }

  target {
    arn      = aws_ecs_cluster.main.arn # the cluster, not the task definition
    role_arn = aws_iam_role.scheduler_backup.arn

    # The default is 185 attempts over 24 hours. Retries only apply when the RunTask call itself
    # fails (capacity, throttling) — a failing pg_dump is a *successful* invocation and is never
    # retried, so a long tail buys nothing.
    retry_policy {
      maximum_retry_attempts       = 5
      maximum_event_age_in_seconds = 3600
    }

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.dbbackup.arn_without_revision
      launch_type         = "FARGATE"
      task_count          = 1
      platform_version    = "1.4.0"
      # Labels the task so a failed backup can be told apart from a failed genotyping run; see
      # the db_backup_failed rule in monitoring.tf.
      group = "scheduled-backup"

      network_configuration {
        subnets          = var.subnets
        security_groups  = [var.head_sg]
        assign_public_ip = true # public subnets, no NAT — a bool here, unlike the CLI's "ENABLED"
      }
    }
  }
}

# ---------- bucket lifecycle ----------
# Imported, not created:
#   terraform import aws_s3_bucket_lifecycle_configuration.data streamgt-data-236726878099
#
# All four hand-made rules are restated because this resource is a whole-bucket replacement: a
# partial one would silently DELETE the rules it omits, and work/ never expiring would quietly
# grow the bill.
resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = var.data_bucket

  # Matches the bucket's current setting; omitting it would change it.
  transition_default_minimum_object_size = "all_storage_classes_128K"

  rule {
    id     = "expire-uploads"
    status = "Enabled"
    filter { prefix = "uploads/" }
    expiration { days = 14 }
  }

  rule {
    id     = "expire-db-backups"
    status = "Enabled"
    filter { prefix = "backups/db/" }
    # 180 days: a weekly dump needs half a year of Sundays, not four. At ~450 KB each that is a
    # few MB. The old 30 days is why September's backups were already gone in October.
    expiration { days = 180 }
  }

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter { prefix = "" } # the API stores an empty prefix here; `filter {}` would churn the plan
    noncurrent_version_expiration { noncurrent_days = 30 }
  }

  rule {
    id     = "expire-work"
    status = "Enabled"
    filter { prefix = "work/" }
    expiration { days = 7 }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}
