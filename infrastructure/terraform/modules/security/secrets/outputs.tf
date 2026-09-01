output "app_secrets_arn" {
  value = aws_secretsmanager_secret.app.arn
}
