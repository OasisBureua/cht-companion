output "db_instance_id" {
  value = aws_db_instance.main.id
}

output "db_endpoint" {
  value = aws_db_instance.main.address
}

output "db_port" {
  value = aws_db_instance.main.port
}

output "database_secret_arn" {
  value = aws_secretsmanager_secret.database.arn
}

output "security_group_id" {
  value = aws_security_group.rds.id
}
