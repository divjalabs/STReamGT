output "app_url" {
  description = "The public HTTPS URL of the app (frontend + /api)."
  value       = "https://${aws_cloudfront_distribution.app.domain_name}"
}

output "api_function_url" {
  description = "Lambda function URL (CloudFront origin for /api/*)."
  value       = aws_lambda_function_url.api.function_url
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.app.id
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "head_task_family" {
  value = aws_ecs_task_definition.head.family
}
