locals {
  prefix = var.resource_prefix
}

resource "aws_ecr_repository" "companion" {
  name                 = var.companion_repository_name
  image_tag_mutability = "MUTABLE"
  force_delete         = var.environment != "prod"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name        = var.companion_repository_name
    Environment = var.environment
    Service     = "cht-companion"
  }
}

resource "aws_ecr_repository" "companion_kb" {
  name                 = var.kb_repository_name
  image_tag_mutability = "MUTABLE"
  force_delete         = var.environment != "prod"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name        = var.kb_repository_name
    Environment = var.environment
    Service     = "cht-companion-kb"
  }
}

resource "aws_ecr_lifecycle_policy" "companion" {
  repository = aws_ecr_repository.companion.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 30 tagged images"
      selection = {
        tagStatus     = "any"
        countType     = "imageCountMoreThan"
        countNumber   = 30
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "companion_kb" {
  repository = aws_ecr_repository.companion_kb.name

  policy = aws_ecr_lifecycle_policy.companion.policy
}
