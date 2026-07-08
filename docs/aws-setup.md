# STReamGT — AWS Infrastructure Setup (cloud-native: Fargate + Batch + Aurora)

Step-by-step to provision the **cloud-native, pay-per-use** topology:

```
                 ┌─ default /*  ─▶ S3 (static SPA)              frontend
Browser ─▶ CloudFront (free *.cloudfront.net, HTTPS)
                 └─ /api/*      ─▶ ALB (HTTP) ─▶ ECS Fargate ── API   always-on, tiny
                                                     │ submit job
                                                     ▼
                      ECS RunTask ─▶ Fargate "Nextflow head" task   per job (ephemeral)
                                     │ nextflow -profile awsbatch (S3 work-dir)
                                     ▼
                      AWS Batch (Fargate/EC2 Spot) ── OBITools processes   per job
                                     ▲
   S3 (data) ◀───────────────────────┘   Aurora Serverless v2 (scale-to-zero)   SES (email)
```

**No custom domain.** One CloudFront distribution fronts everything on its free
`https://xxxx.cloudfront.net` URL (HTTPS included): the default behavior serves the SPA from S3,
and a `/api/*` behavior forwards to the ALB → Fargate API. Because the SPA and API share one
origin, there is **no CORS between them, no `api` subdomain, and no ACM certificate to buy**.
Add a real domain later by attaching it to this one distribution — nothing else changes.

> **⚠️ Code dependency.** This guide sets up the *infrastructure*. The app code (currently
> Celery + `nextflow -profile docker`) must be adapted to use it: add an `awsbatch` profile to
> `pipeline/nextflow.config` with an S3 work-dir, have the API trigger an **ECS RunTask** (or
> Batch SubmitJob) instead of `enqueue_job`, and drop Celery/Redis. Points marked **[CODE]**
> below indicate where the app must match a value you create here. Do the infra now; we wire the
> code after.

---

## Conventions

Run these in a terminal with **AWS CLI v2** configured (`aws configure`, an admin IAM user or
SSO). Set shell variables once; every command below reuses them.

```bash
export AWS_REGION=eu-central-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export PROJECT=streamgt
export DATA_BUCKET=${PROJECT}-data
export SITE_BUCKET=${PROJECT}-site
echo "account=$ACCOUNT_ID region=$AWS_REGION"
```

> **No domain.** We use CloudFront's free `*.cloudfront.net` URL. You won't know it until the
> distribution exists (Phase 10) — a few later values (S3 CORS origin, `FRONTEND_BASE_URL`)
> get filled in once you have `export SITE_URL=https://<dist-id>.cloudfront.net`.

---

## Phase 0 — Guardrails first (do NOT skip)

A cost budget + alert so a misconfiguration can't quietly run up a bill.

```bash
cat > /tmp/budget.json <<JSON
{ "BudgetName": "${PROJECT}-monthly", "BudgetLimit": {"Amount":"50","Unit":"USD"},
  "TimeUnit":"MONTHLY", "BudgetType":"COST" }
JSON
cat > /tmp/notify.json <<JSON
[ { "Notification": {"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80},
    "Subscribers":[{"SubscriptionType":"EMAIL","Address":"you@lab.org"}] } ]
JSON
aws budgets create-budget --account-id $ACCOUNT_ID \
  --budget file:///tmp/budget.json --notifications-with-subscribers file:///tmp/notify.json
```
Also enable a billing alarm in the console (Billing → Budgets already covers it). Turn on **S3
+ Batch cost allocation tags** later if you want per-kit reporting.

---

## Phase 1 — S3 buckets

