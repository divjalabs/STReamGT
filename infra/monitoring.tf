# ---------- monitoring ----------
# Two faults ran in production for weeks before an audit found them: /api/jobs/parameters/defaults
# returned 500 on every call (parameters.json missing from the image), and every S3 call was
# rejected with InvalidAccessKeyId. Both logged loudly; nobody was reading the logs. Everything
# here exists to turn one of those into an email within minutes.
#
# Deliberately small: three signals, no dashboard, no uptime check. All inside the AWS always-free
# allowances, which matters when the whole stack idles at about $0.30/month.

resource "aws_sns_topic" "alerts" {
  name         = "${var.project}-alerts"
  display_name = "STReamGT alerts" # the sender name in the inbox — worth it for filtering
}

# Email rather than SMS or a webhook: nothing to rotate, and the first 1,000 deliveries a month are
# free. The address must confirm ONCE by hand, from the mail AWS sends on apply. Until that link is
# clicked, every alert is discarded without a trace — see the README for how to check.
resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# Attaching any policy REPLACES the default one, which is why the owner statement is restated here:
# without it, publishing from the console or CLI stops working. CloudWatch alarms would be covered
# by that owner statement anyway; EventBridge would NOT, and a rule missing this permission fails
# silently — no email, no error, only a FailedInvocations metric nobody is watching either.
resource "aws_sns_topic_policy" "alerts" {
  arn = aws_sns_topic.alerts.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "OwnerFullAccess"
        Effect    = "Allow"
        Principal = { AWS = "*" }
        Action = ["SNS:Publish", "SNS:Subscribe", "SNS:GetTopicAttributes",
          "SNS:SetTopicAttributes", "SNS:ListSubscriptionsByTopic", "SNS:DeleteTopic",
        "SNS:AddPermission", "SNS:RemovePermission"]
        Resource  = aws_sns_topic.alerts.arn
        Condition = { StringEquals = { "AWS:SourceOwner" = var.account_id } }
      },
      {
        Sid       = "AllowAwsServicePublish"
        Effect    = "Allow"
        Principal = { Service = ["events.amazonaws.com", "cloudwatch.amazonaws.com"] }
        Action    = "SNS:Publish"
        Resource  = aws_sns_topic.alerts.arn
        Condition = { StringEquals = { "AWS:SourceAccount" = var.account_id } }
      },
    ]
  })
}

