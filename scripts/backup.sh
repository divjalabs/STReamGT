#!/usr/bin/env bash
# Off-AWS backup: dump the Aurora DB (via a one-off ECS task in the VPC) and pull the DB dump
# + the S3 data bucket down to a local folder. Run before any `bootstrap --reset` or migration.
#
#   scripts/backup.sh [DEST_DIR]     # default DEST_DIR = ./streamgt-backup
set -euo pipefail

REGION=eu-central-1
CLUSTER=streamgt
TASK_DEF=streamgt-api:3
CONTAINER=api
BUCKET=streamgt-data-236726878099
SUBNETS=subnet-00ce16d02d55fab80,subnet-0979fb2e7f3916aea,subnet-028380a3442c47845
SG=sg-0a952b15762b85860
DEST="${1:-./streamgt-backup}"

echo "[1/3] Dumping the database (one-off ECS task in the VPC)…"
TASK_ARN=$(aws ecs run-task --cluster "$CLUSTER" --launch-type FARGATE --region "$REGION" \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=ENABLED}" \
  --overrides "{\"containerOverrides\":[{\"name\":\"$CONTAINER\",\"command\":[\"python\",\"-m\",\"app.dbbackup\"]}]}" \
  --task-definition "$TASK_DEF" --query 'tasks[0].taskArn' --output text)
echo "      task: $TASK_ARN"
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK_ARN" --region "$REGION"
EXIT=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK_ARN" --region "$REGION" \
  --query 'tasks[0].containers[0].exitCode' --output text)
if [ "$EXIT" != "0" ]; then
  echo "      DB dump task failed (exit $EXIT) — check CloudWatch /ecs/streamgt-api" >&2
  exit 1
fi
echo "      DB dump uploaded to s3://$BUCKET/backups/db/"

echo "[2/3] Syncing DB dumps → $DEST/db …"
aws s3 sync "s3://$BUCKET/backups/db" "$DEST/db" --region "$REGION"

echo "[3/3] Syncing data bucket (FASTQ/results, skipping work/ scratch) → $DEST/data …"
aws s3 sync "s3://$BUCKET" "$DEST/data" --exclude "work/*" --exclude "backups/*" --region "$REGION"

echo "Done. Off-AWS backup at: $DEST"
echo "  DB dumps: $DEST/db   |   data files: $DEST/data"
