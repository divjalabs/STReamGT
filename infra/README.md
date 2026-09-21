# STReamGT — compute/web tier (Terraform)

Creates the pay-per-use web tier: **the API as a Lambda function** (container image + Lambda Web
Adapter, public function URL), **CloudFront** (single distribution: SPA from S3 + `/api/*` →
Lambda URL), the **ECS cluster + per-job head task definition**, the Lambda role, CloudWatch log
groups and the site-bucket policy. Everything else (S3, VPC, security groups, ECR, the ECS
roles) was created by hand in `docs/aws-setup.md` and is referenced via data sources / variable
defaults.

**Nothing runs while the app is idle.** The API runs only per request, the database is a
**Neon** free-tier Postgres (scales to zero), and the pipeline runs as one Fargate task per job.
Idle cost is ~$0–2/month (S3 + ECR storage); a genotyping run costs ~$0.50 per pipeline hour.

## Secrets: SSM Parameter Store
Secrets are `SecureString` parameters under `/streamgt/` (standard tier: free), created by hand
so their values never enter Terraform state. The parameter name is the env var name:

| Parameter | Value |
|---|---|
| `/streamgt/DATABASE_URL` | `postgresql+psycopg://<user>:<pwd>@<neon-host>/streamgt?sslmode=require` |
| `/streamgt/SECRET_KEY` | JWT signing key |
| `/streamgt/SMTP_USER`, `/streamgt/SMTP_PASSWORD` | SES SMTP credentials |

```bash
aws ssm put-parameter --name /streamgt/DATABASE_URL --type SecureString --overwrite --value '...'
```
The Lambda loads them at cold start (`SSM_PARAMETER_PATH`, see `app/config.py`); the head task
gets them injected by ECS. After changing a parameter, force a Lambda cold start (see below).

## Prerequisites
1. **Terraform**, native arm64 build on Apple Silicon (the amd64 provider under Rosetta times out).
2. AWS CLI configured (same account/region as the hand-built resources).
3. **Images pushed to ECR**:
   - `streamgt-backend:api-lambda` — the API (arm64, `deploy/Dockerfile.lambda`):
     `docker buildx build --platform linux/arm64 --provenance=false -f deploy/Dockerfile.lambda -t <ecr>/streamgt-backend:api-lambda --push .`
   - `streamgt-backend:latest` — the head image (amd64, `deploy/Dockerfile.head`).
4. The SSM parameters above exist.

## Deploy
```bash
cd infra
terraform init
terraform plan
terraform apply
terraform output app_url
```

**One manual step after the first apply** — public function URLs also need an
`lambda:InvokeFunction` grant limited to URL calls, which the pinned AWS provider (5.x) can't
express (without it the URL answers 403 Forbidden):
```bash
aws lambda add-permission --function-name streamgt-api --statement-id FunctionURLInvokeAllowPublicAccess \
  --action lambda:InvokeFunction --principal '*' --invoked-via-function-url
```

## Rolling out a new API image
Terraform ignores `image_uri` after creation; push the image, then:
```bash
aws lambda update-function-code --function-name streamgt-api \
  --image-uri 236726878099.dkr.ecr.eu-central-1.amazonaws.com/streamgt-backend:api-lambda
```
To force a cold start (e.g. after changing an SSM parameter) without a new image, bump any env
var, e.g. `aws lambda update-function-configuration` with a new `RESTARTED_AT` value merged into
the existing variables.

## Post-apply
1. **S3 CORS** — allow the browser (on the CloudFront URL) to PUT FASTQ parts (unchanged).
2. **SPA** — `npm run build`, `aws s3 sync dist s3://streamgt-site-236726878099/ --delete`,
   invalidate CloudFront.
3. **DB schema / admin** — Neon is reachable from anywhere (TLS + password), so
   `python -m app.bootstrap` can run locally with `DATABASE_URL` set to the Neon URL.

## Limits of the Lambda API
- Request/response bodies are capped at **6 MB** (FASTQ uploads go direct to S3 via presigned
  URLs, so only project exports/imports could approach this).
- Requests time out after 60 s (CloudFront's origin timeout is 30 s anyway).
- The per-IP rate limiter is in-memory, so per Lambda instance.

## Teardown
`terraform destroy` removes only this tier (Lambda/CloudFront/ECS task def/logs). The
hand-built foundation (S3, ECR, roles) and the Neon database stay.