# ---------- signal 1: an error reached a user ----------
# The one that would have caught both historical faults. It has to read the logs, because the
# Lambda error metric does not move: under the Lambda Web Adapter a FastAPI 500 is a *successful*
# invocation that returns a 500 body. Measured on the day job submission was broken: 204
# invocations, 0 errors.
resource "aws_cloudwatch_log_metric_filter" "api_unhandled" {
  name           = "${var.project}-api-unhandled-errors"
  log_group_name = aws_cloudwatch_log_group.api.name

  # "Exception in ASGI application" is uvicorn's wrapper around anything that escapes a route — the
  # missing parameters.json surfaced as exactly that. InvalidAccessKeyId is listed separately
  # because services/storage.py catches and logs some AWS errors without re-raising, so that
  # outage produced no ASGI exception on every path.
  # Deliberately NOT matching "Traceback": services/dispatch.py and job_health.py log benign races
  # that way, and an alarm that cries wolf gets ignored.
  pattern = "?\"Exception in ASGI application\" ?\"InvalidAccessKeyId\""

  metric_transformation {
    name      = "ApiUnhandledErrors"
    namespace = var.project
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "api_unhandled" {
  alarm_name  = "${var.project}-api-unhandled-errors"
  namespace   = var.project
  metric_name = aws_cloudwatch_log_metric_filter.api_unhandled.metric_transformation[0].name

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  # Sparse by design: no matching log line means no datapoint at all, and most of the day nobody is
  # using the app. Without this the alarm would sit in INSUFFICIENT_DATA for ever.
  treat_missing_data = "notBreaching"

  # A CloudWatch alarm email is raw JSON and cannot be reformatted, so this description is the only
  # prose in it. Written as a note to whoever reads the alert at 7am, not as a label.
  alarm_description = "An unhandled error reached a user of the STReamGT API — an HTTP 500, or an S3 call rejected for bad credentials. This is the alarm the October 2026 outages would have tripped. Look at: aws logs tail /aws/lambda/streamgt-api --since 30m"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# ---------- signal 2: the API function itself failed ----------
# Complements signal 1 rather than duplicating it: this is the only thing that catches a fault
# leaving no log line at all — a broken image rollout, the 60s timeout, out of memory, or a cold
# start that cannot read /streamgt/* from Parameter Store.
resource "aws_cloudwatch_metric_alarm" "api_lambda_errors" {
  alarm_name  = "${var.project}-api-lambda-errors"
  namespace   = "AWS/Lambda"
  metric_name = "Errors"
  dimensions  = { FunctionName = aws_lambda_function.api.function_name }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_description = "The streamgt-api Lambda failed to run at all: a crash before any response, the 60s timeout, out of memory, or a cold start that could not read its secrets. Note an HTTP 500 from the app does NOT appear here — that is streamgt-api-unhandled-errors. Look at: aws logs tail /aws/lambda/streamgt-api --since 30m"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# ---------- signal 3: the pipeline's infrastructure failed ----------
# Free: rules reacting to AWS's own service events are never billed.
#
# Scoped by cluster only. Matching the task definition family would be redundant (nothing else runs
# in this cluster) and useless anyway: scripts/backup.sh runs the database dump as a command
# override on the SAME streamgt-head family, so nothing in the event tells them apart. That is
# fine — a backup task killed by the platform deserves the same email.

resource "aws_cloudwatch_event_rule" "head_task_failed_to_start" {
  name        = "${var.project}-head-task-failed-to-start"
  description = "A genotyping task never ran at all (image pull, networking, secrets, capacity)."

  # lastStatus is not optional: ECS emits an event for PROVISIONING, PENDING, RUNNING and
  # DEPROVISIONING too, so without it every single job would send several emails.
  event_pattern = jsonencode({
    source        = ["aws.ecs"]
    "detail-type" = ["ECS Task State Change"]
    detail = {
      clusterArn = [aws_ecs_cluster.main.arn]
      lastStatus = ["STOPPED"]
      # An allow-list, not "anything but user-initiated": that would also match
      # EssentialContainerExited, i.e. every ordinary analysis failure, which already emails the
      # job's owner. Only TaskFailedToStart can happen today; the others are free insurance.
      stopCode = ["TaskFailedToStart", "SpotInterruption", "TerminationNotice"]
    }
  })
}

resource "aws_cloudwatch_event_rule" "head_task_killed" {
  name        = "${var.project}-head-task-killed"
  description = "A genotyping container was killed by the platform (out of memory), not by the pipeline."

  event_pattern = jsonencode({
    source        = ["aws.ecs"]
    "detail-type" = ["ECS Task State Change"]
    detail = {
      clusterArn = [aws_ecs_cluster.main.arn]
      lastStatus = ["STOPPED"]
      # stopCode MUST be pinned here. Pressing Stop also ends in exit code 137, because ECS sends
      # SIGTERM and kills the container 30s later — but a stop we requested always reports
      # UserInitiated, so this pairing is the only thing keeping the Stop button silent.
      stopCode = ["EssentialContainerExited"]
      # Matched against each element of the containers array. 137 = killed (Fargate's
      # out-of-memory kill), 139 = segfault. Exit code 1 is deliberately absent: run_job.py exits 1
      # for an ordinary analysis failure AND for a user-requested stop, so it distinguishes nothing.
      containers = { exitCode = [137, 139] }
    }
  })
}

# input_template is a hand-written string, NOT jsonencode(): that escapes "<" and would silently
# destroy every <placeholder>, shipping the escape text instead. Raw newlines are invalid inside a
# JSON string, hence \n.
resource "aws_cloudwatch_event_target" "head_task_failed_to_start_sns" {
  rule      = aws_cloudwatch_event_rule.head_task_failed_to_start.name
  target_id = "sns"
  arn       = aws_sns_topic.alerts.arn

  input_transformer {
    input_paths = {
      at      = "$.time"
      code    = "$.detail.stopCode"
      reason  = "$.detail.stoppedReason"
      taskArn = "$.detail.taskArn"
    }
    input_template = "\"STReamGT: a pipeline task could not start, so no analysis ran.\\n\\nWhen:  <at>\\nWhy:   <code> - <reason>\\nTask:  <taskArn>\\n\\nThis is infrastructure, not data. Check the image tag on streamgt-head, the SecureStrings under /streamgt/, and Fargate capacity in eu-central-1. The affected job stays queued until somebody opens it, at which point the app records the failure itself.\""
  }
}

resource "aws_cloudwatch_event_target" "head_task_killed_sns" {
  rule      = aws_cloudwatch_event_rule.head_task_killed.name
  target_id = "sns"
  arn       = aws_sns_topic.alerts.arn

  # input_paths MAY use array indexes, unlike the event patterns above — which is the only way to
  # get the exit code into the message.
  input_transformer {
    input_paths = {
      at       = "$.time"
      exitCode = "$.detail.containers[0].exitCode"
      reason   = "$.detail.stoppedReason"
      taskArn  = "$.detail.taskArn"
    }
    input_template = "\"STReamGT: a pipeline container was killed by the platform.\\n\\nWhen:       <at>\\nExit code:  <exitCode>  (137 = killed, usually out of memory; 139 = segfault)\\nReason:     <reason>\\nTask:       <taskArn>\\n\\nThis is NOT an ordinary analysis failure, and NOT somebody pressing Stop. If 137, the task hit its memory limit - obiuniq dereplication is the usual culprit; raise head_memory. Logs: aws logs tail /ecs/streamgt-head --since 2h\""
  }
}

# ---------- signal 4: cost ----------
# Imported rather than created: this budget predates Terraform, and a hand-made one with
# CLI-added thresholds is invisible to `terraform plan` — in a year nobody would know it exists.
#   terraform import aws_budgets_budget.monthly 236726878099:streamgt-monthly
#
# ONE budget with several notifications, NOT several budgets: AWS gives two budgets free and then
# charges about $0.60/month each, which would cost more than the rest of this stack put together.
resource "aws_budgets_budget" "monthly" {
  name         = "${var.project}-monthly"
  budget_type  = "COST"
  time_unit    = "MONTHLY"
  limit_amount = "50"
  limit_unit   = "USD"

  # Absolute dollars, not percentages. Idle spend is about $0.30/month, so the only question worth
  # asking is "has something started costing real money", and $5 answers it. The original
  # 80%-of-$50 notification is kept as the last rung rather than dropped.
  dynamic "notification" {
    for_each = [5, 15, 30, 40]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "ABSOLUTE_VALUE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }

  # Forecast speaks before the money is spent, but it over-predicts wildly in a month containing
  # one unusually large run — so it is set at the full limit, where it only fires if the month is
  # genuinely heading for $50.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
