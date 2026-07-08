output "app_url" {
  description = "The public HTTPS URL of the app (frontend + /api)."
  value       = "https://${aws_cloudfront_distribution.app.domain_name}"
}

output "alb_dns" {
  description = "ALB DNS name (CloudFront origin for /api/*)."
  value       = aws_lb.api.dns_name
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
