output "secret_arn" {
  value     = aws_secretsmanager_secret.bff_auth.arn
  sensitive = true
}

output "secret_name" {
  value = aws_secretsmanager_secret.bff_auth.name
}
