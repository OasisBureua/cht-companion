locals {
  prefix = var.resource_prefix
}

resource "aws_secretsmanager_secret" "app" {
  name                    = "${local.prefix}/app"
  description             = "cht-companion application secrets"
  recovery_window_in_days = var.environment == "prod" ? 30 : 0
  kms_key_id              = var.kms_key_arn

  tags = {
    Name        = "${local.prefix}-app-secret"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    internal_api_secret = var.internal_api_secret
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}
