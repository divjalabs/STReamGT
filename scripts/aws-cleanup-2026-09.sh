#!/usr/bin/env bash
# One-off cleanup after moving STReamGT off the always-on tier to Lambda + Neon (2026-09).
# Deletes only resources the app no longer uses. Your data (S3 data bucket, Neon DB) is untouched.
# Safe to re-run: steps that are already done fail harmlessly and print a "!" line.
set -uo pipefail
R=eu-central-1
BUCKET=streamgt-data-236726878099
ok()   { echo "   ✓ $*"; }
warn() { echo "   ! $*"; }
step() { echo; echo "== $*"; }

step "1. Aurora: delete streamgt-db-enc (final snapshot streamgt-db-final-20260921 is kept)"
aws rds modify-db-cluster --region $R --db-cluster-identifier streamgt-db-enc \
  --no-deletion-protection --apply-immediately >/dev/null && ok "deletion protection off"
aws rds delete-db-instance --region $R --db-instance-identifier streamgt-db-enc-1 >/dev/null && ok "instance deleting…"
aws rds wait db-instance-deleted --region $R --db-instance-identifier streamgt-db-enc-1 && ok "instance deleted"
aws rds delete-db-cluster --region $R --db-cluster-identifier streamgt-db-enc \
  --final-db-snapshot-identifier streamgt-db-final-20260921 >/dev/null && ok "cluster deleting (taking final snapshot)…"
until ! aws rds describe-db-clusters --region $R --db-cluster-identifier streamgt-db-enc >/dev/null 2>&1; do sleep 20; done
ok "cluster deleted"
for s in streamgt-db-final-preenc-20260727135129 streamgt-db-manual-20260723t153602z; do
  aws rds delete-db-cluster-snapshot --region $R --db-cluster-snapshot-identifier $s >/dev/null && ok "old snapshot $s deleted"
done
aws rds delete-db-subnet-group --region $R --db-subnet-group-name streamgt-db && ok "DB subnet group deleted"

step "2. Secrets Manager → already copied to Parameter Store (7-day recovery window)"
for s in streamgt/app-secret-key streamgt/db-password streamgt/smtp; do
  aws secretsmanager delete-secret --region $R --secret-id $s --recovery-window-in-days 7 >/dev/null && ok "$s scheduled for deletion"
done

step "3. ECR: delete untagged (superseded) images; keep tagged latest / api-lambda / head-2026-07-30"
for repo in streamgt-backend streamgt-obitools; do
  ids=$(aws ecr list-images --region $R --repository-name $repo --filter tagStatus=UNTAGGED --query 'imageIds[].imageDigest' --output text)
  n=0
  for d in $ids; do
    aws ecr batch-delete-image --region $R --repository-name $repo --image-ids imageDigest=$d >/dev/null && n=$((n+1))
  done
  ok "$repo: $n untagged images deleted"
  aws ecr put-lifecycle-policy --region $R --repository-name $repo --lifecycle-policy-text \
    '{"rules":[{"rulePriority":1,"description":"expire superseded (untagged) images","selection":{"tagStatus":"untagged","countType":"sinceImagePushed","countUnit":"days","countNumber":1},"action":{"type":"expire"}}]}' \
    >/dev/null && ok "$repo: lifecycle policy — untagged images auto-expire after 1 day"
done

step "4. S3: delete Nextflow scratch (work/) + auto-expire it after 7 days from now on"
aws s3 rm "s3://$BUCKET/work/" --recursive --only-show-errors && ok "work/ emptied"
LC=$(mktemp)
aws s3api get-bucket-lifecycle-configuration --bucket $BUCKET --query '{Rules:Rules}' --output json > "$LC"
LC="$LC" python3 - <<'EOF'
import json, os
p = os.environ["LC"]
cfg = json.load(open(p))
rules = [r for r in cfg["Rules"] if r.get("ID") != "expire-work"]
rules.append({"ID": "expire-work", "Status": "Enabled", "Filter": {"Prefix": "work/"},
              "Expiration": {"Days": 7}, "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}})
json.dump({"Rules": rules}, open(p, "w"))
EOF
aws s3api put-bucket-lifecycle-configuration --bucket $BUCKET --lifecycle-configuration "file://$LC" \
  && ok "lifecycle: work/ expires after 7 days (existing uploads/ + backups/ rules kept)"
rm -f "$LC"

step "5. Unused AWS Batch setup (pipeline runs on Fargate, not Batch)"
aws batch update-job-queue --region $R --job-queue streamgt-queue --state DISABLED >/dev/null && ok "queue disabled"
while [ "$(aws batch describe-job-queues --region $R --job-queues streamgt-queue --query 'jobQueues[0].status' --output text)" = "UPDATING" ]; do sleep 5; done
aws batch delete-job-queue --region $R --job-queue streamgt-queue >/dev/null && ok "queue deleting…"
while [ "$(aws batch describe-job-queues --region $R --job-queues streamgt-queue --query 'length(jobQueues)' --output text)" != "0" ]; do sleep 5; done
aws batch update-compute-environment --region $R --compute-environment streamgt-ce --state DISABLED >/dev/null && ok "compute env disabled"
while [ "$(aws batch describe-compute-environments --region $R --compute-environments streamgt-ce --query 'computeEnvironments[0].status' --output text)" = "UPDATING" ]; do sleep 5; done
aws batch delete-compute-environment --region $R --compute-environment streamgt-ce >/dev/null && ok "compute env deleting"
aws logs delete-log-group --region $R --log-group-name /aws/batch/job && ok "/aws/batch/job log group deleted"

step "6. Old IAM roles (always-on API service, Batch)"
aws iam delete-role-policy --role-name streamgt-api --policy-name app && aws iam delete-role --role-name streamgt-api && ok "streamgt-api role deleted"
while [ "$(aws batch describe-compute-environments --region $R --compute-environments streamgt-ce --query 'length(computeEnvironments)' --output text)" != "0" ]; do sleep 5; done
aws iam detach-role-policy --role-name streamgt-batch-svc --policy-arn arn:aws:iam::aws:policy/service-role/AWSBatchServiceRole \
  && aws iam delete-role --role-name streamgt-batch-svc && ok "streamgt-batch-svc role deleted"

step "7. Security groups: load balancer, Batch, Aurora (the head task's streamgt-api SG stays)"
aws ec2 revoke-security-group-ingress --region $R --group-id sg-0a952b15762b85860 \
  --ip-permissions 'IpProtocol=tcp,FromPort=8000,ToPort=8000,UserIdGroupPairs=[{GroupId=sg-09ecbd8858282fac6}]' >/dev/null \
  && ok "removed old load-balancer → API rule"
for sg in sg-09ecbd8858282fac6 sg-0558e28375c4f2748 sg-0536a45ac3715a231; do
  for i in $(seq 1 30); do   # Aurora's network interface can take a few minutes to disappear
    aws ec2 delete-security-group --region $R --group-id $sg 2>/dev/null && { ok "$sg deleted"; break; }
    [ $i = 30 ] && warn "$sg still in use — delete later: aws ec2 delete-security-group --group-id $sg"
    sleep 20
  done
done

step "8. Old ECS task definition revisions (free, just clutter)"
for td in streamgt-api:1 streamgt-api:2 streamgt-api:4 streamgt-head:1 streamgt-head:2 streamgt-head:3 streamgt-head:5 streamgt-head:6 streamgt-head:7; do
  aws ecs deregister-task-definition --region $R --task-definition $td >/dev/null && ok "$td deregistered"
done

echo; echo "Done."
