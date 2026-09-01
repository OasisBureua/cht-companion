output "resource_prefix" {
  value = local.resource_prefix
}

output "companion_ecr_repository_url" {
  value = module.ecr.companion_repository_url
}

output "companion_kb_ecr_repository_url" {
  value = module.ecr.companion_kb_repository_url
}

output "companion_service_name" {
  value = module.ecs_companion.service_name
}

output "companion_service_connect_dns_name" {
  value = module.ecs_companion.service_connect_dns_name
}

output "companion_service_connect_namespace_arn" {
  value = aws_service_discovery_http_namespace.companion.arn
}

output "companion_database_endpoint" {
  value = module.companion_db.db_endpoint
}

output "companion_database_secret_arn" {
  value     = module.companion_db.database_secret_arn
  sensitive = true
}

output "kb_lambda_function_name" {
  value = module.kb_lambda.lambda_function_name
}

output "kb_ingest_queue_url" {
  value = module.kb_lambda.kb_ingest_queue_url
}
