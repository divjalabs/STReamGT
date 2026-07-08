# STReamGT — compute/web tier (Terraform)

Creates the interconnected tier that's painful to hand-run: **ECS cluster, API + head task
definitions, ALB, ECS service, CloudFront** (single distribution: SPA + `/api/*` → ALB), plus
CloudWatch log groups and the site-bucket policy. Everything else (S3, VPC, security groups,
Aurora, AWS Batch, ECR, IAM roles, Secrets Manager) was created by hand in `docs/aws-setup.md`
phases 0-8 and is referenced here via data sources / variable defaults.

The DB password is **never** in Terraform state: task definitions inject `DB_PASSWORD` from
Secrets Manager (by ARN) and pass `DB_HOST/USER/NAME` as plain env; the app assembles the URL
(`config.resolved_database_url`).

## Prerequisites
1. **Terraform** installed: `brew install terraform`.
2. AWS CLI configured (same account/region as the hand-built resources).
3. **Both images pushed to ECR** (the tasks won't start otherwise):
   - `streamgt-obitools` — `docker buildx build --platform linux/amd64 -t <ecr>/streamgt-obitools:latest --push pipeline/`
   - `streamgt-backend` — the lean **head/API image** built from `deploy/Dockerfile.head`
     (Python + Java + Nextflow + the backend; no R, so it builds fast even emulated):
     `docker buildx build --platform linux/amd64 -f deploy/Dockerfile.head -t <ecr>/streamgt-backend:latest --push .`

## Deploy
```bash
cd infra
terraform init
terraform plan      # review — note the ALB (~$18/mo) is the only always-on cost here
terraform apply     # type yes
terraform output app_url
```
Defaults in `variables.tf` are your real resource IDs, so no tfvars is needed. Override any in
`terraform.tfvars` if they change.

## Post-apply (three steps)
1. **S3 CORS** — allow the browser (now on the CloudFront URL) to PUT FASTQ parts:
   ```bash
   APP=$(terraform output -raw app_url)
   aws s3api put-bucket-cors --bucket streamgt-data-236726878099 --cors-configuration \
     "{\"CORSRules\":[{\"AllowedOrigins\":[\"$APP\"],\"AllowedMethods\":[\"PUT\",\"GET\"],\"AllowedHeaders\":[\"*\"],\"ExposeHeaders\":[\"ETag\"],\"MaxAgeSeconds\":3000}]}"
   ```
2. **Build + upload the SPA** (calls the API at the relative `/api`, so no build-time URL):
   ```bash
   ( cd ../frontend && npm run build )
   aws s3 sync ../frontend/dist s3://streamgt-site-236726878099/ --delete
   aws cloudfront create-invalidation --distribution-id $(terraform output -raw cloudfront_distribution_id) --paths '/*'
   ```
3. **Migrate the DB + seed an admin** via a one-off ECS task (Aurora is only reachable inside
   the VPC). Runs `alembic upgrade head` (or `python -m app.bootstrap`) using the API task def:
   ```bash
   aws ecs run-task --cluster streamgt --launch-type FARGATE \
     --network-configuration "awsvpcConfiguration={subnets=[subnet-00ce16d02d55fab80],securityGroups=[sg-0a952b15762b85860],assignPublicIp=ENABLED}" \
     --overrides '{"containerOverrides":[{"name":"api","command":["python","-m","app.bootstrap","--admin-email","you@lab.org","--admin-password","<strong>"]}]}' \
     --task-definition streamgt-api
   ```

## Verify
- `terraform output app_url` → open it; the SPA loads over HTTPS, `/api/health` returns ok.
- Register/login, add the DIVJA240 kit, submit a subsampled job → watch the **head** task in
  ECS and the **Batch** jobs → download genotypes.

## Teardown
`terraform destroy` removes only this tier (ECS/ALB/CloudFront/logs). The hand-built
foundation (S3, Aurora, Batch, ECR, roles) stays. To stop the only always-on cost without a
full destroy, set the ECS service `desired_count` to 0 and delete the ALB.

## Known gaps
- **SMTP creds**: email uses SES SMTP but the task defs don't yet inject `SMTP_USER/PASSWORD`
  (create SES SMTP credentials, store as `streamgt/smtp`, add to `common_secrets`). Until then
  completion emails fail silently (they're best-effort).
- **ALB open on :80/:443**: locked only by security group; optionally restrict `alb_sg` ingress
  to the CloudFront `com.amazonaws.global.cloudfront.origin-facing` prefix list.
