resource "aws_ecr_repository" "app" {
  name                 = var.app_name
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy     = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Retain ${var.ecr_retain_count} tagged images for ${var.environment}"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["${var.environment}-"]
          countType     = "imageCountMoreThan"
          countNumber   = var.ecr_retain_count
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Expire untagged images after ${var.ecr_untagged_expire_days} days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = var.ecr_untagged_expire_days
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
