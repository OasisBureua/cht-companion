locals {
  prefix     = var.resource_prefix
  secret_name = "${local.prefix}-bff-auth"
}

resource "random_password" "bff_auth" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "bff_auth" {
  name                    = local.secret_name
  description             = "Shared secret for NestJS BFF → companion X-BFF-Auth (COMPANION_INTERNAL_SECRET)"
  recovery_window_in_days = var.environment == "prod" ? 30 : 0
  kms_key_id              = var.kms_key_arn

  tags = {
    Name        = local.secret_name
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "bff_auth" {
  secret_id     = aws_secretsmanager_secret.bff_auth.id
  secret_string = random_password.bff_auth.result

  # Allow ops / platform to rotate in-console without Terraform reverting on apply.
  lifecycle {
    ignore_changes = [secret_string]
  }
}
