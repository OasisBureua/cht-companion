output "global_cluster_id" {
  value = var.role == "primary" ? aws_rds_global_cluster.this[0].id : var.global_cluster_identifier
}

output "cluster_id" {
  value = aws_rds_cluster.this.id
}

output "cluster_endpoint" {
  description = "Writer endpoint (primary); the secondary's endpoint is read-only until failover"
  value       = aws_rds_cluster.this.endpoint
}

output "reader_endpoint" {
  value = aws_rds_cluster.this.reader_endpoint
}

output "cluster_port" {
  value = aws_rds_cluster.this.port
}

output "engine_version" {
  value = var.engine_version
}

output "database_secret_arn" {
  description = "Connection secret (primary only)"
  value       = var.role == "primary" ? aws_secretsmanager_secret.database[0].arn : null
}

output "security_group_id" {
  value = aws_security_group.aurora.id
}
