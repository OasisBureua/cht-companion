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
  value = local.database_endpoint
}

output "aurora_global_cluster_id" {
  description = "Read by environments/us-east-2 to attach the secondary (empty when db_engine = rds)"
  value       = var.db_engine == "aurora" ? module.aurora_global[0].global_cluster_id : ""
}

output "aurora_engine_version" {
  value = var.aurora_engine_version
}

output "companion_database_secret_arn" {
  value     = local.database_secret_arn
  sensitive = true
}

output "companion_bff_auth_secret_name" {
  description = "Secrets Manager name for COMPANION_INTERNAL_SECRET — platform NestJS must use the same value as X-BFF-Auth"
  value       = module.bff_auth.secret_name
}

output "companion_bff_auth_secret_arn" {
  description = "Secrets Manager ARN for COMPANION_INTERNAL_SECRET"
  value       = module.bff_auth.secret_arn
  sensitive   = true
}

output "kb_lambda_function_name" {
  description = "Embed worker. SQS and the raw-bucket drop zone invoke this function."
  value       = module.kb_lambda.lambda_function_name
}

output "kb_enqueue_function_name" {
  description = "Catalog check. EventBridge invokes this function, which enqueues clips for the embed worker."
  value       = module.kb_lambda.enqueue_function_name
}

output "kb_ingest_queue_url" {
  value = module.kb_lambda.kb_ingest_queue_url
}

output "kb_raw_bucket_name" {
  description = "Drop zone for PDFs and other documents. Uploads invoke the KB Lambda."
  value       = module.kb_lambda.raw_bucket_name
}
