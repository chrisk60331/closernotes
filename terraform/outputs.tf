output "service_url" {
  description = "App Runner service URL."
  value       = aws_apprunner_service.app.service_url
}

output "service_arn" {
  description = "App Runner service ARN."
  value       = aws_apprunner_service.app.arn
}

output "ecr_repository_url" {
  description = "ECR repository URL."
  value       = aws_ecr_repository.app.repository_url
}

output "ecr_push_commands" {
  description = "Helper commands to build and push the image."
  value = [
    "aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${aws_ecr_repository.app.repository_url}",
    "docker build -t ${var.app_name} .",
    "docker tag ${var.app_name}:latest ${aws_ecr_repository.app.repository_url}:${var.environment}-${var.ecr_image_tag}",
    "docker push ${aws_ecr_repository.app.repository_url}:${var.environment}-${var.ecr_image_tag}"
  ]
}