### 1a. Data bucket (FASTQ uploads + results)
```bash
aws s3api create-bucket --bucket $DATA_BUCKET --region $AWS_REGION \
  --create-bucket-configuration LocationConstraint=$AWS_REGION
aws s3api put-public-access-block --bucket $DATA_BUCKET \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket $DATA_BUCKET --versioning-configuration Status=Enabled
```
CORS — the browser PUTs FASTQ parts **directly to S3** (a different origin from CloudFront), so
this stays even without a custom domain; **ETag must be exposed** for multipart. Set
`$SITE_URL` first (you'll have it after Phase 10 — come back and run this then):
```bash
# export SITE_URL=https://d1a2b3c4.cloudfront.net   # from Phase 10
cat > /tmp/cors.json <<JSON
{ "CORSRules":[ { "AllowedOrigins":["${SITE_URL}"],
  "AllowedMethods":["PUT","GET"], "AllowedHeaders":["*"],
  "ExposeHeaders":["ETag"], "MaxAgeSeconds":3000 } ] }
JSON
aws s3api put-bucket-cors --bucket $DATA_BUCKET --cors-configuration file:///tmp/cors.json
```
Lifecycle — expire raw uploads after 14 days (results stay):
```bash
cat > /tmp/lifecycle.json <<JSON
{ "Rules":[ {"ID":"expire-uploads","Status":"Enabled","Filter":{"Prefix":"uploads/"},
  "Expiration":{"Days":14}} ] }
JSON
aws s3api put-bucket-lifecycle-configuration --bucket $DATA_BUCKET --lifecycle-configuration file:///tmp/lifecycle.json
```
**[CODE]** `S3_BUCKET=$DATA_BUCKET`, `S3_REGION=$AWS_REGION`, `S3_ENDPOINT_URL=` (empty = real AWS).

### 1b. Site bucket (static SPA — served via CloudFront, kept private)
```bash
aws s3api create-bucket --bucket $SITE_BUCKET --region $AWS_REGION \
  --create-bucket-configuration LocationConstraint=$AWS_REGION
aws s3api put-public-access-block --bucket $SITE_BUCKET \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

---

## Phase 2 — ECR (container images)

Three images: the **API/head** backend image and the **OBITools** pipeline image. (The head
task and API can share one backend image with different entrypoints.)

```bash
for repo in ${PROJECT}-backend ${PROJECT}-obitools; do
  aws ecr create-repository --repository-name $repo --image-scanning-configuration scanOnPush=true
done
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS \
  --password-stdin ${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

# OBITools image (Batch needs the AWS CLI inside it for S3 staging — add it to pipeline/Dockerfile,
# or enable Nextflow Fusion; see the [CODE] note below).
docker build -t ${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT}-obitools:latest pipeline/
docker push ${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT}-obitools:latest

# Backend image (API + head)
docker build -t ${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT}-backend:latest \
  -f backend/Dockerfile backend/  # note: build context adjusted; see backend/Dockerfile
docker push ${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT}-backend:latest
```
**[CODE]** For Batch, either (a) add `awscli` to `pipeline/Dockerfile`, or (b) enable Nextflow
**Fusion/Wave** so processes read/write the S3 work-dir without a baked-in CLI. The `awsbatch`
profile in `nextflow.config` references `container = '<obitools ECR URI>'` and
`workDir = 's3://${DATA_BUCKET}/work'`.

---

## Phase 3 — Networking (use the default VPC, no NAT)

```bash
export VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
export SUBNETS=$(aws ec2 describe-subnets --filters Name=vpc-id,Values=$VPC_ID \
  --query 'Subnets[?MapPublicIpOnLaunch==`true`].SubnetId' --output text | tr '\t' ',')
echo "vpc=$VPC_ID public subnets=$SUBNETS"
```
Security groups (egress-only tasks; DB reachable only from app):
```bash
mk_sg() { aws ec2 create-security-group --group-name $1 --description "$1" --vpc-id $VPC_ID \
  --query GroupId --output text; }
export ALB_SG=$(mk_sg ${PROJECT}-alb)
export API_SG=$(mk_sg ${PROJECT}-api)
export DB_SG=$(mk_sg ${PROJECT}-db)
export BATCH_SG=$(mk_sg ${PROJECT}-batch)

# ALB: allow 443 from the internet
aws ec2 authorize-security-group-ingress --group-id $ALB_SG --protocol tcp --port 443 --cidr 0.0.0.0/0
# API tasks: allow 8000 only from the ALB
aws ec2 authorize-security-group-ingress --group-id $API_SG --protocol tcp --port 8000 --source-group $ALB_SG
# Aurora: allow 5432 only from API + Batch/head SGs
aws ec2 authorize-security-group-ingress --group-id $DB_SG --protocol tcp --port 5432 --source-group $API_SG
aws ec2 authorize-security-group-ingress --group-id $DB_SG --protocol tcp --port 5432 --source-group $BATCH_SG
```
Free S3 gateway endpoint (keeps S3 traffic off the public path, avoids any NAT need):
```bash
export RT_IDS=$(aws ec2 describe-route-tables --filters Name=vpc-id,Values=$VPC_ID \
  --query 'RouteTables[].RouteTableId' --output text | tr '\t' ' ')
aws ec2 create-vpc-endpoint --vpc-id $VPC_ID --service-name com.amazonaws.${AWS_REGION}.s3 \
  --route-table-ids $RT_IDS
```

---

## Phase 4 — Secrets (Secrets Manager)

```bash
export APP_SECRET=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))")
export DB_PASSWORD=$(python3 -c "import secrets;print(secrets.token_urlsafe(24))")
aws secretsmanager create-secret --name ${PROJECT}/app-secret-key --secret-string "$APP_SECRET"
aws secretsmanager create-secret --name ${PROJECT}/db-password   --secret-string "$DB_PASSWORD"
# (SES SMTP creds get added in Phase 6.)
```
These are injected into ECS task definitions as `secrets:` (not plaintext env).

---

## Phase 5 — Aurora Serverless v2 (PostgreSQL, scale-to-zero)

```bash
# DB subnet group across the public subnets (DB stays private via its SG; not publicly accessible)
aws rds create-db-subnet-group --db-subnet-group-name ${PROJECT}-db \
  --db-subnet-group-description "$PROJECT" --subnet-ids ${SUBNETS//,/ }

# Cluster with scale-to-zero: min capacity 0 ACU
aws rds create-db-cluster --db-cluster-identifier ${PROJECT}-db \
  --engine aurora-postgresql --engine-version 16.4 \
  --serverless-v2-scaling-configuration MinCapacity=0,MaxCapacity=4,SecondsUntilAutoPause=3600 \
  --master-username streamgt --master-user-password "$DB_PASSWORD" \
  --db-subnet-group-name ${PROJECT}-db --vpc-security-group-ids $DB_SG \
  --database-name streamgt

aws rds create-db-instance --db-instance-identifier ${PROJECT}-db-1 \
  --db-cluster-identifier ${PROJECT}-db --engine aurora-postgresql \
  --db-instance-class db.serverless

# Wait, then capture the endpoint
aws rds wait db-instance-available --db-instance-identifier ${PROJECT}-db-1
export DB_ENDPOINT=$(aws rds describe-db-clusters --db-cluster-identifier ${PROJECT}-db \
  --query 'DBClusters[0].Endpoint' --output text)
echo "DB endpoint: $DB_ENDPOINT"
```
**[CODE]** `DATABASE_URL=postgresql+psycopg://streamgt:<db-password>@${DB_ENDPOINT}:5432/streamgt`
(the code already uses this driver — no change beyond the URL). `SecondsUntilAutoPause=3600`
= pause after 1 h idle; first request after a pause waits ~15 s.

---

## Phase 6 — SES (email)

Without a domain you verify a **single sender email** (fine for test notifications; upgrade to a
verified domain later for production DKIM):
1. SES → **Create identity → Email address** → enter your lab address (e.g. `you@lab.org`) →
   click the confirmation link AWS emails you.
2. **Sandbox note:** until you request production access, SES can only send **to** verified
   addresses too — so verify your own recipient email as well for testing.
3. SES → **SMTP settings → Create SMTP credentials** → store them:
```bash
aws secretsmanager create-secret --name ${PROJECT}/smtp \
  --secret-string '{"user":"<SES_SMTP_USER>","password":"<SES_SMTP_PASS>"}'
```
**[CODE]** `SMTP_HOST=email-smtp.${AWS_REGION}.amazonaws.com`, `SMTP_PORT=587`, `SMTP_USE_TLS=true`,
`EMAIL_FROM=<your verified email>`. When you later add a domain, verify it in SES and switch
`EMAIL_FROM` to `no-reply@<domain>` for proper deliverability.

---

## Phase 7 — IAM roles

Trust policies + role creation. (Substitute `$ACCOUNT_ID`/`$AWS_REGION`; policies shown minimal.)

```bash
# --- Trust docs ---
cat > /tmp/ecs-trust.json <<'JSON'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}
JSON
cat > /tmp/batch-trust.json <<'JSON'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"batch.amazonaws.com"},"Action":"sts:AssumeRole"}]}
JSON

# 1) ECS task EXECUTION role (pull image, read secrets, write logs) — shared by API + head
aws iam create-role --role-name ${PROJECT}-exec --assume-role-policy-document file:///tmp/ecs-trust.json
aws iam attach-role-policy --role-name ${PROJECT}-exec \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
# allow reading our secrets
aws iam put-role-policy --role-name ${PROJECT}-exec --policy-name secrets --policy-document "$(cat <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["secretsmanager:GetSecretValue"],
 "Resource":"arn:aws:secretsmanager:${AWS_REGION}:${ACCOUNT_ID}:secret:${PROJECT}/*"}]}
JSON
)"

# 2) API task ROLE (presign S3, submit the head task)
aws iam create-role --role-name ${PROJECT}-api --assume-role-policy-document file:///tmp/ecs-trust.json
aws iam put-role-policy --role-name ${PROJECT}-api --policy-name app --policy-document "$(cat <<JSON
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:PutObject","s3:GetObject","s3:AbortMultipartUpload","s3:ListMultipartUploadParts"],"Resource":"arn:aws:s3:::${DATA_BUCKET}/*"},
 {"Effect":"Allow","Action":["s3:ListBucket"],"Resource":"arn:aws:s3:::${DATA_BUCKET}"},
 {"Effect":"Allow","Action":["ecs:RunTask"],"Resource":"*"},
 {"Effect":"Allow","Action":["iam:PassRole"],"Resource":["arn:aws:iam::${ACCOUNT_ID}:role/${PROJECT}-head","arn:aws:iam::${ACCOUNT_ID}:role/${PROJECT}-exec"]}
]}
JSON
)"

# 3) HEAD task ROLE (S3 rw, submit Batch jobs, send email)
aws iam create-role --role-name ${PROJECT}-head --assume-role-policy-document file:///tmp/ecs-trust.json
aws iam put-role-policy --role-name ${PROJECT}-head --policy-name app --policy-document "$(cat <<JSON
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:*"],"Resource":["arn:aws:s3:::${DATA_BUCKET}","arn:aws:s3:::${DATA_BUCKET}/*"]},
 {"Effect":"Allow","Action":["batch:SubmitJob","batch:DescribeJobs","batch:TerminateJob","batch:RegisterJobDefinition"],"Resource":"*"},
 {"Effect":"Allow","Action":["ses:SendEmail","ses:SendRawEmail"],"Resource":"*"}
]}
JSON
)"

# 4) Batch service role + Fargate execution role for Batch jobs
aws iam create-role --role-name ${PROJECT}-batch-svc --assume-role-policy-document file:///tmp/batch-trust.json
aws iam attach-role-policy --role-name ${PROJECT}-batch-svc \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSBatchServiceRole
# Batch job execution role = reuse ${PROJECT}-exec; Batch job role = reuse ${PROJECT}-head (S3 access)
```

---

## Phase 8 — AWS Batch (Fargate Spot compute for OBITools)

```bash
# Compute environment (Fargate Spot, in public subnets, egress-only SG)
aws batch create-compute-environment --compute-environment-name ${PROJECT}-ce \
  --type MANAGED --state ENABLED \
  --service-role arn:aws:iam::${ACCOUNT_ID}:role/${PROJECT}-batch-svc \
  --compute-resources "type=FARGATE_SPOT,maxvCpus=64,subnets=[${SUBNETS}],securityGroupIds=[${BATCH_SG}]"

# Job queue
aws batch create-job-queue --job-queue-name ${PROJECT}-queue --state ENABLED --priority 1 \
  --compute-environment-order order=1,computeEnvironment=${PROJECT}-ce
```
Nextflow (awsbatch executor) registers its own job definitions per process at runtime, so you
usually don't hand-create one. If you prefer a fixed def, register a Fargate job definition that
uses the OBITools ECR image, `${PROJECT}-exec` as executionRole and `${PROJECT}-head` as jobRole.

**[CODE]** `pipeline/nextflow.config`:
```groovy
profiles {
  awsbatch {
    process.executor = 'awsbatch'
    process.queue    = 'streamgt-queue'
    process.container = '<ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/streamgt-obitools:latest'
    aws.region = '<REGION>'
    aws.batch.cliPath = '/usr/local/bin/aws'   // or enable fusion
    workDir = 's3://streamgt-data/work'
  }
}
```

---

## Phase 9 — ECS Fargate (API service + head task) behind an ALB

No custom domain, so **CloudFront terminates TLS and the ALB is a plain HTTP origin** — no ACM
cert here. Console is easier for the ALB/listener/target-group wiring; key settings:

1. **ECS cluster**: `aws ecs create-cluster --cluster-name ${PROJECT}`.
2. **Task definition — API** (Fargate, 0.5 vCPU / 1 GB): container = backend ECR image, command
   = `uvicorn app.main:app --host 0.0.0.0 --port 8000`, `executionRoleArn=${PROJECT}-exec`,
   `taskRoleArn=${PROJECT}-api`, port 8000, env from Phase 4/5/6 secrets, log group
   `/ecs/${PROJECT}-api`.
3. **ALB** (internet-facing, public subnets, `ALB_SG`) → **target group** (ip, port 8000, health
   check `/health`) → **HTTP:80 listener** (CloudFront does HTTPS). To keep it from being hit
   directly, set `ALB_SG` ingress to the CloudFront **managed prefix list**
   (`com.amazonaws.global.cloudfront.origin-facing`) instead of `0.0.0.0/0`, and/or have
   CloudFront send a secret header the ALB requires.
4. **ECS service**: desired count **1**, launch type Fargate, network = public subnets +
   `API_SG` + assign public IP, attach to the target group.
5. **Task definition — head** (Fargate, 1 vCPU / 2 GB): backend ECR image, command runs the
   Batch-mode `run_pipeline` for one job (reads a `JOB_ID` env passed by RunTask),
   `taskRoleArn=${PROJECT}-head`. No service — the API launches it per job via `ecs run-task`.
6. Capture the ALB DNS name for the CloudFront origin in Phase 10:
   `export ALB_DNS=$(aws elbv2 describe-load-balancers --names ${PROJECT}-alb --query 'LoadBalancers[0].DNSName' --output text)`

**[CODE]** Replace `enqueue_job()` (Celery) with an `ecs run-task` call that launches the head
task definition with `JOB_ID` overridden. The head container entrypoint runs the existing
`run_pipeline(job_id)` logic (stage → build input.tsv → `nextflow -profile awsbatch` → harvest →
upload → SES email → update Aurora).

---

## Phase 10 — CloudFront (single distribution fronting SPA + API)

The frontend already calls the API at the **relative path `/api`** (`frontend/src/api/client.js`
uses `fetch('/api/...')`), so with one distribution serving both, **no build-time API URL is
needed** — just build and upload:
```bash
( cd frontend && npm run build )
aws s3 sync frontend/dist s3://${SITE_BUCKET}/ --delete
```
Console (CloudFront) — create **one distribution** with **two origins + two behaviors**:
1. **Origin 1 (SPA):** `${SITE_BUCKET}` with **Origin Access Control (OAC)** — keeps the bucket
   private; CloudFront generates the bucket policy for you.
2. **Origin 2 (API):** custom origin = the **ALB DNS name** (`$ALB_DNS`), protocol HTTP, port 80.
3. **Default behavior** `*` → Origin 1 (SPA). Viewer protocol: redirect HTTP→HTTPS. Default root
   object `index.html`. Add **custom error responses** 403 & 404 → `/index.html` (200) for SPA
   routing.
4. **Behavior `/api/*`** → Origin 2 (ALB). Use the managed **CachingDisabled** cache policy and
   the **AllViewer** origin-request policy (forward all headers/cookies/query — it's dynamic).
5. Leave the certificate as the **default CloudFront cert** (covers `*.cloudfront.net`). No custom
   domain, no ACM.

After it deploys, capture the URL and finish the two deferred values:
```bash
export SITE_URL=https://$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Origins.Items[?DomainName=='${SITE_BUCKET}.s3.${AWS_REGION}.amazonaws.com']].DomainName | [0]" --output text)
echo "Your app: $SITE_URL"
# 1) set S3 CORS now (Phase 1a command, now that SITE_URL exists)
# 2) [CODE] set FRONTEND_BASE_URL=$SITE_URL in the API + head task envs (email links)
```

---

## Phase 11 — (No DNS needed)

You're live on `$SITE_URL`. **To add a custom domain later:** register it (Route 53 easiest),
request an **ACM cert in us-east-1**, add it as an *alternate domain name* on this same
CloudFront distribution, and point a DNS alias/CNAME at the distribution. The API keeps working
unchanged because it's behind the same distribution — only update S3 CORS + `FRONTEND_BASE_URL`
to the new domain.

---

## Phase 12 — Migrate, seed, verify

Run Alembic against Aurora once (a one-off `ecs run-task` with command
`alembic upgrade head`, or from your laptop if you temporarily allow your IP to the DB SG):
```bash
# example: one-off task
aws ecs run-task --cluster ${PROJECT} --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[${SUBNETS}],securityGroups=[${API_SG}],assignPublicIp=ENABLED}" \
  --overrides '{"containerOverrides":[{"name":"api","command":["alembic","upgrade","head"]}]}' \
  --task-definition ${PROJECT}-api
# then bootstrap an admin similarly with: python -m app.bootstrap --admin-email ... --admin-password ...
```
Register kits (upload each primers CSV + `tags.csv` to S3, `POST /api/kits` with the keys).
**Smoke test:** open `$SITE_URL` → register/login → submit a subsampled job → watch the head
task in ECS + the Batch jobs → download genotypes → confirm the SES email.

---

## Phase 13 — Confirm it actually scales to zero

- **Aurora**: after 1 h idle, `DescribeDBClusters` shows `Capacity: 0`. Only storage billed.
- **Batch**: `DescribeComputeEnvironments` → 0 running/desired vCPUs when no job.
- **ECS API service**: 1 task always on (tiny). If you want *that* to scale to zero too, move the
  API to **Lambda + API Gateway** later — but 1 small Fargate task is simplest.
- Re-check the **Budget** email threshold.

---

## Appendix — this is a lot of manual steps; consider IaC

Fifty CLI/console steps are error-prone and hard to reproduce. For anything beyond a first
trial, capture this as **Terraform** or **AWS CDK** so the whole stack is one `apply`/`deploy`,
versioned in the repo. I can generate that (CDK in Python fits your stack) instead of — or after
— the manual run. The manual guide above is the mental model either way.

### The [CODE] changes — ✅ DONE (2026-07-06)
1. ✅ `pipeline/nextflow.config`: `awsbatch` profile (env-configurable container/queue/workDir).
2. ✅ `pipeline/Dockerfile`: AWS CLI v2 installed at `/usr/local/bin/aws` for Batch S3 staging.
3. ✅ `backend`: `enqueue_job()` branches on `RUN_MODE` — `ecs` launches the head task via
   `ecs run-task` (`app/services/dispatch.py`); the head entrypoint is
   `python -m app.worker.run_job <id>` → `execute_job()` (refactored out of the Celery task).
   Profile-agnostic: runs `nextflow -profile $NEXTFLOW_PROFILE`. Celery path kept for local.
4. ✅ `frontend`: no change (calls relative `/api`, routed by the single CloudFront distribution).

### Settings the ECS phase (9) must inject into the task definitions
Both the **API** and **head** tasks use **one image** — build `deploy/Dockerfile.worker`
(has Nextflow + Java + R + the backend) and push to the `streamgt-backend` ECR repo. The API
task command is `uvicorn app.main:app --host 0.0.0.0 --port 8000`; the head task's container is
named **`head`** (matches `dispatch.HEAD_CONTAINER_NAME`) and its command is overridden per job.

Env for **both** tasks: `DATABASE_URL` (Aurora), `S3_BUCKET`, `S3_REGION`, `SECRET_KEY`
(secret), `SMTP_*`, `EMAIL_FROM`, `FRONTEND_BASE_URL=$SITE_URL`.
API task also: `RUN_MODE=ecs`, `ECS_CLUSTER`, `HEAD_TASK_DEF`, `ECS_SUBNETS` (comma-sep),
`ECS_SECURITY_GROUP`.
Head task also: `NEXTFLOW_PROFILE=awsbatch`, `NXF_BATCH_QUEUE=streamgt-queue`,
`OBITOOLS_IMAGE=<obitools ECR URI>`, `NXF_WORK=s3://<data-bucket>/work`, `PIPELINE_DIR=/app/pipeline`,
`JOB_SCRATCH_ROOT=/scratch`, and **ephemeral storage ≥ 50 GB** (a 2 GB FASTQ expands).
