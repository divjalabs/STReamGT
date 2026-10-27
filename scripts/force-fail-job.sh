#!/usr/bin/env bash
# Mark a stuck job as failed, so its kit stops being locked behind it.
#
#   scripts/force-fail-job.sh <job-id> ["reason"]
#
# For a job whose task died without recording anything — the row still says queued/running/staging
# while nothing is left in the cluster. Check first:
#   aws ecs list-tasks --cluster streamgt --region eu-central-1 --desired-status RUNNING
# An empty list plus a long-"running" job means the task is gone.
#
# Refuses to touch a job that is already finished.
set -euo pipefail

JOB_ID="${1:?usage: scripts/force-fail-job.sh <job-id> [\"reason\"]}"
REASON="${2:-The analysis task stopped without reporting back. Please submit it again.}"
REGION=eu-central-1

RUNNING=$(aws ecs list-tasks --cluster streamgt --region "$REGION" --desired-status RUNNING \
  --query 'length(taskArns)' --output text)
if [ "$RUNNING" != "0" ]; then
  echo "⚠️  $RUNNING pipeline task(s) are still running in the cluster." >&2
  echo "    Check that none of them belongs to job $JOB_ID before forcing it to failed." >&2
  read -r -p "    Continue anyway? [y/N] " answer
  [ "$answer" = "y" ] || { echo "aborted"; exit 1; }
fi

URL=$(aws ssm get-parameter --region "$REGION" --name /streamgt/DATABASE_URL \
  --with-decryption --query Parameter.Value --output text | sed 's/postgresql+psycopg:/postgresql:/')

SQL="UPDATE jobs
       SET status = 'failed', finished_at = now(), error_message = \$reason\$${REASON}\$reason\$
     WHERE id = ${JOB_ID}
       AND status NOT IN ('succeeded', 'failed', 'cancelled')
   RETURNING id, status, left(error_message, 60) AS error_message;"

docker run --rm -e URL -e SQL postgres:16 sh -c 'psql "$URL" -v ON_ERROR_STOP=1 -c "$SQL"' \
  || { echo "Could not reach the database (is Docker running?)" >&2; exit 1; }

echo "If no row came back, the job was already in a finished state — nothing to do."
